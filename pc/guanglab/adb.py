"""ADB 执行通道。

原 Android 版为了拿到 uid=2000(shell)，要在手机上折腾 Shizuku / 无线调试 /
Root 三条通道并自动降级。电脑端的 ``adb shell`` 本身就是 shell 身份，
所以 PC 版只需这一条通道；设备已 root 时可叠加 ``su -c`` 提权。

设计要点：
* 脚本不通过 ``sh -c '<正文>'`` 传递（太长、引号易碎），而是 push 到
  /data/local/tmp 再执行，结束后删除，避免任何命令行注入面。
* Windows 下所有子进程都带 CREATE_NO_WINDOW，不弹黑框。
* 脚本统一以 UTF-8 + LF 写入，规避 Windows CRLF 破坏 Android sh。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_REMOTE_DIR = "/data/local/tmp"


class AdbError(RuntimeError):
    """adb 不可用或命令执行失败。"""


@dataclass
class Device:
    serial: str
    state: str = "device"
    props: dict[str, str] = field(default_factory=dict)

    @property
    def model(self) -> str:
        return self.props.get("model", "").replace("_", " ")

    @property
    def usable(self) -> bool:
        return self.state == "device"

    def label(self) -> str:
        if self.model:
            return f"{self.model}  ({self.serial})"
        return self.serial

    def __str__(self) -> str:
        return self.label()


def bundled_adb_dir() -> Path | None:
    """PyInstaller onefile 释放出来的 platform-tools 目录（若随包附带）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "platform-tools"
        if (p / "adb.exe").is_file() or (p / "adb").is_file():
            return p
    p = Path(__file__).resolve().parent.parent / "platform-tools"
    if (p / "adb.exe").is_file() or (p / "adb").is_file():
        return p
    return None


def find_adb(explicit: str | None = None) -> str | None:
    """按优先级定位 adb：显式指定 > 随包附带 > 环境变量 > SDK > PATH > 常见路径。"""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)

    bundled = bundled_adb_dir()
    if bundled:
        candidates.append(str(bundled / ("adb.exe" if os.name == "nt" else "adb")))

    env_adb = os.environ.get("ADB_PATH")
    if env_adb:
        candidates.append(env_adb)

    exe = "adb.exe" if os.name == "nt" else "adb"
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(key)
        if root:
            candidates.append(os.path.join(root, "platform-tools", exe))

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Android", "Sdk", "platform-tools", exe))

    found = shutil.which("adb")
    if found:
        candidates.append(found)

    candidates += [
        r"C:\Program Files\Android\android-sdk\platform-tools\adb.exe",
        r"C:\Android\platform-tools\adb.exe",
    ]

    seen: set[str] = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        if os.path.isfile(c):
            return c
    return None


@dataclass
class Result:
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def text(self) -> str:
        return self.out if self.out.strip() else self.err


class Adb:
    """轻量 adb 客户端，所有方法同步；GUI 侧负责放进工作线程。"""

    def __init__(self, path: str | None = None, timeout: int = 30):
        resolved = find_adb(path)
        if not resolved:
            raise AdbError(
                "找不到 adb.exe。请到「设置」里手动指定 platform-tools/adb.exe，"
                "或安装 Android SDK Platform Tools。"
            )
        self.path = resolved
        self.timeout = timeout

    # ------------------------------------------------------------------ 基础

    def _run(self, args: list[str], timeout: int | None = None, binary: bool = False):
        cmd = [self.path, *args]
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout or self.timeout,
                creationflags=_CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"命令超时（{timeout or self.timeout}s）：{' '.join(args[:3])}") from e
        except OSError as e:
            raise AdbError(f"无法启动 adb：{e}") from e

        if binary:
            return p.returncode, p.stdout, p.stderr
        dec = lambda b: b.decode("utf-8", "replace").replace("\r\n", "\n")
        return p.returncode, dec(p.stdout), dec(p.stderr)

    def raw(self, args: list[str], timeout: int | None = None) -> Result:
        rc, out, err = self._run(args, timeout)
        return Result(rc, out, err)

    def version(self) -> str:
        r = self.raw(["version"])
        return r.out.strip().splitlines()[0] if r.out.strip() else r.err.strip()

    def start_server(self) -> Result:
        return self.raw(["start-server"], timeout=20)

    # ------------------------------------------------------------------ 设备

    def devices(self) -> list[Device]:
        r = self.raw(["devices", "-l"], timeout=20)
        out: list[Device] = []
        for line in r.out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            props = {}
            for token in parts[2:]:
                if ":" in token:
                    k, v = token.split(":", 1)
                    props[k] = v
            out.append(Device(serial, state, props))
        return out

    def connect(self, host: str, port: int = 5555) -> Result:
        addr = f"{host}:{port}"
        return self.raw(["connect", addr], timeout=20)

    def disconnect(self, addr: str | None = None) -> Result:
        args = ["disconnect"] + ([addr] if addr else [])
        return self.raw(args, timeout=20)

    def tcpip(self, serial: str, port: int = 5555) -> Result:
        return self.raw(["-s", serial, "tcpip", str(port)], timeout=20)

    def _prefix(self, serial: str | None) -> list[str]:
        return ["-s", serial] if serial else []

    # ------------------------------------------------------------------ shell

    def shell(self, serial: str | None, command: str, timeout: int = 60,
              as_root: bool = False) -> Result:
        """在设备端执行一条命令。as_root=True 时用 su -c 包一层。"""
        if as_root:
            # command 由本模块内部构造，不含用户输入；此处只做最小转义。
            escaped = command.replace("\\", "\\\\").replace("'", "'\\''")
            command = f"su -c '{escaped}'"
        rc, out, err = self._run([*self._prefix(serial), "shell", command], timeout)
        return Result(rc, out, err)

    def shell_identity(self, serial: str, as_root: bool = False) -> str:
        r = self.shell(serial, "id", timeout=15, as_root=as_root)
        return r.out.strip() or r.err.strip()

    def push(self, serial: str, local: Path, remote: str, timeout: int = 60) -> Result:
        rc, out, err = self._run(
            [*self._prefix(serial), "push", str(local), remote], timeout
        )
        return Result(rc, out, err)

    def pull(self, serial: str, remote: str, local: Path, timeout: int = 60) -> Result:
        rc, out, err = self._run(
            [*self._prefix(serial), "pull", remote, str(local)], timeout
        )
        return Result(rc, out, err)

    def exec_script(self, serial: str, script: str, timeout: int = 180,
                    as_root: bool = False) -> Result:
        """把一段 shell 脚本 push 到设备执行，返回完整 stdout（含 R| 回执）。

        脚本正文来自仓库 res/raw/*.sh，参数只经 core 层的字符集校验后替换，
        不在这里拼接任何用户输入。
        """
        body = script.replace("\r\n", "\n")
        if not body.endswith("\n"):
            body += "\n"
        name = f"guanglab_{uuid.uuid4().hex[:12]}.sh"
        local = Path(tempfile.gettempdir()) / name
        remote = f"{_REMOTE_DIR}/{name}"
        try:
            local.write_bytes(body.encode("utf-8"))
            pushed = self.push(serial, local, remote, timeout=30)
            if not pushed.ok:
                raise AdbError(f"推送脚本失败：{pushed.text().strip()}")
            result = self.shell(serial, f"sh {remote}", timeout=timeout, as_root=as_root)
            return result
        finally:
            try:
                self.shell(serial, f"rm -f {remote}", timeout=15, as_root=as_root)
            except Exception:
                pass
            try:
                local.unlink(missing_ok=True)
            except Exception:
                pass


def parse_package_list(out: str) -> list[str]:
    """把 ``pm list packages`` 的输出转成包名列表。"""
    pkgs: list[str] = []
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("package:"):
            s = s[len("package:"):]
        if s and re.fullmatch(r"[A-Za-z0-9._]+", s):
            pkgs.append(s)
    return pkgs


def parse_connect_result(out: str) -> tuple[bool, str]:
    s = (out or "").strip()
    ok = "connected to" in s or "already connected" in s
    return ok, s
