"""Game animations: recipient privacy, event-time snapshots and real HTTP/WS delivery."""

import json
import unittest
from contextlib import ExitStack
from copy import deepcopy
from itertools import product
from unittest.mock import patch

from backend.app import storage
from backend.app.game import CATALOG, apply_command
from backend.app.game import animations, engine, plugins
from backend.app.game.roles import nanoka
from backend.app.game.state import passive_card_payload
from checks.rule_factory import PAIRS, arranged_game, player
from checks import test_speech_timer

HOST = {"id": "host", "kind": "host", "host_entered": True, "access_ids": ["host"]}
UNENTERED = {**HOST, "host_entered": False, "access_ids": []}


def skill_event(game, sid="4"):
    events = apply_command(game, player(game, sid), "day.skill", {"ability": "love", "target": "5"})
    return next(event for event in events if event.get("payload", {}).get("ability") == "love")


class GameAnimationProjection(unittest.TestCase):
    def test_public_fake_matches_real_and_private_branches_use_the_declared_role(self):
        real = arranged_game()
        real["cards"]["marg"]["witch"] = True
        genuine = skill_event(real)["payload"]
        fake = arranged_game()
        fake["seats"][3]["cards"][0] = "honoka"
        fake["seats"][6]["cards"][1] = "marg"
        fake["cards"]["honoka"]["states"]["disguise"] = "marg"
        fake["cards"]["honoka"]["witch"] = True
        ordinary_game = deepcopy(fake)
        claimed = skill_event(fake)["payload"]
        before = deepcopy(claimed)
        public = storage.project_message_payload(genuine, player(real, "5"), "alert")
        self.assertEqual(
            public, storage.project_message_payload(claimed, player(fake, "5"), "alert")
        )
        self.assertEqual(public["animation"]["images"], {"skill-portrait": "marg/normal/1.png"})
        self.assertEqual(public["animation"]["texts"]["role-title"], "玛格 · 普通")
        self.assertNotIn("_animation", public)
        self.assertNotIn("card_id", public)
        self.assertNotIn("fake", public)
        self.assertEqual(storage.project_message_payload(claimed, UNENTERED, "alert"), public)
        delegate = {"kind": "player", "access_ids": ["controller", "p4"]}
        for actor in (player(fake, "4"), delegate, HOST):
            view = storage.project_message_payload(claimed, actor, "alert")
            self.assertEqual(view["animation"]["images"], {"skill-portrait": "marg/EX/1.png"})
            self.assertEqual(
                view["animation"]["texts"],
                {
                    "role-title": "玛格 · 魔女",
                    "skill-name": "爱上/移情",
                },
            )
            self.assertNotIn("_animation", view)
        self.assertEqual(claimed, before, "projection must not mutate the durable snapshot")
        ordinary_game["cards"]["honoka"]["witch"] = False
        ordinary_game["cards"]["marg"]["witch"] = True
        ordinary = skill_event(ordinary_game)["payload"]
        self.assertEqual(
            storage.project_message_payload(ordinary, player(ordinary_game, "4"))["animation"],
            public["animation"],
            "the real Marg's witch state must not influence Honoka's declaration",
        )

    def test_private_passive_and_information_intro_do_not_authorize_animation(self):
        game = arranged_game()
        game["cards"]["nanoka"]["witch"] = True
        events = []
        nanoka.auto_gaze(game, events)
        payload = next(event["payload"] for event in events if event.get("payload"))
        outsider = player(game, "5")
        for kind in (None, "information", "notice"):
            view = storage.project_message_payload(payload, outsider, kind)
            self.assertEqual(view["ability_name"], "处决幻视")
            self.assertNotIn("effect", view)
            self.assertNotIn("animation", view)
            self.assertNotIn("_animation", view)
        for actor in (player(game, "7"), HOST):
            view = storage.project_message_payload(payload, actor, "information")
            self.assertEqual(view["effect"], payload["effect"])
            self.assertEqual(view["animation"]["images"]["skill-portrait"], "nanoka/EX/1.png")
        self.assertNotIn("animation", storage.project_message_payload(payload, UNENTERED))
        active = skill_event(game)["payload"]
        self.assertNotIn(
            "animation", storage.project_message_payload(active, outsider, "information")
        )
        self.assertIn("intro", storage.project_message_payload(active, outsider, "information"))
        public_passive = passive_card_payload(game, "rewind", "回溯", public=True)
        self.assertEqual(
            storage.project_message_payload(public_passive, outsider, "notice")["animation"][
                "images"
            ],
            {"skill-portrait": "hiro/normal/1.png"},
        )

    def test_history_keeps_event_time_witch_state_and_participant_identity(self):
        game = arranged_game()
        game["cards"]["marg"]["witch"] = True
        active = skill_event(game)["payload"]
        game["cards"]["nanoka"]["witch"] = True
        passive = passive_card_payload(game, "gaze", "私密结果")
        snapshots = deepcopy([active, passive])
        ordinary_game = arranged_game()
        ordinary = skill_event(ordinary_game)["payload"]
        ordinary_game["cards"]["marg"]["witch"] = True
        self.assertEqual(
            storage.project_message_payload(storage.dumps(ordinary), HOST)["animation"]["images"],
            {"skill-portrait": "marg/normal/1.png"},
        )
        game["cards"]["marg"]["witch"] = False
        game["cards"]["nanoka"]["witch"] = False
        game["seats"][3].update(occupant_id="replacement", cards=["sherry", "marg"])
        game["seats"][6].update(occupant_id="replacement7", cards=["honoka", "nanoka"])
        for payload, former in ((active, "p4"), (passive, "p7")):
            archived = storage.dumps(payload)
            former_view = storage.project_message_payload(archived, {"access_ids": [former]})
            host_view = storage.project_message_payload(archived, HOST)
            self.assertEqual(former_view["animation"], host_view["animation"])
            self.assertIn("/EX/", former_view["animation"]["images"]["skill-portrait"])
        new_actor = {"kind": "player", "access_ids": ["replacement"]}
        self.assertEqual(
            storage.project_message_payload(active, new_actor)["animation"]["images"],
            {"skill-portrait": "marg/normal/1.png"},
        )
        self.assertNotIn(
            "animation", storage.project_message_payload(passive, {"access_ids": ["replacement7"]})
        )
        self.assertEqual([active, passive], snapshots)

    def test_catalog_default_and_role_ability_override_use_real_skill_events(self):
        for role in CATALOG:
            for skill in role["skills"]:
                with self.subTest(role=role["id"], skill=skill["id"]):
                    snapshot = animations.skill_animation_snapshot(
                        role["id"], skill["id"], skill["name"], True
                    )
                    if (role["id"], skill["id"]) != ("emma", "interrupt"):
                        for branch, variant in (("public", "normal"), ("owner", "EX")):
                            self.assertEqual(snapshot[branch]["script"], animations.SKILL_SCRIPT)
                            self.assertEqual(
                                snapshot[branch]["images"],
                                {"skill-portrait": f"{role['id']}/{variant}/1.png"},
                            )
        with patch.dict(
            animations.SKILL_SCRIPTS,
            {
                ("marg", "love"): "scripts/love.json",
                ("nanoka", "gaze"): "scripts/gaze.json",
            },
        ):
            game = arranged_game()
            active = skill_event(game)["payload"]
            events = []
            nanoka.auto_gaze(game, events)
            passive = next(event["payload"] for event in events if event.get("payload"))
            self.assertEqual(
                storage.project_message_payload(active, HOST)["animation"]["script"],
                "scripts/love.json",
            )
            self.assertEqual(
                storage.project_message_payload(passive, HOST)["animation"]["script"],
                "scripts/gaze.json",
            )
            unrelated = passive_card_payload(game, "love_self", "转爱自己")
            self.assertEqual(
                storage.project_message_payload(unrelated, HOST)["animation"]["script"],
                animations.SKILL_SCRIPT,
            )

    def test_speech_turn_timer_reset_skip_and_precommit_share_one_animation_boundary(self):
        game = arranged_game(phase="speech")
        game["public"].update(speaker="1", speech_order=list(map(str, range(1, 8))))
        events = []
        with patch.object(engine.clock, "now", return_value=100):
            engine.sync_speaker(game, events)
            self.assertEqual([event["payload"]["seat_id"] for event in events], ["1"])
            self.assertTrue(engine.touch_speech_timer(game, "1", now=110))
            self.assertEqual(game["public"]["speech_deadline"], 140)
            self.assertEqual(engine.run_speech_timer(game, now=139), [])
            self.assertFalse(engine.publish_speech_turn(game, events, "1"))
            game["speech_passed"] = ["3", "4"]
            game["speech_queued"] = {"3": "提前发言"}
            expired = engine.run_speech_timer(game, now=140)
            self.assertEqual([event["payload"]["seat_id"] for event in expired], ["2"])
            continued = apply_command(game, player(game, "2"), "speech.done", {})
        turns = [event for event in continued if event["kind"] == "speech_turn"]
        self.assertEqual([event["payload"]["seat_id"] for event in turns], ["3", "5"])
        self.assertEqual(
            [event["kind"] for event in continued], ["speech_turn", "chat", "speech_turn"]
        )
        self.assertEqual(game["public"]["speaker"], "5")
        for event in [*events, *expired, *turns]:
            projected = storage.project_message_payload(event["payload"], UNENTERED, "speech_turn")
            self.assertEqual(
                projected["animation"],
                {
                    "script": "scripts/interrogation-start.json",
                    "images": {},
                    "texts": {},
                },
            )


class GameAnimationDelivery(unittest.TestCase):
    def setUp(self):
        # Compose the established real-room fixture without inheriting its unrelated tests.
        self.room = test_speech_timer.SpeechTimerRelay()
        self.addCleanup(self.room.doCleanups)
        self.room.setUp()
        self.players, _ = self.room.speaking_phase()
        self.room.command(self.room.host, "host.auto")
        fresh = arranged_game()

        def arrange(game):
            game.update(cards=fresh["cards"], phase="discussion", half="day", day=2, pending=[])
            for row, pair in zip(game["seats"], PAIRS, strict=True):
                row["cards"] = list(pair)
            game["public"].update(speaker=None, speech_deadline=None, speech_deadline_seat=None)
            game["cards"]["marg"]["witch"] = True
            game["cards"]["nanoka"]["witch"] = True

        self.room.edit_state(arrange)
        self.headers = {sid: self.room.seat_headers(self.players, sid) for sid in ("4", "5", "7")}
        self.room.account("10002")
        accounts = self.room.client.get(
            "/api/hosts/accounts", headers=self.room.host, params={"q": "10002"}
        ).json()["accounts"]
        account_id = next(row["account_id"] for row in accounts if row["qq_id"] == "10002")
        self.room.client.post(
            f"/api/hosts/{account_id}", headers=self.room.host, json={"level": 3}
        ).raise_for_status()
        self.unentered, _ = self.room.host_login("10002")

    def history(self, headers):
        response = self.room.client.get(self.room.root + "/messages", headers=headers)
        response.raise_for_status()
        return response.json()["messages"]

    def messages_through(self, socket, version):
        messages = []
        for _ in range(80):
            frame = socket.receive_json()
            if frame["type"] == "message":
                messages.append(frame["message"])
            if frame["type"] == "state" and frame["state"]["version"] >= version:
                return messages
        raise AssertionError("the command's state frame was not delivered")

    def test_emma_interrupt_and_private_hiro_forgery_keep_frozen_slots(self):
        emma = self.room.seat_headers(self.players, "1")
        hiro = self.room.seat_headers(self.players, "2")
        for witch, expression in product((False, True), range(1, 4)):
            with self.subTest(witch=witch, expression=expression):

                def arrange(game, witch=witch):
                    game["day"] += 1
                    game["phase"] = "speech"
                    game["speech_passed"] = []
                    game["speech_queued"] = {}
                    game["public"].update(
                        speaker="2", speech_order=["2", "1", "3", "4", "5", "6", "7"]
                    )
                    game["seats"][0]["cards"] = ["emma", "millia"]
                    game["cards"]["emma"]["witch"] = witch
                    game["cards"]["hiro"]["witch"] = witch
                    game["declarations"] = []
                    game["rule_plugins"] = plugins.manifest(["hiro_forgery"])

                self.room.edit_state(arrange)
                before = {item["id"] for item in self.history(self.room.host)}
                with patch.object(animations.SystemRandom, "randrange", return_value=expression):
                    self.room.command(emma, "day.skill", {"ability": "interrupt", "target": "2"})
                    self.room.command(hiro, "hiro_forgery.publish", {"text": "公开正文"})
                delivered = {
                    name: [item for item in self.history(headers) if item["id"] not in before]
                    for name, headers in {
                        "emma": emma,
                        "hiro": hiro,
                        "other": self.headers["5"],
                        "host": self.room.host,
                        "unentered": self.unentered,
                    }.items()
                }
                for name, messages in delivered.items():
                    animated = [
                        item for item in messages if item.get("payload", {}).get("animation")
                    ]
                    self.assertEqual(animated[0]["kind"], "speech_turn")
                    self.assertEqual(animated[0]["payload"]["seat_id"], "1")
                    self.assertEqual(animated[1]["payload"]["ability"], "interrupt")
                    interrupt = next(
                        item
                        for item in messages
                        if item.get("payload", {}).get("ability") == "interrupt"
                    )
                    animation = interrupt["payload"]["animation"]
                    self.assertEqual(
                        animation["script"], f"scripts/emma-interrupt-{expression}.json"
                    )
                    self.assertEqual(
                        animation["images"],
                        {
                            "skill-portrait": (
                                "emma/EX/1.png"
                                if witch and name in {"emma", "host"}
                                else f"scripts/images/emma-interrupt/portrait-{expression}.webp"
                            )
                        },
                    )
                    public = next(item for item in messages if item["text"] == "公开正文")
                    self.assertEqual(public["kind"], "notice")
                    self.assertNotIn("payload", public)
                    private = [
                        item
                        for item in messages
                        if item.get("payload", {}).get("type") == "animation"
                    ]
                    if name not in {"hiro", "host"}:
                        self.assertEqual(private, [])
                        continue
                    self.assertEqual(len(private), 1)
                    payload = private[0]["payload"]
                    self.assertEqual(set(payload), {"type", "animation"})
                    self.assertEqual(payload["type"], "animation")
                    self.assertEqual(
                        payload["animation"]["script"], f"scripts/hiro-forgery-{expression}.json"
                    )
                    self.assertEqual(
                        payload["animation"]["images"],
                        {
                            "skill-portrait": f"scripts/images/hiro-forgery/portrait-{'ex-' if witch else ''}{expression}.webp"
                        },
                    )

                def change_identity(game, witch=witch):
                    game["cards"]["emma"]["witch"] = not witch
                    game["cards"]["hiro"]["witch"] = not witch

                self.room.edit_state(change_identity)
                for name, headers in (("emma", emma), ("hiro", hiro), ("host", self.room.host)):
                    archived = {item["id"]: item for item in self.history(headers)}
                    for item in delivered[name]:
                        self.assertEqual(archived[item["id"]].get("payload"), item.get("payload"))
                hint = next(
                    item
                    for item in delivered["host"]
                    if item.get("payload", {}).get("type") == "animation"
                )
                with storage.transaction() as db:
                    raw = db.execute(
                        "SELECT payload FROM messages WHERE id=?", (hint["id"],)
                    ).fetchone()["payload"]
                owner_id = json.loads(raw)["actor_participant_id"]
                self.assertEqual(
                    storage.project_message_payload(
                        raw,
                        {"kind": "player", "access_ids": ["controller", owner_id]},
                        "information",
                    ),
                    hint["payload"],
                )
                for actor in (UNENTERED, {"kind": "player", "access_ids": ["replacement"]}):
                    self.assertIsNone(storage.project_message_payload(raw, actor, "information"))
                for kind in (None, "notice", "alert"):
                    self.assertIsNone(storage.project_message_payload(raw, HOST, kind))

    def test_http_and_live_skill_privacy_and_private_passive_audience(self):
        viewers = {
            "owner": self.headers["4"],
            "other": self.headers["5"],
            "host": self.room.host,
            "unentered": self.unentered,
        }
        with ExitStack() as stack:
            sockets = {
                name: stack.enter_context(self.room.connect(headers))
                for name, headers in viewers.items()
            }
            state = self.room.command(
                self.headers["4"], "day.skill", {"ability": "love", "target": "5"}
            )
            for name, socket in sockets.items():
                messages = self.messages_through(socket, state["version"])
                skill = next(
                    item for item in messages if item.get("payload", {}).get("ability") == "love"
                )
                animation = skill["payload"]["animation"]
                ex = name in {"owner", "host"}
                self.assertEqual(
                    animation["images"],
                    {"skill-portrait": f"marg/{'EX' if ex else 'normal'}/1.png"},
                )
                self.assertEqual(
                    animation["texts"]["role-title"], "玛格 · " + ("魔女" if ex else "普通")
                )
                archived = next(
                    item for item in self.history(viewers[name]) if item["id"] == skill["id"]
                )
                self.assertEqual(archived["payload"], skill["payload"])
                self.assertNotIn("_animation", skill["payload"])
        self.room.edit_state(
            lambda game: game.update(
                phase="nomination",
                nominations=[],
                nomination_done=list(map(str, range(1, 8))),
            )
        )
        viewers["owner"] = self.headers["7"]
        with ExitStack() as stack:
            sockets = {
                name: stack.enter_context(self.room.connect(headers))
                for name, headers in viewers.items()
            }
            state = self.room.command(self.room.host, "host.advance")
            for name, socket in sockets.items():
                messages = self.messages_through(socket, state["version"])
                skills = [
                    item for item in messages if item.get("payload", {}).get("ability") == "gaze"
                ]
                archived = [
                    item
                    for item in self.history(viewers[name])
                    if item.get("payload", {}).get("ability") == "gaze"
                ]
                if name in {"owner", "host"}:
                    self.assertEqual(len(skills), 1)
                    self.assertEqual(
                        skills[0]["payload"]["animation"]["images"],
                        {"skill-portrait": "nanoka/EX/1.png"},
                    )
                    self.assertEqual([item["id"] for item in archived], [skills[0]["id"]])
                else:
                    self.assertEqual(skills, [])
                    self.assertEqual(archived, [])


if __name__ == "__main__":
    unittest.main()
