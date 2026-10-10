"""Windows 更新器的命令行检查（隔离下载缓存，不改系统安装状态）。

这是应用内更新系统的独立检查，不碰别的检查文件。更新器是随
`flutter build windows --release` 一起构建出来的 `Updater.exe`；没有构建产物时
整个文件跳过，不会让其它环境的后端检查失败。

不执行真实安装的 --uninstall 或会装证书的 --prepare；卸载检查只运行改了产品名与
快捷方式名的临时副本，所有程序文件、下载缓存与数据都在独立临时目录中。

运行方式（仓库根目录）：
    .venv/Scripts/python.exe -m unittest checks.test_updater_cli -v
"""

import ctypes
import hashlib
import os
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from ctypes import wintypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tools.update_manifest import client_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATER = (
    PROJECT_ROOT / "client" / "build" / "windows" / "x64" / "runner" / "Release" / "Updater.exe"
)


@unittest.skipUnless(os.name == "nt", "Windows 更新器只能在 Windows 上运行")
@unittest.skipUnless(UPDATER.is_file(), f"缺少 {UPDATER}，先执行 flutter build windows --release")
class UpdaterCommandLine(unittest.TestCase):
    """参数足够时命令行就能完成功能：先验证不会改动机器状态的那几条。"""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.local = Path(directory.name)
        self.environment = {
            **os.environ,
            "LOCALAPPDATA": str(self.local),
            "APPDATA": str(self.local),
        }

    def run_updater(self, *arguments, timeout=120):
        return subprocess.run(
            [str(UPDATER), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=self.environment,
            check=False,  # 断言由调用方看 returncode 做，这里不抛异常
        )

    def test_version_matches_the_client_release_version(self):
        """--version 必须精确匹配 client_version() 读取的 Dart 发行版本。"""
        result = self.run_updater("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((result.stdout or "").strip(), "magicjudge-updater " + client_version())

    def test_read_only_commands_preserve_downloads(self):
        cache = self.local / "MagicJudge" / "downloads" / "cached.zip"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"cached package")
        for command in ("--help", "--version", "--check-install"):
            with self.subTest(command=command):
                self.run_updater(command, "--dir", str(self.local / "bare"))
                self.assertEqual(cache.read_bytes(), b"cached package")

    def test_check_install_reports_not_installed_for_a_bare_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_updater("--check-install", "--dir", directory)
        # 4 = 没有找到安装；空目录必须是这个结果，不能报成成功。
        self.assertEqual(result.returncode, 4, result.stdout or result.stderr)

    def test_prepare_dry_run_changes_nothing(self):
        cache = self.local / "MagicJudge" / "downloads" / "cached.zip"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"cached package")
        result = self.run_updater("--prepare", "--dry-run")
        self.assertEqual(
            result.returncode,
            0,
            f"dry-run 必须成功：{result.stdout or result.stderr}",
        )
        self.assertEqual(cache.read_bytes(), b"cached package")
        self.assertFalse((self.local / "MagicJudge" / "update.log").exists())

    def test_exit_cleanup_continues_past_locked_files_without_changing_exit_code(self):
        downloads = self.local / "MagicJudge" / "downloads"
        nested = downloads / "old" / "nested"
        nested.mkdir(parents=True)
        (nested / "package.zip").write_bytes(b"old package")
        locked = downloads / "locked.zip"
        locked.write_bytes(b"in use")
        outside = downloads.parent / "keep.txt"
        outside.write_bytes(b"not a download")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(locked), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value, ctypes.get_last_error())
        try:
            result = self.run_updater(
                "--install", "--portable", "--dir", str(self.local / "app"), "--silent"
            )
        finally:
            kernel.CloseHandle(handle)
        self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
        self.assertEqual(locked.read_bytes(), b"in use")
        self.assertFalse((downloads / "old").exists())
        self.assertEqual(outside.read_bytes(), b"not a download")
        result = self.run_updater(
            "--install", "--portable", "--dir", str(self.local / "app"), "--silent"
        )
        self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
        self.assertFalse(downloads.exists())

    def test_exit_cleanup_does_not_follow_a_linked_download_directory(self):
        outside = self.local / "outside"
        outside.mkdir()
        keep = outside / "keep.zip"
        keep.write_bytes(b"not a download")
        downloads = self.local / "MagicJudge" / "downloads"
        downloads.parent.mkdir()
        link = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(downloads), str(outside)],
            capture_output=True,
            check=False,
        )
        self.assertEqual(link.returncode, 0, link.stderr)
        result = self.run_updater(
            "--install", "--portable", "--dir", str(self.local / "app"), "--silent"
        )
        self.assertEqual(result.returncode, 1, result.stdout or result.stderr)
        self.assertEqual(keep.read_bytes(), b"not a download")

    def test_install_against_an_unreachable_server_fails_without_a_half_install(self):
        downloads = self.local / "MagicJudge" / "downloads"
        downloads.mkdir(parents=True)
        (downloads / "previous.zip").write_bytes(b"old package")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "MagicJudge"
            result = self.run_updater(
                "--install",
                "--from",
                "http://127.0.0.1:1",
                "--dir",
                str(target),
                "--silent",
            )
            self.assertNotEqual(result.returncode, 0, "取不到更新包时必须报失败")
            self.assertFalse(
                (target / "seven_double_client.exe").exists(),
                "下载失败却留下了程序文件",
            )
            self.assertFalse(downloads.exists())

    def test_install_running_from_target_replaces_itself_and_preserves_package_updater(self):
        target = self.local / "安装目录 with spaces"
        target.mkdir()
        updater = target / "Updater.exe"
        original = UPDATER.read_bytes()
        updater.write_bytes(original)
        client = target / "seven_double_client.exe"
        client.write_bytes(b"old client")

        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_arguments):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(self.local)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for index, directory in enumerate((str(target), ".")):
                with self.subTest(directory=directory):
                    # PE 尾部附加数据不影响运行，能核对包内新文件没有被旧自身覆盖。
                    replacement = original + f"package updater {index}".encode()
                    package = self.local / "update.zip"
                    with zipfile.ZipFile(package, "w") as archive:
                        archive.writestr("Updater.exe", replacement)
                        archive.writestr("seven_double_client.exe", b"new client")
                    result = subprocess.run(
                        [
                            str(updater),
                            "--install",
                            "--portable",
                            "--silent",
                            "--dir",
                            directory,
                            "--from",
                            f"http://127.0.0.1:{server.server_port}/update.zip",
                            "--sha256",
                            hashlib.sha256(package.read_bytes()).hexdigest(),
                            "--size",
                            str(package.stat().st_size),
                        ],
                        cwd=target,
                        env=self.environment,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=120,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(updater.read_bytes(), replacement)
                    self.assertEqual(client.read_bytes(), b"new client")
                    self.assertFalse((target / ".install-staging").exists())
                    self.assertFalse((self.local / "MagicJudge" / "downloads").exists())
            installed_updater = self.local / "MagicJudge" / "Updater.exe"
            installed_updater.write_bytes(replacement)
            result = self.run_updater("--prepare", "--dry-run", "--dir", str(target))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("updater_copy=ready", result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @unittest.skipIf(
        os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "此边界需要普通用户令牌，管理员终端由隔离原生验收覆盖",
    )
    def test_uninstall_without_elevated_privileges_preserves_files_and_data(self):
        target = self.local / "app"
        target.mkdir()
        client = target / "seven_double_client.exe"
        client.write_bytes(b"installed client")
        data = self.local / "com.sevendouble" / "save.dat"
        data.parent.mkdir()
        data.write_bytes(b"saved game")
        result = self.run_updater(
            "--uninstall", "--dir", str(target), "--purge-data", "--silent", "--elevated"
        )
        self.assertEqual(result.returncode, 3, result.stdout or result.stderr)
        self.assertEqual(client.read_bytes(), b"installed client")
        self.assertEqual(data.read_bytes(), b"saved game")

    def test_install_rejects_protected_targets_before_creating_or_downloading(self):
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell.SHGetKnownFolderPath.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole = ctypes.WinDLL("ole32")
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        targets = [Path(os.environ["SYSTEMROOT"]).anchor]
        for guid in (
            "F38BF404-1D43-42F2-9305-67DE0B28FC23",  # Windows
            "5E6C858F-0E22-4760-9AFE-EA3317B67173",  # 用户主目录
            "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",  # 桌面
            "FDD39AD0-238F-46AF-ADB4-6C85480369C7",  # 文档
            "374DE290-123F-4565-9164-39C4925E467B",  # 下载
        ):
            identifier = ctypes.create_string_buffer(uuid.UUID(guid).bytes_le)
            path = ctypes.c_void_p()
            self.assertEqual(shell.SHGetKnownFolderPath(identifier, 0, None, ctypes.byref(path)), 0)
            try:
                targets.append(ctypes.wstring_at(path))
            finally:
                ole.CoTaskMemFree(path)
        targets.extend((targets[1] + r"\System32", targets[2] + r"\child\.."))
        alias = self.local / "windows-alias"
        link = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(alias), targets[1]],
            capture_output=True,
            check=False,
        )
        self.assertEqual(link.returncode, 0, link.stderr)
        self.addCleanup(alias.rmdir)
        targets.extend((str(alias), str(alias / "System32")))
        for target in targets:
            with self.subTest(target=target):
                result = self.run_updater(
                    "--install",
                    "--portable",
                    "--silent",
                    "--from",
                    "http://127.0.0.1:1",
                    "--dir",
                    target,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    @unittest.skipUnless(
        os.name == "nt" and bool(ctypes.windll.shell32.IsUserAnAdmin()),
        "隔离卸载检查需要管理员终端，避免自动化触发 UAC",
    )
    def test_uninstall_warning_cancellation_preserves_files_and_count_boundary(self):
        product = "MJ" + uuid.uuid4().hex[:8]
        display = "验收" + uuid.uuid4().hex[:2]
        binary = UPDATER.read_bytes()
        for source, replacement in (("MagicJudge", product), ("魔法裁判", display)):
            before, after = source.encode("utf-16le"), replacement.encode("utf-16le")
            self.assertIn(before, binary)
            binary = binary.replace(before, after)
        updater = self.local / "isolated-Updater.exe"
        updater.write_bytes(binary)
        user = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        user.GetDlgItem.restype = wintypes.HWND
        user.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        for suffix, count, warning_expected in (
            (".TxT", 1, True),
            (".dll", 799, False),
            (".dll", 800, True),
        ):
            with self.subTest(suffix=suffix, count=count):
                target = self.local / f"app-{count}"
                target.mkdir()
                (target / "Updater.exe").write_bytes(binary)
                nested = target / "nested"
                nested.mkdir()
                for index in range(count):
                    (nested / f"file-{index}{suffix}").write_bytes(b"keep")
                cache = self.local / product / "downloads" / "cached.zip"
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(b"cached package")
                process = subprocess.Popen(
                    [str(updater), "--uninstall", "--silent", "--dir", str(target)],
                    env=self.environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                dialogs = []

                @callback_type
                def cancel_warning(window, _parameter, expected_pid=process.pid, observed=dialogs):
                    pid = wintypes.DWORD()
                    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    no_button = user.GetDlgItem(window, 7) if pid.value == expected_pid else None
                    if no_button:
                        observed.append(window)
                        user.PostMessageW(no_button, 0xF5, 0, 0)  # BM_CLICK / IDNO
                    return True

                try:
                    deadline = time.monotonic() + 15
                    while process.poll() is None and time.monotonic() < deadline:
                        user.EnumWindows(cancel_warning, 0)
                        time.sleep(0.02)
                    process.communicate(timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)
                self.assertEqual(bool(dialogs), warning_expected, f"exit={process.returncode}")
                self.assertEqual(process.returncode, 1223 if warning_expected else 0)
                self.assertEqual((target / "Updater.exe").read_bytes(), binary)
                if warning_expected:
                    self.assertEqual(cache.read_bytes(), b"cached package")
                    for index in range(count):
                        self.assertEqual((nested / f"file-{index}{suffix}").read_bytes(), b"keep")
                else:
                    self.assertFalse(nested.exists())


if __name__ == "__main__":
    unittest.main()
