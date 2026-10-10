"""Windows 发行包完整性与 `tools/package-release.py` 的分片上传参数。

2026-09-27 实测出现过 43.9MB 的 Windows 包上传 293.8s（聚合 153 KB/s，像是一条连接
卡住不动），而同一个文件、同一套参数健康时只要 15.3s。分片 PUT 不能跟着别的请求共用
`S3_TIMEOUT`（默认 300s），否则一次抖动就要白等几分钟才重传。这个检查固定住
「分片有自己的、短得多的超时，且能被 `S3_PART_TIMEOUT` 覆盖」这条边界。

运行方式（仓库根目录）：
    .venv/Scripts/python.exe -m unittest checks.test_package_release -v
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "package-release.py"


def load_module():
    spec = importlib.util.spec_from_file_location("package_release", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PartTimeout(unittest.TestCase):
    """分片 PUT 的 socket 超时。"""

    def setUp(self):
        self.module = load_module()

    def test_default_is_much_shorter_than_request_timeout(self):
        values = {"S3_TIMEOUT": "300"}
        self.assertEqual(self.module.part_timeout_of(values), 30)
        self.assertLess(
            self.module.part_timeout_of(values),
            self.module.timeout_of(values),
            "分片超时不该跟着 S3_TIMEOUT：那正是 293.8s 那次事故的成因",
        )

    def test_can_be_overridden(self):
        self.assertEqual(self.module.part_timeout_of({"S3_PART_TIMEOUT": "12"}), 12)
        self.assertEqual(self.module.part_timeout_of({"S3_PART_TIMEOUT": " 7.9 "}), 7)

    def test_rejects_non_number(self):
        with self.assertRaises(self.module.ReleaseError):
            self.module.part_timeout_of({"S3_PART_TIMEOUT": "很快"})


class PartRanges(unittest.TestCase):
    """分片切分：片号从 1 起，除最后一片外都等长。"""

    def setUp(self):
        self.module = load_module()

    def test_even_split(self):
        self.assertEqual(self.module.part_ranges(16, 8), [(1, 0, 8), (2, 8, 8)])

    def test_last_part_may_be_shorter(self):
        self.assertEqual(self.module.part_ranges(20, 8), [(1, 0, 8), (2, 8, 8), (3, 16, 4)])

    def test_smaller_than_one_part(self):
        self.assertEqual(self.module.part_ranges(3, 8), [(1, 0, 3)])

    def test_empty_file_has_no_part(self):
        self.assertEqual(self.module.part_ranges(0, 8), [])


class WindowsReleaseBundle(unittest.TestCase):
    def test_debug_engine_cannot_replace_previous_release(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module.__dict__["ROOT"] = root
            sdk = root / "flutter"
            engine = sdk / "bin/cache/artifacts/engine/windows-x64-release/flutter_windows.dll"
            engine.parent.mkdir(parents=True)
            engine.write_bytes(b"release engine")
            config = root / "client/.dart_tool/package_config.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"flutterRoot": sdk.as_uri()}), encoding="utf-8")
            source = root / "Release"
            source.mkdir()
            module.__dict__["WINDOWS_RELEASE"] = source
            module.__dict__["WINDOWS_EXE"] = source / "seven_double_client.exe"
            module.WINDOWS_EXE.write_bytes(b"runner")
            bundled_engine = source / "flutter_windows.dll"
            bundled_engine.write_bytes(engine.read_bytes())
            package = source / "release.zip"
            module.make_zip(package, source)
            previous = module.sha256_file(package)

            bundled_engine.write_bytes(b"debug engine")
            with self.assertRaisesRegex(module.ReleaseError, "Release 引擎不一致"):
                module.make_zip(package, source)
            self.assertEqual(module.sha256_file(package), previous)
            self.assertFalse(package.with_name(package.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
