"""`tools/update_manifest.py` 的更新清单维护逻辑（发布脚本调用它）。

部署者把「版本区间 → 不同更新信息」写进 `data/updates.json`，发布脚本只刷新
每个平台那条兜底区间（没有 min_version / max_version 的）。这个检查固定住
「手工写的字段与更窄的区间条目不能被发布流程覆盖掉」这条数据边界。

运行方式（仓库根目录）：
    .venv/Scripts/python.exe -m unittest checks.test_update_manifest -v
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "update_manifest.py"


def load_module():
    spec = importlib.util.spec_from_file_location("update_manifest", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManifestRefresh(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "updates.json"

    def write(self, payload):
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def entries(self):
        return [
            {
                "platform": "windows",
                "url": "https://cdn.example/魔法裁判Windows.zip",
                "updater_url": "https://cdn.example/Updater.exe",
                "size": 100,
                "sha256": "a" * 64,
            },
            {
                "platform": "android",
                "url": "https://cdn.example/app-release.apk",
                "size": 200,
                "sha256": "b" * 64,
            },
        ]

    def test_creates_one_catch_all_entry_per_platform(self):
        self.module.refresh_manifest(self.path, "1.1.0", self.entries())
        updates = self.read()["updates"]
        self.assertEqual([item["platform"] for item in updates], ["windows", "android"])
        for item in updates:
            self.assertEqual(item["latest"], "1.1.0")
            self.assertNotIn("min_version", item)
            self.assertNotIn("max_version", item)
        self.assertEqual(updates[1]["size"], 200)

    def test_keeps_handwritten_fields_and_narrow_ranges(self):
        self.write(
            {
                "updates": [
                    {
                        "platform": "windows",
                        "min_version": "1.0.0",
                        "max_version": "1.1.0",
                        "latest": "1.0.9",
                        "notes": "老版本先升到 1.0.9",
                    },
                    {
                        "platform": "windows",
                        "latest": "1.0.5",
                        "minimum": "1.0.0",
                        "title": "必须更新",
                        "notes": "兜底区间的说明",
                        "guide_url": "https://example.invalid/help",
                        "size": 1,
                        "sha256": "c" * 64,
                    },
                ]
            }
        )
        self.module.refresh_manifest(self.path, "1.1.0", self.entries())
        updates = self.read()["updates"]
        self.assertEqual(len(updates), 3, "windows 兜底区间要就地刷新而不是新加一条")
        narrow, catch_all, android = updates
        self.assertEqual(narrow["latest"], "1.0.9")
        self.assertEqual(narrow["notes"], "老版本先升到 1.0.9")
        self.assertEqual(narrow["max_version"], "1.1.0")
        self.assertEqual(catch_all["latest"], "1.1.0")
        self.assertEqual(catch_all["notes"], "兜底区间的说明")
        self.assertEqual(catch_all["title"], "必须更新")
        self.assertEqual(catch_all["minimum"], "1.0.0")
        self.assertEqual(catch_all["guide_url"], "https://example.invalid/help")
        self.assertEqual(catch_all["url"], "https://cdn.example/魔法裁判Windows.zip")
        self.assertEqual(catch_all["size"], 100)
        self.assertEqual(android["platform"], "android")

    def test_platform_any_counts_as_catch_all(self):
        self.write({"updates": [{"platform": "any", "latest": "1.0.0"}]})
        self.module.refresh_manifest(self.path, "1.1.0", self.entries()[:1])
        updates = self.read()["updates"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["latest"], "1.1.0")

    def test_broken_json_is_refused_without_touching_the_file(self):
        self.path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(self.module.ManifestError):
            self.module.refresh_manifest(self.path, "1.1.0", self.entries())
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ not json")


class ClientVersionSource(unittest.TestCase):
    def test_reads_the_version_name_from_pubspec(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            pubspec = Path(directory) / "pubspec.yaml"
            pubspec.write_text("name: x\nversion: 2.3.4+7\n", encoding="utf-8")
            original = module.PUBSPEC
            module.PUBSPEC = pubspec
            try:
                self.assertEqual(module.client_version(), "2.3.4")
            finally:
                module.PUBSPEC = original

    def test_rejects_a_pubspec_without_a_version(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            pubspec = Path(directory) / "pubspec.yaml"
            pubspec.write_text("name: x\nversion: latest\n", encoding="utf-8")
            original = module.PUBSPEC
            module.PUBSPEC = pubspec
            try:
                with self.assertRaises(module.ManifestError):
                    module.client_version()
            finally:
                module.PUBSPEC = original


if __name__ == "__main__":
    unittest.main()
