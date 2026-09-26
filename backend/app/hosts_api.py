"""主持授权接口：4 级可授权/取消 1-3 级，5 级可授权/取消 1-5 级。

授权与 QQ 账号绑定：内置管理员由 GAME_ADMIN_QQ 指定（恒为 5 级，不受这里管理），
其余账号的等级存在鉴权库的 host_authorizations 里。1 级只主持 1 局，那一局结束后
授权自动作废（见 auth_storage.consume_single_use_for_game）。
"""

from fastapi import APIRouter, HTTPException, Query, Request

from . import auth, auth_storage, schemas, storage
from .game.state import display_player_name

router = APIRouter(prefix="/api/hosts")


def require_manager(request):
    """4 级及以上才能看/改主持授权。"""
    with storage.connect() as db:
        return auth.require_host_level(db, request, 4)


def grantable_limit(actor):
    return auth_storage.HOST_GRANT_LIMITS.get(int(actor.get("host_level", 0)), 0)


def account_view(row, level, *, builtin=False, authorization=None):
    authorization = authorization or {}
    return {
        "account_id": row["id"],
        "name": display_player_name(row["nickname"]),
        "qq_id": row["qq_id"],
        "avatar_url": row["avatar_url"],
        "level": int(level),
        # consumed：1 级授权已经用完那一局，实际等级为 0，需要重新授权。
        "consumed": bool(authorization.get("consumed_at")),
        "builtin": builtin,
        "granted_by": authorization.get("granted_by"),
        "granted_at": authorization.get("granted_at"),
        "hosted_game_id": authorization.get("hosted_game_id"),
    }


@router.get("")
async def list_hosts(request: Request):
    """授权名单：内置管理员 + 已被授权的账号（含已经用完 1 局权限的）。"""
    actor = require_manager(request)
    listed = []
    seen = set()
    for qq_id in sorted(auth.admin_qq_ids()):
        row = auth_storage.account_by_qq(qq_id)
        if not row or row["id"] in seen:
            continue
        seen.add(row["id"])
        listed.append(account_view(row, auth_storage.HOST_LEVEL_MAX, builtin=True))
    for stored in auth_storage.host_authorizations():
        account = auth_storage.account(stored["account_id"])
        if not account or account["id"] in seen:
            continue
        seen.add(account["id"])
        listed.append(
            account_view(account, stored["level"], authorization=stored)
        )
    listed.sort(key=lambda item: (-item["level"], item["name"]))
    return {
        "hosts": listed,
        "min_level": auth_storage.HOST_LEVEL_MIN,
        "max_level": auth_storage.HOST_LEVEL_MAX,
        "grantable": grantable_limit(actor),
    }


@router.get("/accounts")
async def search_accounts(
    request: Request,
    q: str = Query(default="", max_length=40),
    limit: int = Query(default=20, ge=1, le=50),
):
    """按昵称或 QQ 号找账号：授权页用它挑人（这里显示 QQ 号，便于区分同名）。"""
    require_manager(request)
    result = []
    for row in auth_storage.accounts_matching(q, limit=limit):
        stored = auth_storage.host_authorization(row["id"])
        builtin = row["qq_id"] in auth.admin_qq_ids()
        level = auth_storage.HOST_LEVEL_MAX if builtin else (stored["level"] if stored else 0)
        result.append(account_view(row, level, builtin=builtin, authorization=stored))
    return {"accounts": result}


@router.post("/{account_id}")
async def authorize(account_id: str, body: schemas.HostAuthorization, request: Request):
    with storage.connect() as db:
        actor = auth.require_host_level(db, request, 4)
    limit = grantable_limit(actor)
    if not auth_storage.HOST_LEVEL_MIN <= body.level <= limit:
        raise HTTPException(
            403, f"你只能授权 {auth_storage.HOST_LEVEL_MIN}-{limit} 级主持"
        )
    account = auth_storage.account(account_id)
    if not account:
        raise HTTPException(404, "账号不存在")
    if account["qq_id"] in auth.admin_qq_ids():
        raise HTTPException(409, "该账号是内置管理员，始终为 5 级，不需要授权")
    return account_view(
        account,
        body.level,
        authorization=auth_storage.authorize_host(
            account_id, body.level, granted_by=actor.get("account_id") or ""
        ),
    )


@router.delete("/{account_id}")
async def revoke(account_id: str, request: Request):
    with storage.connect() as db:
        actor = auth.require_host_level(db, request, 4)
    limit = grantable_limit(actor)
    account = auth_storage.account(account_id)
    if not account:
        raise HTTPException(404, "账号不存在")
    if account["qq_id"] in auth.admin_qq_ids():
        raise HTTPException(409, "内置管理员的权限由服务端配置决定，不能在界面取消")
    stored = auth_storage.host_authorization(account_id)
    if not stored:
        raise HTTPException(404, "该账号没有授权记录")
    if int(stored["level"]) > limit:
        raise HTTPException(403, f"你不能取消 {limit} 级以上的主持授权")
    auth_storage.revoke_host(account_id)
    return {"ok": True}
