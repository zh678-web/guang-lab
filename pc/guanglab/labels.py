"""「应用中文名」解析 —— 零配置、带缓存、失败原因可见。

adb shell 拿不到 ApplicationInfo.label（那是 PackageManager 解析 resources.arsc
之后的结果）。本模块在 PC 侧从 APK 读取 badging：

    pm path <pkg>  ->  adb pull base.apk  ->  aapt2 dump badging
                                         ->  application-label[-zh*]

aapt2 优先用**打包时随 exe 附带**的副本（PyInstaller 的 _MEIPASS/build-tools），
其次才是显式指定 / 环境变量 / 本机 Android SDK。所以单文件 exe 换一台电脑
也能直接解析，不需要装 Android SDK。

解析结果按 (设备序列号, 包名) 写进用户目录的 JSON，重启后秒出，不会重复 pull
APK。所有失败路径都返回中文原因，不再静默返回空字符串。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_LABEL_RE = re.compile(r"application-label(?:-([A-Za-z\-]+))?:'((?:[^'\\]|\\.)*)'")
_NONLOCAL_RE = re.compile(r"nonLocalizedLabel\s*=\s*([^\s]+)")
_ZH_EXACT = frozenset({"zh-cn", "zh-rcn", "zh-hans", "zh-hans-cn", "zh-rhk", "zh-tw"})


def bundled_aapt2() -> str | None:
    """随包附带的 aapt2（PyInstaller onefile 释放到 _MEIPASS）。"""
    roots: list[Path] = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(Path(base) / "build-tools")
    roots.append(Path(__file__).resolve().parent.parent / "build-tools")
    names = ("aapt2.exe", "aapt2") if os.name == "nt" else ("aapt2", "aapt2.exe")
    for root in roots:
        for name in names:
            p = root / name
            if p.is_file():
                return str(p)
    return None


def find_aapt2(explicit: str | None = None) -> str | None:
    """定位顺序：显式指定 > 随包附带 > 环境变量 > Android SDK > PATH。"""
    if explicit and os.path.isfile(explicit):
        return explicit
    bundled = bundled_aapt2()
    if bundled:
        return bundled
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

    found = shutil.which("aapt2")
    return found if found and os.path.isfile(found) else None


def aapt2_status(path: str | None) -> str:
    """给状态栏用的一行说明。"""
    if not path:
        return "aapt2 未就绪（应用名不可用）"
    return "aapt2 内置" if path == bundled_aapt2() else f"aapt2: {Path(path).parent.name}"


def label_from_dumpsys(dump: str) -> str:
    """少数 ROM 会在 dumpsys 里直接给出 nonLocalizedLabel，零传输成本。"""
    for m in _NONLOCAL_RE.finditer(dump or ""):
        v = m.group(1).strip().rstrip("},")
        if v and v.lower() not in {"null", "0", "none"}:
            return v
    return ""


def label_from_badging(text: str) -> str:
    """优先简体中文标签，其次任意中文标签，最后默认标签。"""
    zh_any = ""
    default = ""
    for m in _LABEL_RE.finditer(text or ""):
        locale, value = (m.group(1) or ""), m.group(2)
        value = value.replace("\\'", "'").replace("\\\\", "\\").strip()
        if not value:
            continue
        low = locale.lower()
        if low.startswith("zh"):
            if low in _ZH_EXACT or not locale:
                return value
            zh_any = zh_any or value
        elif not locale and not default:
            default = value
    return zh_any or default


def _decode(data: bytes) -> str:
    """aapt2 一般输出 UTF-8，个别版本按系统 ANSI(GBK) 输出。"""
    s = data.decode("utf-8", "replace")
    if "\ufffd" in s:
        gbk = data.decode("gbk", "replace")
        if "\ufffd" not in gbk:
            return gbk
    return s


def default_cache_file() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "GuangLab" / "labels.json"


class LabelResolver:
    """按需解析 + 内存/磁盘缓存；GUI 侧放到工作线程里调用。"""

    def __init__(self, adb, aapt2: str | None = None, cache_file: Path | None = None):
        self.adb = adb
        self.aapt2 = find_aapt2(aapt2)
        self.status = aapt2_status(self.aapt2)
        self.cache_file = cache_file or default_cache_file()
        self._lock = threading.Lock()
        self.cache: dict[str, str] = {}
        self._load_cache()

    @property
    def available(self) -> bool:
        return bool(self.aapt2)

    @staticmethod
    def _key(serial: str, pkg: str) -> str:
        return f"{serial}|{pkg}"

    def _load_cache(self):
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.cache = {str(k): str(v) for k, v in data.items() if v}
        except (OSError, ValueError, TypeError):
            self.cache = {}

    def flush(self):
        """把缓存落盘；GUI 批量解析结束时调用一次，避免逐条写盘。"""
        with self._lock:
            snapshot = dict(self.cache)
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=0),
                           encoding="utf-8")
            tmp.replace(self.cache_file)
        except OSError:
            pass

    def cached(self, serial: str, pkg: str) -> str:
        return self.cache.get(self._key(serial, pkg), "")

    def _store(self, key: str, name: str) -> str:
        self.cache[key] = name
        return name

    # ------------------------------------------------------------------ 解析

    def resolve(self, serial: str, pkg: str) -> str:
        """兼容旧调用：只要名字。"""
        return self.resolve_detail(serial, pkg)[0]

    def resolve_detail(self, serial: str, pkg: str) -> tuple[str, str]:
        """返回 (应用名, 失败原因)。成功时原因为空串。"""
        key = self._key(serial, pkg)
        hit = self.cache.get(key)
        if hit:
            return hit, ""
        if not serial:
            return "", "没有已授权的设备（设备 offline / unauthorized 时 adb 不可用）"

        reason = ""
        try:
            r = self.adb.shell(serial, f"dumpsys package {pkg}", timeout=30)
            if not r.ok:
                reason = f"adb shell 失败：{(r.err or r.out).strip()[:120]}"
            name = label_from_dumpsys(r.out)
            if name:
                return self._store(key, name), ""
        except Exception as e:  # noqa: BLE001 - 设备侧异常要转成可读原因
            reason = f"dumpsys 异常：{type(e).__name__}: {e}"

        if not self.aapt2:
            return "", (reason or
                        "未找到 aapt2：内置副本缺失，且本机没有 Android SDK build-tools")

        name, why = self._via_aapt2(serial, pkg)
        if name:
            return self._store(key, name), ""
        return "", why or reason or "APK 中没有 application-label"

    def _via_aapt2(self, serial: str, pkg: str) -> tuple[str, str]:
        try:
            r = self.adb.shell(serial, f"pm path {pkg}", timeout=20)
            if not r.ok:
                return "", f"pm path 失败：{(r.err or r.out).strip()[:120]}"
            paths = [
                ln.strip()[len("package:"):]
                for ln in r.out.splitlines()
                if ln.strip().startswith("package:")
            ]
            if not paths:
                return "", "pm path 没有返回 APK 路径（应用已卸载或对 shell 不可见）"
            base = next((p for p in paths if p.endswith("base.apk")), paths[0])
            tmp = Path(tempfile.gettempdir()) / f"guanglab_{uuid.uuid4().hex[:12]}.apk"
            try:
                pulled = self.adb.pull(serial, base, tmp, timeout=120)
                if not pulled.ok or not tmp.is_file():
                    return "", f"adb pull 失败：{(pulled.err or pulled.out).strip()[:120]}"
                try:
                    p = subprocess.run(
                        [self.aapt2, "dump", "badging", str(tmp)],
                        capture_output=True, timeout=60,
                        creationflags=_CREATE_NO_WINDOW,
                    )
                except subprocess.TimeoutExpired:
                    return "", "aapt2 解析超时（60s）"
                except OSError as e:
                    return "", f"无法启动 aapt2：{e}"
                if p.returncode != 0:
                    return "", (f"aapt2 退出码 {p.returncode}："
                                f"{_decode(p.stderr).strip()[:120]}")
                name = label_from_badging(_decode(p.stdout))
                return (name, "") if name else ("", "aapt2 输出中没有 application-label")
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        except Exception as e:  # noqa: BLE001
            return "", f"解析异常：{type(e).__name__}: {e}"

    def resolve_many(self, serial: str, pkgs: list[str], on_item=None,
                     stop: threading.Event | None = None) -> int:
        """批量解析；on_item((pkg, name, reason, done, total))；返回成功个数。"""
        total = len(pkgs)
        ok = 0
        for i, pkg in enumerate(pkgs, 1):
            if stop is not None and stop.is_set():
                break
            name, reason = self.resolve_detail(serial, pkg)
            if name:
                ok += 1
            if on_item:
                on_item((pkg, name, reason, i, total))
        self.flush()
        return ok
