"""守护进程：环境文件解析、接口鉴权、失败上报、HTTP 重启与崩溃自愈。"""

import http.client
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from supervisor import (
    ManagedProcess,
    ProcessFailure,
    Supervisor,
    SupervisorHandler,
    SupervisorServer,
    read_env_file,
)

SLEEPER = "import time; time.sleep(120)"


def wait_until(predicate, timeout: float = 15.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class EnvFile(unittest.TestCase):
    def test_reads_key_value_and_ignores_noise(self):
        """gateway/.env 是 run-gateway.cmd 读的那份，解析规则必须一致。"""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text(
                "# 注释\n\nNAPCAT_WS_URL=ws://127.0.0.1:3001\nGAME_QQ_GROUP_ID = 1105925736 \n坏行\n",
                encoding="utf-8",
            )
            values = read_env_file(path)
        self.assertEqual(values["NAPCAT_WS_URL"], "ws://127.0.0.1:3001")
        self.assertEqual(values["GAME_QQ_GROUP_ID"], "1105925736")
        self.assertEqual(len(values), 2)

    def test_missing_file_is_empty(self):
        self.assertEqual(read_env_file(Path("does-not-exist.env")), {})


class FailureReporting(unittest.TestCase):
    def test_start_failure_reports_exit_code_and_log_tail(self):
        """起不来的子进程要把退出码和日志末尾报出来，不能只回一句 500。"""
        with tempfile.TemporaryDirectory() as folder:
            proc = ManagedProcess(
                "backend",
                [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"],
                env=dict(os.environ),
                log_path=Path(folder) / "backend.log",
                settle=0.5,
            )
            with self.assertRaises(ProcessFailure) as ctx:
                proc.start()
            message = str(ctx.exception)
        self.assertIn("退出码 3", message)
        self.assertIn("boom", message)


class HttpApi(unittest.TestCase):
    """接口是本机脚本用的重启入口，鉴权与进程名白名单都是真实的权限边界。"""

    TOKEN = "test-supervisor-token"

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.backend = ManagedProcess(
            "backend",
            [sys.executable, "-c", SLEEPER],
            env=dict(os.environ),
            log_path=Path(self.folder.name) / "backend.log",
            settle=0.3,
        )
        self.supervisor = Supervisor([self.backend], autostart=False)
        self.server = SupervisorServer(
            ("127.0.0.1", 0), SupervisorHandler, supervisor=self.supervisor, token=self.TOKEN
        )
        self.addCleanup(self._close)
        threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        ).start()
        self.port = self.server.server_address[1]

    def _close(self):
        self.server.shutdown()
        self.server.server_close()
        self.backend.stop()

    def request(self, method: str, path: str, *, token: str | None = None, origin: str | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {}
        if token:
            headers["X-Supervisor-Token"] = token
        if origin:
            headers["Origin"] = origin
        connection.request(method, path, body=b"", headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, payload

    def test_health_is_open_but_status_needs_token(self):
        self.assertEqual(self.request("GET", "/health")[0], 200)
        self.assertEqual(self.request("GET", "/status")[0], 401)
        status, payload = self.request("GET", "/status", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(payload["processes"]["backend"]["state"], "stopped")

    def test_browser_origin_is_rejected(self):
        """带 Origin 的请求一律拒绝，否则任意网页都能 POST 重启服务。"""
        status, payload = self.request(
            "POST", "/restart/backend", token=self.TOKEN, origin="https://super.tkcloud.online"
        )
        self.assertEqual(status, 403)
        self.assertIn("Origin", payload["error"])

    def test_unmanaged_process_name_is_rejected(self):
        self.assertEqual(self.request("POST", "/restart/napcat", token=self.TOKEN)[0], 404)
        self.assertEqual(self.request("POST", "/restart/backend/extra", token=self.TOKEN)[0], 404)

    def test_restart_replaces_the_process(self):
        status, payload = self.request("POST", "/start/backend", token=self.TOKEN)
        self.assertEqual(status, 200)
        old_pid = payload["results"][0]["pid"]
        self.assertIsNotNone(old_pid)
        status, payload = self.request("POST", "/restart/backend", token=self.TOKEN)
        self.assertEqual(status, 200)
        self.assertNotEqual(payload["results"][0]["pid"], old_pid)
        self.assertEqual(payload["results"][0]["state"], "running")
        self.assertEqual(self.backend.snapshot()["restarts"], 1)


class AutoRespawn(unittest.TestCase):
    def test_crashed_child_comes_back_without_a_post(self):
        """守护的底线：子进程被杀掉后自己回来，不需要人工调用接口。"""
        with tempfile.TemporaryDirectory() as folder:
            proc = ManagedProcess(
                "gateway",
                [sys.executable, "-c", SLEEPER],
                env=dict(os.environ),
                log_path=Path(folder) / "gateway.log",
                settle=0.3,
            )
            supervisor = Supervisor([proc], autostart=False)
            supervisor.begin()
            try:
                proc.start()
                first = proc.snapshot()["pid"]
                os.kill(first, signal.SIGTERM)
                revived = wait_until(lambda: proc.running and proc.snapshot()["pid"] != first)
                self.assertTrue(revived, "子进程被杀掉后没有被守护进程拉起")
                self.assertGreaterEqual(proc.snapshot()["restarts"], 1)
            finally:
                # 必须先停子进程再退出 with：子进程还握着 gateway.log，临时目录删不掉。
                supervisor.shutdown()


if __name__ == "__main__":
    unittest.main()
