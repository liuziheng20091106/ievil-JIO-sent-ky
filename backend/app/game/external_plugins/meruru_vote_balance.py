"""Optional Meruru rule: puppets cannot cast ballots, but affect the tally."""

from ..state import current, puppet_master

ID = "meruru_vote_balance"
VERSION = 1
NAME = "梅露露傀儡平衡性调整"
DESCRIPTION = "自动修正投票结果以实现傀儡不占票位的效果，隐藏傀儡事实的同时调整平衡性。"
CATEGORY = "external_default_off"
DEPENDS = ("meruru",)
COMMANDS = {}


def vote_eligibility(game, events, context):
    frozen = game.get("vote_freeze") or {}
    if frozen.get("day") == game.get("day") and "excluded_puppet_seats" in frozen:
        excluded = set(frozen["excluded_puppet_seats"])
    else:
        excluded = {
            seat["id"]
            for seat in context["voters"]
            if (card := current(game, seat))
            and card["states"].get("puppet")
            and puppet_master(game, card) is not None
        }
    context["excluded_puppet_seats"] = sorted(excluded)
    context["excluded_puppets"] = len(excluded)
    context["voters"][:] = [seat for seat in context["voters"] if seat["id"] not in excluded]


def vote_tally(game, events, context):
    excluded = context["excluded_puppets"]
    if not excluded:
        return
    real = context["denominator"]
    nominal = real + excluded
    threshold = max(1, nominal // 2) if context["duel"] else nominal // 2 + 1
    yes = context["yes"]
    context["denominator"] = nominal
    context["threshold"] = threshold
    if yes >= (real + 1) // 2 and yes < threshold:
        context["yes"] += min(excluded, threshold - yes)


HANDLERS = {"vote_eligibility": vote_eligibility, "vote_tally": vote_tally}
