"""Observable optional Meruru vote behavior and aggregate-only disclosure."""

from copy import deepcopy
import unittest

from backend.app.game import apply_command
from backend.app.game.engine import open_vote
from backend.app.game.external_plugins import meruru_vote_balance as balance
from backend.app.game.state import eligible_voters, seat_choice
from checks.rule_factory import arranged_game, player

HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}


class MeruruVoteBalance(unittest.TestCase):
    def test_eligibility_excludes_only_current_controlled_puppets_without_changing_game(self):
        game = arranged_game("voting")
        game["cards"]["meruru"]["witch"] = True
        game["cards"]["millia"]["states"]["puppet"] = "meruru"
        game["cards"]["coco"]["states"]["puppet"] = "missing-master"
        game["cards"]["leia"]["states"]["no_vote"] = True
        before = deepcopy(game)
        context = {"voters": eligible_voters(game)}
        balance.vote_eligibility(game, [], context)
        self.assertEqual([s["id"] for s in context["voters"]], ["2", "3", "4", "6", "7"])
        self.assertEqual(game, before)

    def test_frozen_tally_gate_and_duel_threshold(self):
        for yes, duel, expected in (
            (3, False, (4, 7, 4)),
            (2, False, (2, 7, 4)),
            (3, True, (3, 7, 3)),
            (2, True, (2, 7, 3)),
        ):
            with self.subTest(yes=yes, duel=duel):
                tally = {
                    "yes": yes,
                    "denominator": 6,
                    "threshold": 3 if duel else 4,
                    "duel": duel,
                    "candidate": "3",
                    "excluded_puppets": 1,
                }
                balance.vote_tally({}, [], tally)
                self.assertEqual((tally["yes"], tally["denominator"], tally["threshold"]), expected)
        no_puppet = {
            "yes": 3,
            "denominator": 6,
            "threshold": 4,
            "duel": False,
            "candidate": "3",
            "excluded_puppets": 0,
        }
        unchanged = no_puppet.copy()
        balance.vote_tally({}, [], no_puppet)
        self.assertEqual(no_puppet, unchanged)

    def vote(self, selected, yes_seats, *, puppet=True):
        game = arranged_game("nomination")
        if selected:
            game["rule_plugins"].append({"id": balance.ID, "version": balance.VERSION})
        game["cards"]["meruru"]["witch"] = True
        if puppet:
            game["cards"]["millia"]["states"].update(puppet="meruru", no_ability=True)
        game["nominations"] = [{"seat_id": "3", "card_id": "meruru", "by": "2"}]
        events = []
        open_vote(game, events)
        self.assertEqual(game["vote_freeze"]["denominator"], 6 if selected and puppet else 7)
        for sid in ("1", "3", "4", "5", "6", "7"):
            if puppet and sid == "1":
                continue
            apply_command(
                game,
                player(game, sid),
                "vote.cast",
                {"meruru": "yes" if sid in yes_seats else "no"},
            )
        events += apply_command(game, HOST, "host.advance", {})
        return game, events

    def test_enabled_vs_disabled_and_no_fabricated_ballot_or_private_disclosure(self):
        enabled, events = self.vote(True, {"3", "4"})
        disabled, _ = self.vote(False, {"3", "4"})
        self.assertEqual(
            enabled["vote_rounds"][0],
            {"candidate": "3", "yes": 4, "denominator": 7, "threshold": 4, "passed": True},
        )
        self.assertEqual(
            disabled["vote_rounds"][0],
            {"candidate": "3", "yes": 3, "denominator": 7, "threshold": 4, "passed": False},
        )
        self.assertIn("meruru", enabled["execution"])
        self.assertNotIn("meruru", disabled["execution"])
        self.assertEqual(
            sum(
                seat_choice(enabled, sid, "meruru") == "yes"
                for sid in ("2", "3", "4", "5", "6", "7")
            ),
            3,
        )
        self.assertNotIn("1", enabled["ballots"])
        public_text = " ".join(event["text"] for event in events if event.get("audience") is None)
        self.assertIn("同意4/7，门槛4", public_text)
        self.assertNotIn("傀儡", public_text)
        self.assertNotIn("傀儡", " ".join(row["text"] for row in enabled["log"]))

        below_gate, _ = self.vote(True, {"3"})
        self.assertEqual(below_gate["vote_rounds"][0]["yes"], 2)
        self.assertEqual(below_gate["vote_rounds"][0]["denominator"], 7)
        self.assertFalse(below_gate["vote_rounds"][0]["passed"])

        no_puppet, _ = self.vote(True, {"3", "4"}, puppet=False)
        self.assertEqual(no_puppet["vote_rounds"][0], disabled["vote_rounds"][0])


if __name__ == "__main__":
    unittest.main()
