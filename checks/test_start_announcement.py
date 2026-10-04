"""Start announcements respect selection, saved games and the one-time start boundary."""

import unittest

from backend.app.game import GameError, apply_command, plugins
from backend.app.game.external_plugins import start_announcement
from backend.app.game.state import upgrade_game
from checks.rule_factory import arranged_game

HOST = {"id": "host", "kind": "host", "host_entered": True}


class StartAnnouncementRules(unittest.TestCase):
    def test_start_announces_only_when_enabled(self):
        for selection, legacy, expected in ((None, False, 1), ([], False, 0), (None, True, 0)):
            with self.subTest(selection=selection, legacy=legacy):
                game = arranged_game("ordering", "night")
                game.update(status="lobby", day=1, rule_plugins=plugins.manifest(selection))
                if legacy:
                    del game["rule_plugins"]
                    upgrade_game(game)
                events = apply_command(game, HOST, "host.start", {})
                announcements = [
                    event for event in events if event.get("title") == start_announcement.NAME
                ]
                self.assertEqual(
                    announcements,
                    [
                        {
                            "kind": "alert",
                            "text": start_announcement.ANNOUNCEMENT,
                            "audience": None,
                            "title": start_announcement.NAME,
                        }
                    ]
                    if expected
                    else [],
                )
                self.assertEqual(game["status"], "playing")
                with self.assertRaises(GameError):
                    apply_command(game, HOST, "host.start", {})
                self.assertFalse(
                    any(
                        event.get("title") == start_announcement.NAME
                        for event in apply_command(game, HOST, "host.auto", {})
                    )
                )


if __name__ == "__main__":
    unittest.main()
