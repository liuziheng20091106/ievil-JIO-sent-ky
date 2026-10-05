"""希罗伪证：每日次数、公开假公告与私密技能提示。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app import storage
from backend.app.api import chat_references
from backend.app.game import GameError, apply_command, game_view, plugins
from checks.rule_factory import arranged_game, player


class HiroForgery(unittest.TestCase):
    def test_public_forgery_once_per_day_and_optional_evidence(self):
        disabled = arranged_game()
        disabled["rule_plugins"] = plugins.manifest([])
        self.assertNotIn(
            "hiro_forgery.publish",
            [a["id"] for a in game_view(disabled, player(disabled, "2"))["actions"]],
        )
        game = arranged_game()
        game["rule_plugins"] = plugins.manifest(["hiro_forgery"])
        hiro = player(game, "2")
        other = player(game, "1")
        host = {"id": "host", "kind": "host", "host_entered": True}
        self.assertIn("hiro_forgery.publish", [a["id"] for a in game_view(game, hiro)["actions"]])
        self.assertNotIn(
            "hiro_forgery.publish", [a["id"] for a in game_view(game, other)["actions"]]
        )
        for actor in (other, host):
            with self.assertRaises(GameError):
                apply_command(game, actor, "hiro_forgery.publish", {"text": "盗用"})
        with self.assertRaises(GameError):
            apply_command(game, hiro, "hiro_forgery.publish", {"text": "  "})
        plain = apply_command(game, hiro, "hiro_forgery.publish", {"text": "伪造的遗物"})
        self.assertEqual(plain[0]["audience"], [hiro["id"]])
        self.assertIsNone(plain[1]["audience"])
        self.assertEqual(plain[1]["kind"], "notice")
        self.assertNotIn(
            "hiro_forgery.publish", [a["id"] for a in game_view(game, hiro)["actions"]]
        )
        with self.assertRaises(GameError):
            apply_command(game, hiro, "hiro_forgery.publish", {"text": "同日第二次"})
        game["day"] += 1
        marked = apply_command(
            game, hiro, "hiro_forgery.publish", {"text": "另一条伪造遗物", "evidence": True}
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
        ):
            storage.initialize()
            with storage.transaction() as db:
                db.execute(
                    "INSERT INTO games(id,state,version,status,created_at) VALUES(?,?,?,?,?)",
                    (
                        game["id"],
                        storage.dumps(game),
                        game["version"],
                        game["status"],
                        storage.now_text(),
                    ),
                )
                first = storage.add_events(db, game["id"], plain)
                second = storage.add_events(db, game["id"], marked)
                visible = storage.messages(db, game["id"], other)["messages"]
                self.assertEqual([m["text"] for m in visible], ["伪造的遗物", "另一条伪造遗物"])
                self.assertEqual(
                    [m["id"] for m in storage.messages(db, game["id"], host)["messages"]],
                    [m["id"] for m in [*first, *second]],
                )
                unentered = {"id": "host", "kind": "host", "host_entered": False, "access_ids": []}
                self.assertEqual(
                    [m["text"] for m in storage.messages(db, game["id"], unentered)["messages"]],
                    ["伪造的遗物", "另一条伪造遗物"],
                )
                references = storage.reference_events(db, game["id"])
                self.assertEqual([item["text"] for item in references], ["另一条伪造遗物"])
                item = references[0]
                text = "#" + item["label"]
                ref = SimpleNamespace(type="event", id=item["id"], start=0, end=len(text))
                self.assertEqual(
                    chat_references(db, game["id"], text, [ref])["items"][0]["text"],
                    "另一条伪造遗物",
                )


if __name__ == "__main__":
    unittest.main()
