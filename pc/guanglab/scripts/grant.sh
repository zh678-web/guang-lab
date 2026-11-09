# 光 · 实验室 —— 一键直写脚本（由 App 生成参数后交给 Shizuku 的 shell 执行）
# 回执格式：R|<分组>|<条目>|<ok|skip|fail>|<详情>
# 原则：每一步都回读系统真实状态，不信退出码。

P='__PKG__'

# 0) 解除「停用」：被停用的应用写什么权限都不生效
o=$(pm enable "$P" 2>&1)
r=$?
if [ $r -eq 0 ]; then
  echo "R|base|解除停用|ok|"
else
  echo "R|base|解除停用|fail|$(echo "$o" | head -n 1 | tr -d '|')"
fi

# 1) 运行时权限：逐个 pm grant
g() {
  o=$(pm grant "$P" "$1" 2>&1)
  r=$?
  if [ $r -eq 0 ]; then
    echo "R|perm|$1|ok|"
  else
    case "$o" in
      *"not a changeable"* | *"has not requested"* | *"Unknown permission"* | *"not found"*)
        echo "R|perm|$1|skip|该权限不能由 shell 授予" ;;
      *) echo "R|perm|$1|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
  fi
}
__PERMS__

# 1.5) Shizuku 授权：把 Shizuku 的 shell 能力授给目标应用（不需要电脑 / 无线调试）
if pm grant "$P" moe.shizuku.manager.permission.API_V23 >/dev/null 2>&1; then
  echo "R|shizuku|Shizuku 授权|ok|"
else
  echo "R|shizuku|Shizuku 授权|skip|目标应用未声明 Shizuku 权限（或未装 Shizuku）"
fi

# 2) AppOps 直写：写完立刻 appops get 回读
s() {
  o=$(appops set "$P" "$1" allow 2>&1)
  v=$(appops get "$P" "$1" 2>/dev/null | head -n 1)
  case "$v" in
    *allow*) echo "R|op|$1|ok|" ;;
    *) echo "R|op|$1|skip|该 ROM 不接受这个 AppOp 写入" ;;
  esac
}
__OPS__

# 3) 无障碍服务：追加进 enabled_accessibility_services（保留别人的），再开总开关
a() {
  t="$P/$1"
  c=$(settings get secure enabled_accessibility_services)
  case ":$c:" in
    *":$t:"*) ;;
    "::" | ":null:")
      settings put secure enabled_accessibility_services "$t"
      ;;
    *)
      settings put secure enabled_accessibility_services "$c:$t"
      ;;
  esac
  settings put secure accessibility_enabled 1
  n=$(settings get secure enabled_accessibility_services)
  case ":$n:" in
    *":$t:"*) echo "R|acc|$1|ok|" ;;
    *) echo "R|acc|$1|fail|写入后回读未命中" ;;
  esac
}
__ACC__

# 4) 通知使用权
l() {
  t="$P/$1"
  o=$(cmd notification allow_listener "$t" 2>&1)
  c=$(settings get secure enabled_notification_listeners)
  case ":$c:" in
    *":$t:"*) ;;
    "::" | ":null:")
      settings put secure enabled_notification_listeners "$t"
      ;;
    *)
      settings put secure enabled_notification_listeners "$c:$t"
      ;;
  esac
  n=$(settings get secure enabled_notification_listeners)
  case ":$n:" in
    *":$t:"*) echo "R|nl|$1|ok|" ;;
    *) echo "R|nl|$1|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
  esac
}
__NL__

# 5) 设备管理员
d() {
  o=$(dpm set-active-admin "$P/$1" 2>&1)
  if dumpsys device_policy 2>/dev/null | grep -qF "$P/$1"; then
    echo "R|admin|$1|ok|"
  else
    echo "R|admin|$1|fail|$(echo "$o" | head -n 1 | tr -d '|')"
  fi
}
__ADMIN__

# 6) 电池优化白名单（cmd / dumpsys 两条老接口都写一遍，兼容各 ROM）
cmd deviceidle whitelist +"$P" >/dev/null 2>&1
dumpsys deviceidle whitelist +"$P" >/dev/null 2>&1
if dumpsys deviceidle whitelist 2>/dev/null | grep -qF "$P"; then
  echo "R|batt|免电池优化|ok|"
else
  echo "R|batt|免电池优化|fail|"
fi

exit 0
