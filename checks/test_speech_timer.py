"""顺序发言的30秒公开倒计时：发言与「正在输入」都会把它重新拨满。

纯规则部分（到点自动顺延、离开阶段清除、回溯不恢复过期倒计时、横幅带倒计时字段）
在 checks/test_resolution.py 与 checks/test_rules.py 里。这里只走真实 HTTP/WebSocket
两条路径，确认 api.send_message 与 realtime.handle_typing 动的是同一份公开字段，
并且真的把它推给全场——这条链路断开时，玩家看到的倒计时会停在旧值上。
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
from backend.app.main import app


class SpeechTimerRelay(unittest.TestCase):
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
        self.host, self.host_actor_id = self.host_login("10001")
        created = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        entered = self.client.post(self.root + "/host/enter", headers=self.host)
        entered.raise_for_status()
        self.command(self.host, "room.open_join", {"open": True})
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
        return (
            {"Authorization": "Bearer " + completed.json()["session_token"]},
            completed.json()["session"]["actor"]["id"],
        )

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

    def state(self, headers):
        response = self.client.get(self.root + "/state", headers=headers)
        response.raise_for_status()
        return response.json()

    def command(self, headers, action, payload=None):
        version = self.state(headers)["version"]
        response = self.client.post(
            self.root + "/commands",
            headers=headers,
            json={
                "expected_version": version,
                "action": action,
                "payload": payload or {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def join_player(self, headers, qq_id):
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": "player"}
        )
        response.raise_for_status()
        actor = response.json()["actor"]
        self._qq_by_actor[actor["id"]] = qq_id
        return actor

    def edit_state(self, mutate):
        """把倒计时压到只剩几秒，好在一次请求内量出「被重新拨满」的差别。"""
        with storage.transaction() as db:
            game = storage.load_game(db, self.game_id)
            mutate(game)
            game["version"] += 1
            storage.save_game(db, game)

    @contextmanager
    def connect(self, headers):
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

    # ------------------------------------------------------------------ 夹具

    def speaking_phase(self):
        """凑齐七人、连续准备两轮开局，再由玩家确认放弃夜间行动走到顺序发言。"""
        players = [
            self.join_player(self.account(str(16000 + index)), str(16000 + index))
            for index in range(7)
        ]
        for _ in range(2):
            for actor in players:
                self.command(self.account(self._qq_by_actor[actor["id"]]), "lobby.ready")
        self.command(self.host, "host.start")
        for _ in range(10):
            state = self.state(self.host)
            if state["phase"] == "speech":
                break
            if state["phase"] in {"night", "night_coco"}:
                for actor in players:
                    headers = self.account(self._qq_by_actor[actor["id"]])
                    if any(
                        action["id"] == "night.confirm" for action in self.state(headers)["actions"]
                    ):
                        self.command(headers, "night.confirm")
                if self.state(self.host)["phase"] != state["phase"]:
                    continue
            self.command(self.host, "host.advance")
        state = self.state(self.host)
        self.assertEqual(state["phase"], "speech", "推进后应到达顺序发言阶段")
        return players, state

    def seat_headers(self, players, seat_id):
        actor = next(item for item in players if item["seat_id"] == seat_id)
        return self.account(self._qq_by_actor[actor["id"]])

    def shorten(self, headers):
        """当前倒计时压到5秒，返回压缩后的截止时间。"""
        self.edit_state(lambda game: game["public"].update(speech_deadline=time.time() + 5))
        return self.state(headers)["public"]["speech_deadline"]

    # ------------------------------------------------------------------ 用例

    def test_turn_boundaries_are_live_and_survive_skips_reordering_and_reconnect(self):
        earlier = self.client.post(
            self.root + "/messages",
            headers=self.host,
            json={"channel_id": "public", "text": "开局前的自由聊天"},
        )
        earlier.raise_for_status()
        players, state = self.speaking_phase()
        headers = {sid: self.seat_headers(players, sid) for sid in map(str, range(1, 8))}
        self.command(self.host, "host.auto")  # 收尾由本用例显式推进，避免五秒计时竞态。
        state = self.command(self.host, "host.speech", {"start": "1", "direction": "asc"})

        def history():
            response = self.client.get(
                self.root + "/messages", headers=headers["2"], params={"scope": "public"}
            )
            response.raise_for_status()
            return response.json()["messages"]

        initial = [item for item in history() if item["kind"] == "speech_turn"]
        self.assertEqual(initial[-1]["payload"]["seat_id"], "1")
        self.assertGreater(initial[0]["id"], earlier.json()["id"])
        seat = next(item for item in state["seats"] if item["id"] == "1")
        self.assertEqual(initial[-1]["payload"]["avatar_role_id"], seat["avatar_role_id"])
        sent = self.client.post(
            self.root + "/messages",
            headers=headers["1"],
            json={"channel_id": "public", "text": "一号本轮发言"},
        )
        sent.raise_for_status()
        self.assertLess(initial[-1]["id"], sent.json()["id"])
        self.command(headers["3"], "speech.speak", {"text": "三号提前写好的发言"})
        self.command(headers["4"], "speech.done")

        with self.connect(headers["2"]) as socket:
            self.command(headers["1"], "speech.done")
            received = []
            for _ in range(30):
                frame = socket.receive_json()
                if frame["type"] == "message":
                    received.append(frame["message"])
                if frame["type"] == "state" and frame["state"]["public"]["speaker"] == "2":
                    break
            live_turns = [item for item in received if item["kind"] == "speech_turn"]
            self.assertEqual([item["payload"]["seat_id"] for item in live_turns], ["2"])
            self.assertFalse(any(item["kind"] == "chat" for item in received))
            # 预提交在轮到时先发布边界、再公开正文；跳过4号之后直接开始5号。
            self.command(headers["2"], "speech.done")
            received = []
            for _ in range(30):
                frame = socket.receive_json()
                if frame["type"] == "message" and frame["message"]["kind"] in {
                    "chat",
                    "speech_turn",
                }:
                    received.append(frame["message"])
                if frame["type"] == "state" and frame["state"]["public"]["speaker"] == "5":
                    break
            self.assertEqual(
                [item["kind"] for item in received], ["speech_turn", "chat", "speech_turn"]
            )
            self.assertEqual(received[0]["payload"]["seat_id"], "3")
            self.assertEqual(received[1]["text"], "三号提前写好的发言")
            self.assertEqual(received[2]["payload"]["seat_id"], "5")

        # 改顺序不能重新占用已提交席位，也不能把新起点移动到旧聊天前。
        state = self.command(self.host, "host.speech", {"start": "3", "direction": "asc"})
        self.assertEqual(state["public"]["speaker"], "5")
        state = self.command(self.host, "host.speech", {"start": "6", "direction": "asc"})
        self.assertEqual(state["public"]["speaker"], "6")
        for sid in ("6", "7", "5"):
            self.command(headers[sid], "speech.done")
        self.command(self.host, "host.advance")
        self.assertEqual(self.state(headers["2"])["phase"], "discussion")
        saved = [item for item in history() if item["kind"] == "speech_turn"]
        seats = [item["payload"]["seat_id"] for item in saved[len(initial) :]]
        self.assertEqual(seats, ["2", "3", "5", "6", "7", "5"])
        with self.client.websocket_connect("/api/live", headers=headers["2"]) as socket:
            frame = socket.receive_json()
            self.assertEqual(frame["type"], "sync")
            recovered = [item for item in frame["messages"] if item["kind"] == "speech_turn"]
            self.assertEqual(recovered, saved)

    def test_the_speaking_phase_publishes_one_clock_to_everyone(self):
        players, state = self.speaking_phase()
        speaker = state["public"]["speaker"]
        self.assertTrue(speaker)
        # 轮到的席位、旁观的席位都拿到同一份公开倒计时（横幅据此显示还剩几秒）。
        deadline = state["public"]["speech_deadline"]
        self.assertGreater(deadline, time.time() + 20)
        self.assertEqual(state["public"]["speech_deadline_seat"], speaker)
        for actor in players:
            headers = self.account(self._qq_by_actor[actor["id"]])
            prompt = self.state(headers).get("action_prompt")
            self.assertIsNotNone(prompt, "顺序发言阶段每个玩家都应看到全场横幅")
            self.assertEqual(prompt["speech_deadline"], deadline)
            self.assertEqual(prompt["speech_seconds"], 30)

    def test_speaking_restarts_the_clock(self):
        players, state = self.speaking_phase()
        speaker = state["public"]["speaker"]
        headers = self.seat_headers(players, speaker)
        near = self.shorten(headers)
        sent = self.client.post(
            self.root + "/messages",
            headers=headers,
            json={"channel_id": "public", "text": "我开始发言"},
        )
        sent.raise_for_status()
        after = self.state(headers)["public"]["speech_deadline"]
        self.assertGreater(after, near + 20, "本人发言后倒计时要重新拨满")
        # 发言权没有因此换人：倒计时只重置，不提前推进。
        self.assertEqual(self.state(headers)["public"]["speaker"], speaker)
        # 别的席位在顺序发言阶段没有公屏发言权，也就无从重置这个计时。
        other = next(actor for actor in players if actor["seat_id"] != speaker)
        denied = self.client.post(
            self.root + "/messages",
            headers=self.account(self._qq_by_actor[other["id"]]),
            json={"channel_id": "public", "text": "抢话"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_typing_restarts_the_clock_only_for_the_current_speaker(self):
        players, state = self.speaking_phase()
        speaker = state["public"]["speaker"]
        headers = self.seat_headers(players, speaker)
        near = self.shorten(headers)
        with self.connect(headers) as socket:
            socket.send_json({"type": "typing", "channel_id": "public", "active": True})
            # 连接建立时服务端自己会补推一帧状态（带的是拨满前的旧值），所以不是
            # 「读到第一帧状态」就算数，而是等那一帧真的把倒计时拨到了新的截止时间。
            updated = None
            for _ in range(30):
                frame = socket.receive_json()
                if frame["type"] != "state":
                    continue
                deadline = frame["state"]["public"]["speech_deadline"]
                if deadline > near + 5:
                    updated = deadline
                    break
            self.assertIsNotNone(updated, "本人继续输入后应当把倒计时拨满")
        # 旁观的席位在发言阶段没有公屏输入权：它的输入帧被丢弃，倒计时不动。
        other = next(actor for actor in players if actor["seat_id"] != speaker)
        other_headers = self.account(self._qq_by_actor[other["id"]])
        untouched = self.shorten(headers)
        with self.connect(other_headers) as socket:
            socket.send_json({"type": "typing", "channel_id": "public", "active": True})
            time.sleep(1.05)
        self.assertEqual(self.state(headers)["public"]["speech_deadline"], untouched)


if __name__ == "__main__":
    unittest.main()
