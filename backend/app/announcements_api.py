"""公告接口：5 级主持（系统管理员）发布，其余已登录身份只读。

正文是 markdown，服务端只做长度与形状校验，不解析内容；客户端负责渲染，并按每条
公告的 sha256 记录已读。
"""

from fastapi import APIRouter, HTTPException, Request

from . import announcement_storage, auth, auth_storage, schemas, storage
from .game.state import display_player_name

router = APIRouter(prefix="/api/announcements")


def require_reader(request):
    """任何已登录身份（主持人或 QQ 玩家）都可以读公告。"""
    with storage.connect() as db:
        actor = auth.actor_for_token(db, auth.token_hash(request))
    if not actor:
        raise HTTPException(401, "登录已失效")
    return actor


def require_admin(request):
    with storage.connect() as db:
        return auth.require_host_level(db, request, auth_storage.HOST_LEVEL_MAX)


@router.get("/public")
async def public_announcements():
    """公开只读：不需要登录。供网页首页展示，不含任何私密信息。"""
    return announcement_storage.lobby_payload()


@router.get("")
async def list_announcements(request: Request):
    require_reader(request)
    items = announcement_storage.announcements()
    return {
        "announcements": items,
        "announcements_version": announcement_storage.version(items),
    }


@router.post("")
async def create_announcement(body: schemas.Announcement, request: Request):
    actor = require_admin(request)
    account_id = actor.get("account_id") or ""
    account = auth_storage.account(account_id) if account_id else None
    # 署名用 QQ 昵称；对局里显示的主持人名字仍是「主持人」。
    author = display_player_name(account["nickname"] if account else actor["name"])
    return announcement_storage.create(body.title, body.body, account_id, author)


@router.post("/{announcement_id}")
async def update_announcement(
    announcement_id: str, body: schemas.Announcement, request: Request
):
    require_admin(request)
    updated = announcement_storage.update(announcement_id, body.title, body.body)
    if not updated:
        raise HTTPException(404, "公告不存在")
    return updated


@router.delete("/{announcement_id}")
async def delete_announcement(announcement_id: str, request: Request):
    require_admin(request)
    if not announcement_storage.delete(announcement_id):
        raise HTTPException(404, "公告不存在")
    return {"ok": True}
