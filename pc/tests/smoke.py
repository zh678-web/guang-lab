"""端到端烟雾测试：用 PC 版 core 生成脚本，在原仓库的假 pm/appops/settings
桩上真实执行，确认 R| 回执协议在移植后依然成立。

不连设备、不需要 adb。需要 Git Bash / 任意 POSIX sh 在 PATH 里。

运行： python tests/smoke.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PC = HERE.parent
REPO = PC.parent
sys.path.insert(0, str(PC))

from guanglab import core  # noqa: E402

STUB = REPO / "test" / "bin"
OUT = HERE / "out"
STATE = Path("/tmp/gltest/state")
PKG = "com.test.app"

OPS_CASES = [
    ("freeze", ""), ("unfreeze", ""), ("uninstall", ""), ("restore", ""),
    ("forcestop", ""), ("clear", ""), ("battery", ""), ("unbattery", ""),
    ("appops", "SYSTEM_ALERT_WINDOW"),
    ("perm_grant", "android.permission.CAMERA"),
    ("perm_revoke", "android.permission.CAMERA"),
    ("acc_on", f"{PKG}.MyAccService"), ("acc_off", f"{PKG}.MyAccService"),
    ("nl_on", f"{PKG}.MyListener"), ("nl_off", f"{PKG}.MyListener"),
    ("admin_on", f"{PKG}.Admin"), ("admin_off", f"{PKG}.Admin"),
    ("listdisabled", ""), ("listuninstalled", ""),
]


def build_scripts() -> list[Path]:
    OUT.mkdir(exist_ok=True)
    t = core.Target(
        pkg=PKG,
        perms=["android.permission.CAMERA", "android.permission.RECORD_AUDIO"],
        accessibility=[f"{PKG}.MyAccService"],
        listeners=[f"{PKG}.MyListener"],
        admins=[f"{PKG}.Admin"],
    )
    files: list[Path] = []
    for name, text in (
        ("grant.sh", core.grant_script(t)),
        ("revoke.sh", core.grant_script(t, revoke=True)),
    ):
        p = OUT / name
        p.write_bytes(text.encode("utf-8"))
        files.append(p)
    for action, extra in OPS_CASES:
        p = OUT / f"ops-{action}.sh"
        p.write_bytes(core.op_script(action, PKG, extra).encode("utf-8"))
        files.append(p)
    return files


def reset_state() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    for f in STATE.iterdir():
        if f.is_file():
            f.unlink()
    (STATE / "enabled_accessibility_services").write_text("null\n")
    (STATE / "enabled_notification_listeners").write_text("null\n")


def main() -> int:
    sh = shutil.which("sh")
    if not sh:
        print("SKIP: 找不到 sh，跳过烟雾测试")
        return 0
    if not STUB.is_dir():
        print(f"SKIP: 找不到原仓库桩目录 {STUB}")
        return 0

    env = os.environ.copy()
    env["PATH"] = str(STUB) + os.pathsep + env.get("PATH", "")
    files = build_scripts()
    reset_state()

    total = 0
    failed: list[str] = []
    for p in files:
        r = subprocess.run(
            [sh, str(p)], capture_output=True, timeout=60, env=env,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        out = r.stdout.decode("utf-8", "replace")
        receipts = core.parse_receipt(out)
        payload = [ln.strip() for ln in out.splitlines() if ln.strip()]
        protocol = [ln for ln in payload if ln.startswith(("R|", "SCAN|", "SRV|"))]
        total += len(receipts)
        states = {}
        for x in receipts:
            states[x.state] = states.get(x.state, 0) + 1
        tag = " ".join(f"{k}={v}" for k, v in sorted(states.items())) or "列表输出"
        print(f"{p.name:<28} {tag:<28} 输出行={len(payload)}")
        # listdisabled / listuninstalled 是列表类动作，输出纯包名而非 R| 回执，
        # 对齐原版 Ops.listPackages 的行为，所以只要求有非空输出。
        if not payload:
            err = r.stderr.decode("utf-8", "replace").strip().splitlines()
            failed.append(f"{p.name}: 脚本无任何输出; stderr={err[:2]}")
        elif not protocol and not any(core.PKG_RE.fullmatch(ln) for ln in payload):
            failed.append(f"{p.name}: 输出既不是回执也不是包名列表: {payload[:2]}")

    print(f"\n合计 {len(files)} 段脚本 / {total} 条回执")
    if failed:
        print("失败：")
        for f in failed:
            print("  -", f)
        return 1
    print("PASS: 全部脚本都能在假系统命令上产出协议输出")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
