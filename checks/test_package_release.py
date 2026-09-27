"""`tools/package-release.py` 的分片上传参数（发布脚本上传大对象时用得上）。

2026-09-27 实测出现过 43.9MB 的 Windows 包上传 293.8s（聚合 153 KB/s，像是一条连接
卡住不动），而同一个文件、同一套参数健康时只要 15.3s。分片 PUT 不能跟着别的请求共用
`S3_TIMEOUT`（默认 300s），否则一次抖动就要白等几分钟才重传。这个检查固定住
「分片有自己的、短得多的超时，且能被 `S3_PART_TIMEOUT` 覆盖」这条边界。

运行方式（仓库根目录）：
    .venv/Scripts/python.exe -m unittest checks.test_package_release -v
"""

import importlib.util
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
            self.module.part_timeout_of(values), self.module.timeout_of(values),
            "分片超时不该跟着 S3_TIMEOUT：那正是 293.8s 那次事故的成因",
        )

    def test_can_be_overridden(self):
        self.assertEqual(self.module.part_timeout_of({"S3_PART_TIMEOUT": "12"}), 12)
        self.assertEqual(self.module.part_timeout_of({"S3_PART_TIMEOUT": " 7.9 "}), 7)

    def test_rejects_non_number(self):
        with self.assertRaises(self.module.ReleaseError):
            self.module.part_timeout_of({"S3_PART_TIMEOUT": "很快"})

    def test_key_sits_in_defaults_so_env_can_override(self):
        # load_env 从 DEFAULTS 起步并逐个查同名进程环境变量，键不在 DEFAULTS 里就覆盖不到。
        self.assertIn("S3_PART_TIMEOUT", self.module.DEFAULTS)


class PartRanges(unittest.TestCase):
    """分片切分：片号从 1 起，除最后一片外都等长。"""

    def setUp(self):
        self.module = load_module()

    def test_even_split(self):
        self.assertEqual(self.module.part_ranges(16, 8), [(1, 0, 8), (2, 8, 8)])

    def test_last_part_may_be_shorter(self):
        self.assertEqual(
            self.module.part_ranges(20, 8), [(1, 0, 8), (2, 8, 8), (3, 16, 4)]
        )

    def test_smaller_than_one_part(self):
        self.assertEqual(self.module.part_ranges(3, 8), [(1, 0, 3)])

    def test_empty_file_has_no_part(self):
        self.assertEqual(self.module.part_ranges(0, 8), [])


if __name__ == "__main__":
    unittest.main()
