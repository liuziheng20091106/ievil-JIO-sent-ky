"""客户端版本下发、入局版本门槛与用户协议接口。

这是应用内更新系统的独立检查：自带一份临时 `GAME_DATA_DIR`，只覆盖
`updates.json` 区间下发、`/api/online` 的「有更新」标记、过旧客户端的入局拒绝、
`/api/agreement` 与 `/releases/*`，不与其它检查文件混放。

运行方式（只跑这一个文件，不跑全量）：
    $env:GAME_DATA_DIR="<临时目录>"; .venv/Scripts/python.exe -m unittest checks.test_client_release -v
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import client_release, storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


def agent(version, platform="windows"):
    """本客户端真实发送的 UA 形状（见 client/lib/src/client_version.dart）。"""
    suffix = f" ({platform})" if platform else ""
    return {"User-Agent": f"seven-double-flutter/{version}{suffix}"}


class AgentParsing(unittest.TestCase):
    """UA 解析与版本比较：形状不对一律「无法判断」，绝不当成过旧。"""

    def test_reads_version_and_platform(self):
        self.assertEqual(
            client_release.parse_client_agent("seven-double-flutter/1.2.3 (windows)"),
            ("1.2.3", "windows"),
        )
        self.assertEqual(
            client_release.parse_client_agent("seven-double-flutter/1.2.3 (android)"),
            ("1.2.3", "android"),
        )

    def test_rejects_foreign_and_malformed_agents(self):
        for value in ("", "python-httpx/0.27.0", "seven-double-flutter/1", "seven-double-flutter/1.2"):
            self.assertEqual(client_release.parse_client_agent(value), (None, None), value)
        self.assertEqual(client_release.parse_client_agent(None), (None, None))

    def test_reads_the_windows_updater_agent(self):
        # Updater 自己请求 /api/health 取 Windows 更新包；不带平台后缀时按 Windows 处理。
        self.assertEqual(
            client_release.parse_client_agent("magicjudge-updater/1.1.0 (windows)"),
            ("1.1.0", "windows"),
        )
        self.assertEqual(
            client_release.parse_client_agent("magicjudge-updater/1.1.0"),
            ("1.1.0", "windows"),
        )
        self.assertEqual(
            client_release.parse_client_agent("magicjudge-updater/1.1.0 (android)"),
            ("1.1.0", "android"),
        )

    def test_unknown_platform_still_yields_version(self):
        # 平台认不出来仍认版本：只影响分平台区间的匹配，不做任何拦截。
        self.assertEqual(
            client_release.parse_client_agent("seven-double-flutter/1.2.3 (linux)"),
            ("1.2.3", None),
        )

    def test_compare_versions(self):
        self.assertEqual(client_release.compare_versions("1.0.9", "1.0.10"), -1)
        self.assertEqual(client_release.compare_versions("2.0.0", "1.9.9"), 1)
        self.assertEqual(client_release.compare_versions("1.0.0", "1.0.0"), 0)
        self.assertIsNone(client_release.compare_versions("1.0", "1.0.0"))


class ReleaseData(unittest.TestCase):
    """带临时数据目录的检查基类：只替换 `storage.DATA_DIR`，不碰用户的 `data/`。"""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_dir = Path(self.directory.name)
        self.data_patch = patch.object(storage, "DATA_DIR", self.data_dir)
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        # 版本标签默认清空：部署环境里可能设了它们，不清掉会让断言跟着环境变。
        self.env_patch = patch.dict(
            os.environ,
            {
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
                "GAME_CLIENT_LATEST": "",
                "GAME_CLIENT_MINIMUM": "",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(app, base_url="http://testserver")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def write_updates(self, payload):
        (self.data_dir / "updates.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def health(self, version=None, platform="windows", headers=None):
        response = self.client.get(
            "/api/health", headers=headers if headers is not None else agent(version, platform)
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class UpdateRanges(ReleaseData):
    """不同版本区间下发不同的更新信息。"""

    UPDATES = {
        "updates": [
            {
                "platform": "windows",
                "min_version": "1.0.0",
                "max_version": "1.2.0",
                "latest": "1.2.0",
                "minimum": "1.1.0",
                "notes": "## Windows 更新\n- 修好了下载",
                "url": "/releases/魔法裁判Windows.zip",
                "size": 123,
            },
            {
                "platform": "android",
                "min_version": "1.0.0",
                "latest": "2.0.0",
                "notes": "## 安卓更新\n- 静默安装",
                "url": "/releases/app-release.apk",
                "guide_url": "https://example.invalid/help",
            },
            {"latest": "3.0.0", "notes": "默认区间"},
        ]
    }

    def setUp(self):
        super().setUp()
        self.write_updates(self.UPDATES)

    def test_windows_range_carries_its_own_notes_and_url(self):
        body = self.health("1.0.9")
        self.assertEqual(body["client_latest"], "1.2.0")
        self.assertEqual(body["client_minimum"], "1.1.0")
        update = body["update"]
        self.assertEqual(update["platform"], "windows")
        self.assertEqual(update["latest"], "1.2.0")
        self.assertIn("Windows 更新", update["notes"])
        self.assertEqual(update["url"], "/releases/魔法裁判Windows.zip")
        self.assertEqual(update["size"], 123)
        # Windows 没有显式配置 updater_url 时用默认的 Updater 路径。
        self.assertEqual(update["updater_url"], "/releases/Updater.exe")

    def test_android_gets_a_different_range(self):
        body = self.health("1.0.9", platform="android")
        self.assertEqual(body["client_latest"], "2.0.0")
        self.assertIsNone(body["client_minimum"])
        update = body["update"]
        self.assertEqual(update["platform"], "android")
        self.assertIn("安卓更新", update["notes"])
        self.assertEqual(update["guide_url"], "https://example.invalid/help")
        self.assertEqual(update["updater_url"], "")

    def test_default_range_catches_everything_else(self):
        body = self.health("2.5.0")
        self.assertEqual(body["client_latest"], "3.0.0")
        self.assertEqual(body["update"]["notes"], "默认区间")

    def test_windows_updater_gets_the_windows_package(self):
        # 更新器用 magicjudge-updater/<版本> (windows) 请求 health，取到的是 Windows 区间。
        body = self.health(headers={"User-Agent": "magicjudge-updater/1.0.9 (windows)"})
        self.assertEqual(body["client_latest"], "1.2.0")
        self.assertEqual(body["update"]["url"], "/releases/魔法裁判Windows.zip")
        self.assertEqual(body["update"]["updater_url"], "/releases/Updater.exe")

    def test_client_at_latest_gets_labels_without_update_payload(self):
        body = self.health("2.0.0", platform="android")
        self.assertEqual(body["client_latest"], "2.0.0")
        self.assertIsNone(body["update"], "已经是最新版就不必下发更新详情")

    def test_required_flag_tracks_the_minimum(self):
        self.assertTrue(self.health("1.0.0")["update"]["required"])
        self.assertFalse(self.health("1.1.0")["update"]["required"])

    def test_environment_fallback_without_a_matching_range(self):
        os.environ["GAME_CLIENT_LATEST"] = "1.4.0"
        os.environ["GAME_CLIENT_MINIMUM"] = "1.3.0"
        self.write_updates({"updates": []})
        body = self.health("1.0.0")
        self.assertEqual(body["client_latest"], "1.4.0")
        self.assertEqual(body["client_minimum"], "1.3.0")
        self.assertIsNone(body["update"])

    def test_broken_config_falls_back_instead_of_failing(self):
        (self.data_dir / "updates.json").write_text("{ not json", encoding="utf-8")
        body = self.health("1.0.0")
        self.assertIsNone(body["client_latest"])
        self.assertIsNone(body["update"])

    def test_invalid_entries_are_skipped(self):
        self.write_updates(
            {
                "updates": [
                    {"platform": "windows", "latest": "not-a-version"},
                    {"platform": "windows", "latest": "1.5.0", "max_version": "nope"},
                    {"platform": "windows", "latest": "1.5.0"},
                ]
            }
        )
        self.assertEqual(self.health("1.0.0")["client_latest"], "1.5.0")

    def test_health_without_user_agent_keeps_plain_labels(self):
        body = self.health(headers={})
        self.assertIsNone(body["client_latest"])
        self.assertIsNone(body["update"], "不知道平台就不下发更新详情")


class OnlineFlag(ReleaseData):
    """`/api/online` 只回答「有没有更新」；有更新时客户端才回去请求 health。"""

    def setUp(self):
        super().setUp()
        self.write_updates(
            {"updates": [{"platform": "any", "latest": "1.5.0", "minimum": "1.4.0", "notes": "x"}]}
        )
        challenge = self.client.post("/api/native/auth/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": "11000",
                "nickname": "玩家",
                "group_id": 123456,
            },
        )
        self.headers = {
            "Authorization": "Bearer "
            + self.client.get("/api/native/auth/challenges/" + challenge["id"]).json()[
                "session_token"
            ]
        }

    def online(self, version, platform="windows"):
        response = self.client.get("/api/online", headers={**self.headers, **agent(version, platform)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_old_client_is_flagged(self):
        self.assertTrue(self.online("1.4.9")["update_available"])

    def test_current_client_is_not_flagged(self):
        self.assertFalse(self.online("1.5.0")["update_available"])

    def test_unknown_agent_is_not_flagged(self):
        response = self.client.get("/api/online", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["update_available"])

    def test_online_still_returns_the_usual_payload(self):
        body = self.online("1.4.9")
        self.assertIn("accounts", body)
        self.assertIn("host_online", body)


class JoinGate(ReleaseData):
    """过旧客户端只拒绝「加入对局」，其它功能一律不受限。"""

    def setUp(self):
        super().setUp()
        self.write_updates(
            {
                "updates": [
                    {
                        "platform": "any",
                        "min_version": "1.0.0",
                        "latest": "1.5.0",
                        "minimum": "1.2.0",
                        "notes": "x",
                    }
                ]
            }
        )
        self.host, _ = self.login("/api/native/auth/host/challenges", "10001")
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
        created.raise_for_status()
        self.root = "/api/games/" + created.json()["id"]
        entered = self.client.post(self.root + "/host/enter", headers=self.host)
        self.assertEqual(entered.status_code, 200, entered.text)
        state = self.client.get(self.root + "/state", headers=self.host).json()
        opened = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={"expected_version": state["version"], "action": "room.open_join", "payload": {"open": True}},
        )
        self.assertEqual(opened.status_code, 200, opened.text)

    def login(self, path, qq_id):
        challenge = self.client.post(path).json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "QQ" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get(path + "/" + challenge["id"])
        completed.raise_for_status()
        headers = {"Authorization": "Bearer " + completed.json()["session_token"]}
        return headers, completed.json()

    def join(self, headers, kind="player"):
        return self.client.post(
            self.root + "/participations", headers=headers, json={"kind": kind}
        )

    def test_outdated_client_cannot_join_as_player(self):
        headers, _ = self.login("/api/native/auth/challenges", "11001")
        response = self.join({**headers, **agent("1.1.9")})
        self.assertEqual(response.status_code, 426, response.text)
        self.assertIn("更新", response.json()["detail"])

    def test_outdated_client_can_still_spectate(self):
        headers, _ = self.login("/api/native/auth/challenges", "11002")
        response = self.join({**headers, **agent("1.1.9")}, kind="spectator")
        self.assertEqual(response.status_code, 200, response.text)

    def test_current_client_joins_normally(self):
        headers, _ = self.login("/api/native/auth/challenges", "11003")
        response = self.join({**headers, **agent("1.2.0")})
        self.assertEqual(response.status_code, 200, response.text)

    def test_client_without_the_agent_header_is_not_blocked(self):
        # 浏览器、模拟器与检查脚本都不发这个 UA：按「不满足 UA」拦会把它们一起误伤。
        headers, _ = self.login("/api/native/auth/challenges", "11004")
        response = self.join(headers)
        self.assertEqual(response.status_code, 200, response.text)

    def test_lobby_and_messages_stay_open_for_outdated_clients(self):
        headers, _ = self.login("/api/native/auth/challenges", "11005")
        stale = {**headers, **agent("1.1.9")}
        self.assertEqual(self.client.get("/api/lobby", headers=stale).status_code, 200)
        self.assertEqual(self.client.get("/api/online", headers=stale).status_code, 200)
        self.assertEqual(self.client.get("/api/catalog", headers=stale).status_code, 200)
        self.assertEqual(self.client.get("/api/agreement", headers=stale).status_code, 200)

    def test_accepting_an_invite_is_gated_too(self):
        target, session = self.login("/api/native/auth/challenges", "11006")
        # 邀请只发给在线账号：先让目标账号有一次活动。
        self.client.get("/api/online", headers=target)
        invite = self.client.post(
            self.root + "/invites",
            headers=self.host,
            json={"account_id": session["session"]["actor"]["account_id"]},
        )
        self.assertEqual(invite.status_code, 200, invite.text)
        stale = {**target, **agent("1.1.9")}
        rejected = self.client.post(
            "/api/invites/" + invite.json()["id"] + "/accept", headers=stale
        )
        self.assertEqual(rejected.status_code, 426, rejected.text)
        accepted = self.client.post(
            "/api/invites/" + invite.json()["id"] + "/accept",
            headers={**target, **agent("1.2.0")},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)


class Agreement(ReleaseData):
    """用户协议查询接口。"""

    def test_missing_file_means_no_gate(self):
        body = self.client.get("/api/agreement").json()
        self.assertEqual(body["text"], "")
        self.assertEqual(body["hash"], "")

    def test_serves_markdown_with_a_content_hash(self):
        text = "# 用户协议\n\n1. 友善发言\n2. 不泄露身份\n"
        (self.data_dir / "agreement.md").write_text(text, encoding="utf-8")
        body = self.client.get("/api/agreement").json()
        self.assertEqual(body["text"], text)
        self.assertEqual(body["hash"], hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_blank_file_is_treated_as_absent(self):
        (self.data_dir / "agreement.md").write_text("   \n", encoding="utf-8")
        self.assertEqual(self.client.get("/api/agreement").json()["text"], "")


class ReleaseFiles(ReleaseData):
    """更新包的同源分发。"""

    def setUp(self):
        super().setUp()
        self.releases = self.data_dir / "releases"
        self.releases.mkdir()
        (self.releases / "app-release.apk").write_bytes(b"apk-bytes")

    def test_serves_a_known_file(self):
        response = self.client.get("/releases/app-release.apk")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, b"apk-bytes")

    def test_missing_file_is_404(self):
        self.assertEqual(self.client.get("/releases/Updater.exe").status_code, 404)

    def test_path_traversal_is_refused(self):
        for name in ("../updates.json", "..%2Fupdates.json", "sub/app-release.apk"):
            response = self.client.get("/releases/" + name)
            self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
