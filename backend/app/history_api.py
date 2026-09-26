"""历史对局接口：任何已登录身份都可以查看已归档的对局。

历史是**公开记录**（胜负、七个席位的两张角色牌、公屏与全场公告时间线），所以这里
只需要登录，不做逐局放行；私信与只发给个人的情报在归档时就被排除了（见
``history_storage``）。主持人用的是同一条令牌，只是身份种类不同，因此鉴权用
``auth.actor_for_token`` 而不是只认玩家账号的 ``auth.require_account``。
删除整条历史是 4 级及以上主持人的账号级维护操作，不需要先进入某一局的管理界面。
"""

from fastapi import APIRouter, HTTPException, Query, Request

from . import auth, history_storage, storage

router = APIRouter(prefix="/api/history")


def require_reader(request):
    with storage.connect() as db:
        actor = auth.actor_for_token(db, auth.token_hash(request))
    if not actor:
        raise HTTPException(401, "登录已失效")
    return actor


@router.get("")
async def history(
    request: Request,
    limit: int = Query(default=history_storage.DEFAULT_PAGE, ge=1, le=history_storage.PAGE_LIMIT),
    before: str | None = Query(default=None, max_length=64),
):
    """历史对局列表：最近结束的在前；``before`` 用上一页最后一条的 ended_at。"""
    require_reader(request)
    return history_storage.matches(limit=limit, before=before)


@router.get("/{match_id}")
async def match_detail(match_id: str, request: Request):
    require_reader(request)
    detail = history_storage.match(match_id)
    if not detail:
        raise HTTPException(404, "历史对局不存在")
    return detail


@router.delete("/{match_id}")
async def delete_match(match_id: str, request: Request):
    """删除一条历史对局：4 级及以上主持人的维护操作（与是否进入某局管理界面无关）。"""
    with storage.connect() as db:
        auth.require_host_level(db, request, 4)
    if not history_storage.delete(match_id):
        raise HTTPException(404, "历史对局不存在")
    return {"ok": True}
