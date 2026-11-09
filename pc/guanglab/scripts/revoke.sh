# 光 · 实验室 —— 撤销脚本：把一键直写写进去的东西退回去
P='__PKG__'

p() {
  o=$(pm revoke "$P" "$1" 2>&1)
  r=$?
  if [ $r -eq 0 ]; then
    echo "R|perm|$1|ok|"
  else
    case "$o" in
      *"not a changeable"* | *"has not requested"* | *"Unknown permission"* | *"not found"*)
        echo "R|perm|$1|skip|该权限不能由 shell 撤销" ;;
      *) echo "R|perm|$1|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
  fi
}
__PERMS__

s() {
  o=$(appops set "$P" "$1" default 2>&1)
  v=$(appops get "$P" "$1" 2>/dev/null | head -n 1)
  case "$v" in
    *default* | "") echo "R|op|$1|ok|" ;;
    *) echo "R|op|$1|skip|该 ROM 不支持复位这个 AppOp" ;;
  esac
}
__OPS__

# 从 enabled_accessibility_services 列表里摘掉目标服务，其余原样保留
a() {
  t="$P/$1"
  c=$(settings get secure enabled_accessibility_services)
  n=""
  rest="$c"
  while [ -n "$rest" ]; do
    case "$rest" in
      *:*) item="${rest%%:*}"; rest="${rest#*:}" ;;
      *) item="$rest"; rest="" ;;
    esac
    if [ "$item" = "$t" ]; then
      continue
    fi
    if [ -n "$item" ] && [ "$item" != "null" ]; then
      n="${n:+$n:}$item"
    fi
  done
  settings put secure enabled_accessibility_services "$n"
  if [ -z "$n" ]; then
    settings put secure accessibility_enabled 0
  fi
  n2=$(settings get secure enabled_accessibility_services)
  case ":$n2:" in
    *":$t:"*) echo "R|acc|$1|fail|仍在列表中" ;;
    *) echo "R|acc|$1|ok|" ;;
  esac
}
__ACC__

l() {
  t="$P/$1"
  cmd notification disallow_listener "$t" >/dev/null 2>&1
  c=$(settings get secure enabled_notification_listeners)
  n=""
  rest="$c"
  while [ -n "$rest" ]; do
    case "$rest" in
      *:*) item="${rest%%:*}"; rest="${rest#*:}" ;;
      *) item="$rest"; rest="" ;;
    esac
    if [ "$item" = "$t" ]; then
      continue
    fi
    if [ -n "$item" ] && [ "$item" != "null" ]; then
      n="${n:+$n:}$item"
    fi
  done
  settings put secure enabled_notification_listeners "$n"
  n2=$(settings get secure enabled_notification_listeners)
  case ":$n2:" in
    *":$t:"*) echo "R|nl|$1|fail|仍在列表中" ;;
    *) echo "R|nl|$1|ok|" ;;
  esac
}
__NL__

d() {
  o=$(dpm remove-active-admin "$P/$1" 2>&1)
  r=$?
  if [ $r -eq 0 ]; then
    echo "R|admin|$1|ok|"
  else
    echo "R|admin|$1|fail|$(echo "$o" | head -n 1 | tr -d '|')"
  fi
}
__ADMIN__

cmd deviceidle whitelist -"$P" >/dev/null 2>&1
dumpsys deviceidle whitelist -"$P" >/dev/null 2>&1
if dumpsys deviceidle whitelist 2>/dev/null | grep -qF "$P"; then
  echo "R|batt|免电池优化|fail|"
else
  echo "R|batt|免电池优化|ok|"
fi

exit 0
