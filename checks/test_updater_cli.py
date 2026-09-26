"""Windows 更新器的命令行检查（只跑只读/无副作用的子命令）。

这是应用内更新系统的独立检查，不碰别的检查文件。更新器是随
`flutter build windows --release` 一起构建出来的 `Updater.exe`；没有构建产物时
整个文件跳过，不会让其它环境的后端检查失败。

刻意**不**执行 `--uninstall`、`--prepare`（不带 --dry-run）这类会改动机器状态的命令：
它们会删计划任务、删注册表键、往系统信任库装证书，必须由人工按 README 的步骤验证。

运行方式（仓库根目录）：
    .venv/Scripts/python.exe -m unittest checks.test_updater_cli -v
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATER = (
    PROJECT_ROOT
    / "client"
    / "build"
    / "windows"
    / "x64"
    / "runner"
    / "Release"
    / "Updater.exe"
)

VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")


@unittest.skipUnless(os.name == "nt", "Windows 更新器只能在 Windows 上运行")
@unittest.skipUnless(UPDATER.is_file(), f"缺少 {UPDATER}，先执行 flutter build windows --release")
class UpdaterCommandLine(unittest.TestCase):
    """参数足够时命令行就能完成功能：先验证不会改动机器状态的那几条。"""

    def run_updater(self, *arguments, timeout=120):
        return subprocess.run(
            [str(UPDATER), *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def test_version_reports_a_semantic_version(self):
        result = self.run_updater("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = (result.stdout or "").strip()
        if output:
            self.assertRegex(output, VERSION_PATTERN)

    def test_help_lists_the_documented_commands(self):
        result = self.run_updater("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout or ""
        if output.strip():
            for flag in ("--install", "--update-app", "--prepare", "--uninstall"):
                self.assertIn(flag, output)

    def test_check_install_reports_not_installed_for_a_bare_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_updater("--check-install", "--dir", directory)
        # 4 = 没有找到安装；空目录必须是这个结果，不能报成成功。
        self.assertEqual(result.returncode, 4, result.stdout or result.stderr)

    def test_prepare_dry_run_changes_nothing(self):
        result = self.run_updater("--prepare", "--dry-run")
        self.assertEqual(
            result.returncode,
            0,
            f"dry-run 必须成功：{result.stdout or result.stderr}",
        )

    def test_install_against_an_unreachable_server_fails_without_a_half_install(self):
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
        # 网络失败不该留下一个「看起来装好了」的目录。
        self.assertFalse(
            (target / "seven_double_client.exe").exists(),
            "下载失败却留下了程序文件",
        )


if __name__ == "__main__":
    unittest.main()
