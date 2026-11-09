"""应用名解析层的离线测试：纯函数 + FakeAdb 全链路 + 缓存 + 失败原因。"""
from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guanglab import labels  # noqa: E402
from guanglab.adb import Result  # noqa: E402

BADGING = (
    "package: name='com.tencent.mm' versionCode='1'\n"
    "application-label:'WeChat'\n"
    "application-label-zh-CN:'微信'\n"
).encode("utf-8")


class FakeAdb:
    def __init__(self, *, offline=False, path_out="package:/data/app/x/base.apk",
                 pull_ok=True, nonlocalized="", aapt_rc=0, aapt_out=BADGING,
                 aapt_err=b""):
        self.offline = offline
        self.path_out = path_out
        self.pull_ok = pull_ok
        self.nonlocalized = nonlocalized
        self.aapt_rc = aapt_rc
        self.aapt_out = aapt_out
        self.aapt_err = aapt_err
        self.shell_calls: list[str] = []
        self.pull_calls = 0

    def shell(self, serial, command, timeout=60):
        self.shell_calls.append(command)
        if self.offline:
            return Result(1, "", "error: device offline")
        if command.startswith("dumpsys"):
            return Result(0, f"nonLocalizedLabel={self.nonlocalized or 'null'}", "")
        if command.startswith("pm path"):
            return Result(0, self.path_out, "")
        return Result(0, "", "")

    def pull(self, serial, remote, local, timeout=60):
        self.pull_calls += 1
        if self.pull_ok:
            Path(local).write_bytes(b"fake apk")
            return Result(0, "1 file pulled", "")
        return Result(1, "", "adb: error: failed to copy")

    def aapt_result(self):
        return SimpleNamespace(returncode=self.aapt_rc, stdout=self.aapt_out,
                               stderr=self.aapt_err)


def make_resolver(fake, tmp: Path):
    with patch.object(labels, "find_aapt2", return_value="aapt2.exe"):
        return labels.LabelResolver(fake, cache_file=tmp / "labels.json")


class TestPureFunctions(unittest.TestCase):
    def test_badging_prefers_simplified_chinese(self):
        self.assertEqual(labels.label_from_badging(BADGING.decode("utf-8")), "微信")
        self.assertEqual(
            labels.label_from_badging("application-label:'App'\napplication-label-zh-rCN:'中文'\n"),
            "中文")
        self.assertEqual(
            labels.label_from_badging("application-label:'Only English'\n"),
            "Only English")
        self.assertEqual(labels.label_from_badging("package: name='x'\n"), "")
        self.assertEqual(
            labels.label_from_badging("application-label:'It\\'s OK'\n"), "It's OK")

    def test_dumpsys_nonlocalized(self):
        self.assertEqual(labels.label_from_dumpsys("nonLocalizedLabel=null }"), "")
        self.assertEqual(labels.label_from_dumpsys("nonLocalizedLabel=测试应用}"), "测试应用")

    def test_decode_gbk_fallback(self):
        raw = "application-label:'中文名'\n".encode("gbk")
        self.assertEqual(labels.label_from_badging(labels._decode(raw)), "中文名")

    def test_bundled_aapt2_has_priority(self):
        with patch.object(labels, "bundled_aapt2", return_value="BUNDLED"), \
             patch.object(labels.os.path, "isfile", return_value=True):
            self.assertEqual(labels.find_aapt2(None), "BUNDLED")
            self.assertEqual(labels.find_aapt2("EXPLICIT"), "EXPLICIT")


class TestResolver(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _resolve(self, fake, pkg="com.tencent.mm"):
        r = make_resolver(fake, self.tmp)
        with patch.object(labels.subprocess, "run", return_value=fake.aapt_result()) as m:
            name, reason = r.resolve_detail("SERIAL", pkg)
        return r, name, reason, m

    def test_success_via_aapt2(self):
        fake = FakeAdb()
        r, name, reason, m = self._resolve(fake)
        self.assertEqual((name, reason), ("微信", ""))
        self.assertEqual(fake.pull_calls, 1)
        self.assertEqual(m.call_args[0][0][1:3], ["dump", "badging"])

    def test_success_via_dumpsys_needs_no_pull(self):
        fake = FakeAdb(nonlocalized="免拉包应用")
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual((name, reason), ("免拉包应用", ""))
        self.assertEqual(fake.pull_calls, 0)

    def test_cache_hit_skips_adb(self):
        fake = FakeAdb()
        r, name, _, _ = self._resolve(fake)
        self.assertEqual(name, "微信")
        before = len(fake.shell_calls)
        self.assertEqual(r.resolve("SERIAL", "com.tencent.mm"), "微信")
        self.assertEqual(len(fake.shell_calls), before)

    def test_cache_survives_restart(self):
        fake = FakeAdb()
        r, _, _, _ = self._resolve(fake)
        r.flush()
        fresh = FakeAdb(offline=True)
        r2 = make_resolver(fresh, self.tmp)
        self.assertEqual(r2.resolve("SERIAL", "com.tencent.mm"), "微信")
        self.assertEqual(fresh.shell_calls, [])

    def test_offline_reports_reason(self):
        fake = FakeAdb(offline=True)
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual(name, "")
        self.assertIn("offline", reason)

    def test_no_device_reports_reason(self):
        r = make_resolver(FakeAdb(), self.tmp)
        name, reason = r.resolve_detail("", "com.x")
        self.assertEqual(name, "")
        self.assertIn("设备", reason)

    def test_missing_apk_path_reports_reason(self):
        fake = FakeAdb(path_out="")
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual(name, "")
        self.assertIn("pm path", reason)

    def test_pull_failure_reports_reason(self):
        fake = FakeAdb(pull_ok=False)
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual(name, "")
        self.assertIn("pull", reason)

    def test_aapt2_failure_reports_reason(self):
        fake = FakeAdb(aapt_rc=1, aapt_err=b"bad apk")
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual(name, "")
        self.assertIn("aapt2 退出码 1", reason)

    def test_no_label_in_badging_reports_reason(self):
        fake = FakeAdb(aapt_out=b"package: name='x'\n")
        r, name, reason, _ = self._resolve(fake)
        self.assertEqual(name, "")
        self.assertIn("application-label", reason)

    def test_no_aapt2_reports_reason(self):
        fake = FakeAdb()
        with patch.object(labels, "find_aapt2", return_value=None):
            r = labels.LabelResolver(fake, cache_file=self.tmp / "labels.json")
        name, reason = r.resolve_detail("SERIAL", "com.x")
        self.assertEqual(name, "")
        self.assertIn("aapt2", reason)
        self.assertFalse(r.available)

    def test_resolve_many_progress_and_stop(self):
        fake = FakeAdb()
        r = make_resolver(fake, self.tmp)
        seen = []
        with patch.object(labels.subprocess, "run", return_value=fake.aapt_result()):
            n = r.resolve_many("SERIAL", ["a", "b", "c"],
                               lambda t: seen.append(t))
        self.assertEqual(n, 3)
        self.assertEqual([x[3] for x in seen], [1, 2, 3])
        self.assertTrue(all(x[1] == "微信" for x in seen))

        stop = threading.Event()
        stop.set()
        seen2 = []
        with patch.object(labels.subprocess, "run", return_value=fake.aapt_result()):
            r2 = make_resolver(FakeAdb(), self.tmp / "other")
            n2 = r2.resolve_many("SERIAL", ["x", "y"], lambda t: seen2.append(t), stop)
        self.assertEqual((n2, seen2), (0, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
