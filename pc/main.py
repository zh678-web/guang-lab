"""光 · 实验室 PC 版入口。

双击 / 无参数        → 启动桌面界面
--selftest           → 无界面自检（验证打包后的脚本资源确实可用）
--version            → 打印版本
"""
from __future__ import annotations

import sys


def selftest() -> int:
    from guanglab import __version__, core
    from guanglab.adb import find_adb

    print(f"GuangLab PC {__version__}")
    print(f"python   : {sys.version.split()[0]}")
    print(f"frozen   : {bool(getattr(sys, '_MEIPASS', None))}")
    print(f"scripts  : {core.scripts_dir()}")

    ok = True
    for name in ("grant.sh", "revoke.sh", "ops.sh"):
        try:
            text = core.load_script(name)
            print(f"  [OK] {name} {len(text)} bytes, LF={chr(13) not in text}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            ok = False

    try:
        t = core.Target(pkg="com.test.app", perms=["android.permission.CAMERA"],
                        accessibility=["com.test.app.AccService"])
        s = core.grant_script(t)
        assert "__PKG__" not in s and "P='com.test.app'" in s
        o = core.op_script("freeze", "com.test.app")
        assert "A='freeze'" in o and "__E__" not in o
        r = core.parse_receipt("R|base|解除停用|ok|\nR|perm|android.permission.CAMERA|skip|x")
        assert len(r) == 2 and r[0].group == "base" and r[1].state == "skip"
        print("  [OK] script factory + receipt parser")
    except Exception as e:
        print(f"  [FAIL] core: {e}")
        ok = False

    try:
        core.op_script("freeze", "com.test;id")
        print("  [FAIL] injection guard did not reject bad package")
        ok = False
    except ValueError:
        print("  [OK] injection guard")

    adb = find_adb()
    print(f"adb      : {adb or 'NOT FOUND (can be set in Settings)'}")
    print("SELFTEST " + ("PASS" if ok else "FAIL"))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    return 0 if ok else 1


def main() -> int:
    args = sys.argv[1:]
    # --windowed 打包后没有控制台，自检输出可落盘以便验证
    log_arg = next((a.split("=", 1)[1] for a in args if a.startswith("--selftest-log=")), None)
    if log_arg:
        try:
            sys.stdout = open(log_arg, "w", encoding="utf-8")
            sys.stderr = sys.stdout
        except OSError:
            pass
    if "--version" in args:
        from guanglab import __version__
        print(f"GuangLab PC {__version__}")
        return 0
    if "--selftest" in args:
        return selftest()
    if "--gui-smoke" in args:
        import os
        os.environ["GUANGLAB_SMOKE"] = "1"
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            from guanglab.ui import MainWindow
        except ImportError as e:
            print(f"Qt 依赖缺失：{e}")
            return 2
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        win = MainWindow()
        if "--demo" in args:
            # 纯 UI 演示数据：只用于打包后检查布局，不触碰 adb
            from types import SimpleNamespace
            from guanglab import core as _c
            third = {"com.tencent.mm", "com.eg.android.AlipayGphone",
                     "com.android.chrome", "com.ss.android.ugc.aweme",
                     "com.xiaomi.market", "org.telegram.messenger"}
            system = {"com.android.settings", "com.miui.securitycenter"}
            installed = third | system
            inv = {"third": third, "system": system,
                   "disabled": {"com.android.chrome"},
                   "uninstalled": {"com.miui.system"},
                   "installed": installed}
            win._fill_inventory((inv, {"android.permission.CAMERA"}))
            win._fill_target(_c.Target(
                pkg="com.tencent.mm",
                perms=["android.permission.CAMERA", "android.permission.RECORD_AUDIO",
                       "android.permission.WRITE_SECURE_SETTINGS",
                       "android.permission.READ_CONTACTS", "android.permission.INTERNET"],
                accessibility=["com.tencent.mm.WeChatAccessibility"],
                listeners=[], admins=[],
            ))
            win._show_result(
                "一键授权 · com.tencent.mm",
                SimpleNamespace(rc=0, out=(
                    "R|base|解除停用|ok|\n"
                    "R|perm|android.permission.CAMERA|ok|\n"
                    "R|perm|android.permission.RECORD_AUDIO|ok|\n"
                    "R|perm|android.permission.WRITE_SECURE_SETTINGS|skip|该权限不能由 shell 授予\n"
                    "R|shizuku|Shizuku 授权|skip|目标应用未声明 Shizuku 权限\n"
                    "R|op|SYSTEM_ALERT_WINDOW|ok|\n"
                    "R|op|GET_USAGE_STATS|ok|\n"
                    "R|acc|com.tencent.mm.WeChatAccessibility|ok|\n"
                    "R|batt|免电池优化|ok|\n"), err=""),
                1.24,
            )
        win.show()
        shot = next((a.split("=", 1)[1] for a in args if a.startswith("--shot=")), None)

        def finish():
            if shot:
                win.grab().save(shot)
                try:
                    print(f"screenshot: {shot}")
                except Exception:
                    pass
            app.quit()

        QTimer.singleShot(1200, finish)
        return app.exec()

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        from guanglab.ui import APP_TITLE, MainWindow
    except ImportError as e:
        print(f"Qt 依赖缺失：{e}\n请执行 pip install PySide6-Essentials")
        return 2

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
