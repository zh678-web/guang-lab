# 光 · 实验室 —— 单动作脚本（动作名与包名由 App 填入，均已校验字符集）
# 回执：R|<分组>|<条目>|<ok|fail>|<详情>

A='__A__'
P='__P__'
E='__E__'

case "$A" in

  freeze)
    o=$(pm disable-user --user 0 "$P" 2>&1)
    if pm list packages -d --user 0 2>/dev/null | grep -qxF "package:$P"; then
      echo "R|freeze|冻结|ok|"
    else
      echo "R|freeze|冻结|fail|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  unfreeze)
    pm enable "$P" >/dev/null 2>&1
    pm unsuspend --user 0 "$P" >/dev/null 2>&1
    pm unhide "$P" >/dev/null 2>&1
    if pm list packages -d --user 0 2>/dev/null | grep -qxF "package:$P"; then
      echo "R|freeze|解冻|fail|仍处于禁用状态"
    else
      echo "R|freeze|解冻|ok|"
    fi
    ;;

  suspend)
    pm suspend --user 0 "$P" >/dev/null 2>&1
    if dumpsys package "$P" 2>/dev/null | grep -q "suspended=true"; then
      echo "R|freeze|挂起|ok|"
    else
      echo "R|freeze|挂起|skip|该 ROM 不支持 pm suspend（需要 Android 12+）"
    fi
    ;;

  hide)
    o=$(pm hide "$P" 2>&1)
    if dumpsys package "$P" 2>/dev/null | grep -q "hidden=true"; then
      echo "R|freeze|隐藏|ok|"
    else
      echo "R|freeze|隐藏|skip|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  uninstall)
    o=$(pm uninstall --user 0 "$P" 2>&1)
    case "$o" in
      *Success*) echo "R|canta|卸载|ok|" ;;
      *) echo "R|canta|卸载|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
    ;;

  restore)
    o=$(cmd package install-existing --user 0 "$P" 2>&1)
    case "$o" in
      *installed* | *Success*) echo "R|canta|恢复|ok|" ;;
      *) echo "R|canta|恢复|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
    ;;

  forcestop)
    am force-stop "$P" >/dev/null 2>&1
    r=$?
    if [ $r -eq 0 ]; then
      echo "R|act|强制停止|ok|"
    else
      echo "R|act|强制停止|fail|exit=$r"
    fi
    ;;

  clear)
    o=$(pm clear "$P" 2>&1)
    case "$o" in
      *Success*) echo "R|act|清除数据|ok|" ;;
      *) echo "R|act|清除数据|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
    ;;

  start)
    o=$(monkey -p "$P" -c android.intent.category.LAUNCHER 1 2>&1)
    if echo "$o" | grep -q "Events injected"; then
      echo "R|act|启动应用|ok|"
    else
      echo "R|act|启动应用|fail|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  battery)
    cmd deviceidle whitelist +"$P" >/dev/null 2>&1
    dumpsys deviceidle whitelist +"$P" >/dev/null 2>&1
    if dumpsys deviceidle whitelist 2>/dev/null | grep -qF "$P"; then
      echo "R|batt|免电池优化|ok|"
    else
      echo "R|batt|免电池优化|fail|"
    fi
    ;;

  unbattery)
    cmd deviceidle whitelist -"$P" >/dev/null 2>&1
    dumpsys deviceidle whitelist -"$P" >/dev/null 2>&1
    if dumpsys deviceidle whitelist 2>/dev/null | grep -qF "$P"; then
      echo "R|batt|免电池优化|fail|"
    else
      echo "R|batt|免电池优化|ok|"
    fi
    ;;

  appops)
    # 两条命令都写一遍（cmd appops 与 appops 在部分 ROM 上只有一条生效）
    o=$(appops set "$P" "$E" allow 2>&1)
    cmd appops set "$P" "$E" allow >/dev/null 2>&1
    # EMUI 的 AppOp 写入是异步的：最多读 6 次，间隔 0.5s
    i=0
    ok=false
    while [ $i -lt 6 ]; do
      v=$(appops get "$P" "$E" 2>/dev/null | head -n 1)
      case "$v" in
        *allow*) ok=true; break ;;
      esac
      i=$((i + 1))
      sleep 0.5 2>/dev/null || sleep 1
    done
    if [ "$ok" = true ]; then
      echo "R|op|$E|ok|"
    else
      echo "R|op|$E|skip|该 ROM 不接受这个 AppOp 写入"
    fi
    ;;

  perm_grant)
    o=$(pm grant "$P" "$E" 2>&1)
    r=$?
    if [ $r -eq 0 ]; then
      echo "R|perm|$E|ok|"
    else
      case "$o" in
        *"not a changeable"* | *"has not requested"* | *"Unknown permission"* | *"not found"*)
          echo "R|perm|$E|skip|该权限不能由 shell 授予" ;;
        *) echo "R|perm|$E|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
      esac
    fi
    ;;

  shizuku_on)
    o=$(pm grant "$P" moe.shizuku.manager.permission.API_V23 2>&1)
    r=$?
    if dumpsys package "$P" 2>/dev/null | grep -q "moe.shizuku.manager.permission.API_V23: granted=true"; then
      echo "R|shizuku|Shizuku 授权|ok|"
    elif [ $r -eq 0 ]; then
      echo "R|shizuku|Shizuku 授权|ok|已写入"
    else
      echo "R|shizuku|Shizuku 授权|skip|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  shizuku_off)
    o=$(pm revoke "$P" moe.shizuku.manager.permission.API_V23 2>&1)
    if dumpsys package "$P" 2>/dev/null | grep -q "moe.shizuku.manager.permission.API_V23: granted=true"; then
      echo "R|shizuku|Shizuku 授权|fail|仍在授权表"
    else
      echo "R|shizuku|Shizuku 授权|ok|"
    fi
    ;;

  perm_revoke)
    o=$(pm revoke "$P" "$E" 2>&1)
    r=$?
    if [ $r -eq 0 ]; then
      echo "R|perm|$E|ok|"
    else
      echo "R|perm|$E|fail|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  acc_on)
    t="$P/$E"
    c=$(settings get secure enabled_accessibility_services)
    case ":$c:" in
      *":$t:"*) ;;
      "::" | ":null:") settings put secure enabled_accessibility_services "$t" ;;
      *) settings put secure enabled_accessibility_services "$c:$t" ;;
    esac
    settings put secure accessibility_enabled 1
    n=$(settings get secure enabled_accessibility_services)
    case ":$n:" in
      *":$t:"*) echo "R|acc|无障碍|ok|" ;;
      *) echo "R|acc|无障碍|fail|写入后回读未命中" ;;
    esac
    ;;

  acc_off)
    t="$P/$E"
    c=$(settings get secure enabled_accessibility_services)
    n=""
    rest="$c"
    while [ -n "$rest" ]; do
      case "$rest" in
        *:*) item="${rest%%:*}"; rest="${rest#*:}" ;;
        *) item="$rest"; rest="" ;;
      esac
      if [ "$item" = "$t" ]; then continue; fi
      if [ -n "$item" ] && [ "$item" != "null" ]; then n="${n:+$n:}$item"; fi
    done
    settings put secure enabled_accessibility_services "$n"
    if [ -z "$n" ]; then settings put secure accessibility_enabled 0; fi
    n2=$(settings get secure enabled_accessibility_services)
    case ":$n2:" in
      *":$t:"*) echo "R|acc|无障碍|fail|仍在列表中" ;;
      *) echo "R|acc|无障碍|ok|" ;;
    esac
    ;;

  nl_on)
    t="$P/$E"
    o=$(cmd notification allow_listener "$t" 2>&1)
    c=$(settings get secure enabled_notification_listeners)
    case ":$c:" in
      *":$t:"*) ;;
      "::" | ":null:") settings put secure enabled_notification_listeners "$t" ;;
      *) settings put secure enabled_notification_listeners "$c:$t" ;;
    esac
    n=$(settings get secure enabled_notification_listeners)
    case ":$n:" in
      *":$t:"*) echo "R|nl|通知使用权|ok|" ;;
      *) echo "R|nl|通知使用权|fail|$(echo "$o" | head -n 1 | tr -d '|')" ;;
    esac
    ;;

  nl_off)
    t="$P/$E"
    cmd notification disallow_listener "$t" >/dev/null 2>&1
    c=$(settings get secure enabled_notification_listeners)
    n=""
    rest="$c"
    while [ -n "$rest" ]; do
      case "$rest" in
        *:*) item="${rest%%:*}"; rest="${rest#*:}" ;;
        *) item="$rest"; rest="" ;;
      esac
      if [ "$item" = "$t" ]; then continue; fi
      if [ -n "$item" ] && [ "$item" != "null" ]; then n="${n:+$n:}$item"; fi
    done
    settings put secure enabled_notification_listeners "$n"
    n2=$(settings get secure enabled_notification_listeners)
    case ":$n2:" in
      *":$t:"*) echo "R|nl|通知使用权|fail|仍在列表中" ;;
      *) echo "R|nl|通知使用权|ok|" ;;
    esac
    ;;

  admin_on)
    o=$(dpm set-active-admin "$P/$E" 2>&1)
    if dumpsys device_policy 2>/dev/null | grep -qF "$P/$E"; then
      echo "R|admin|设备管理员|ok|"
    else
      echo "R|admin|设备管理员|fail|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  admin_off)
    o=$(dpm remove-active-admin "$P/$E" 2>&1)
    r=$?
    if [ $r -eq 0 ]; then
      echo "R|admin|设备管理员|ok|"
    else
      echo "R|admin|设备管理员|fail|$(echo "$o" | head -n 1 | tr -d '|')"
    fi
    ;;

  gray_on)
    settings put secure accessibility_display_daltonizer_enabled 1
    settings put secure accessibility_display_daltonizer 0
    settings put secure accessibility_display_inversion_enabled 0
    v=$(settings get secure accessibility_display_daltonizer_enabled)
    case "$v" in
      1) echo "R|screen|屏幕灰度|ok|" ;;
      *) echo "R|screen|屏幕灰度|fail|系统未接受 daltonizer 开关" ;;
    esac
    ;;

  gray_off)
    settings put secure accessibility_display_daltonizer_enabled 0
    v=$(settings get secure accessibility_display_daltonizer_enabled)
    case "$v" in
      0 | null) echo "R|screen|屏幕灰度|ok|" ;;
      *) echo "R|screen|屏幕灰度|fail|仍在灰度" ;;
    esac
    ;;

  install_priv)
    src=$(pm path com.guang.lab 2>/dev/null | head -n 1 | sed 's/^package://')
    M=/data/adb/modules/guanglab
    if mkdir -p "$M/system/priv-app/GuangLab" "$M/system/etc/permissions" 2>/dev/null && [ -n "$src" ] && cp "$src" "$M/system/priv-app/GuangLab/GuangLab.apk" 2>/dev/null; then
      cat > "$M/system/etc/permissions/privapp-permissions-guanglab.xml" <<'XMLEOF'
<?xml version="1.0" encoding="utf-8"?>
<permissions>
    <privapp-permissions package="com.guang.lab">
        <permission name="android.permission.CHANGE_COMPONENT_ENABLED_STATE" />
    </privapp-permissions>
</permissions>
XMLEOF
      cat > "$M/module.prop" <<'PROPEOF'
id=guanglab
name=Guang Lab system app
version=1.0.0
versionCode=1
author=guang-lab
description=Install Guang Lab as priv-app so system-level freeze works
PROPEOF
      chmod 644 "$M/system/priv-app/GuangLab/GuangLab.apk" 2>/dev/null
      if [ -s "$M/system/priv-app/GuangLab/GuangLab.apk" ] && [ -s "$M/system/etc/permissions/privapp-permissions-guanglab.xml" ]; then
        echo "R|priv|系统级安装|ok|已写入 magisk 模块 guanglab，重启后生效"
      else
        echo "R|priv|系统级安装|fail|写入后校验失败"
      fi
    else
      echo "R|priv|系统级安装|skip|需要 root 且 /data/adb/modules 可写（Magisk / KernelSU）"
    fi
    ;;  scene_up)
    S=/sdcard/Android/data/com.omarea.vtools/up.sh
    if [ ! -f "$S" ]; then
      echo "R|act|Scene 激活|skip|没找到 up.sh：先在 Scene 里点一次 ADB 授权，让它生成这个脚本"
      exit 0
    fi
    o=$(sh "$S" 2>&1)
    if pgrep scene-daemon >/dev/null 2>&1 || [ -f /data/local/tmp/scene-daemon ]; then
      echo "R|act|Scene 激活|ok|daemon 已就位"
    else
      echo "R|act|Scene 激活|fail|$(echo "$o" | tail -n 2 | tr '\n' ' ' | tr -d '|')"
    fi
    ;;
  scan_adb)
    for d in /sdcard/Android/data/*/; do
      p=$(basename "$d")
      for f in "$d"*.sh; do
        if [ -f "$f" ]; then echo "SCAN|$p|$f"; fi
      done
    done
    for d in /storage/emulated/0/Android/data/*/; do
      p=$(basename "$d")
      for f in "$d"*.sh; do
        if [ -f "$f" ]; then echo "SCAN|$p|$f"; fi
      done
    done
    exit 0
    ;;

  run_script)
    if [ ! -f "$E" ]; then
      echo "R|act|执行脚本|skip|找不到 $E"
    else
      o=$(sh "$E" 2>&1)
      d=$(echo "$o" | grep -E "Daemon OK|Daemon Fail|Success|Error|error|not found|denied" | head -n 3 | tr '\n' ' ' | tr -d '|')
      if echo "$o" | grep -q "Daemon Fail"; then
        echo "R|act|执行 $(basename "$E")|fail|$d"
      else
        echo "R|act|执行 $(basename "$E")|ok|$d"
      fi
    fi
    ;;
  scan_pkg)
    for root in /sdcard/Android/data /storage/emulated/0/Android/data; do
      d="$root/$P"
      if [ -d "$d" ]; then
        for f in "$d"/*.sh; do
          if [ -f "$f" ]; then echo "SCAN|$P|$f"; fi
        done
      fi
    done
    exit 0
    ;;
  brevent_up)
    if [ ! -f /data/local/tmp/brevent.sh ]; then
      echo "R|act|黑阈脚本|fail|/data/local/tmp/brevent.sh 不存在，先在黑阈里点一次激活生成它"
      exit 0
    fi
    nohup sh /data/local/tmp/brevent.sh >/dev/null 2>&1 &
    sleep 3
    if ps -A 2>/dev/null | grep -q brevent_server; then
      echo "R|act|黑阈 daemon|ok|已以 shell 身份运行"
    else
      echo "R|act|黑阈 daemon|fail|进程没起来（看黑阈自己怎么说）"
    fi
    exit 0
    ;;
  server_state)
    if ps -A 2>/dev/null | grep -q shizuku_server; then echo "SRV|Shizuku"; fi
    if ps -A 2>/dev/null | grep -q stellar_server; then echo "SRV|Stellar"; fi
    exit 0
    ;;
  listdisabled)
    pm list packages -d --user 0 2>/dev/null | sed 's/^package://'
    ;;

  listuninstalled)
    pm list packages -u --user 0 2>/dev/null | sed 's/^package://'
    ;;

  *)
    echo "R|sys|未知动作|fail|$A"
    ;;
esac

exit 0
