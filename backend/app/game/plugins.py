"""Trusted, deployment-time rule modules; saved games pin their exact versions."""

from importlib import import_module
from pathlib import Path

from .catalog import ROLES
from .state import GameError
from .roles import (
    emma,
    hiro,
    hanna,
    sherry,
    meruru,
    noah,
    annan,
    millia,
    coco,
    nanoka,
    arisa,
    marg,
    leia,
    honoka,
)


class PluginMismatch(GameError):
    pass


BUILTINS = (
    emma,
    hiro,
    hanna,
    sherry,
    meruru,
    noah,
    annan,
    millia,
    coco,
    nanoka,
    arisa,
    marg,
    leia,
    honoka,
)

EXTERNAL_DIR = Path(__file__).with_name("external_plugins")


def discover_external():
    """Import administrator-deployed modules once; dependencies determine event order."""
    waiting = [
        import_module(f"{__package__}.external_plugins.{path.stem}")
        for path in sorted(EXTERNAL_DIR.glob("*.py"))
        if path.stem != "__init__" and path.stem.isidentifier() and not path.stem.startswith("_")
    ]
    ordered = []
    known = {module.ID for module in BUILTINS}
    while waiting:
        ready = next((module for module in waiting if set(module.DEPENDS) <= known), None)
        if ready is None:
            raise ValueError("外置规则模块依赖缺失或形成循环")
        ordered.append(ready)
        known.add(ready.ID)
        waiting.remove(ready)
    return ordered


REGISTRY = [*BUILTINS, *discover_external()]


def category(module):
    return "builtin_required" if module in BUILTINS else module.CATEGORY


def info(module):
    from .catalog import ROLES

    if module in BUILTINS:
        role = ROLES[module.ID]
        name = role["name"]
        description = f"普通：{role['normal']}\n魔女化：{role['witch']}"
    else:
        name, description = module.NAME, module.DESCRIPTION
    kind = category(module)
    return {
        "id": module.ID,
        "name": name,
        "version": module.VERSION,
        "description": description,
        "category": kind,
        "depends": list(module.DEPENDS),
        "required": kind.endswith("required"),
        "default_enabled": kind in {"builtin_required", "external_required", "external_default_on"},
    }


def catalog():
    return [info(module) for module in REGISTRY]


def manifest(selected=None):
    optional_ids = {
        module.ID
        for module in REGISTRY
        if category(module) in {"external_default_on", "external_default_off"}
    }
    if selected is None:
        chosen = {module.ID for module in REGISTRY if category(module) == "external_default_on"}
    else:
        if not isinstance(selected, list) or any(not isinstance(pid, str) for pid in selected):
            raise GameError("附加规则选择无效")
        chosen = set(selected)
        if len(chosen) != len(selected) or not chosen <= optional_ids:
            raise GameError("附加规则选择无效")
    enabled_ids = {
        module.ID for module in REGISTRY if category(module).endswith("required")
    } | chosen
    if any(
        not set(module.DEPENDS) <= enabled_ids for module in REGISTRY if module.ID in enabled_ids
    ):
        raise GameError("附加规则缺少依赖")
    return [
        {"id": module.ID, "version": module.VERSION}
        for module in REGISTRY
        if module.ID in enabled_ids
    ]


def validate_registry():
    ids, commands, required_roles = set(), set(), []
    valid = {"external_required", "external_default_on", "external_default_off"}
    for module in REGISTRY:
        kind = category(module)
        if not isinstance(module.ID, str) or not module.ID.isidentifier() or module.ID in ids:
            raise ValueError(f"规则模块 ID 无效：{module.ID}")
        if module not in BUILTINS and kind not in valid:
            raise ValueError(f"规则模块分类无效：{module.ID}")
        if not isinstance(module.VERSION, int) or module.VERSION < 1:
            raise ValueError(f"规则模块版本无效：{module.ID}")
        if module in BUILTINS:
            required_roles.append(module.ID)
        elif (
            not isinstance(module.NAME, str)
            or not module.NAME.strip()
            or not isinstance(module.DESCRIPTION, str)
            or not module.DESCRIPTION.strip()
        ):
            raise ValueError(f"规则模块名称或简介无效：{module.ID}")
        default_ids = {
            other.ID
            for other in REGISTRY
            if category(other).endswith("required") or category(other) == "external_default_on"
        }
        if kind == "external_default_on" and not set(module.DEPENDS) <= default_ids:
            raise ValueError(f"默认启用模块依赖默认未启用模块：{module.ID}")
        if commands.intersection(module.COMMANDS) or any(
            not command.startswith(module.ID + ".") for command in module.COMMANDS
        ):
            raise ValueError(f"规则模块命令 ID 重复或前缀无效：{module.ID}")
        commands.update(module.COMMANDS)
        ids.add(module.ID)
    if required_roles != list(ROLES):
        raise ValueError("必需角色模块与角色目录不一致")


def required_manifest():
    return [
        {"id": module.ID, "version": module.VERSION}
        for module in REGISTRY
        if category(module).endswith("required")
    ]


def enabled(game):
    selected = {item["id"] for item in game["rule_plugins"]}
    return [module for module in REGISTRY if module.ID in selected]


def require_compatible(game):
    saved = game["rule_plugins"]
    registered = {module.ID: module for module in REGISTRY}
    seen = set()
    for entry in saved:
        module = registered.get(entry.get("id"))
        if module is None or entry.get("version") != module.VERSION:
            raise PluginMismatch(
                f"规则模块不兼容：{entry.get('id')}，保存版本 {entry.get('version')}，当前版本 {module.VERSION if module else '未部署'}"
            )
        if entry["id"] in seen or any(dep not in seen for dep in module.DEPENDS):
            raise PluginMismatch(f"规则模块重复或缺少前置依赖：{module.ID}")
        seen.add(module.ID)
    if any(module.ID not in seen for module in REGISTRY if category(module).endswith("required")):
        raise PluginMismatch("规则模块缺少必需模块")
    if [entry["id"] for entry in saved] != [module.ID for module in REGISTRY if module.ID in seen]:
        raise PluginMismatch("规则模块注册顺序与存档不一致")


def emit(game, events, kind, context):
    for module in enabled(game):
        handler = module.HANDLERS.get(kind)
        if handler:
            result = handler(game, events, context)
            if result == "stop":
                break
            if result is not None:
                raise GameError(f"规则模块 {module.ID} 的事件返回值无效")


validate_registry()
