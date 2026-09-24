"""Achievement endpoints: host-managed definitions and grants, player-owned display.

权限边界：定义的新建/修改/删除、给谁授权、撤销授权都只有主持人令牌能做；玩家只能读
自己的成就并佩戴其中一个，且只能佩戴自己名下的记录。头像摘要与对局内的佩戴信息是
公开的展示数据——前者任何已登录身份可读，后者只有该局的主持人/参与者/观战者可读。
"""

from fastapi import APIRouter, HTTPException, Request

from . import achievement_storage, auth, auth_storage, schemas, storage

router = APIRouter(prefix="/api/achievements")


def require_host(request):
    with storage.connect() as db:
        return auth.require_actor(db, request, host=True)


def require_reader(request):
    """任何已登录身份（主持人或 QQ 玩家）都可以读公开的成就展示数据。"""
    with storage.connect() as db:
        actor = auth.actor_for_token(db, auth.token_hash(request))
    if not actor:
        raise HTTPException(401, "登录已失效")
    return actor


def account_name(account_id):
    account = auth_storage.account(account_id)
    if account:
        return account["nickname"]
    row = achievement_storage.player_row(account_id)
    return (row or {}).get("nickname") or account_id


@router.get("/catalog")
async def catalog(request: Request):
    """成就目录：玩家用它看自己拿到的成就，主持人用它挑要授权的成就。"""
    require_reader(request)
    return {
        "achievements": achievement_storage.definitions(),
        "max_rarity": achievement_storage.MAX_RARITY,
    }


@router.post("/defs")
async def create_definition(body: schemas.Achievement, request: Request):
    require_host(request)
    return achievement_storage.create_definition(body.name, body.detail, body.rarity)


@router.post("/defs/{achievement_id}")
async def update_definition(achievement_id: str, body: schemas.Achievement, request: Request):
    require_host(request)
    updated = achievement_storage.update_definition(
        achievement_id, body.name, body.detail, body.rarity
    )
    if not updated:
        raise HTTPException(404, "成就不存在")
    return updated


@router.delete("/defs/{achievement_id}")
async def delete_definition(achievement_id: str, request: Request):
    require_host(request)
    result = achievement_storage.delete_definition(achievement_id)
    if not result["deleted"]:
        raise HTTPException(404, "成就不存在")
    return {"ok": True, "removed_grants": result["removed_grants"]}


@router.get("/players")
async def players(request: Request):
    """总玩家列表：参加过对局或获得过成就的账号，最近的参赛顺序在前。"""
    require_host(request)
    rows = achievement_storage.player_rows()
    listed = []
    for row in rows:
        account = auth_storage.account(row["account_id"])
        listed.append(
            {
                "account_id": row["account_id"],
                "name": (account["nickname"] if account else row["nickname"])
                or row["account_id"],
                "avatar_url": account["avatar_url"] if account else "",
                "last_played_at": row["last_played_at"],
                "achievement_count": row["achievement_count"],
                "equipped": row["equipped"],
                "achievements": achievement_storage.grants_for(row["account_id"]),
            }
        )
    # 两趟稳定排序：先按昵称，再按最近参赛时间倒序——从未参赛的排在最后。
    listed.sort(key=lambda item: item["name"])
    listed.sort(key=lambda item: item["last_played_at"] or "", reverse=True)
    return {"players": listed, "max_rarity": achievement_storage.MAX_RARITY}


@router.post("/players/{account_id}/grants")
async def create_grant(account_id: str, body: schemas.AchievementGrant, request: Request):
    require_host(request)
    created = achievement_storage.grant(account_id, body.achievement_id, account_name(account_id))
    if not created:
        raise HTTPException(409, "该玩家已经获得过这个成就，或成就已不存在")
    return created


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: str, request: Request):
    require_host(request)
    if not achievement_storage.revoke(grant_id):
        raise HTTPException(404, "授权记录不存在")
    return {"ok": True}


@router.get("/me")
async def my_achievements(request: Request):
    account = auth.require_account(request)
    return {
        "achievements": achievement_storage.grants_for(account["id"]),
        "equipped": achievement_storage.equipped(account["id"]),
        "max_rarity": achievement_storage.MAX_RARITY,
    }


@router.post("/me/equip")
async def equip(body: schemas.AchievementEquip, request: Request):
    account = auth.require_account(request)
    if not achievement_storage.equip(account["id"], body.grant_id):
        raise HTTPException(403, "只能佩戴自己已经获得的成就")
    return {"ok": True, "equipped": achievement_storage.equipped(account["id"])}


@router.get("/accounts/{account_id}")
async def account_summary(account_id: str, request: Request):
    """头像摘要：总成就数 + 最稀有的 5 个（名 + 详细）。"""
    require_reader(request)
    grants = achievement_storage.grants_for(account_id)
    return {
        "account_id": account_id,
        "name": account_name(account_id),
        "total": len(grants),
        "equipped": achievement_storage.equipped(account_id),
        "top": grants[:5],
        "max_rarity": achievement_storage.MAX_RARITY,
    }


@router.get("/games/{game_id}/equipped")
async def game_equipped(game_id: str, request: Request):
    """本局每个参与身份佩戴的成就：按参与者 id 给，对局内昵称旁直接显示。"""
    with storage.connect() as db:
        auth.require_actor(db, request, game_id)
        rows = db.execute(
            """SELECT id, account_id FROM participants
               WHERE game_id=? AND active=1 AND blocked=0""",
            (game_id,),
        ).fetchall()
    return {
        "participants": [
            {
                "participant_id": row["id"],
                "account_id": row["account_id"],
                "equipped": achievement_storage.equipped(row["account_id"]),
            }
            for row in rows
        ]
    }
