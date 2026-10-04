"""Animation metadata is snapshotted with the skill, never inferred from a later game state."""

from random import SystemRandom

from .catalog import ROLES

SKILL_SCRIPT = "scripts/skill-cut-in.json"
SPEECH_SCRIPT = "scripts/interrogation-start.json"
# Specific role/ability scripts replace the default here, for both active and passive cards.
SKILL_SCRIPTS = {
    ("emma", "interrupt"): "scripts/emma-interrupt-{expression}.json",
    ("hiro", "forgery"): "scripts/hiro-forgery-{expression}.json",
    ("emma", "challenge_success"): "scripts/emma-challenge-success.json",
    ("hiro", "challenge_success"): "scripts/hiro-challenge-success.json",
}


def skill_animation_snapshot(role_id, ability, ability_name, witch):
    script = SKILL_SCRIPTS.get(
        (role_id, ability),
        "scripts/challenge-success.json" if ability == "challenge_success" else SKILL_SCRIPT,
    )
    role_name = ROLES[role_id]["name"]
    expression = None
    if ability == "challenge_success":
        expression = {"emma": 2, "hiro": 3}.get(role_id)
    elif (role_id, ability) in {("emma", "interrupt"), ("hiro", "forgery")}:
        expression = SystemRandom().randrange(1, 4)
        script = script.format(expression=expression)

    def animation(ex):
        images = {"skill-portrait": f"{role_id}/{'EX' if ex else 'normal'}/1.png"}
        if ability == "challenge_success" and role_id == "honoka" and not ex:
            images = {"skill-portrait": "warden-portrait.png"}
        if expression is not None:
            images = {
                "skill-portrait": (
                    "emma/EX/1.png"
                    if role_id == "emma" and ex
                    else f"scripts/images/{role_id}-{'interrupt' if role_id == 'emma' else 'forgery'}/"
                    f"portrait-{'ex-' if role_id == 'hiro' and ex else ''}{expression}.webp"
                )
            }
        return {
            "script": script,
            "images": images,
            "texts": {
                "role-title": f"{role_name} · {'魔女' if ex else '普通'}",
                "skill-name": ability_name,
            },
        }

    public = animation(False)
    return {"public": public, "owner": animation(True) if witch else public}


def speech_animation():
    return {"script": SPEECH_SCRIPT, "images": {}, "texts": {}}
