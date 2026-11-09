"""PC 版核心层：脚本工厂、输入校验、回执解析、设备侧信息采集。

这一层是原 Android 版 ``Ops.kt`` / ``Repo.kt`` 的 Python 等价实现。
脚本正文仍来自 ``app/src/main/res/raw/*.sh``（复制到 guanglab/scripts/），
回执协议 ``R|<分组>|<条目>|<ok|skip|fail>|<详情>`` 完全不变。

安全模型与原版一致：
* 脚本正文是常量，来自仓库文件；
* 用户输入只经过字符集白名单校验后替换脚本里的占位符；
* 唯一能执行任意命令的入口是「手动 shell 终端」，属于显式功能。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------- 常量

APPOPS: tuple[str, ...] = (
    "SYSTEM_ALERT_WINDOW", "GET_USAGE_STATS", "MANAGE_EXTERNAL_STORAGE",
    "WRITE_SETTINGS", "RUN_IN_BACKGROUND", "RUN_ANY_IN_BACKGROUND",
    "START_FOREGROUND", "START_ACTIVITIES_FROM_BACKGROUND", "WAKE_LOCK",
    "POST_NOTIFICATION", "ACCESS_NOTIFICATIONS", "READ_CLIPBOARD",
    "WRITE_CLIPBOARD", "REQUEST_INSTALL_PACKAGES", "REQUEST_DELETE_PACKAGES",
    "PROJECT_MEDIA", "TAKE_AUDIO_FOCUS", "ACTIVATE_VPN", "TURN_SCREEN_ON",
    "MOCK_LOCATION", "BOOT_COMPLETED",
)

ACTIONS: frozenset[str] = frozenset({
    "freeze", "unfreeze", "uninstall", "restore", "forcestop", "clear", "start",
    "battery", "unbattery", "appops", "perm_grant", "perm_revoke",
    "shizuku_on", "shizuku_off", "suspend", "hide", "gray_on", "gray_off",
    "install_priv", "scan_adb", "scan_pkg", "run_script", "server_state",
    "brevent_up", "acc_on", "acc_off", "nl_on", "nl_off", "admin_on",
    "admin_off", "listdisabled", "listuninstalled",
})

APPOP_ONLY: frozenset[str] = frozenset({
    "android.permission.SYSTEM_ALERT_WINDOW",
    "android.permission.WRITE_SETTINGS",
    "android.permission.MANAGE_EXTERNAL_STORAGE",
})

SHIZUKU_PERM = "moe.shizuku.manager.permission.API_V23"

"""非 dangerous、但 shell 有权授予的高价值权限（对齐原版 Repo.SPECIAL）。"""
SPECIAL: frozenset[str] = frozenset({
    "android.permission.WRITE_SECURE_SETTINGS",
    "android.permission.PACKAGE_USAGE_STATS",
    "android.permission.READ_LOGS",
    "android.permission.DUMP",
    "android.permission.CHANGE_CONFIGURATION",
    "android.permission.BATTERY_STATS",
    "android.permission.SET_ANIMATION_SCALE",
    "android.permission.READ_PRECISE_PHONE_STATE",
})

ACTION_ACC = "android.accessibilityservice.AccessibilityService"
ACTION_NL = "android.service.notification.NotificationListenerService"
ACTION_ADMIN = "android.app.action.DEVICE_ADMIN_ENABLED"

GROUP_ORDER: tuple[str, ...] = (
    "base", "perm", "shizuku", "op", "acc", "nl", "admin",
    "batt", "freeze", "canta", "act", "screen", "priv", "sys",
)
GROUP_NAME: dict[str, str] = {
    "base": "基础", "perm": "运行时权限", "shizuku": "Shizuku 授权",
    "op": "AppOps", "acc": "无障碍", "nl": "通知使用权",
    "admin": "设备管理员", "batt": "电池白名单", "freeze": "冻结",
    "canta": "卸载 / 恢复", "act": "应用操作", "screen": "屏幕",
    "priv": "系统级", "sys": "系统",
}

PKG_RE = re.compile(r"[A-Za-z0-9._]{1,150}\Z")
CLS_RE = re.compile(r"[A-Za-z0-9._$]{1,200}\Z")
PERM_RE = re.compile(r"[A-Za-z0-9._]{1,150}\Z")
PATH_RE = re.compile(r"/[A-Za-z0-9._/-]{1,300}\Z")

# UI 生成动作按钮用：(action, 中文名, extra 类型, 风险级别, 提示)
ACTION_DEFS: tuple[tuple[str, str, str | None, str, str], ...] = (
    ("freeze", "冻结", None, "warn", "pm disable-user，应用图标消失但数据保留"),
    ("unfreeze", "解冻", None, "safe", "同时解除禁用 / 挂起 / 隐藏三种状态"),
    ("uninstall", "卸载", None, "danger", "pm uninstall --user 0；第三方应用是真删"),
    ("restore", "恢复", None, "warn", "仅对预装应用有效"),
    ("forcestop", "强制停止", None, "safe", "am force-stop"),
    ("clear", "清除数据", None, "danger", "pm clear，会删掉应用数据"),
    ("start", "启动应用", None, "safe", "通过 launcher intent 拉起"),
    ("battery", "免电池优化", None, "safe", "加入 deviceidle 白名单"),
    ("unbattery", "取消白名单", None, "safe", "移出 deviceidle 白名单"),
    ("suspend", "挂起", None, "warn", "需要 Android 12+，部分 ROM 不支持"),
    ("hide", "隐藏", None, "warn", "依 ROM 而异"),
    ("gray_on", "屏幕灰度", None, "safe", "可反转，不改亮度与分辨率"),
    ("gray_off", "关闭灰度", None, "safe", "恢复彩色显示"),
    ("shizuku_on", "Shizuku 授权", None, "safe", "把 Shizuku 的 shell 权限授给目标应用"),
    ("shizuku_off", "撤销 Shizuku", None, "safe", "pm revoke API_V23"),
    ("perm_grant", "授予单项权限", "perm", "safe", "pm grant"),
    ("perm_revoke", "撤销单项权限", "perm", "safe", "pm revoke"),
    ("appops", "设置 AppOp", "appop", "safe", "写完回读系统真值，最多轮询 6 次"),
    ("acc_on", "开启无障碍", "component", "warn", "追加进 enabled_accessibility_services"),
    ("acc_off", "关闭无障碍", "component", "warn", "从列表中摘除，保留其它服务"),
    ("nl_on", "通知使用权", "component", "warn", "追加进 enabled_notification_listeners"),
    ("nl_off", "关闭通知使用权", "component", "warn", "从列表中摘除"),
    ("admin_on", "设为设备管理员", "component", "danger", "dpm set-active-admin"),
    ("admin_off", "撤销设备管理员", "component", "warn", "dpm remove-active-admin"),
    ("server_state", "探测守护进程", None, "safe", "查看 Shizuku / Stellar 是否运行"),
    ("scan_adb", "扫描 ADB 脚本", None, "safe", "列出 /sdcard/Android/data 下的 .sh"),
    ("install_priv", "生成 Magisk 模块", None, "warn", "需要 root 与 /data/adb/modules 可写"),
)


# --------------------------------------------------------------------- 数据结构

@dataclass
class Target:
    """一个目标应用的可写清单（对齐原版 Core.Target）。"""
    pkg: str
    label: str = ""
    perms: list[str] = field(default_factory=list)
    accessibility: list[str] = field(default_factory=list)
    listeners: list[str] = field(default_factory=list)
    admins: list[str] = field(default_factory=list)


@dataclass
class Receipt:
    """一行 R| 回执。"""
    group: str
    key: str
    state: str  # ok / skip / fail
    detail: str = ""

    @property
    def group_name(self) -> str:
        return GROUP_NAME.get(self.group, "系统")

    @property
    def ok(self) -> bool:
        return self.state == "ok"


# --------------------------------------------------------------------- 资源

def scripts_dir() -> Path:
    """兼容源码运行与 PyInstaller onefile（资源在 _MEIPASS）。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "guanglab" / "scripts"
        if p.is_dir():
            return p
    return Path(__file__).resolve().parent / "scripts"


def load_script(name: str) -> str:
    if name not in {"grant.sh", "revoke.sh", "ops.sh"}:
        raise ValueError("未知脚本")
    text = (scripts_dir() / name).read_text(encoding="utf-8")
    return text.replace("\r\n", "\n")


# --------------------------------------------------------------------- 校验

def valid_pkg(pkg: str) -> bool:
    return bool(PKG_RE.fullmatch(pkg or ""))


def valid_extra(action: str, extra: str) -> bool:
    """UI 侧预校验；真正的构造期校验在 op_script 里（含 run_script 路径白名单）。"""
    if not extra:
        return True
    if action == "run_script":
        return bool(PATH_RE.fullmatch(extra))
    if action == "appops" and extra in APPOPS:
        return True
    return bool(CLS_RE.fullmatch(extra) or PERM_RE.fullmatch(extra))


def normalize_component(pkg: str, comp: str) -> str | None:
    """把 dumpsys 里的 ``pkg/.Cls`` / ``pkg/full.Cls`` 转成脚本要求的完整类名。"""
    comp = (comp or "").strip()
    if not comp:
        return None
    if "/" in comp:
        part, cls = comp.split("/", 1)
        if cls.startswith("."):
            comp = part + cls
        else:
            comp = cls
    elif comp.startswith("."):
        comp = pkg + comp
    return comp if CLS_RE.fullmatch(comp) else None


# --------------------------------------------------------------------- 脚本工厂

def grant_script(t: Target, revoke: bool = False) -> str:
    """生成一键授权 / 撤销脚本（对齐 Ops.grantScript）。"""
    if not valid_pkg(t.pkg):
        raise ValueError(f"非法包名：{t.pkg!r}")
    fn = "p" if revoke else "g"
    perms = [
        p for p in t.perms
        if PERM_RE.fullmatch(p) and p not in APPOP_ONLY and p != SHIZUKU_PERM
    ]
    clean = lambda xs: [x for x in xs if CLS_RE.fullmatch(x)]
    return (
        load_script("revoke.sh" if revoke else "grant.sh")
        .replace("__PKG__", t.pkg)
        .replace("__PERMS__", "\n".join(f"{fn} '{p}'" for p in perms))
        .replace("__OPS__", "\n".join(f"s '{o}'" for o in APPOPS))
        .replace("__ACC__", "\n".join(f"a '{c}'" for c in clean(t.accessibility)))
        .replace("__NL__", "\n".join(f"l '{c}'" for c in clean(t.listeners)))
        .replace("__ADMIN__", "\n".join(f"d '{c}'" for c in clean(t.admins)))
    )


def op_script(action: str, pkg: str, extra: str = "") -> str:
    """生成单动作脚本（对齐 Ops.opScript），含完全相同的字符集白名单。"""
    if action not in ACTIONS:
        raise ValueError(f"未知动作：{action!r}")
    if not valid_pkg(pkg):
        raise ValueError(f"非法包名：{pkg!r}")

    e = ""
    if extra:
        if action == "run_script":
            own = (
                f"/sdcard/Android/data/{pkg}/",
                f"/storage/emulated/0/Android/data/{pkg}/",
                f"/storage/self/primary/Android/data/{pkg}/",
            )
            # 比原版更严：原版只做 startswith，'/…/pkg/../other/x.sh' 能越出白名单。
            # 这里显式禁掉任何 . / .. 路径段，并拒绝软链常见的重定向写法。
            segments = extra.split("/")
            if (".." in segments or "." in segments
                    or not PATH_RE.fullmatch(extra)
                    or not extra.startswith(own)):
                raise ValueError("脚本路径必须落在目标应用自己的 Android/data 目录内")
            e = extra
        elif CLS_RE.fullmatch(extra) or PERM_RE.fullmatch(extra):
            e = extra
        elif action == "appops" and extra in APPOPS:
            e = extra
        else:
            raise ValueError(f"非法参数：{extra!r}")

    return (
        load_script("ops.sh")
        .replace("__A__", action)
        .replace("__P__", pkg)
        .replace("__E__", e)
    )


# --------------------------------------------------------------------- 回执

def parse_receipt(out: str) -> list[Receipt]:
    """解析 R| 回执并按分组顺序排序（对齐 Ops.parse）。"""
    items: list[Receipt] = []
    for line in (out or "").splitlines():
        s = line.strip()
        if not s.startswith("R|"):
            continue
        f = s.split("|")
        if len(f) < 4:
            continue
        state = f[3] if f[3] in {"ok", "skip", "fail"} else "fail"
        detail = "|".join(f[4:]).strip() if len(f) > 4 else ""
        items.append(Receipt(f[1], f[2], state, detail))
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    return sorted(items, key=lambda r: order.get(r.group, len(GROUP_ORDER)))


# --------------------------------------------------------------------- 设备侧采集

def parse_requested_permissions(dump: str) -> list[str]:
    """从 ``dumpsys package <pkg>`` 抽出 requested permissions 段。"""
    lines = dump.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "requested permissions:":
            continue
        base = len(line) - len(line.lstrip())
        found: list[str] = []
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip()) <= base:
                break
            token = nxt.strip().split(":", 1)[0].strip()
            if PERM_RE.fullmatch(token) and token not in found:
                found.append(token)
        return sorted(found)
    return []


def resolver_components(dump: str, action: str, pkg: str) -> list[str]:
    """从 dumpsys 的 Resolver Table 里按 action 找本包的组件，返回完整类名。

    AOSP 输出形如::

        Non-Data Actions:
            android.accessibilityservice.AccessibilityService:
              8d3f1a2 com.foo/.AccService filter 4b2c1d0
                Action: "android.accessibilityservice.AccessibilityService"

    """
    lines = dump.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() != action + ":":
            continue
        base = len(line) - len(line.lstrip())
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip()) <= base:
                break
            m = re.match(
                r"^\s*[0-9a-fA-F]+\s+([A-Za-z0-9._]+/[A-Za-z0-9._$]+)\s+filter\b",
                nxt,
            )
            if not m:
                continue
            comp = m.group(1)
            if not comp.startswith(pkg + "/"):
                continue
            full = normalize_component(pkg, comp)
            if full and full not in found:
                found.append(full)
    return found


def parse_dangerous_permissions(out: str) -> set[str]:
    """解析 ``pm list permissions -g -d`` 的输出。"""
    perms: set[str] = set()
    for line in (out or "").splitlines():
        token = line.strip()
        if PERM_RE.fullmatch(token) and "." in token and not token.startswith("group:"):
            perms.add(token)
    return perms


def suggested_permissions(perms: list[str], dangerous: set[str]) -> set[str]:
    """默认勾选：声明过的 dangerous 权限 + 高价值 SPECIAL 权限。"""
    return {p for p in perms if p in dangerous or p in SPECIAL}


def describe(adb, serial: str, pkg: str) -> Target:
    """读取单个应用的权限与三类组件，失败时返回只含包名的 Target。"""
    if not valid_pkg(pkg):
        raise ValueError(f"非法包名：{pkg!r}")
    dump = ""
    try:
        dump = adb.shell(serial, f"dumpsys package {pkg}", timeout=45).out
    except Exception:
        pass
    return Target(
        pkg=pkg,
        perms=parse_requested_permissions(dump),
        accessibility=resolver_components(dump, ACTION_ACC, pkg),
        listeners=resolver_components(dump, ACTION_NL, pkg),
        admins=resolver_components(dump, ACTION_ADMIN, pkg),
    )


def package_inventory(adb, serial: str) -> dict[str, set[str]]:
    """一次性拿到应用的第三方 / 系统 / 冻结 / 已卸载状态集合。"""
    def fetch(flag: str) -> set[str]:
        from .adb import parse_package_list
        try:
            r = adb.shell(serial, f"pm list packages {flag}", timeout=60)
            return set(parse_package_list(r.out))
        except Exception:
            return set()

    third = fetch("-3")
    system = fetch("-s")
    disabled = fetch("-d --user 0")
    all_with_uninstalled = fetch("-u --user 0")
    installed = third | system
    return {
        "third": third,
        "system": system,
        "disabled": disabled,
        "uninstalled": all_with_uninstalled - installed,
        "installed": installed,
    }


def dangerous_permissions(adb, serial: str) -> set[str]:
    try:
        r = adb.shell(serial, "pm list permissions -g -d", timeout=60)
        return parse_dangerous_permissions(r.out)
    except Exception:
        return set()
