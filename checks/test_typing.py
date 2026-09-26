"""输入状态（正在输入）中继的可见性与发言权边界。

输入状态是纯内存瞬态：服务端只把 typing 帧转发给能看见该频道的连接，
不能落库、不能产生系统消息，也不能让没有发言权的身份刷帧。

测试技巧：WebSocket 的 receive 会一直阻塞到下一帧（ping 间隔 20 秒），
所以「断言某连接收不到某帧」不用无界等待，而是用一个**已知必然中继的帧**
（主持人的公屏输入状态）作为同步点：读到同步点之前出现的所有 typing 帧里
不允许出现被禁者的那一帧。
"""

import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.game import DEFAULT_CODEX
from backend.app.game.views import SPEECH_WAIT_REASON
from backend.app.main import app


class TypingRelay(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        data_patch.start()
        self.addCleanup(data_patch.stop)
        env_patch = patch.dict(
            "os.environ",
            {
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
            },
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.client = TestClient(
            app, base_url="http://testserver", headers={"Origin": "http://testserver"}
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.host, host_actor = self.host_login("10001")
        self.host_actor_id = host_actor["id"]
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        entered = self.client.post(self.root + "/host/enter", headers=self.host)
        entered.raise_for_status()
        self.open_join()
        self._qq_by_actor = {}

    # -------------------------------------------------------------- 登录夹具

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
        completed = self.client.get("/api/native/auth/host/challenges/" + challenge["id"])
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
        self.assertEqual(completed.json().get("status"), "completed")
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

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
        return response.json()

    def open_join(self):
        self.command(self.host, "room.open_join", {"open": True})

    def join_player(self, headers, qq_id):
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": "player"}
        )
        response.raise_for_status()
        actor = response.json()["actor"]
        self._qq_by_actor[actor["id"]] = qq_id
        return actor

    def edit_state(self, mutate):
        with storage.transaction() as db:
            game = storage.load_game(db, self.game_id)
            mutate(game)
            game["version"] += 1
            storage.save_game(db, game)

    # ------------------------------------------------------------ WebSocket

    @contextmanager
    def connect(self, headers):
        """建立实时连接并读完首帧 sync。

        测试门户在套件内连续开关多个连接时，socket 关闭偶发 CancelledError
        （portal 收尾竞态，与业务无关）：断言早已完成，这里吞掉清理期异常。
        """
        cm = self.client.websocket_connect("/api/live", headers=headers)
        socket = cm.__enter__()
        try:
            frame = socket.receive_json()
            self.assertEqual(frame["type"], "sync")
            yield socket
        finally:
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001 - 关闭期的门户竞态不影响断言结果
                pass

    def collect_typing_until(self, socket, participant_id, limit=60):
        """读帧直到出现 [participant_id] 的 typing 帧（含），返回沿途全部 typing 帧。

        主持人的输入状态对所有玩家可见，必然中继，用它当同步点。
        """
        frames = []
        for _ in range(limit):
            frame = socket.receive_json()
            if frame["type"] != "typing":
                continue
            frames.append(frame)
            if frame["participant_id"] == participant_id:
                return frames
        self.fail(f"没有等到来自 {participant_id} 的 typing 帧")

    # ------------------------------------------------------------------ 用例

    def test_typing_relays_to_game_peers_with_sender_display(self):
        first = self.account("15001")
        second = self.account("15002")
        first_actor = self.join_player(first, "15001")
        self.join_player(second, "15002")
        with self.connect(first) as a, self.connect(second) as b:
            a.send_json({"type": "typing", "channel_id": "public"})
            frames = self.collect_typing_until(b, first_actor["id"])
            self.assertEqual(len(frames), 1, "沿途不应有别的输入状态帧")
            frame = frames[0]
            self.assertTrue(frame["active"])
            self.assertEqual(frame["channel_id"], "public")
            self.assertEqual(frame["participant_id"], first_actor["id"])
            self.assertEqual(frame["kind"], "player")
            self.assertIn("name", frame)
            self.assertIn("avatar_role_id", frame)

    def test_typing_is_not_echoed_to_the_sender(self):
        solo = self.account("15003")
        solo_actor = self.join_player(solo, "15003")
        with self.connect(solo) as a:
            a.send_json({"type": "typing", "channel_id": "public"})
            # 同步点：自己发出的聊天消息会以 message 帧回声，读到它之前
            # 不允许出现任何 typing 帧（自己的输入状态不被回送）。
            sent = self.client.post(
                self.root + "/messages", headers=solo, json={"channel_id": "public", "text": "你好"}
            )
            sent.raise_for_status()
            for _ in range(60):
                frame = a.receive_json()
                if frame["type"] == "message":
                    break
                self.assertNotEqual(frame["type"], "typing")
            self.assertTrue(solo_actor["id"])

    def test_private_typing_stays_inside_the_channel(self):
        first, second, stranger = (
            self.account("15004"),
            self.account("15005"),
            self.account("15006"),
        )
        first_actor = self.join_player(first, "15004")
        second_actor = self.join_player(second, "15005")
        self.join_player(stranger, "15006")
        created = self.command(
            first, "channel.create", {"participant_ids": [second_actor["id"]]}
        )
        channel = next(
            item for item in created["channels"] if item["id"].startswith("private:")
        )
        self.command(second, "channel.accept", {"channel_id": channel["id"]})
        with self.connect(self.host) as h, self.connect(first) as a, self.connect(
            second
        ) as b, self.connect(stranger) as c:
            a.send_json({"type": "typing", "channel_id": channel["id"]})
            frames = self.collect_typing_until(b, first_actor["id"])
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["channel_id"], channel["id"])
            # 旁观者不该看到私信里的输入状态；用主持人的公屏帧做同步点：
            # c 读到的第一个 typing 帧必须是主持人的，而不是 1 号的。
            time.sleep(1.05)
            h.send_json({"type": "typing", "channel_id": "public"})
            frames = self.collect_typing_until(c, self.host_actor_id)
            for frame in frames:
                self.assertNotEqual(frame["participant_id"], first_actor["id"])

    def test_typing_requires_send_permission(self):
        solo, other = self.account("15007"), self.account("15008")
        solo_actor = self.join_player(solo, "15007")
        self.join_player(other, "15008")
        for qq in range(15009, 15014):
            headers = self.account(str(qq))
            self.join_player(headers, str(qq))
            self.command(headers, "lobby.ready")
        self.command(solo, "lobby.ready")
        self.command(other, "lobby.ready")
        # 二次全员准备后由主持人开局：开局即第一夜，公屏对玩家关闭。
        for qq in range(15009, 15014):
            self.command(self.account(str(qq)), "lobby.ready")
        self.command(solo, "lobby.ready")
        self.command(other, "lobby.ready")
        self.command(self.host, "host.start")
        state = self.client.get(self.root + "/state", headers=solo).json()
        self.assertIn(state["phase"], {"night", "witch", "night_coco"})
        public = next(item for item in state["channels"] if item["id"] == "public")
        self.assertFalse(
            public["can_send"], f"夜间公屏应当不可发言：{state['phase']}"
        )
        self.assertFalse(public["blocked_transient"], "夜间是频道级失效，不是临时等待")
        with self.connect(self.host) as h, self.connect(solo) as a, self.connect(other) as b:
            # 没有发言权的公屏输入帧必须被服务端忽略：b 在同步点之前收不到 1 号帧。
            a.send_json({"type": "typing", "channel_id": "public"})
            time.sleep(1.05)
            h.send_json({"type": "typing", "channel_id": "public"})
            frames = self.collect_typing_until(b, self.host_actor_id)
            for frame in frames:
                self.assertNotEqual(frame["participant_id"], solo_actor["id"])

    def test_stop_frame_relays_with_same_visibility(self):
        first, second = self.account("15015"), self.account("15016")
        first_actor = self.join_player(first, "15015")
        self.join_player(second, "15016")
        with self.connect(first) as a, self.connect(second) as b:
            a.send_json({"type": "typing", "channel_id": "public", "active": False})
            frames = self.collect_typing_until(b, first_actor["id"])
            self.assertEqual(len(frames), 1)
            self.assertFalse(frames[0]["active"])

    def test_typing_is_throttled_per_connection(self):
        first, second = self.account("15017"), self.account("15018")
        first_actor = self.join_player(first, "15017")
        self.join_player(second, "15018")
        with self.connect(self.host) as h, self.connect(first) as a, self.connect(second) as b:
            a.send_json({"type": "typing", "channel_id": "public"})
            # 1 秒内的第二帧必须被节流丢弃。
            a.send_json({"type": "typing", "channel_id": "public"})
            time.sleep(1.05)
            h.send_json({"type": "typing", "channel_id": "public"})
            frames = self.collect_typing_until(b, self.host_actor_id)
            from_first = [
                frame for frame in frames if frame["participant_id"] == first_actor["id"]
            ]
            self.assertEqual(
                len(from_first), 1, f"1 秒内重复帧应当被节流：{frames}"
            )

    def test_public_channel_marks_speech_wait_as_transient(self):
        players = [
            self.join_player(self.account(str(15020 + index)), str(15020 + index))
            for index in range(7)
        ]
        for actor in players:
            self.command(self.account(self._qq_by_actor[actor["id"]]), "lobby.ready")
        for actor in players:
            self.command(self.account(self._qq_by_actor[actor["id"]]), "lobby.ready")
        self.command(self.host, "host.start")
        # 连续推进离开夜间流程：night* 阶段玩家未完成的行动按超时处理，
        # 直到进入第一天的顺序发言（强制推进是主持人的合法手段）。
        for _ in range(10):
            state = self.client.get(self.root + "/state", headers=self.host).json()
            if state["phase"] == "speech":
                break
            self.command(self.host, "host.advance")
        state = self.client.get(
            self.root + "/state", headers=self.account(self._qq_by_actor[players[1]["id"]])
        ).json()
        self.assertEqual(state["phase"], "speech", "推进后应到达顺序发言阶段")
        self.assertEqual(state["half"], "day")
        public = next(item for item in state["channels"] if item["id"] == "public")
        self.assertFalse(public["can_send"])
        self.assertTrue(public["blocked_transient"])
        self.assertEqual(public["reason"], SPEECH_WAIT_REASON)


if __name__ == "__main__":
    unittest.main()
