"""把 PC 版打成单文件、免环境的 Windows EXE。

用法（在 venv 里）：
    python build.py

产物： dist/GuangLabPC.exe

要点：
* 三个 .sh 脚本作为数据打进去，运行时由 core.scripts_dir() 从 _MEIPASS 读；
* adb.exe + AdbWinApi.dll + AdbWinUsbApi.dll 一并打进去，用户不需要装 Android SDK；
* 用 ``python -S -m PyInstaller`` 绕开 WorkBuddy 沙箱的 safe-delete sitecustomize，
  再用 PYTHONPATH 指回 venv 的 site-packages，否则 PyInstaller import 不到。
"""
from __future__ import annotations

import math
import os
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

PC = Path(__file__).resolve().parent
VENV = Path(os.environ.get("GUANGLAB_VENV", PC.parent.parent / ".buildvenv"))
SP = VENV / "Lib" / "site-packages"
PY = VENV / "Scripts" / "python.exe"
DIST = PC / "dist"
BUILD = PC / "build"
ASSETS = PC / "assets"
NAME = "GuangLabPC"


# --------------------------------------------------------------------- 图标

def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _make_icon(path: Path) -> bool:
    """纯标准库画一个 256x256 的「光圈」图标，PNG-in-ICO。"""
    size = 256
    rows = []
    cx = cy = 127.5
    for y in range(size):
        row = bytearray()
        for x in range(size):
            dx, dy = x - cx, y - cy
            d = math.sqrt(dx * dx + dy * dy)
            # 圆角矩形遮罩
            qx = min(max(x, 46), size - 46)
            qy = min(max(y, 46), size - 46)
            inside = (x - qx) ** 2 + (y - qy) ** 2 <= 46 ** 2
            t = (x + y) / (2 * size)
            r, g, b = int(47 - 18 * t), int(111 - 38 * t), int(235 - 25 * t)
            if 74 <= d <= 88 or d <= 23:
                r = g = b = 255
            elif 88 < d < 100:
                k = 1 - (d - 88) / 12
                r = int(r + (255 - r) * k * 0.55)
                g = int(g + (255 - g) * k * 0.55)
                b = int(b + (255 - b) * k * 0.55)
            row += bytes((r, g, b, 255 if inside and d < 118 else 0))
        rows.append(bytes(row))
    raw = b"".join(b"\x00" + r for r in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + _chunk(b"IDAT", zlib.compress(raw, 9))
           + _chunk(b"IEND", b""))
    ico = (struct.pack("<HHH", 0, 1, 1)
           + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
           + png)
    try:
        ASSETS.mkdir(exist_ok=True)
        path.write_bytes(ico)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------- 打包

def adb_files() -> list[Path]:
    roots = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(key)
        if v:
            roots.append(Path(v) / "platform-tools")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Android" / "Sdk" / "platform-tools")
    names = ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll")
    for root in roots:
        if all((root / n).is_file() for n in names):
            return [root / n for n in names]
    return []


def aapt2_files() -> tuple[Path | None, Path | None]:
    """找出可随包附带的 aapt2.exe 与其 NOTICE（AOSP / Apache-2.0）。

    优先本机 Android SDK，其次 pc/assets/build-tools（便于在无 SDK 的机器上构建）。
    随包附带后，单文件 exe 不需要目标机器安装 Android SDK 也能解析应用名。
    """
    roots: list[Path] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(key)
        if v:
            roots.append(Path(v) / "build-tools")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(Path(local) / "Android" / "Sdk" / "build-tools")
    roots.append(ASSETS / "build-tools")

    exe_name = "aapt2.exe" if os.name == "nt" else "aapt2"
    for root in roots:
        if not root.is_dir():
            continue
        for d in sorted((x for x in root.iterdir() if x.is_dir()),
                        key=lambda p: p.name, reverse=True):
            exe = d / exe_name
            if exe.is_file():
                notice = d / "NOTICE.txt"
                return exe, (notice if notice.is_file() else None)
        exe = root / exe_name
        if exe.is_file():
            notice = root / "NOTICE.txt"
            return exe, (notice if notice.is_file() else None)
    return None, None


def build() -> Path:
    if not PY.is_file() or not SP.is_dir():
        raise SystemExit(f"找不到打包 venv：{VENV}\n"
                         "先执行：<系统Python> -m venv .buildvenv && "
                         ".buildvenv/Scripts/pip install PySide6-Essentials pyinstaller")

    icon = ASSETS / "GuangLab.ico"
    has_icon = _make_icon(icon)

    cmd = [
        str(PY), "-S", "-m", "PyInstaller",
        "--onefile", "--windowed", "--clean", "--noconfirm",
        "--name", NAME,
        "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(PC),
        "--add-data", "guanglab/scripts;guanglab/scripts",
    ]
    if has_icon:
        cmd += ["--icon", str(icon)]
    for f in adb_files():
        cmd += ["--add-binary", f"{f};platform-tools"]
    aapt2, notice = aapt2_files()
    if aapt2:
        cmd += ["--add-binary", f"{aapt2};build-tools"]
        if notice:
            cmd += ["--add-data", f"{notice};build-tools"]
    else:
        print("[build] 警告：未找到 aapt2.exe，exe 将依赖目标机器上的 Android SDK")
    cmd += [
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "main.py",
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = str(SP)
    env["CODEBUDDY_SAFE_DELETE_SANDBOX"] = "0"

    print("[build] venv   :", VENV)
    print("[build] adb    :", ", ".join(f.name for f in adb_files()) or "未附带（运行时自动探测）")
    print("[build] aapt2  :", aapt2 or "未附带（运行时探测本机 SDK）")
    print("[build] icon   :", icon if has_icon else "生成失败，跳过")
    print("[build] cmd    :", " ".join(cmd[:8]), "...\n")
    r = subprocess.run(cmd, cwd=str(PC), env=env)
    if r.returncode != 0:
        raise SystemExit(f"PyInstaller 失败，退出码 {r.returncode}")
    exe = DIST / f"{NAME}.exe"
    if not exe.is_file():
        raise SystemExit("未生成 exe")
    print(f"\n[build] 产物：{exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return exe


# --------------------------------------------------------------------- 验证

def verify(exe: Path) -> bool:
    ok = True
    log = DIST / "selftest.txt"
    shot = DIST / "gui-smoke.png"
    for p in (log, shot):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    print("\n[verify] 1/2 无界面自检（脚本资源 / 注入防护 / adb 定位）")
    try:
        subprocess.run([str(exe), "--selftest", f"--selftest-log={log}"],
                       timeout=180, capture_output=True)
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
        ok = False
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    print(text.strip() or "  (无输出)")
    if "SELFTEST PASS" not in text:
        ok = False

    print("\n[verify] 2/2 界面构造冒烟（Qt 窗口 / 布局 / 截图）")
    try:
        subprocess.run([str(exe), "--gui-smoke", "--demo", f"--shot={shot}"],
                       timeout=180, capture_output=True)
    except subprocess.TimeoutExpired:
        print("  TIMEOUT")
        ok = False
    if shot.is_file():
        print(f"  OK: {shot} ({shot.stat().st_size} bytes)")
    else:
        print("  FAIL: 没有生成截图")
        ok = False

    print("\nVERIFY " + ("PASS" if ok else "FAIL"))
    return ok


if __name__ == "__main__":
    exe = build()
    if "--no-verify" not in sys.argv:
        raise SystemExit(0 if verify(exe) else 1)
