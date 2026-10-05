"""希罗夜间回溯边界；HTTP烟测：python -m unittest checks.test_hiro_night_rewind。"""

from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.app import storage
from backend.app.game import GameError, engine, game_view
from backend.app.game.resolution import begin_night, prepare_night_preview
from backend.app.game.state import (
    SNAPSHOT_EXCLUDED,
    clear_seat_actions,
    save_snapshot,
    upgrade_game,
)
from checks.rule_factory import arranged_game, player
from checks.test_resolution import HOST, command, settle_night_witnesses
from checks import test_speech_timer


def night_game(witch=False, *, last_card=False, snapshots=True):
    game = arranged_game("speech", "day")
    game["day"] = 1
    game["seats"][0]["cards"] = ["emma", "millia"]
    game["seats"][2]["cards"] = ["hanna", "meruru"]
    if last_card:
        game["seats"][1]["cards"] = ["coco", "hiro"]
        game["cards"]["coco"]["alive"] = False
    for card in game["cards"].values():
        card["witch"] = False
    game["cards"]["hiro"]["witch"] = witch
    game["cards"]["hanna"]["witch"] = True
    for row in game["seats"]:
        row["avatar_role_id"] = next(cid for cid in row["cards"] if game["cards"][cid]["alive"])
    game["public"].update(speaker=None, auto_advance_off=True)
    if snapshots:
        save_snapshot(game)
    game["day"] = 2
    begin_night(game, [])
    return game


def knife_review(game):
    command(game, player(game, "3"), "night.submit", {"ability": "knife", "target": "2"})
    command(game, player(game, "3"), "night.confirm")
    game["night"]["confirmed"] = list(game["night"]["actors"])
    return command(game, HOST, "host.advance")


def seed_http_night(game, witch=False):
    """仅给隔离数据库的已开局房间布置场景；保留房间、主持人和席位账号。"""
    fresh = night_game(witch, last_card=True)
    for key, value in fresh.items():
        if key not in SNAPSHOT_EXCLUDED | {"host", "host_entries", "log"}:
            game[key] = deepcopy(value)
    game["spiritual"] = deepcopy(fresh["spiritual"])
    for row, source in zip(game["seats"], fresh["seats"], strict=True):
        row["cards"] = list(source["cards"])
        row["avatar_role_id"] = source["avatar_role_id"]
    game["snapshots"] = []
    game.update(day=1, half="day", phase="speech")
    save_snapshot(game)
    game["day"] = 2
    begin_night(game, [])
    game["night"]["confirmed"] = [sid for sid in game["night"]["actors"] if sid != "3"]


class HiroNightBoundary(unittest.TestCase):
    def test_both_modes_wait_for_death_witness_and_evidence_before_rewind(self):
        for witch in (False, True):
            with self.subTest(witch=witch):
                game = night_game(witch, last_card=True)
                mode = "witch" if witch else "normal"
                knife_review(game)
                self.assertEqual(game["phase"], "night_review")
                self.assertTrue(game["cards"]["hiro"]["alive"])
                self.assertIsNone(game["night"]["hiro_rewind"])
                self.assertEqual(game["public"]["rewinds"], 0)
                command(game, HOST, "host.advance")
                self.assertEqual(game["phase"], "night_results")
                self.assertFalse(game["cards"]["hiro"]["alive"])
                self.assertEqual(game["night"]["hiro_rewind"], mode)
                self.assertFalse(game["spiritual"]["hiro_used"][mode])
                with self.assertRaises(GameError):
                    command(game, HOST, "host.advance")
                settle_night_witnesses(game)
                received = deepcopy(game["information"])
                self.assertTrue(received)
                self.assertIn(
                    "evidence.submit",
                    {item["id"] for item in game_view(game, player(game, "2"))["actions"]},
                )
                command(
                    game, player(game, "2"), "evidence.submit", {"card_id": "hiro", "text": "遗物"}
                )
                with self.assertRaises(GameError):
                    command(game, HOST, "host.advance")
                item = game["pending"][0]
                command(
                    game,
                    HOST,
                    "host.resolve",
                    {"pending_id": item["id"], "allow": True, "public": True},
                )
                events = command(game, HOST, "host.advance")
                payloads = [item.get("payload", {}) for item in events]
                death_index = next(
                    i for i, item in enumerate(payloads) if item.get("type") == "death"
                )
                rewind_index = next(
                    i for i, item in enumerate(payloads) if item.get("ability") == "rewind"
                )
                self.assertLess(death_index, rewind_index)
                self.assertEqual(payloads[death_index]["half"], "night")
                self.assertEqual(payloads[death_index]["deaths"][0]["avatar_role_id"], "hiro")
                self.assertEqual((game["day"], game["half"], game["phase"]), (1, "day", "speech"))
                self.assertTrue(game["cards"]["hiro"]["alive"])
                self.assertEqual(game["public"]["rewinds"], 1)
                self.assertTrue(game["spiritual"]["hiro_used"][mode])
                self.assertFalse(game["spiritual"]["hiro_used"]["normal" if witch else "witch"])
                self.assertTrue(all(item in game["information"] for item in received))

    def test_same_batch_keeps_lower_cards_hidden_and_passives_before_rewind(self):
        game = night_game()
        game["seats"][0].update(cards=["millia", "emma"], avatar_role_id="millia")
        begin_night(game, [])
        command(game, player(game, "1"), "night.submit", {"ability": "swap", "target": "5"})
        command(game, player(game, "1"), "night.confirm")
        knife_review(game)
        command(
            game,
            HOST,
            "host.damage",
            {"targets": ["leia"], "effect": "death", "source": "hanna", "reason": "联动"},
        )
        command(game, HOST, "host.advance")
        self.assertFalse(game["cards"]["millia"]["alive"])
        self.assertFalse(game["cards"]["hiro"]["alive"])
        view = game_view(game, player(game, "7"))
        self.assertEqual(
            next(row for row in view["seats"] if row["id"] == "2")["avatar_role_id"], "hiro"
        )
        settle_night_witnesses(game)
        with patch("backend.app.game.engine.start_phase", wraps=engine.start_phase) as phases:
            events = command(game, HOST, "host.advance")
        self.assertEqual(phases.call_count, 0)
        payloads = [item.get("payload", {}) for item in events]
        substitute_index = next(
            i for i, item in enumerate(payloads) if item.get("ability") == "substitute"
        )
        rewind_index = next(i for i, item in enumerate(payloads) if item.get("ability") == "rewind")
        self.assertLess(substitute_index, rewind_index)
        substitute_event = events[substitute_index]
        self.assertEqual(substitute_event["audience"], ["p1"])
        self.assertTrue(game["cards"]["millia"]["alive"])
        self.assertEqual(game["seats"][1]["avatar_role_id"], "hiro")

    def test_night_winner_is_deferred_and_cannot_be_confirmed(self):
        game = night_game()
        knife_review(game)
        command(
            game,
            HOST,
            "host.damage",
            {
                "targets": ["millia", "arisa"],
                "effect": "unconditional",
                "source": "hanna",
                "reason": "同时达成胜负",
            },
        )
        command(game, HOST, "host.advance")
        self.assertFalse(game["cards"]["millia"]["alive"])
        self.assertFalse(game["cards"]["arisa"]["alive"])
        self.assertIsNone(game["winner_candidate"])
        settle_night_witnesses(game)
        with self.assertRaises(GameError):
            command(game, HOST, "host.confirm_winner", {"confirm": True})
        self.assertEqual(game["status"], "playing")
        command(game, HOST, "host.advance")
        self.assertEqual(game["day"], 1)
        self.assertEqual(game["status"], "playing")

    def test_preview_recalculation_and_abandonment_do_not_arm_or_spend(self):
        game = night_game()
        knife_review(game)
        for _ in range(3):
            prepare_night_preview(game, [])
            self.assertTrue(
                any(item["target_card"] == "hiro" for item in game["night"]["preview"]["deaths"])
            )
            self.assertIsNone(game["night"]["hiro_rewind"])
        clear_seat_actions(game, "3", [])
        self.assertFalse(game["night"]["preview"]["deaths"])
        command(game, HOST, "host.advance")
        command(game, HOST, "host.advance")
        self.assertEqual((game["day"], game["phase"]), (2, "speech"))
        self.assertEqual(game["spiritual"]["hiro_used"], {"normal": False, "witch": False})

    def test_host_damage_exit_and_water_all_use_the_results_boundary(self):
        for cause in ("host", "exit", "water"):
            with self.subTest(cause=cause):
                game = night_game(witch=cause == "exit")
                if cause == "host":
                    command(
                        game,
                        HOST,
                        "host.damage",
                        {
                            "targets": ["hiro"],
                            "effect": "death",
                            "source": "hanna",
                            "reason": "裁定",
                        },
                    )
                elif cause == "exit":
                    command(game, player(game, "2"), "hiro.exit")
                else:
                    command(game, HOST, "host.water", {"seat_id": "3"})
                    command(game, player(game, "3"), "water.use", {"target": "2"})
                game["night"]["confirmed"] = list(game["night"]["actors"])
                command(game, HOST, "host.advance")
                self.assertEqual(game["phase"], "night_review")
                self.assertTrue(game["cards"]["hiro"]["alive"])
                command(game, HOST, "host.advance")
                self.assertEqual(game["phase"], "night_results")
                self.assertFalse(game["cards"]["hiro"]["alive"])
                settle_night_witnesses(game)
                command(game, HOST, "host.advance")
                self.assertEqual((game["day"], game["phase"]), (1, "speech"))

    def test_actual_death_keeps_its_mode_after_revive_and_state_change(self):
        game = night_game(witch=True)
        game["seats"][2]["cards"] = ["meruru", "hanna"]
        game["seats"][2]["avatar_role_id"] = "meruru"
        game["cards"]["meruru"]["witch"] = True
        begin_night(game, [])
        knife_review(game)
        command(game, HOST, "host.advance")
        death = next(item for item in game["deaths"] if item["target_card"] == "hiro")
        command(game, player(game, "3"), "meruru.revive", {"death_id": death["id"]})
        command(
            game,
            HOST,
            "host.state",
            {"card_id": "hiro", "state": "witch", "value": False, "reason": "身份裁定"},
        )
        self.assertTrue(game["cards"]["hiro"]["alive"])
        self.assertEqual(game["night"]["hiro_rewind"], "witch")
        settle_night_witnesses(game)
        command(game, HOST, "host.advance")
        self.assertTrue(game["spiritual"]["hiro_used"]["witch"])
        self.assertFalse(game["spiritual"]["hiro_used"]["normal"])
        self.assertTrue(game["cards"]["hiro"]["witch"])

    def test_no_quota_or_snapshot_enters_day_without_spending(self):
        for missing in ("quota", "snapshot"):
            with self.subTest(missing=missing):
                game = night_game(snapshots=missing != "snapshot")
                if missing == "quota":
                    game["spiritual"]["hiro_used"]["normal"] = True
                knife_review(game)
                if missing == "snapshot":
                    game["snapshots"] = []
                command(game, HOST, "host.advance")
                self.assertIsNone(game["night"]["hiro_rewind"])
                settle_night_witnesses(game)
                command(game, HOST, "host.advance")
                self.assertEqual((game["day"], game["half"], game["phase"]), (2, "day", "speech"))
                self.assertEqual(game["public"]["rewinds"], 0)
                self.assertEqual(game["spiritual"]["hiro_used"]["normal"], missing == "quota")

    def test_results_damage_and_puppet_owner_death_arm_only_once(self):
        for cause in ("host", "puppet"):
            with self.subTest(cause=cause):
                game = night_game()
                game["night"]["confirmed"] = list(game["night"]["actors"])
                command(game, HOST, "host.advance")
                command(game, HOST, "host.advance")
                self.assertEqual(game["phase"], "night_results")
                if cause == "puppet":
                    game["cards"]["meruru"]["witch"] = True
                    game["cards"]["hiro"]["states"].update(puppet="meruru", no_ability=True)
                command(
                    game,
                    HOST,
                    "host.damage",
                    {
                        "targets": ["meruru" if cause == "puppet" else "hiro"],
                        "effect": "unconditional",
                        "source": "hanna",
                        "reason": "结果阶段死亡",
                    },
                )
                self.assertFalse(game["cards"]["hiro"]["alive"])
                self.assertEqual(game["night"]["hiro_rewind"], "normal")
                self.assertEqual(game["public"]["rewinds"], 0)
                self.assertEqual(sum(item["target_card"] == "hiro" for item in game["deaths"]), 1)
                settle_night_witnesses(game)
                game["winner_candidate"] = {"winner": "witch", "reason": "旧候选"}
                command(game, HOST, "host.advance")
                self.assertEqual((game["day"], game["phase"]), (1, "speech"))
                self.assertEqual(game["public"]["rewinds"], 1)

    def test_missing_legacy_field_and_replayed_night_do_not_repeat(self):
        game = night_game()
        game["night"].pop("hiro_rewind")
        self.assertTrue(upgrade_game(game))
        self.assertIsNone(game["night"]["hiro_rewind"])
        knife_review(game)
        command(game, HOST, "host.advance")
        settle_night_witnesses(game)
        command(game, HOST, "host.advance")
        self.assertIsNone(game["night"].get("hiro_rewind"))
        game["day"] = 2
        begin_night(game, [])
        knife_review(game)
        command(game, HOST, "host.advance")
        settle_night_witnesses(game)
        command(game, HOST, "host.advance")
        self.assertEqual((game["day"], game["phase"]), (2, "speech"))
        self.assertEqual(game["public"]["rewinds"], 1)


class HiroNightHTTP(unittest.TestCase):
    """复用真实账号/开局夹具，所有推进、目击、证物与回溯通过HTTP落盘。"""

    def setUp(self):
        self.room = test_speech_timer.SpeechTimerRelay()
        self.addCleanup(self.room.doCleanups)
        self.room.setUp()
        self.players, _ = self.room.speaking_phase()
        self.headers = {sid: self.room.seat_headers(self.players, sid) for sid in ("2", "3", "7")}

    def delegate(self, seat_id, action, payload=None):
        response = self.room.client.post(
            self.room.root + "/commands",
            headers=self.room.host,
            json={
                "expected_version": self.room.state(self.room.host)["version"],
                "action": action,
                "payload": payload or {},
                "as_seat": seat_id,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_both_modes_persist_results_and_preserve_http_history_order(self):
        for witch in (False, True):
            with self.subTest(witch=witch):
                self.room.edit_state(lambda game, witch=witch: seed_http_night(game, witch))
                self.delegate("3", "night.submit", {"ability": "knife", "target": "2"})
                self.delegate("3", "night.confirm")
                review = self.room.command(self.room.host, "host.advance")
                self.assertEqual(review["phase"], "night_review")
                results = self.room.command(self.room.host, "host.advance")
                self.assertEqual(results["phase"], "night_results")
                with storage.transaction() as db:
                    stored = storage.load_game(db, self.room.game_id)
                self.assertFalse(stored["cards"]["hiro"]["alive"])
                mode = "witch" if witch else "normal"
                self.assertEqual(stored["night"]["hiro_rewind"], mode)
                self.assertFalse(stored["spiritual"]["hiro_used"][mode])
                for item in list(stored["pending"]):
                    self.room.command(
                        self.room.host,
                        "host.resolve",
                        {"pending_id": item["id"], "suspects": ["hanna", "emma", "noah"]},
                    )
                self.assertIn(
                    "evidence.submit",
                    {item["id"] for item in self.room.state(self.headers["2"])["actions"]},
                )
                self.delegate("2", "evidence.submit", {"card_id": "hiro", "text": "烟测遗物"})
                with storage.transaction() as db:
                    stored = storage.load_game(db, self.room.game_id)
                item = next(item for item in stored["pending"] if item["kind"] == "evidence")
                rejected = self.room.client.post(
                    self.room.root + "/commands",
                    headers=self.room.host,
                    json={
                        "expected_version": stored["version"],
                        "action": "host.advance",
                        "payload": {},
                    },
                )
                self.assertEqual(rejected.status_code, 422, rejected.text)
                self.room.command(
                    self.room.host,
                    "host.resolve",
                    {"pending_id": item["id"], "allow": True, "public": True},
                )
                restored = self.room.command(self.room.host, "host.advance")
                self.assertEqual(
                    (restored["day"], restored["half"], restored["phase"]), (1, "day", "speech")
                )
                with storage.transaction() as db:
                    stored = storage.load_game(db, self.room.game_id)
                self.assertTrue(stored["cards"]["hiro"]["alive"])
                self.assertTrue(stored["spiritual"]["hiro_used"][mode])
                response = self.room.client.get(
                    self.room.root + "/messages", headers=self.headers["7"]
                )
                response.raise_for_status()
                history = response.json()["messages"]
                death = next(
                    item
                    for item in reversed(history)
                    if item.get("payload", {}).get("type") == "death"
                )
                rewound = next(
                    item
                    for item in reversed(history)
                    if item.get("payload", {}).get("ability") == "rewind"
                )
                self.assertLess(death["id"], rewound["id"])
                self.assertEqual(death["payload"]["deaths"][0]["avatar_role_id"], "hiro")
                self.assertEqual(
                    next(
                        row
                        for row in self.room.state(self.headers["7"])["seats"]
                        if row["id"] == "2"
                    )["avatar_role_id"],
                    "hiro",
                )


if __name__ == "__main__":
    unittest.main()
