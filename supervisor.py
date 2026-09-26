"""守护进程：托管「后端」与「登录网关」两个子进程，并提供 HTTP 接口快捷重启。

启动：

    .venv\\Scripts\\python.exe supervisor.py
    run-supervisor.cmd

默认只监听 127.0.0.1:13900（可用 GAME_SUPERVISOR_HOST/PORT 覆盖）：

    GET  /status              两个进程的状态（pid、存活时长、健康检查、重启次数）
    POST /restart/backend     重启后端（run.py，默认 8000）
    POST /restart/gateway     重启登录网关（python -m gateway.gateway）
    POST /restart/all         先重启后端，再重启登录网关
    POST /start|stop/{name}   启动 / 停止单个进程（name 也可为 all）

子进程意外退出会按 2s→60s 退避自动拉起；两个进程的 stdout/stderr 追加在
logs/backend.log 与 logs/gateway.log；退出守护进程会一并停掉子进程。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
LOG_MAX_BYTES = 5 * 1024 * 1024
MANAGED_NAMES = ("backend", "gateway")
ALL_NAMES = (*MANAGED_NAMES, "all")
BACKEND_HEALTH_PATH = "/api/health"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_SUPERVISOR_PORT = 13900
POLL_INTERVAL = 2.0
READY_TIMEOUT = 30.0
STOP_TIMEOUT = 15.0
# 网关没有健康检查端口：进程活过这一小会儿就算起来了（缺密钥等启动失败会立刻退出）。
GATEWAY_SETTLE = 1.5
RESPAWN_MIN_DELAY = 2.0
RESPAWN_MAX_DELAY = 60.0
RESPAWN_RESET_AFTER = 60.0
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

LOG = logging.getLogger("seven-double-supervisor")
# 健康检查只连本机，显式清空代理设置，否则环境里的 HTTP_PROXY 会把 127.0.0.1 也拦下。
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ProcessFailure(RuntimeError):
    """子进程没起来或没能停掉；消息里带日志末尾，调用方可以直接看到原因。"""


class UnknownProcess(KeyError):
    """接口里出现了不受管理的进程名。"""


class BatchFailure(ProcessFailure):
    """全量重启里至少有一个进程失败；结果列表里逐项标了 ok。"""

    def __init__(self, failures: list[str], results: list[dict[str, Any]]):
        super().__init__("；".join(failures))
        self.results = results


def read_env_file(path: Path) -> dict[str, str]:
    """按 KEY=VALUE 读取 env 文件（忽略注释与空行），与 run-gateway.cmd 的读法一致。"""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip()
    return values


def rotate_log(path: Path) -> None:
    """只留一份上一版日志，避免长期运行的守护进程把磁盘写满。"""
    try:
        if path.stat().st_size >= LOG_MAX_BYTES:
            backup = path.with_suffix(path.suffix + ".1")
            backup.unlink(missing_ok=True)
            path.replace(backup)
    except OSError as exc:
        LOG.debug("轮转日志 %s 失败：%s", path, exc)


def tail_log(path: Path | None, lines: int = 12) -> str:
    """取日志末尾若干行，用于把「启动即退出」的原因一并报给调用者。"""
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


class ManagedProcess:
    """一个被守护的子进程：启动、停止、等待就绪，意外退出后按退避重启。"""

    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        env: dict[str, str],
        log_path: Path,
        health_url: str | None = None,
        settle: float = 0.0,
    ):
        self.name = name
        self.command = list(command)
        self.env = env
        self.log_path = log_path
        self.health_url = health_url
        self.settle = settle
        self.keep_running = False
        self.restarts = 0
        self.last_exit_code: int | None = None
        self.last_error = ""
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._started_at = 0.0
        self._next_start_at = 0.0
        self._respawn_delay = RESPAWN_MIN_DELAY

    # ---- 状态 ----

    @property
    def running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def health(self) -> str | None:
        """后端有 /api/health；网关没有（连不上 NapCat 会自己重连），没配就返回 None。"""
        if self.health_url is None:
            return None
        return "ok" if self._health_ok() else "unreachable"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            proc = self._proc
            running = proc is not None and proc.poll() is None
            data: dict[str, Any] = {
                "state": "running" if running else "stopped",
                "pid": proc.pid if running else None,
                "uptime_seconds": round(time.time() - self._started_at, 1) if running else None,
                "keep_running": self.keep_running,
                "restarts": self.restarts,
                "last_exit_code": self.last_exit_code,
                "last_error": self.last_error,
                "command": " ".join(self.command),
                "log": str(self.log_path),
            }
        # 健康检查有网络等待，放到锁外做，别卡住 start/stop。
        data["health"] = self.health()
        return data

    # ---- 操作 ----

    def start(self, *, wait: bool = True, timeout: float = READY_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            self.keep_running = True
            self._next_start_at = 0.0
            if self._proc is not None and self._proc.poll() is None:
                changed = False
            else:
                rotate_log(self.log_path)
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.log_path.open("ab")
                try:
                    proc = subprocess.Popen(
                        self.command,
                        cwd=ROOT,
                        env=self.env,
                        stdin=subprocess.DEVNULL,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                        start_new_session=os.name != "nt",
                    )
                finally:
                    handle.close()
                self._proc = proc
                self._started_at = time.time()
                self.last_error = ""
                self.last_exit_code = None
                changed = True
                LOG.info("已启动 %s（pid=%s）", self.name, proc.pid)
        if changed and wait:
            self.wait_ready(timeout)
        # _result 里会做健康检查（有网络等待），放在锁外。
        return self._result(changed=changed)

    def stop(self, *, timeout: float = STOP_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            self.keep_running = False
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                self.last_exit_code = proc.returncode if proc is not None else None
                changed = False
            else:
                self._terminate(proc, timeout)
                self._proc = None
                self.last_exit_code = proc.returncode
                changed = True
                LOG.info("已停止 %s（pid=%s，退出码=%s）", self.name, proc.pid, proc.returncode)
        return self._result(changed=changed)

    def restart(self, *, timeout: float = READY_TIMEOUT) -> dict[str, Any]:
        self.stop()
        with self._lock:
            self._respawn_delay = RESPAWN_MIN_DELAY
        self.start(timeout=timeout)
        with self._lock:
            self.restarts += 1
            self.last_error = ""
        return self._result(changed=True)

    def supervise(self) -> None:
        """监督线程调用：意外退出就按退避重新拉起，稳定运行一段时间后退避归零。"""
        with self._lock:
            if not self.keep_running:
                return
            proc = self._proc
            if proc is not None and proc.poll() is None:
                if time.time() - self._started_at >= RESPAWN_RESET_AFTER:
                    self._respawn_delay = RESPAWN_MIN_DELAY
                return
            now = time.time()
            if proc is not None:
                self.last_exit_code = proc.returncode
                self._proc = None
                self.restarts += 1
                self.last_error = f"意外退出（退出码 {proc.returncode}）"
                self._next_start_at = now + self._respawn_delay
                LOG.warning(
                    "%s 意外退出（退出码 %s），%.0fs 后重启",
                    self.name,
                    proc.returncode,
                    self._respawn_delay,
                )
                self._respawn_delay = min(self._respawn_delay * 2, RESPAWN_MAX_DELAY)
                return
            if now < self._next_start_at:
                return
        try:
            self.start(wait=False)
        except OSError as exc:
            # 连可执行文件都拉不起来（例如 .venv 被删）：退避后重试，别在这里抛给监督线程。
            with self._lock:
                self.last_error = str(exc)
                self._next_start_at = time.time() + self._respawn_delay
                self._respawn_delay = min(self._respawn_delay * 2, RESPAWN_MAX_DELAY)
            LOG.error("自动启动 %s 失败：%s", self.name, exc)

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        """等进程真的可用：后端轮询 /api/health，网关只确认没当场退出。"""
        if self.health_url is None:
            time.sleep(min(self.settle, max(timeout, 0.0)))
            if not self.running:
                self.last_exit_code = self._exit_code()
                raise ProcessFailure(self._failure_message("启动后立即退出"))
            return
        deadline = time.monotonic() + timeout
        while True:
            if not self.running:
                self.last_exit_code = self._exit_code()
                raise ProcessFailure(self._failure_message("启动后立即退出"))
            if self._health_ok():
                return
            if time.monotonic() >= deadline:
                raise ProcessFailure(
                    self._failure_message(f"{timeout:.0f}s 内 {self.health_url} 未就绪")
                )
            time.sleep(0.4)

    # ---- 内部实现 ----

    def _exit_code(self) -> int | None:
        with self._lock:
            return self._proc.returncode if self._proc is not None else None

    def _health_ok(self) -> bool:
        try:
            with OPENER.open(self.health_url, timeout=2) as response:
                return int(response.status) == 200
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def _terminate(self, proc: subprocess.Popen, timeout: float) -> None:
        try:
            if os.name == "nt":
                # taskkill /T 连子进程一起收，别留下 uvicorn 派生的进程。
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError as exc:
            LOG.debug("结束 %s（pid=%s）时出错：%s", self.name, proc.pid, exc)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            LOG.warning("%s 未在 %.0fs 内退出，强制结束", self.name, timeout)
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                LOG.error("%s（pid=%s）无法结束", self.name, proc.pid)

    def _failure_message(self, reason: str) -> str:
        message = f"{self.name} {reason}"
        if self.last_exit_code is not None:
            message += f"（退出码 {self.last_exit_code}）"
        tail = tail_log(self.log_path)
        if tail:
            message += f"；日志 {self.log_path} 末尾：\n{tail}"
        return message

    def _result(self, *, changed: bool) -> dict[str, Any]:
        return {"name": self.name, "changed": changed, **self.snapshot()}


class Supervisor:
    """两个子进程的集合，以及 start/stop/restart 的公共入口。"""

    def __init__(self, processes: list[ManagedProcess], *, autostart: bool = True):
        self.processes = {item.name: item for item in processes}
        self.autostart = autostart
        self.started_at = time.time()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def begin(self) -> None:
        self._thread = threading.Thread(target=self._watch, name="supervisor-watch", daemon=True)
        self._thread.start()
        if not self.autostart:
            return
        for proc in self.processes.values():
            try:
                proc.start()
            except (ProcessFailure, OSError) as exc:
                # 自动启动失败不致命：接口仍然可用，修好以后 POST /start 即可。
                LOG.error("%s 自动启动失败：%s", proc.name, exc)

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=POLL_INTERVAL + 1)
        for proc in reversed(list(self.processes.values())):
            try:
                proc.stop()
            except OSError as exc:
                LOG.error("停止 %s 失败：%s", proc.name, exc)

    def snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "processes": {name: proc.snapshot() for name, proc in self.processes.items()},
        }

    def run(self, action: str, name: str) -> list[dict[str, Any]]:
        """单个进程失败不打断其余进程（all 时尤其重要），最后统一报错。"""
        targets = self._resolve(name)
        if action == "restart" and name == "all":
            # 全量重启先都停掉，别让网关在后端重启期间反复连不上。
            for proc in targets:
                proc.stop()
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        for proc in targets:
            try:
                if action == "start":
                    entry = proc.start()
                elif action == "stop":
                    entry = proc.stop()
                else:
                    entry = proc.restart()
            except (ProcessFailure, OSError) as exc:
                LOG.error("%s %s 失败：%s", action, proc.name, exc)
                proc.last_error = str(exc)
                failures.append(str(exc))
                results.append({"ok": False, "error": str(exc), **proc.snapshot()})
            else:
                results.append({"ok": True, **entry})
        if failures:
            raise BatchFailure(failures, results)
        return results

    def _resolve(self, name: str) -> list[ManagedProcess]:
        if name == "all":
            return list(self.processes.values())
        try:
            return [self.processes[name]]
        except KeyError as exc:
            raise UnknownProcess(name) from exc

    def _watch(self) -> None:
        while not self._stop_event.wait(POLL_INTERVAL):
            for proc in self.processes.values():
                try:
                    proc.supervise()
                except Exception:
                    LOG.exception("监督 %s 时出错", proc.name)


class SupervisorServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 上 SO_REUSEADDR 允许两个进程绑同一端口，会让第二个守护进程静默起来。
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], handler, *, supervisor: Supervisor, token: str):
        self.supervisor = supervisor
        self.token = token
        super().__init__(address, handler)


class SupervisorHandler(BaseHTTPRequestHandler):
    server_version = "SevenDoubleSupervisor/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.debug("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        path = self._path()
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if not self._authorized():
            return
        if path == "/":
            self._send(
                200,
                {
                    "service": "魔法裁判 · 七双 守护进程",
                    "endpoints": [
                        "GET  /status",
                        "POST /restart/{backend|gateway|all}",
                        "POST /start/{backend|gateway|all}",
                        "POST /stop/{backend|gateway|all}",
                    ],
                },
            )
            return
        if path == "/status":
            self._send(200, self.server.supervisor.snapshot())
            return
        self._send(404, {"ok": False, "error": f"未知路径 {path}"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        self._drain_body()
        parts = [item for item in self._path().split("/") if item]
        if len(parts) != 2 or parts[0] not in {"start", "stop", "restart"}:
            self._send(
                404,
                {"ok": False, "error": "用法：POST /{start|stop|restart}/{backend|gateway|all}"},
            )
            return
        action, name = parts
        if name not in ALL_NAMES:
            self._send(
                404,
                {"ok": False, "error": f"不受管理的进程名 {name}，可用：{'、'.join(ALL_NAMES)}"},
            )
            return
        try:
            results = self.server.supervisor.run(action, name)
        except UnknownProcess as exc:
            self._send(404, {"ok": False, "error": f"不受管理的进程名 {exc.args[0]}"})
            return
        except BatchFailure as exc:
            self._send(500, {"ok": False, "error": str(exc), "results": exc.results})
            return
        self._send(200, {"ok": True, "action": action, "results": results})

    # ---- 内部实现 ----

    def _path(self) -> str:
        return urlsplit(self.path).path.rstrip("/") or "/"

    def _authorized(self) -> bool:
        # 这个接口只给本机脚本用：浏览器页面（含跨站 fetch）一律拒绝，
        # 否则随便一个网页就能 POST 重启服务。
        if self.headers.get("Origin"):
            self._send(403, {"ok": False, "error": "拒绝带 Origin 的浏览器请求，请用本机脚本或 curl"})
            return False
        token = self.server.token
        if token:
            supplied = self.headers.get("X-Supervisor-Token") or ""
            if not secrets.compare_digest(supplied, token):
                self._send(401, {"ok": False, "error": "缺少或错误的 X-Supervisor-Token"})
                return False
        return True

    def _drain_body(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 0:
            self.rfile.read(length)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            LOG.debug("客户端提前断开：%s %s", self.command, self.path)


def build_processes(args: argparse.Namespace) -> list[ManagedProcess]:
    """后端排在前：全量重启时网关最后起来，少一轮连不上的重试。"""
    python = os.environ.get("GAME_SUPERVISOR_PYTHON") or sys.executable
    explicit_port = args.backend_port or os.environ.get("GAME_SUPERVISOR_BACKEND_PORT")
    backend_port = int(explicit_port) if explicit_port else DEFAULT_BACKEND_PORT
    backend = ManagedProcess(
        "backend",
        [python, "run.py", "--port", str(backend_port)],
        env=dict(os.environ),
        health_url=f"http://127.0.0.1:{backend_port}{BACKEND_HEALTH_PATH}",
        log_path=LOG_DIR / "backend.log",
    )
    gateway_env = dict(os.environ)
    gateway_env.update(read_env_file(Path(args.gateway_env)))
    if explicit_port:
        # 显式改了后端端口时，网关必须跟着改，否则它还在连旧的地址。
        gateway_env["GAME_BACKEND_URL"] = f"http://127.0.0.1:{backend_port}"
    gateway = ManagedProcess(
        "gateway",
        [python, "-m", "gateway.gateway"],
        env=gateway_env,
        settle=GATEWAY_SETTLE,
        log_path=LOG_DIR / "gateway.log",
    )
    return [backend, gateway]


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS or host.startswith("127.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="守护后端与登录网关，并提供 HTTP 重启接口")
    parser.add_argument("--host", default=os.environ.get("GAME_SUPERVISOR_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("GAME_SUPERVISOR_PORT", DEFAULT_SUPERVISOR_PORT)),
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=None,
        help=f"后端端口，默认取 GAME_SUPERVISOR_BACKEND_PORT 或 {DEFAULT_BACKEND_PORT}",
    )
    parser.add_argument(
        "--gateway-env",
        default=os.environ.get("GAME_SUPERVISOR_GATEWAY_ENV", str(ROOT / "gateway" / ".env")),
        help="网关的环境变量文件，默认 gateway/.env",
    )
    parser.add_argument("--no-autostart", action="store_true", help="只提供接口，不自动拉起两个进程")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    token = os.environ.get("GAME_SUPERVISOR_TOKEN", "").strip()
    if not is_loopback(args.host) and not token:
        LOG.error(
            "绑定非回环地址 %s 时必须设置 GAME_SUPERVISOR_TOKEN，否则任何人都能重启服务", args.host
        )
        return 2
    supervisor = Supervisor(build_processes(args), autostart=not args.no_autostart)
    try:
        server = SupervisorServer(
            (args.host, args.port), SupervisorHandler, supervisor=supervisor, token=token
        )
    except OSError as exc:
        LOG.error("无法监听 %s:%s（%s）；可能已有一个守护进程在跑", args.host, args.port, exc)
        return 1

    def on_terminate(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_terminate)
    supervisor.begin()
    LOG.info(
        "守护进程已启动：http://%s:%s/status（后端端口 %s，网关环境 %s，鉴权 %s）",
        args.host,
        args.port,
        args.backend_port or os.environ.get("GAME_SUPERVISOR_BACKEND_PORT") or DEFAULT_BACKEND_PORT,
        args.gateway_env,
        "已开启" if token else "未开启（仅本机可用）",
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        LOG.info("收到中断，正在停止子进程…")
    finally:
        server.server_close()
        supervisor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
