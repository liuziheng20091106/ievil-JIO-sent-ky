"""Achievement boundaries: host-only management, player-owned display, ordering.

成就库独立于对局库，所以这里既验证权限（只有主持人能定义与授权、玩家只能佩戴自己的），
也验证两个独立库的互不影响：建立新对局清空对局数据后，成就定义与授权仍然在。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import achievement_storage, storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


class AchievementFlow(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.env_patch = patch.dict(
            os.environ,
            {
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(
            app,
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        # 管理员 QQ（GAME_ADMIN_QQ）登录后就是 5 级主持。
        self.host, self.host_actor = self.host_login("10001")
        self.created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
        self.created.raise_for_status()
        self.game_id = self.created.json()["id"]
        self.root = f"/api/games/{self.game_id}"

    def host_login(self, qq_id):
        challenge = self.client.post("/api/native/auth/host/challenges").json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "主持" + qq_id,
                "avatar_url": "https://example.invalid/" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get(
            "/api/native/auth/host/challenges/" + challenge["id"]
        )
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return {
            "Authorization": "Bearer " + completed.json()["session_token"]
        }, completed.json()["session"]["actor"]

    def account(self, qq_id):
        challenge = self.client.post("/api/native/auth/challenges").json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "QQ" + qq_id,
                "avatar_url": "https://example.invalid/" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get("/api/native/auth/challenges/" + challenge["id"])
        completed.raise_for_status()
        return (
            {"Authorization": "Bearer " + completed.json()["session_token"]},
            completed.json()["session"]["actor"],
        )

    def join(self, qq_id, kind="player"):
        headers, actor = self.account(qq_id)
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": kind}
        )
        response.raise_for_status()
        return headers, response.json()["actor"], actor

    def command(self, headers, action, payload=None):
        state = self.client.get(self.root + "/state", headers=headers)
        state.raise_for_status()
        response = self.client.post(
            self.root + "/commands",
            headers=headers,
            json={
                "expected_version": state.json()["version"],
                "action": action,
                "payload": payload or {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def define(self, name, detail, rarity, headers=None):
        response = self.client.post(
            "/api/achievements/defs",
            headers=headers or self.host,
            json={"name": name, "detail": detail, "rarity": rarity},
        )
        return response

    def open_join(self):
        self.command(self.host, "room.open_join", {"open": True})

    def test_only_host_defines_and_grants(self):
        player_headers, _ = self.account("10001")
        for response in (
            self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2, headers=player_headers),
            self.client.post(
                "/api/achievements/defs/ach-x",
                headers=player_headers,
                json={"name": "x", "detail": "y", "rarity": 1},
            ),
            self.client.delete("/api/achievements/defs/ach-x", headers=player_headers),
            self.client.post(
                "/api/achievements/players/a1/grants",
                headers=player_headers,
                json={"achievement_id": "ach-x"},
            ),
            self.client.delete("/api/achievements/grants/grant-x", headers=player_headers),
            self.client.get("/api/achievements/players", headers=player_headers),
        ):
            self.assertEqual(response.status_code, 403, response.text)

        # 未登录身份连目录都读不到。
        self.assertEqual(self.client.get("/api/achievements/catalog").status_code, 401)
        self.assertEqual(self.client.get("/api/achievements/players").status_code, 401)

    def test_definition_shape_is_validated(self):
        self.assertEqual(self.define("x", "y", 0).status_code, 422)
        self.assertEqual(self.define("x", "y", 11).status_code, 422)
        self.assertEqual(self.define("", "y", 3).status_code, 422)
        self.assertEqual(self.define("x", "", 3).status_code, 422)
        self.assertEqual(self.define("名" * 25, "y", 3).status_code, 422)
        self.assertEqual(self.define("名" * 24, "内" * 200, 10).status_code, 200)
        # 目录按稀有度倒序，主持人能直接拿到完整定义与已授予人数。
        created = self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2).json()
        catalog = self.client.get("/api/achievements/catalog", headers=self.host).json()
        self.assertEqual(catalog["max_rarity"], 10)
        rarities = [item["rarity"] for item in catalog["achievements"]]
        self.assertEqual(rarities, sorted(rarities, reverse=True))
        listed = {item["id"]: item for item in catalog["achievements"]}
        self.assertIn(created["id"], listed)
        self.assertEqual(listed[created["id"]]["granted_count"], 0)
        self.assertEqual(listed[created["id"]]["detail"], "在一局内控制傀儡未被识破")

    def test_grant_is_unique_and_revocable_and_definition_delete_cascades(self):
        player_headers, actor = self.account("10002")
        first = self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2).json()
        second = self.define("吹笛人", "连续三晚让同一人成为魔女刀目标", 9).json()

        granted = self.client.post(
            f"/api/achievements/players/{actor['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": first["id"]},
        )
        self.assertEqual(granted.status_code, 200, granted.text)
        # 同一个成就对同一个玩家只记一次。
        again = self.client.post(
            f"/api/achievements/players/{actor['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": first["id"]},
        )
        self.assertEqual(again.status_code, 409, again.text)
        # 不存在的成就不能授权。
        missing = self.client.post(
            f"/api/achievements/players/{actor['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": "ach-none"},
        )
        self.assertEqual(missing.status_code, 409, missing.text)

        mine = self.client.get("/api/achievements/me", headers=player_headers).json()
        self.assertEqual([item["name"] for item in mine["achievements"]], ["神秘黑幕女"])
        self.assertIsNone(mine["equipped"])

        # 删除定义会连同授权一起删掉，并给出被移除的授权条数。
        removed = self.client.delete(
            f"/api/achievements/defs/{first['id']}", headers=self.host
        )
        self.assertEqual(removed.json()["removed_grants"], 1)
        self.assertEqual(
            self.client.get("/api/achievements/me", headers=player_headers).json()[
                "achievements"
            ],
            [],
        )
        self.assertEqual(
            self.client.delete(f"/api/achievements/defs/{first['id']}", headers=self.host).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/api/achievements/players/{actor['account_id']}/grants",
                headers=self.host,
                json={"achievement_id": second["id"]},
            ).status_code,
            200,
        )

    def test_player_only_equips_own_grant(self):
        owner_headers, owner = self.account("10003")
        other_headers, other = self.account("10004")
        definition = self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2).json()
        granted = self.client.post(
            f"/api/achievements/players/{owner['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": definition["id"]},
        ).json()

        # 别人的记录佩戴不了。
        stolen = self.client.post(
            "/api/achievements/me/equip", headers=other_headers, json={"grant_id": granted["id"]}
        )
        self.assertEqual(stolen.status_code, 403, stolen.text)

        equipping = self.client.post(
            "/api/achievements/me/equip", headers=owner_headers, json={"grant_id": granted["id"]}
        )
        self.assertEqual(equipping.status_code, 200, equipping.text)
        self.assertEqual(equipping.json()["equipped"]["name"], "神秘黑幕女")
        self.assertEqual(equipping.json()["equipped"]["rarity"], 2)

        # 摘要对任何已登录身份可见：总数 + 最稀有的 5 个。
        summary = self.client.get(
            f"/api/achievements/accounts/{owner['account_id']}", headers=other_headers
        ).json()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["equipped"]["id"], granted["id"])

        # 撤销后佩戴自动清空，摘要也不再有内容。
        self.assertEqual(
            self.client.delete(
                f"/api/achievements/grants/{granted['id']}", headers=self.host
            ).status_code,
            200,
        )
        self.assertIsNone(
            self.client.get("/api/achievements/me", headers=owner_headers).json()["equipped"]
        )
        self.assertEqual(
            self.client.get(
                f"/api/achievements/accounts/{owner['account_id']}", headers=owner_headers
            ).json()["total"],
            0,
        )

    def test_summary_keeps_the_five_rarest(self):
        player_headers, actor = self.account("10005")
        for rarity in range(1, 7):
            definition = self.define(f"成就{rarity}", f"内容{rarity}", rarity).json()
            self.client.post(
                f"/api/achievements/players/{actor['account_id']}/grants",
                headers=self.host,
                json={"achievement_id": definition["id"]},
            )
        summary = self.client.get(
            f"/api/achievements/accounts/{actor['account_id']}", headers=player_headers
        ).json()
        self.assertEqual(summary["total"], 6)
        self.assertEqual([item["rarity"] for item in summary["top"]], [6, 5, 4, 3, 2])
        # 目录里的定义带上已授予人数，方便主持人删除前判断影响。
        catalog = self.client.get("/api/achievements/catalog", headers=self.host).json()
        self.assertTrue(all(item["granted_count"] == 1 for item in catalog["achievements"]))

    def test_player_list_orders_by_recent_participation(self):
        self.open_join()
        self.join("10006")
        first_headers, first_actor = self.account("10007")
        second_headers, second_actor = self.account("10008")
        # 旁观不算参赛，不进入玩家列表。
        self.join("10009", kind="spectator")
        for headers in (first_headers, second_headers):
            response = self.client.post(
                self.root + "/participations", headers=headers, json={"kind": "player"}
            )
            response.raise_for_status()

        listed = self.client.get("/api/achievements/players", headers=self.host).json()["players"]
        names = [item["name"] for item in listed]
        self.assertEqual(len(listed), 3)
        self.assertNotIn("QQ10009", names)
        # 最后参赛的排在最前。
        self.assertEqual(names[0], "QQ10008")
        self.assertEqual(names[1], "QQ10007")
        self.assertEqual(names[2], "QQ10006")
        self.assertTrue(all(item["achievement_count"] == 0 for item in listed))

    def test_game_equipped_map_is_scoped_to_the_game(self):
        self.open_join()
        player_headers, actor = self.account("10010")
        joined = self.client.post(
            self.root + "/participations", headers=player_headers, json={"kind": "player"}
        )
        joined.raise_for_status()
        participant_id = joined.json()["actor"]["id"]
        definition = self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2).json()
        granted = self.client.post(
            f"/api/achievements/players/{actor['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": definition["id"]},
        ).json()
        self.client.post(
            "/api/achievements/me/equip", headers=player_headers, json={"grant_id": granted["id"]}
        )

        equipped = self.client.get(
            f"/api/achievements/games/{self.game_id}/equipped", headers=self.host
        ).json()["participants"]
        self.assertEqual(len(equipped), 1)
        self.assertEqual(equipped[0]["participant_id"], participant_id)
        self.assertEqual(equipped[0]["equipped"]["name"], "神秘黑幕女")
        self.assertEqual(equipped[0]["equipped"]["rarity"], 2)

        # 不在本局的已登录账号读不到本局的佩戴信息。
        stranger, _ = self.account("10011")
        outside = self.client.get(
            f"/api/achievements/games/{self.game_id}/equipped", headers=stranger
        )
        self.assertEqual(outside.status_code, 401, outside.text)

    def test_achievements_survive_game_reset(self):
        player_headers, actor = self.account("10012")
        definition = self.define("神秘黑幕女", "在一局内控制傀儡未被识破", 2).json()
        granted = self.client.post(
            f"/api/achievements/players/{actor['account_id']}/grants",
            headers=self.host,
            json={"achievement_id": definition["id"]},
        ).json()
        self.client.post(
            "/api/achievements/me/equip", headers=player_headers, json={"grant_id": granted["id"]}
        )
        self.client.post("/api/reset", headers=self.host).raise_for_status()

        mine = self.client.get("/api/achievements/me", headers=player_headers).json()
        self.assertEqual([item["name"] for item in mine["achievements"]], ["神秘黑幕女"])
        self.assertEqual(mine["equipped"]["name"], "神秘黑幕女")
        # 建立新对局会清空对局库，但成就库里仍然是同一条记录。
        self.assertEqual(
            achievement_storage.definition(definition["id"])["name"], "神秘黑幕女"
        )


if __name__ == "__main__":
    unittest.main()
