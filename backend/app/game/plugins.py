"""Trusted, deployment-time rule modules; saved games pin their exact versions."""

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


REGISTRY = [
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
]


def validate_registry():
    ids = set()
    commands = set()
    required = []
    layer_rank = {"role": 0, "patch": 1, "experiment": 2}
    previous_rank = 0
    for module in REGISTRY:
        if module.ID in ids or module.LAYER not in layer_rank:
            raise ValueError(f"规则模块 ID 或层级无效：{module.ID}")
        rank = layer_rank[module.LAYER]
        if rank < previous_rank or (module.REQUIRED != (rank == 0)):
            raise ValueError(f"规则模块顺序或必需标记无效：{module.ID}")
        if any(dep not in ids for dep in module.DEPENDS):
            raise ValueError(f"规则模块依赖未在前序注册：{module.ID}")
        if commands.intersection(module.COMMANDS) or any(
            not command.startswith(module.ID + ".") for command in module.COMMANDS
        ):
            raise ValueError(f"规则模块命令 ID 重复或前缀无效：{module.ID}")
        commands.update(module.COMMANDS)
        if module.REQUIRED:
            required.append(module.ID)
        ids.add(module.ID)
        previous_rank = rank
    if required != list(ROLES):
        raise ValueError("必需角色模块与角色目录不一致")


def required_manifest():
    return [{"id": module.ID, "version": module.VERSION} for module in REGISTRY if module.REQUIRED]


def enabled(game):
    selected = {item["id"] for item in game["rule_plugins"]}
    return [module for module in REGISTRY if module.ID in selected]


def optional():
    return [module for module in REGISTRY if not module.REQUIRED]


def require_compatible(game):
    saved = game["rule_plugins"]
    registered = {module.ID: module for module in REGISTRY}
    seen = set()
    for entry in saved:
        module = registered.get(entry.get("id"))
        if module is None or entry.get("version") != module.VERSION:
            raise PluginMismatch(
                f"规则模块不兼容：{entry.get('id')}，保存版本 {entry.get('version')}，"
                f"当前版本 {module.VERSION if module else '未部署'}"
            )
        if entry["id"] in seen or any(dep not in seen for dep in module.DEPENDS):
            raise PluginMismatch(f"规则模块重复或缺少前置依赖：{module.ID}")
        seen.add(module.ID)
    if any(module.ID not in seen for module in REGISTRY if module.REQUIRED):
        raise PluginMismatch("规则模块缺少必需角色")
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
