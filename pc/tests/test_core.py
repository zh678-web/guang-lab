"""离线自检：不依赖 adb、不依赖设备、不依赖 Qt。

覆盖：脚本占位符替换、字符集白名单、回执协议、dumpsys 文本解析。
运行： python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guanglab import core  # noqa: E402

FAKE_DUMP = """
Packages:
  Package [com.demo.app] (a1b2c3):
    userId=10123
    codePath=/data/app/~~xyz/com.demo.app-abc
    requested permissions:
      android.permission.CAMERA
      android.permission.WRITE_SECURE_SETTINGS
      android.permission.SYSTEM_ALERT_WINDOW
      com.demo.app.permission.CUSTOM
    install permissions:
      android.permission.INTERNET: granted=true
    User 0: ceDataInode=1 installed=true hidden=false suspended=false
      runtime permissions:

Service Resolver Table:
  Non-Data Actions:
      android.accessibilityservice.AccessibilityService:
        8d3f1a2 com.demo.app/.AccService filter 4b2c1d0
          Action: "android.accessibilityservice.AccessibilityService"
        1234567 com.other/.OtherAcc filter 9999999
      android.service.notification.NotificationListenerService:
        abcd123 com.demo.app/com.demo.app.NLService filter 0011

Receiver Resolver Table:
  Non-Data Actions:
      android.app.action.DEVICE_ADMIN_ENABLED:
        deadbee com.demo.app/.AdminReceiver filter 5555
      android.intent.action.BOOT_COMPLETED:
        cafe001 com.demo.app/.BootReceiver filter 6666
"""


class TestScriptFactory(unittest.TestCase):

    def test_scripts_present_and_lf(self):
        for name in ("grant.sh", "revoke.sh", "ops.sh"):
            text = core.load_script(name)
            self.assertGreater(len(text), 100, name)
            self.assertNotIn("\r\n", text, f"{name} 必须是 LF")

    def test_grant_has_no_placeholder_left(self):
        t = core.Target(
            pkg="com.demo.app",
            perms=["android.permission.CAMERA", "android.permission.WRITE_SECURE_SETTINGS",
                   "android.permission.SYSTEM_ALERT_WINDOW", core.SHIZUKU_PERM],
            accessibility=["com.demo.app.AccService"],
            listeners=["com.demo.app.NLService"],
            admins=["com.demo.app.AdminReceiver"],
        )
        s = core.grant_script(t)
        for ph in ("__PKG__", "__PERMS__", "__OPS__", "__ACC__", "__NL__", "__ADMIN__"):
            self.assertNotIn(ph, s)
        self.assertIn("P='com.demo.app'", s)
        self.assertIn("g 'android.permission.CAMERA'", s)
        # 这三项不能进 pm grant：两个 appop-only + API_V23（脚本自己处理）
        self.assertNotIn("g 'android.permission.SYSTEM_ALERT_WINDOW'", s)
        self.assertNotIn("g 'moe.shizuku.manager.permission.API_V23'", s)
        self.assertEqual(s.count("s '"), len(core.APPOPS))
        self.assertIn("a 'com.demo.app.AccService'", s)
        self.assertIn("l 'com.demo.app.NLService'", s)
        self.assertIn("d 'com.demo.app.AdminReceiver'", s)

    def test_revoke_uses_p_function(self):
        s = core.grant_script(core.Target(pkg="com.demo.app", perms=["android.permission.CAMERA"]),
                              revoke=True)
        self.assertIn("p 'android.permission.CAMERA'", s)
        self.assertNotIn("g 'android.permission.CAMERA'", s)

    def test_invalid_pkg_rejected(self):
        for bad in ("com.demo;rm -rf /", "com.demo app", "com/../x", "$(id)", ""):
            with self.assertRaises(ValueError, msg=bad):
                core.grant_script(core.Target(pkg=bad))
            with self.assertRaises(ValueError, msg=bad):
                core.op_script("freeze", bad)

    def test_op_script_substitutes_action_pkg_extra(self):
        s = core.op_script("perm_grant", "com.demo.app", "android.permission.CAMERA")
        self.assertIn("A='perm_grant'", s)
        self.assertIn("P='com.demo.app'", s)
        self.assertIn("E='android.permission.CAMERA'", s)
        self.assertNotIn("__A__", s)

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            core.op_script("freeze; rm -rf /", "com.demo.app")

    def test_injection_in_extra_rejected(self):
        for bad in ("a' ; id ; '", "$(id)", "x\nrm -rf /", "a|b", "a b"):
            with self.assertRaises(ValueError, msg=bad):
                core.op_script("perm_grant", "com.demo.app", bad)

    def test_run_script_path_whitelist(self):
        pkg = "com.demo.app"
        good = "/sdcard/Android/data/com.demo.app/up.sh"
        self.assertIn(f"E='{good}'", core.op_script("run_script", pkg, good))
        for bad in ("/sdcard/Android/data/com.other/up.sh",
                    "/data/local/tmp/evil.sh",
                    "/sdcard/Android/data/com.demo.app/../evil.sh"):
            with self.assertRaises(ValueError, msg=bad):
                core.op_script("run_script", pkg, bad)


class TestReceipt(unittest.TestCase):

    def test_parse_and_group_order(self):
        out = ("noise line\n"
               "R|act|启动应用|ok|\n"
               "R|perm|android.permission.CAMERA|skip|不能由 shell 授予\n"
               "R|base|解除停用|fail|Permission denied|a|b\n"
               "R|op|SYSTEM_ALERT_WINDOW|ok|\n")
        items = core.parse_receipt(out)
        self.assertEqual(len(items), 4)
        self.assertEqual([r.group for r in items], ["base", "perm", "op", "act"])
        self.assertEqual(items[0].detail, "Permission denied|a|b")
        self.assertEqual(items[0].state, "fail")
        self.assertTrue(items[0].ok is False)
        self.assertEqual(items[1].state, "skip")

    def test_unknown_state_becomes_fail(self):
        self.assertEqual(core.parse_receipt("R|sys|x|weird|")[0].state, "fail")


class TestDumpParsing(unittest.TestCase):

    def test_requested_permissions(self):
        got = core.parse_requested_permissions(FAKE_DUMP)
        self.assertIn("android.permission.CAMERA", got)
        self.assertIn("com.demo.app.permission.CUSTOM", got)
        self.assertNotIn("android.permission.INTERNET", got)  # install permissions 段

    def test_resolver_components(self):
        pkg = "com.demo.app"
        acc = core.resolver_components(FAKE_DUMP, core.ACTION_ACC, pkg)
        self.assertEqual(acc, ["com.demo.app.AccService"])
        nl = core.resolver_components(FAKE_DUMP, core.ACTION_NL, pkg)
        self.assertEqual(nl, ["com.demo.app.NLService"])
        admin = core.resolver_components(FAKE_DUMP, core.ACTION_ADMIN, pkg)
        self.assertEqual(admin, ["com.demo.app.AdminReceiver"])

    def test_normalize_component(self):
        pkg = "com.demo.app"
        self.assertEqual(core.normalize_component(pkg, "com.demo.app/.Acc"), "com.demo.app.Acc")
        self.assertEqual(core.normalize_component(pkg, "com.demo.app/com.demo.app.Acc"),
                         "com.demo.app.Acc")
        self.assertEqual(core.normalize_component(pkg, ".Acc"), "com.demo.app.Acc")
        self.assertIsNone(core.normalize_component(pkg, "../evil;id"))

    def test_dangerous_permissions(self):
        out = ("group:android.permission-group.CAMERA\n"
               "  android.permission.CAMERA\n"
               "  android.permission.RECORD_AUDIO\n")
        self.assertEqual(core.parse_dangerous_permissions(out),
                         {"android.permission.CAMERA", "android.permission.RECORD_AUDIO"})

    def test_suggested_permissions(self):
        perms = ["android.permission.CAMERA", "android.permission.WRITE_SECURE_SETTINGS",
                 "android.permission.INTERNET"]
        got = core.suggested_permissions(perms, {"android.permission.CAMERA"})
        self.assertEqual(got, {"android.permission.CAMERA",
                               "android.permission.WRITE_SECURE_SETTINGS"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
