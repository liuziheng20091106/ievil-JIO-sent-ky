"""主持人强制推进保护：阶段起点持久化，不让连点吞掉玩家行动。"""

import json
import sqlite3
import unittest
from copy import deepcopy

from backend.app import storage
from backend.app.game import GameError, apply_command, game_view
from backend.app.game.actions import discussion_end_reached, outstanding_seats
from backend.app.game.clock import FakeClock
from backend.app.game.engine import enter_execution, open_vote, run_auto_advance, sync_auto_advance
from backend.app.game.resolution import begin_night, damage_preview
from backend.app.game.state import pending, rewind, save_snapshot, start_phase, upgrade_game
from checks.rule_factory import arranged_game, player

HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}


class PhaseAdvanceGuard(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock(1000)
        self.enterContext(self.clock.installed())

    def command(self, game, action, payload=None, sid=None):
        return apply_command(game, player(game, sid) if sid else HOST, action, payload or {})

    def voting(self):
        game = arranged_game("nomination")
        self.command(game, "vote.nominate", {"target": "3"}, "1")
        open_vote(game, [])
        return game

    def witness(self, game):
        pending(
            game,
            "honoka_witness",
            "等待穗乃香目击选择",
            seat_id="7",
            victim="millia",
            witness_seat="7",
            suspects=["honoka", "emma", "noah", "coco"],
        )

    def waiting_game(self, phase):
        if phase == "voting":
            return self.voting()
        game = arranged_game(phase, "night" if phase.startswith("night") else "day")
        if phase == "night":
            begin_night(game, [])
        elif phase == "night_coco":
            game["seats"][1]["cards"] = ["coco", "hiro"]
            game["cards"]["coco"]["witch"] = True
            begin_night(game, [])
            self.command(game, "night.submit", {"ability": "swap", "target": "3"}, "1")
            for sid in list(outstanding_seats(game)):
                self.command(game, "night.confirm", sid=sid)
            self.assertEqual(game["phase"], "night_coco")
        elif phase == "speech":
            self.command(game, "host.speech", {"start": "1", "direction": "asc"})
        elif phase == "execution":
            game["execution"] = ["nanoka"]
            enter_execution(game, [])
        elif phase == "night_results":
            game["cards"]["meruru"]["witch"] = True
            start_phase(game, "night_review")
            game["night"]["preview"] = damage_preview(
                game, [{"target_card": "millia", "source_card": "meruru", "cause": "knife"}]
            )
            self.command(game, "host.advance")
            game["pending"] = []
            self.assertIn("3", outstanding_seats(game))
        return game

    def assert_refused_unchanged(self, game):
        before = deepcopy(game)
        with self.assertRaisesRegex(GameError, "不足45秒.*仍有玩家"):
            self.command(game, "host.advance")
        self.assertEqual(game, before)

    def test_44999_refuses_without_mutating_and_45_accepts_each_waiting_phase(self):
        for phase in (
            "night",
            "night_coco",
            "nomination",
            "speech",
            "discussion",
            "voting",
            "execution",
            "night_results",
        ):
            with self.subTest(phase=phase):
                game = self.waiting_game(phase)
                self.clock.advance_to(game["public"]["phase_started_at"] + 44.999)
                self.assert_refused_unchanged(game)
                self.clock.advance_to(game["public"]["phase_started_at"] + 45)
                self.command(game, "host.advance")
                self.assertNotEqual(game["phase"], phase)

    def test_missing_honoka_witness_obeys_the_same_window(self):
        game = arranged_game("night_results", "night")
        self.witness(game)
        self.clock.advance(44.999)
        self.assert_refused_unchanged(game)
        self.clock.advance_to(1045)
        self.command(game, "host.advance")
        self.assertEqual(game["pending"], [])
        self.assertIsNotNone(game["witness"])
        self.assertEqual(game["phase"], "speech")

    def test_finished_nominations_and_ballots_advance_at_zero_seconds(self):
        game = arranged_game("nomination")
        self.command(game, "vote.nominate", {"target": "3"}, "1")
        for sid in "234567":
            self.command(game, "vote.pass", sid=sid)
        self.command(game, "host.advance")
        candidate = game["nominations"][0]["card_id"]
        for sid in "1234567":
            self.command(game, "vote.cast", {candidate: "abstain"}, sid)
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "execution")
        self.assertEqual(self.clock.now(), 1000)

    def test_new_phase_rejects_the_next_click_and_preserves_the_submitted_vote(self):
        game = arranged_game("nomination")
        self.command(game, "vote.nominate", {"target": "3"}, "1")
        self.clock.advance(45)
        self.command(game, "host.advance")
        self.assertEqual(game["public"]["phase_started_at"], 1045)
        candidate = game["nominations"][0]["card_id"]
        self.command(game, "vote.cast", {candidate: "yes"}, "1")
        self.assert_refused_unchanged(game)
        self.assertEqual(game["ballots"], {"1": {candidate: "yes"}})
        self.clock.advance(45)
        self.command(game, "host.advance")
        self.assertEqual(game["vote_rounds"][0]["yes"], 1)

    def test_rewind_same_phase_and_legacy_snapshot_restart_the_window(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                game = self.voting()
                snap = save_snapshot(game)
                if legacy:
                    snap["state"]["public"].pop("phase_started_at")
                self.clock.advance(90)
                rewind(game, snap["id"], [])
                self.assertEqual(game["public"]["phase_started_at"], self.clock.now())
                self.assert_refused_unchanged(game)
                self.clock.advance(45)
                self.command(game, "host.advance")
                self.assertEqual(game["phase"], "execution")

    def test_actions_speaker_changes_and_snapshots_do_not_restart_the_window(self):
        game = self.waiting_game("speech")
        started = game["public"]["phase_started_at"]
        self.clock.advance(20)
        self.command(game, "speech.done", sid="1")
        self.command(game, "vote.nominate", {"target": "3"}, "2")
        self.command(game, "host.speech", {"start": "2", "direction": "asc"})
        snap = save_snapshot(game)
        self.assertEqual(game["public"]["phase_started_at"], started)
        self.assertEqual(snap["state"]["public"]["phase_started_at"], started)
        self.clock.advance(25)
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "discussion")

    def test_discussion_requires_six_or_every_present_player(self):
        for count in (7, 5):
            with self.subTest(present=count):
                game = arranged_game("discussion")
                for seat in game["seats"][count:]:
                    for cid in seat["cards"]:
                        game["cards"][cid]["alive"] = False
                needed = min(6, count)
                for sid in map(str, range(1, needed)):
                    self.command(game, "discussion.request_end", sid=sid)
                self.assertFalse(discussion_end_reached(game))
                self.assert_refused_unchanged(game)
                self.command(game, "discussion.request_end", sid=str(needed))
                self.assertTrue(discussion_end_reached(game))
                self.command(game, "host.advance")
                self.assertEqual(game["phase"], "nomination")

    def test_no_present_discussion_players_do_not_require_waiting(self):
        game = arranged_game("discussion")
        for card in game["cards"].values():
            card["alive"] = False
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "nomination")

    def test_player_confirmation_unlocking_coco_gets_a_fresh_window(self):
        game = arranged_game("witch", "night")
        game["seats"][1]["cards"] = ["coco", "hiro"]
        game["cards"]["coco"]["witch"] = True
        begin_night(game, [])
        self.clock.advance(90)
        self.command(game, "night.submit", {"ability": "swap", "target": "3"}, "1")
        for sid in list(outstanding_seats(game)):
            self.command(game, "night.confirm", sid=sid)
        self.assertEqual(game["phase"], "night_coco")
        self.assertEqual(game["public"]["phase_started_at"], 1090)
        self.assert_refused_unchanged(game)
        self.command(game, "night.confirm", sid="2")
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "night_review")

    def test_force_timeout_cannot_consume_the_new_coco_stage(self):
        game = arranged_game("witch", "night")
        game["seats"][1]["cards"] = ["coco", "hiro"]
        game["cards"]["coco"]["witch"] = True
        begin_night(game, [])
        self.clock.advance(45)
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "night_coco")
        self.assertNotIn("2", game["night"]["confirmed"])
        self.assert_refused_unchanged(game)
        self.clock.advance(45)
        self.command(game, "host.advance")
        self.assertEqual(game["phase"], "night_review")

    def test_day_night_cycle_and_auto_advance_keep_their_own_entry_time(self):
        game = arranged_game("dusk")
        self.clock.advance(5)
        self.command(game, "host.advance")
        self.assertEqual((game["day"], game["half"], game["phase"]), (3, "night", "witch"))
        self.assertEqual(game["public"]["phase_started_at"], 1005)
        self.command(game, "host.advance")
        self.assertEqual(game["public"]["phase_started_at"], 1005)
        self.assert_refused_unchanged(game)
        game = arranged_game("nomination")
        for sid in "1234567":
            self.command(game, "vote.pass", sid=sid)
        sync_auto_advance(game)
        self.clock.advance(5)
        run_auto_advance(game)
        self.assertEqual(game["phase"], "execution")
        self.assertEqual(game["public"]["phase_started_at"], 1010)

    def test_rulings_and_winner_reject_before_any_timeout_mutation(self):
        for winner in (False, True):
            with self.subTest(winner=winner):
                game = self.waiting_game("night_results")
                if winner:
                    game["winner_candidate"] = {"winner": "witch", "reason": "检查"}
                else:
                    pending(game, "evidence", "遗留证物", seat_id="1", text="证物")
                self.clock.advance(45)
                before = deepcopy(game)
                with self.assertRaises(GameError):
                    self.command(game, "host.advance")
                self.assertEqual(game, before)

    def test_legacy_load_fills_once_and_reloads_preserve_it(self):
        game = self.voting()
        game["public"].pop("phase_started_at")
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE games (id TEXT PRIMARY KEY, state TEXT, version INTEGER, status TEXT)"
        )
        db.execute(
            "INSERT INTO games VALUES (?, ?, ?, ?)",
            (game["id"], json.dumps(game), game["version"], game["status"]),
        )
        db.commit()
        loaded = storage.load_game(db, game["id"])
        self.assertEqual(loaded["public"]["phase_started_at"], 1000)
        self.assertFalse(db.in_transaction)
        self.assertFalse(upgrade_game(loaded))
        self.clock.advance(44.999)
        reloaded = storage.load_game(db, game["id"])
        self.assertEqual(reloaded["public"]["phase_started_at"], 1000)
        self.assertEqual(game_view(reloaded, HOST)["public"]["phase_started_at"], 1000)
        self.assert_refused_unchanged(reloaded)
        self.clock.advance_to(1045)
        self.command(reloaded, "host.advance")
        self.assertEqual(reloaded["phase"], "execution")
