"""Optional rule selection, bounded intent rewriting and stored-game safety."""

import json
import os
import sys
from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import realtime, storage
from backend.app.game import DEFAULT_CODEX, GameError, apply_command, game_view
from backend.app.game import plugins
from backend.app.game.actions import action, field
from backend.app.game.resolution import death_batch, resolve_intents
from backend.app.game.state import rewind, save_snapshot, upgrade_game
from backend.app.main import app
from checks.rule_factory import arranged_game, player

HOST = {"id": "host", "kind": "host", "host_entered": True}
ID = "testpatch"


def panel_actions(game, actor, *, as_seat=None):
    if actor["kind"] != "host":
        return []
    return [
        action(
            ID + ".mark",
            "标记一张牌的攻击取消",
            [field("card_id", "牌", "select", [(cid, cid) for cid in game["cards"]])],
            short_label="标记",
            description="取消指定牌受到的一次测试攻击。",
        )
    ]


def mark(game, actor, events, payload, *, by_host=False):
    if actor["kind"] != "host":
        raise GameError("只有主持人可调整附加规则")
    game["plugin_state"][ID] = {"cancel": payload["card_id"]}


def cancel(game, events, context):
    target = game["plugin_state"].get(ID, {}).get("cancel")
    if target:
        context["attacks"][:] = [
            attack for attack in context["attacks"] if attack["target_card"] != target
        ]


VERSION = 1
NAME = "测试附加规则"
DESCRIPTION = "取消主持人标记牌所受的一次攻击。"
CATEGORY = "external_default_off"
DEPENDS = ()
HANDLERS = {"attack_intents": cancel}
COMMANDS = {ID + ".mark": mark}
TEST_PATCH = sys.modules[__name__]


class OptionalRules(unittest.TestCase):
    def setUp(self):
        plugins.REGISTRY.append(TEST_PATCH)
        self.addCleanup(plugins.REGISTRY.pop)
        plugins.validate_registry()

    def started(self, selection):
        game = arranged_game("ordering", "night")
        game.update(status="lobby", day=1, rule_plugins=plugins.manifest(selection))
        apply_command(game, HOST, "host.start", {})
        return game

    def test_choice_freezes_and_rewrites_only_selected_game(self):
        plain = self.started([])
        enabled = self.started([ID])
        self.assertNotIn(ID + ".mark", [a["id"] for a in game_view(plain, HOST)["actions"]])
        self.assertIn(ID + ".mark", [a["id"] for a in game_view(enabled, HOST)["actions"]])
        apply_command(enabled, HOST, ID + ".mark", {"card_id": "marg"})
        attack = {"target_card": "marg", "source_card": "coco", "cause": "knife"}
        for game in (plain, enabled):
            game["phase"] = "night_review"
            preview = resolve_intents(game, [], [dict(attack)], night=True)
            death_batch(game, [], preview)
        self.assertEqual([d["target_card"] for d in plain["deaths"]], ["marg"])
        self.assertEqual(enabled["deaths"], [])
        self.assertTrue(plain["pending"])  # attacked seat receives a witness
        self.assertEqual(enabled["pending"], [])
        self.assertTrue(any("规则补丁调整攻击意图" in line["text"] for line in enabled["log"]))
        self.assertNotIn("plugin_state", game_view(enabled, player(enabled, "1")))
        self.assertIn(
            NAME, [row["name"] for row in game_view(enabled, player(enabled, "1"))["rule_plugins"]]
        )

    def test_preview_edit_recomputes_once_without_double_substitution(self):
        game = self.started([ID])
        game["phase"] = "night_review"
        game["millia_swap"] = {"seat": "4", "day": 1}
        game["plugin_state"][ID] = {"cancel": "coco"}

        def change_after(game, events, context):
            context["preview"]["deaths"].clear()  # must not modify the core preview
            context["attacks"].append(
                {"target_card": "marg", "source_card": "coco", "cause": "knife"}
            )

        with patch.dict(
            TEST_PATCH.HANDLERS, {"attack_intents": lambda *_: None, "post_preview": change_after}
        ):
            preview = resolve_intents(game, [], [], night=True)
        self.assertEqual([d["target_card"] for d in preview["deaths"]], ["millia"])
        self.assertEqual(game["night"]["reactions"], ["millia"])
        self.assertEqual(preview["witch_targets"][0]["seat_id"], "4")

    def test_old_snapshots_and_rewind_keep_selection_but_restore_private_mechanics(self):
        game = self.started([ID])
        game["plugin_state"][ID] = {"cancel": "marg"}
        snap = save_snapshot(game)
        game["plugin_state"][ID]["cancel"] = "coco"
        rewind(game, snap["id"], [])
        self.assertEqual(game["plugin_state"][ID]["cancel"], "marg")
        self.assertEqual(game["rule_plugins"][-1], {"id": ID, "version": 1})
        game["snapshots"][0]["state"].pop("plugin_state", None)
        self.assertTrue(upgrade_game(game))
        self.assertFalse(upgrade_game(game))
        self.assertEqual(game["snapshots"][0]["state"]["plugin_state"], {})

    def test_unselected_and_unentered_callers_cannot_dispatch_module_command(self):
        game = self.started([])
        for actor in (HOST, player(game, "1"), {**HOST, "host_entered": False}):
            with self.assertRaises(GameError):
                apply_command(game, actor, ID + ".mark", {"card_id": "marg"})
        selected = self.started([ID])
        with self.assertRaises(GameError):
            apply_command(selected, player(selected, "1"), ID + ".mark", {"card_id": "marg"})
        with self.assertRaises(GameError):
            apply_command(
                selected, {**HOST, "host_entered": False}, ID + ".mark", {"card_id": "marg"}
            )
        self.assertNotIn(ID, selected["plugin_state"])


class PluginRegistrySelection(unittest.TestCase):
    def module(self, id, category, depends=()):
        return SimpleNamespace(
            ID=id,
            VERSION=1,
            NAME=id,
            DESCRIPTION="示例外置规则",
            CATEGORY=category,
            DEPENDS=depends,
            HANDLERS={},
            COMMANDS={},
        )

    def test_categories_dependency_and_deployment_manifest(self):
        always = self.module("always", "external_required", ("meruru",))
        default = self.module("default_rule", "external_default_on", ("always",))
        optional = self.module("optional_rule", "external_default_off", ("default_rule",))
        with patch.object(plugins, "REGISTRY", [*plugins.BUILTINS, always, default, optional]):
            plugins.validate_registry()
            self.assertEqual(
                [row["id"] for row in plugins.manifest()][-2:], ["always", "default_rule"]
            )
            self.assertEqual([row["id"] for row in plugins.manifest([])][-1], "always")
            self.assertEqual(
                [row["id"] for row in plugins.manifest(["default_rule", "optional_rule"])][-3:],
                ["always", "default_rule", "optional_rule"],
            )
            for selected in (
                ["optional_rule"],
                ["optional_rule", "optional_rule"],
                ["nonexistent"],
                ["always"],
            ):
                with self.subTest(selected=selected), self.assertRaises(GameError):
                    plugins.manifest(selected)
            self.assertEqual(plugins.catalog()[-1]["name"], "optional_rule")
            self.assertFalse(plugins.catalog()[-1]["default_enabled"])
        invalid_default = self.module("invalid_default", "external_default_on", ("optional_rule",))
        with patch.object(plugins, "REGISTRY", [*plugins.BUILTINS, optional, invalid_default]):
            with self.assertRaisesRegex(ValueError, "默认启用"):
                plugins.validate_registry()

    def test_discovery_orders_dependent_files_and_rejects_missing_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a_dependent.py").write_text("", encoding="utf-8")
            (root / "z_base.py").write_text("", encoding="utf-8")
            base = self.module("base_rule", "external_default_off")
            dependent = self.module("dependent_rule", "external_default_off", ("base_rule",))
            registry = {"a_dependent": dependent, "z_base": base}
            with (
                patch.object(plugins, "EXTERNAL_DIR", root),
                patch.object(
                    plugins,
                    "import_module",
                    side_effect=lambda name: registry[name.rsplit(".", 1)[-1]],
                ),
            ):
                self.assertEqual(plugins.discover_external(), [base, dependent])
                registry["z_base"] = self.module("base_rule", "external_default_off", ("missing",))
                with self.assertRaisesRegex(ValueError, "依赖"):
                    plugins.discover_external()


class PluginHTTP(unittest.TestCase):
    def setUp(self):
        plugins.REGISTRY.append(TEST_PATCH)
        self.addCleanup(plugins.REGISTRY.pop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        data_patch.start()
        self.addCleanup(data_patch.stop)
        env_patch = patch.dict(
            os.environ,
            {
                "GAME_ADMIN_QQ": "10001,10002",
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
            },
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.client = TestClient(
            app, base_url="http://testserver", headers={"Origin": "http://testserver"}
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.host = self.login("10001", host=True)
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX, "rule_plugins": [ID]}
        )
        created.raise_for_status()
        self.root = "/api/games/" + created.json()["id"]
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()

    def login(self, qq, *, host=False):
        prefix = "/api/native/auth/host/challenges" if host else "/api/native/auth/challenges"
        challenge = self.client.post(prefix).json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq,
                "nickname": qq,
                "avatar_url": "https://example.invalid/avatar",
                "group_id": 123456,
            },
        ).raise_for_status()
        result = self.client.get(prefix + "/" + challenge["id"])
        result.raise_for_status()
        return {"Authorization": "Bearer " + result.json()["session_token"]}

    def command(self, headers, name, payload=None, *, version=None):
        if version is None:
            view = self.client.get(self.root + "/state", headers=headers)
            view.raise_for_status()
            version = view.json()["version"]
        return self.client.post(
            self.root + "/commands",
            headers=headers,
            json={"expected_version": version, "action": name, "payload": payload or {}},
        )

    def select_disguises(self, headers_by_seat):
        for headers in headers_by_seat.values():
            view = self.client.get(self.root + "/state", headers=headers)
            view.raise_for_status()
            if any(action["id"] == "honoka.disguise" for action in view.json()["actions"]):
                self.command(headers, "honoka.disguise", {"role": "emma"}).raise_for_status()

    def complete_night(self, by_seat):
        # 未选技能的玩家真实确认放弃；可可解锁后再确认一次，不绕过45秒保护。
        for _ in range(2):
            for headers in by_seat.values():
                view = self.client.get(self.root + "/state", headers=headers).json()
                if any(action["id"] == "night.confirm" for action in view["actions"]):
                    self.command(headers, "night.confirm").raise_for_status()

    def test_real_http_selection_auth_version_and_intent(self):
        self.command(self.host, "room.open_join", {"open": True}).raise_for_status()
        players = []
        for number in range(7):
            headers = self.login(str(11001 + number))
            joined = self.client.post(
                self.root + "/participations", headers=headers, json={"kind": "player"}
            )
            joined.raise_for_status()
            players.append((headers, joined.json()["actor"]["seat_id"]))
        spectator = self.login("11009")
        self.client.post(
            self.root + "/participations", headers=spectator, json={"kind": "spectator"}
        ).raise_for_status()
        for headers, _ in players:
            self.command(headers, "lobby.ready").raise_for_status()
        for headers, _ in players:
            self.command(headers, "lobby.ready").raise_for_status()
        self.select_disguises({seat_id: headers for headers, seat_id in players})
        version = self.client.get(self.root + "/state", headers=self.host).json()["version"]
        self.assertEqual(
            self.command(self.host, "host.start", version=version - 1).status_code,
            409,
        )
        self.command(self.host, "host.start", version=version).raise_for_status()
        host_view = self.client.get(self.root + "/state", headers=self.host).json()
        unentered = self.login("10002", host=True)
        unentered_view = self.client.get(self.root + "/state", headers=unentered)
        unentered_view.raise_for_status()
        self.assertEqual(unentered_view.json()["actions"], [])
        self.assertTrue(unentered_view.json()["host_entry_required"])
        self.assertNotIn(ID + ".mark", unentered_view.text)
        self.assertNotIn("plugin_state", unentered_view.text)
        self.assertEqual(
            self.command(
                unentered, ID + ".mark", {"card_id": "marg"}, version=host_view["version"]
            ).status_code,
            403,
        )
        self.assertIn(ID, [row["id"] for row in host_view["rule_plugins"]])
        announced = [
            message
            for message in self.client.get(self.root + "/messages", headers=spectator).json()[
                "messages"
            ]
            if message.get("payload", {}).get("type") == "plugin"
        ]
        self.assertEqual(len(announced), len(host_view["rule_plugins"]))
        patch_notice = next(message for message in announced if message["payload"]["id"] == ID)
        self.assertEqual(patch_notice["kind"], "alert")
        self.assertEqual(patch_notice["payload"]["name"], NAME)
        self.assertEqual(patch_notice["payload"]["version"], VERSION)
        self.assertEqual(patch_notice["payload"]["description"], DESCRIPTION)
        self.assertNotIn(
            "plugin_state", self.client.get(self.root + "/state", headers=spectator).text
        )
        self.assertNotIn(
            ID + ".mark", self.client.get(self.root + "/state", headers=spectator).text
        )
        self.assertEqual(
            self.command(players[0][0], ID + ".mark", {"card_id": "marg"}).status_code, 422
        )
        by_seat = {sid: headers for headers, sid in players}
        state_version = host_view["version"]
        forbidden = self.client.post(
            self.root + "/commands",
            headers=players[0][0],
            json={
                "expected_version": state_version,
                "action": ID + ".mark",
                "as_seat": players[1][1],
                "payload": {"card_id": "marg"},
            },
        )
        self.assertEqual(forbidden.status_code, 403)
        attacker = next(
            s
            for s in host_view["seats"]
            if s["current_card_id"]
            in {"meruru", "noah", "annan", "marg", "leia", "nanoka", "hanna"}
        )
        if not any(
            c["id"] == attacker["current_card_id"] and c["witch"] for c in attacker["cards"]
        ):
            self.command(
                self.host,
                "host.state",
                {
                    "card_id": attacker["current_card_id"],
                    "state": "witch",
                    "value": True,
                    "reason": "测试规则补丁",
                },
            ).raise_for_status()
        self.command(self.host, "host.advance").raise_for_status()
        state = self.client.get(self.root + "/state", headers=self.host).json()
        self.assertIn(state["phase"], {"night", "night_coco"})
        knife = next(
            action
            for action in self.client.get(
                self.root + "/state", headers=by_seat[attacker["id"]]
            ).json()["actions"]
            if action["id"] == "night.submit" and action["payload"]["ability"] == "knife"
        )
        targets = {seat["id"]: seat for seat in state["seats"]}
        victim_id = next(
            option["value"]
            for option in knife["fields"][0]["options"]
            if option["value"] != attacker["id"]
            and targets[option["value"]]["current_card_id"] not in {"hiro", "millia"}
        )
        victim = targets[victim_id]
        self.command(
            self.host, ID + ".mark", {"card_id": victim["current_card_id"]}
        ).raise_for_status()
        self.command(
            by_seat[attacker["id"]], "night.submit", {"ability": "knife", "target": victim["id"]}
        ).raise_for_status()
        self.command(by_seat[attacker["id"]], "night.confirm").raise_for_status()
        self.complete_night(by_seat)
        self.command(self.host, "host.advance").raise_for_status()
        with storage.connect() as db:
            game = storage.load_game(db, host_view["id"])
        self.assertEqual(game["phase"], "night_review")
        self.assertNotIn(
            victim["current_card_id"],
            [item["target_card"] for item in game["night"]["preview"]["deaths"]],
        )
        self.assertTrue(any("规则补丁调整攻击意图" in item["text"] for item in game["log"]))
        self.command(self.host, "host.advance").raise_for_status()
        self.assertEqual(
            self.client.get(self.root + "/state", headers=self.host).json()["phase"],
            "night_results",
        )
        self.assertTrue(
            self.client.get(self.root + "/messages", headers=self.host).json()["messages"]
        )
        self.command(
            self.host, "host.end", {"winner": "aborted", "reason": "测试另一局"}
        ).raise_for_status()
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX, "rule_plugins": []}
        )
        created.raise_for_status()
        self.root = "/api/games/" + created.json()["id"]
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()
        self.command(self.host, "room.open_join", {"open": True}).raise_for_status()
        empty_seats = {}
        for headers, _ in players:
            joined = self.client.post(
                self.root + "/participations", headers=headers, json={"kind": "player"}
            )
            joined.raise_for_status()
            empty_seats[joined.json()["actor"]["seat_id"]] = headers
        for headers in empty_seats.values():
            self.command(headers, "lobby.ready").raise_for_status()
        for headers in empty_seats.values():
            self.command(headers, "lobby.ready").raise_for_status()
        self.select_disguises(empty_seats)
        self.command(self.host, "host.start").raise_for_status()
        empty_notices = [
            message
            for message in self.client.get(self.root + "/messages", headers=self.host).json()[
                "messages"
            ]
            if message.get("payload", {}).get("type") == "plugin"
        ]
        self.assertNotIn(ID, [message["payload"]["id"] for message in empty_notices])
        setup = self.client.get(self.root + "/state", headers=self.host).json()
        witch = next(
            s
            for s in setup["seats"]
            if s["current_card_id"]
            in {"meruru", "noah", "annan", "marg", "leia", "nanoka", "hanna"}
        )
        self.command(
            self.host,
            "host.state",
            {
                "card_id": witch["current_card_id"],
                "state": "witch",
                "value": True,
                "reason": "测试未选附加规则",
            },
        ).raise_for_status()
        self.command(self.host, "host.advance").raise_for_status()
        plain = self.client.get(self.root + "/state", headers=self.host).json()
        target = next(
            s
            for s in plain["seats"]
            if s["id"] != witch["id"] and s["current_card_id"] not in {"hiro", "millia"}
        )
        knife = self.command(
            empty_seats[witch["id"]], "night.submit", {"ability": "knife", "target": target["id"]}
        )
        self.assertEqual(
            knife.status_code,
            200,
            knife.text
            + str(
                self.client.get(self.root + "/state", headers=empty_seats[witch["id"]])
                .json()
                .get("actions")
            ),
        )
        self.command(empty_seats[witch["id"]], "night.confirm").raise_for_status()
        self.complete_night(empty_seats)
        self.command(self.host, "host.advance").raise_for_status()
        with storage.connect() as db:
            plain_game = storage.load_game(db, plain["id"])
        self.assertIn(
            target["current_card_id"],
            [item["target_card"] for item in plain_game["night"]["preview"]["deaths"]],
        )
        self.assertNotIn(
            ID + ".mark",
            [
                a["id"]
                for a in self.client.get(self.root + "/state", headers=self.host).json()["actions"]
            ],
        )

    def test_incompatible_saved_game_refuses_get_post_and_clock(self):
        game_id = self.root.rsplit("/", 1)[-1]
        with storage.connect() as db:
            original = json.loads(
                db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()["state"]
            )
        for entry, expected in (
            ({"id": "emma", "version": 999}, "保存版本 999"),
            ({"id": "unknown", "version": 1}, "未部署"),
        ):
            game = json.loads(storage.dumps(original))
            game["rule_plugins"][0] = entry
            with storage.transaction() as db:
                db.execute("UPDATE games SET state=? WHERE id=?", (storage.dumps(game), game_id))
                before = db.execute(
                    "SELECT state, version FROM games WHERE id=?", (game_id,)
                ).fetchone()
            self.assertEqual(
                self.client.get(self.root + "/state", headers=self.host).status_code, 409
            )
            response = self.command(self.host, "host.start", version=game["version"])
            self.assertEqual(response.status_code, 409)
            self.assertIn(expected, response.text)
            self.assertEqual(realtime.run_timers(), [])
            with storage.connect() as db:
                after = db.execute(
                    "SELECT state, version FROM games WHERE id=?", (game_id,)
                ).fetchone()
            self.assertEqual(tuple(before), tuple(after))
