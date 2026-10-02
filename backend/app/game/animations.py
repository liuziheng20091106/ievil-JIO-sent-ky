"""Animation metadata is snapshotted with the skill, never inferred from a later game state."""

from .catalog import ROLES

SKILL_SCRIPT = "scripts/skill-cut-in.json"
SPEECH_SCRIPT = "scripts/interrogation-start.json"
# Specific role/ability scripts replace the default here, for both active and passive cards.
SKILL_SCRIPTS = {}


def skill_animation_snapshot(role_id, ability, ability_name, witch):
    script = SKILL_SCRIPTS.get((role_id, ability), SKILL_SCRIPT)
    role_name = ROLES[role_id]["name"]

    def animation(ex):
        return {
            "script": script,
            "images": {"skill-portrait": f"{role_id}/{'EX' if ex else 'normal'}/1.png"},
            "texts": {
                "role-title": f"{role_name} · {'魔女' if ex else '普通'}",
                "skill-name": ability_name,
            },
        }

    public = animation(False)
    return {"public": public, "owner": animation(True) if witch else public}


def speech_animation():
    return {"script": SPEECH_SCRIPT, "images": {}, "texts": {}}
