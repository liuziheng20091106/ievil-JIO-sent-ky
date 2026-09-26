"""登录挑战接口的工作量证明（PoW）防护。

独立检查：谜题签发与校验（stdlib 部分）、端到端 HTTP 行为
（关闭时不领题直接创建、开启后无证明 428、有效证明放行、令牌篡改拒绝）。

运行方式（只跑这一个文件，不跑全量）：
    .venv/Scripts/python.exe -m unittest checks.test_pow -v
"""

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import auth_storage, pow_guard, storage
from backend.app.main import app


def solve(token, difficulty):
    """与服务端一致的朴素枚举；检查里难度都压得很低。"""
    nonce = 0
    prefix = "0" * difficulty
    while True:
        digest = hashlib.sha256(f"{token}{nonce}".encode()).hexdigest()
        if digest.startswith(prefix):
            return nonce
        nonce += 1


class PuzzleToken(unittest.TestCase):
    def test_disabled_without_env(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": ""}, clear=False):
            self.assertEqual(pow_guard.difficulty(), 0)
            self.assertFalse(pow_guard.enabled())
            self.assertEqual(pow_guard.issue_puzzle(), {"required": False})
            # 关闭时校验恒过：任何 token/nonce 都放行。
            self.assertTrue(pow_guard.verify_solution("", None))
            self.assertTrue(pow_guard.verify_solution("garbage", -1))

    def test_ignores_broken_difficulty_and_clamps(self):
        for raw, expected in (("abc", 0), ("-3", 0), ("5", 5), ("99", pow_guard.MAX_DIFFICULTY)):
            with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": raw}, clear=False):
                self.assertEqual(pow_guard.difficulty(), expected, raw)

    def test_clamped_difficulty_is_feasible(self):
        """上限必须保持可解：钳制值不能高到连服务器都算不完。"""
        self.assertLessEqual(pow_guard.MAX_DIFFICULTY, 8)

    def test_issue_and_verify_roundtrip(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            puzzle = pow_guard.issue_puzzle()
            self.assertTrue(puzzle["required"])
            self.assertEqual(puzzle["difficulty"], 3)
            nonce = solve(puzzle["token"], 3)
            self.assertTrue(pow_guard.verify_solution(puzzle["token"], nonce))

    def test_rejects_wrong_solution_and_tampered_token(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            puzzle = pow_guard.issue_puzzle()
            self.assertFalse(pow_guard.verify_solution(puzzle["token"], 10**18))
            parts = puzzle["token"].split(".")
            forged = ".".join([*parts[:3], "1", parts[4]])  # difficulty 降到 1
            self.assertFalse(pow_guard.verify_solution(forged, solve(forged, 1)))
            self.assertFalse(pow_guard.verify_solution("v1.0.1.x.deadbeef", 0))

    def test_rejects_expired_token(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            puzzle = pow_guard.issue_puzzle()
            nonce = solve(puzzle["token"], 3)
            future = time.time() + (pow_guard._TOKEN_TTL_SECONDS + 30) * 1000
            with patch("time.time", return_value=future):
                self.assertFalse(pow_guard.verify_solution(puzzle["token"], nonce))

    def test_rejects_non_integer_nonce(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            puzzle = pow_guard.issue_puzzle()
            for bad in ("1", 1.5, True, None):
                self.assertFalse(pow_guard.verify_solution(puzzle["token"], bad), bad)


class ChallengeEndpoints(unittest.TestCase):
    """端到端：PoW 开关对四个挑战创建端点的实际效果。"""

    def setUp(self):
        # 与 test_client_release 同款基线：临时数据目录，不碰用户的 data/；
        # 登录挑战写 auth.sqlite3，目录必须真实存在。
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        # 登录挑战写 auth.sqlite3：初始化建表。
        auth_storage.initialize()
        # PoW 密钥默认派生自网关共享密钥：固定它让检查不随部署环境漂移。
        self.env_patch = patch.dict(os.environ, {"GAME_GATEWAY_TOKEN": "test-gateway-secret"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(app)

    def test_disabled_allows_bare_creation(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": ""}, clear=False):
            listing = self.client.post("/api/pow/challenges")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual(listing.json(), {"required": False})
            response = self.client.post("/api/native/auth/challenges")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "pending")

    def test_enabled_requires_proof(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            puzzle = self.client.post("/api/pow/challenges").json()
            self.assertTrue(puzzle["required"])
            # 没有证明：428，提示更新客户端。
            bare = self.client.post("/api/native/auth/challenges")
            self.assertEqual(bare.status_code, 428)
            self.assertIn("更新客户端", bare.json()["detail"])
            # 错误证明同样 428。
            wrong = self.client.post(
                "/api/native/auth/challenges", json={"token": puzzle["token"], "nonce": 7}
            )
            self.assertEqual(wrong.status_code, 428)
            # 正确证明：放行。
            nonce = solve(puzzle["token"], puzzle["difficulty"])
            good = self.client.post(
                "/api/native/auth/challenges", json={"token": puzzle["token"], "nonce": nonce}
            )
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json()["status"], "pending")

    def test_enabled_host_endpoints_behave_the_same(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "2"}, clear=False):
            bare = self.client.post("/api/native/auth/host/challenges")
            self.assertEqual(bare.status_code, 428)
            puzzle = self.client.post("/api/pow/challenges").json()
            nonce = solve(puzzle["token"], puzzle["difficulty"])
            good = self.client.post(
                "/api/native/auth/host/challenges", json={"token": puzzle["token"], "nonce": nonce}
            )
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json()["status"], "pending")

    def test_solution_shape_is_validated(self):
        with patch.dict(os.environ, {"GAME_POW_DIFFICULTY": "3"}, clear=False):
            # nonce 传字符串：请求体格式不合法直接 422，不进入 PoW 校验。
            response = self.client.post(
                "/api/native/auth/challenges", json={"token": "x", "nonce": "1"}
            )
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
