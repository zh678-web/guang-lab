"""可选的「应用中文名」解析。

adb shell 拿不到 ApplicationInfo.label（那是 PackageManager 的资源解析结果）。
这里用本机 Android SDK 自带的 aapt2 按需解析 APK 的 badging，只做展示，
不参与任何命令构造。没有 aapt2 时自动降级为只显示包名，功能不受影响。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_LABEL_RE = re.compile(r"application-label(?:-([A-Za-z\-]+))?:'((?:[^'\\]|\\.)*)'")
_NONLOCAL_RE = re.compile(r"nonLocalizedLabel\s*=\s*([^\s]+)")


def find_aapt2(explicit: str | None = None) -> str | None:
    if explicit and os.path.isfile(explicit):
        return explicit
    env = os.environ.get("AAPT2_PATH")
    if env and os.path.isfile(env):
        return env

    roots: list[str] = []
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        v = os.environ.get(key)
        if v:
            roots.append(os.path.join(v, "build-tools"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Android", "Sdk", "build-tools"))

    exe = "aapt2.exe" if os.name == "nt" else "aapt2"
    for root in roots:
        if not os.path.isdir(root):
            continue
        versions = sorted(
            (d for d in Path(root).iterdir() if d.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
        for d in versions:
            p = d / exe
            if p.is_file():
                return str(p)
    return None


def label_from_dumpsys(dump: str) -> str:
    m = _NONLOCAL_RE.search(dump or "")
    if not m:
        return ""
    v = m.group(1).strip()
    return "" if v in {"null", "0", ""} else v


def label_from_badging(text: str) -> str:
    """优先中文标签，其次默认标签。"""
    zh = ""
    default = ""
    for m in _LABEL_RE.finditer(text or ""):
        locale, value = m.group(1) or "", m.group(2)
        value = value.replace("\\'", "'").replace("\\\\", "\\")
        if not value:
            continue
        if locale.lower().startswith("zh"):
            return value
        if not locale and not default:
            default = value
    return zh or default


class LabelResolver:
    """按需解析 + 内存缓存；GUI 侧放到工作线程里调用。"""

    def __init__(self, adb, aapt2: str | None = None):
        self.adb = adb
        self.aapt2 = find_aapt2(aapt2)
        self.cache: dict[str, str] = {}

    @property
    def available(self) -> bool:
        return bool(self.aapt2)

    def resolve(self, serial: str, pkg: str) -> str:
        if pkg in self.cache:
            return self.cache[pkg]
        name = ""
        try:
            # 先试零成本路径：部分 ROM 在 dumpsys 里直接给了 nonLocalizedLabel
            dump = self.adb.shell(serial, f"dumpsys package {pkg}", timeout=30).out
            name = label_from_dumpsys(dump)
        except Exception:
            pass
        if not name and self.aapt2:
            name = self._via_aapt2(serial, pkg)
        self.cache[pkg] = name
        return name

    def _via_aapt2(self, serial: str, pkg: str) -> str:
        try:
            r = self.adb.shell(serial, f"pm path {pkg}", timeout=20)
            paths = [
                ln.strip()[len("package:"):]
                for ln in r.out.splitlines()
                if ln.strip().startswith("package:")
            ]
            if not paths:
                return ""
            base = next((p for p in paths if p.endswith("base.apk")), paths[0])
            tmp = Path(tempfile.gettempdir()) / f"guanglab_{abs(hash(pkg)) & 0xffffffff:x}.apk"
            pulled = self.adb.pull(serial, base, tmp, timeout=90)
            if not pulled.ok or not tmp.is_file():
                return ""
            try:
                p = subprocess.run(
                    [self.aapt2, "dump", "badging", str(tmp)],
                    capture_output=True, timeout=60,
                    creationflags=_CREATE_NO_WINDOW,
                )
                return label_from_badging(p.stdout.decode("utf-8", "replace"))
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        except Exception:
            return ""
