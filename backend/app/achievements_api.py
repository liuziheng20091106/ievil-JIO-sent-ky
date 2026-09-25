"""Achievement endpoints: host-managed definitions and grants, player-owned display.

权限边界：定义的新建/修改/删除、给谁授权、撤销授权都需要 3 级及以上主持，且稀有度
不能超过该等级的上限（3 级 ≤3、4 级 ≤4、5 级全部）；玩家只能读自己的成就并佩戴其中
一个，且只能佩戴自己名下的记录。头像摘要与对局内的佩戴信息是公开的展示数据——
前者任何已登录身份可读，后者只有该局的主持人/参与者/观战者可读。
"""

from fastapi import APIRouter, HTTPException, Request

from . import achievement_storage, auth, auth_storage, schemas, storage

router = APIRouter(prefix="/api/achievements")


def require_achievement_host(request):
    """成就管理需要 3 级及以上主持（先鉴权，再看目标是否存在）。"""
    with storage.connect() as db:
        return auth.require_host_level(db, request, 3)


def check_rarity(actor, rarity):
    """各级主持只能碰自己档位内的稀有度：3 级 ≤3、4 级 ≤4、5 级全部。"""
    level = int(actor.get("host_level", 0))
    limit = auth_storage.HOST_ACHIEVEMENT_LIMITS.get(level, 0)
    if int(rarity) > limit:
        raise HTTPException(
            403, f"你当前是 {level} 级主持，最多只能分发稀有度 {limit} 的成就"
        )
    return actor


def require_host(request):
    return require_achievement_host(request)


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
    check_rarity(require_achievement_host(request), body.rarity)
    return achievement_storage.create_definition(body.name, body.detail, body.rarity)


@router.post("/defs/{achievement_id}")
async def update_definition(achievement_id: str, body: schemas.Achievement, request: Request):
    actor = require_achievement_host(request)
    existing = achievement_storage.definition(achievement_id)
    if not existing:
        raise HTTPException(404, "成就不存在")
    # 改前改后都要在自己档位内：不能把别人的高级成就改低，也不能改成超出上限。
    check_rarity(actor, max(body.rarity, existing["rarity"]))
    return achievement_storage.update_definition(
        achievement_id, body.name, body.detail, body.rarity
    )


@router.delete("/defs/{achievement_id}")
async def delete_definition(achievement_id: str, request: Request):
    actor = require_achievement_host(request)
    existing = achievement_storage.definition(achievement_id)
    if not existing:
        raise HTTPException(404, "成就不存在")
    check_rarity(actor, existing["rarity"])
    result = achievement_storage.delete_definition(achievement_id)
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
    actor = require_achievement_host(request)
    definition = achievement_storage.definition(body.achievement_id)
    if not definition:
        raise HTTPException(409, "成就已不存在")
    check_rarity(actor, definition["rarity"])
    created = achievement_storage.grant(account_id, body.achievement_id, account_name(account_id))
    if not created:
        raise HTTPException(409, "该玩家已经获得过这个成就")
    return created


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: str, request: Request):
    actor = require_achievement_host(request)
    grant = achievement_storage.grant_by_id(grant_id)
    if not grant:
        raise HTTPException(404, "授权记录不存在")
    check_rarity(actor, grant["rarity"])
    achievement_storage.revoke(grant_id)
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
    """本局每个参与身份佩戴的成就：按参与者 id 给，对局内昵称旁直接显示。

    主持人不是本局的参与身份，但主持账号与它的玩家身份本来就是同一个 QQ 账号，
    成就（含佩戴）完全同步，所以这里额外补一行 participant_id 为 "host" 的记录，
    让对局内的主持人也有徽章与可点开的成就摘要。
    """
    with storage.connect() as db:
        actor = auth.require_actor(db, request, game_id)
        # 未确认进入本局管理界面的主持人还不算本局身份，不给本局的佩戴信息。
        auth.require_host_capable(actor)
        rows = db.execute(
            """SELECT id, account_id FROM participants
               WHERE game_id=? AND active=1 AND blocked=0""",
            (game_id,),
        ).fetchall()
        game = storage.load_game(db, game_id)
    participants = [
        {
            "participant_id": row["id"],
            "account_id": row["account_id"],
            "equipped": achievement_storage.equipped(row["account_id"]),
        }
        for row in rows
    ]
    host_account = ((game or {}).get("host") or {}).get("account_id") or ""
    if host_account:
        participants.append(
            {
                "participant_id": "host",
                "account_id": host_account,
                "equipped": achievement_storage.equipped(host_account),
            }
        )
    return {"participants": participants}
