# 光 · 实验室 · PC 版

在 **Windows 电脑**上运行、通过 ADB 管理 Android 设备的桌面工具。单文件 `exe`，双击即用，不需要装 Python、不需要装 Android SDK。

这是 [Yukstarlight/guang-lab](https://github.com/Yukstarlight/guang-lab)（Android APK，GPL-3.0）的 fork 后的移植版本。原 Android 版代码在仓库的 `app/`，本目录 `pc/` 是新增的桌面版，两者互不干扰。

---

## 为什么要移植，以及变了什么

原版是手机上的 App，为了拿到 `uid=2000(shell)` 权限，要做三条通道并自动降级：Shizuku、无线调试 ADB（SPAKE2 配对）、Root。**电脑上的 `adb shell` 天生就是 shell 身份**，这三条折腾在 PC 端全都不需要。

| | 原 Android 版 | PC 桌面版 |
|---|---|---|
| 运行位置 | 手机（minSdk 26） | Windows 电脑（Python 3.11 + Qt 6，打包成 exe） |
| 权限通道 | Shizuku / 无线调试 ADB / Root 自动降级 | **仅 `adb shell`**（可选叠加 `su -c`） |
| 手机前置条件 | 装 Shizuku，或 Android 11+ 无线调试配对，或 root | 只需开「USB 调试」并授权本机 |
| 执行脚本 | `res/raw/{grant,revoke,ops}.sh` | **同一份脚本**，复制到 `guanglab/scripts/`，逐字节复用 |
| 回执协议 | `R\|分组\|条目\|ok/skip/fail\|详情` | **完全不变**，`core.parse_receipt()` 是对 `Ops.parse()` 的等价重写 |
| 安全模型 | 字符集白名单 + 占位符替换 | **完全不变**，并额外堵掉 `run_script` 的 `..` 目录穿越 |
| 界面 | Kotlin 五页 + 底部导航 | Qt：设备栏 / 应用列表 / 一键授权 / 应用操作 / Shell 终端 / 执行结果 / 日志 |

**没变的部分才是最关键的**：所有系统写入仍然发生在同一段 shell 脚本里，写完回读系统真值（`appops get` / `settings get` / `dumpsys`）再判定 ok / fail，不信退出码。PC 端只是换了个「按按钮的地方」。

---

## 快速开始

1. 手机：设置 → 开发者选项 → 打开 **USB 调试**，用数据线连上电脑，在弹窗里点「允许」。
2. 电脑：双击 `dist/GuangLabPC.exe`。
3. 左上角「设备」应出现你的手机；点「刷新应用」加载应用列表。
4. 选中一个应用 → 「一键授权」页确认权限清单 → 点「一键授权」。
5. 看底部「执行结果」：每一项的分组、条目、状态与详情都来自设备回读。

WiFi 连接：先 USB 状态下执行过一次 `adb tcpip 5555`，再点「WiFi 连接…」输入 `手机IP:5555`。

> 首次使用会弹一次免责声明。卸载第三方应用是真删，恢复只对预装应用有效；请只在自己的设备上操作。

---

## 功能

- **设备**：USB / WiFi ADB 枚举、`adb shell id` 身份自检、可选 root（`su -c`）模式、offline / unauthorized 设备状态可见与「重连」。
- **应用列表**：第三方 / 系统 / 已冻结 / 已卸载筛选，包名搜索；**exe 内置 aapt2**，刷新后自动后台解析第三方应用中文名，可「解析全部名称」、可随时停止，结果按设备持久化缓存。
- **一键授权 / 撤销**：自动从 `dumpsys package` 读出声明的权限与三类组件（无障碍服务 / 通知监听器 / 设备管理员），默认勾选 dangerous 与高价值权限；脚本固定处理 21 项 AppOps、Shizuku 授权、电池白名单。
- **应用操作**：27 个动作（冻结、解冻、卸载、恢复、强停、清数据、启动、电池白名单、挂起、隐藏、屏幕灰度、单项权限、单项 AppOp、无障碍 / 通知 / 管理员开关、守护进程探测、ADB 脚本扫描、Magisk 模块…）。危险动作执行前二次确认。
- **Shell 终端**：手动执行任意 `adb shell` 命令，输出原样返回。这是唯一的任意命令入口，属于显式功能。
- **执行结果**：回执表格按分组排序，成功 / 跳过 / 失败分别着色，可切到原始输出。
- **运行日志**：所有动作带时间戳、耗时与结果统计。

---

## 目录结构

```
pc/
├── main.py                 入口（含 --selftest / --gui-smoke / --version）
├── build.py                PyInstaller 单文件打包 + 产物验证 + 图标生成
├── requirements.txt
├── guanglab/
│   ├── adb.py              ADB 客户端：设备 / 连接 / shell / push 脚本 / 清理
│   ├── core.py             脚本工厂、字符集白名单、回执解析、dumpsys 解析
│   ├── labels.py           应用名解析：内置 aapt2 + 缓存 + 失败原因
│   ├── ui.py               Qt 主窗口（所有 adb 调用在工作线程）
│   └── scripts/            从 app/src/main/res/raw/ 复制的三个 .sh（LF）
└── tests/
    ├── test_core.py        15 项离线单测（脚本工厂 / 回执 / 注入防护）
    ├── test_labels.py      13 项应用名解析单测（FakeAdb 全链路 / 缓存 / 失败原因）
    └── smoke.py            21 段脚本在假 pm/appops/settings 桩上真实执行
```

### 执行链路

```
[UI] 选中应用 + 勾选清单
  → core.grant_script() / core.op_script()   字符集校验 + 占位符替换
  → adb.exec_script()                         UTF-8/LF 写入 → push 到
                                             /data/local/tmp/guanglab_*.sh
                                             → adb shell sh <文件> → rm
  → 设备端脚本回读系统真值，逐行 echo "R|..."
  → core.parse_receipt() → 结果表格
```

脚本走 `push + sh <文件>` 而不是 `sh -c '<正文>'`：`ops.sh` 有 11KB，命令行长度和引号转义都容易出问题，push 方式也彻底避免了命令拼接面。

---

## 安全模型

- 脚本正文全部来自仓库内的 `.sh` 常量文件；Python 侧只做**字符集白名单校验**（包名 `[A-Za-z0-9._]`、组件名额外允许 `$`）与**占位符替换**。
- 任何用户输入都不可能变成任意命令。测试里有 `com.demo;rm -rf /`、`a' ; id ; '`、`$(id)` 等注入用例。
- `run_script` 的脚本路径被限制在目标应用自己的 `Android/data/<pkg>/` 下；移植时额外禁止了 `.` / `..` 路径段，堵掉原版 `startswith` 可被 `pkg/../other/x.sh` 绕过的隐患。
- 唯一的任意命令入口是「Shell 终端」页，界面上有醒目提示。

---

## 构建

```bash
# 1) 建 venv（Windows，Python 3.11+）
"<系统Python>" -m venv ../.buildvenv
../.buildvenv/Scripts/pip install -r requirements.txt

# 2) 打包并自动验证
../.buildvenv/Scripts/python.exe build.py
# 产物： dist/GuangLabPC.exe
```

`build.py` 会：

1. 用纯标准库生成一枚 ICO 图标；
2. 把三个 `.sh` 作为 data、把 `adb.exe` + `AdbWinApi.dll` + `AdbWinUsbApi.dll` 与
   `aapt2.exe`（含其 `NOTICE.txt`）作为 binary 一起打进单文件；
3. 用 `python -S -m PyInstaller` + `PYTHONPATH=<venv>/Lib/site-packages`，绕开 WorkBuddy 沙箱注入的 `sitecustomize`（它会拦截 `os.remove` 导致 PyInstaller 收尾清理失败）；
4. 打包后跑两次验证：`--selftest`（脚本资源 / 注入防护 / adb 与 aapt2 定位及可运行性）与 `--gui-smoke --demo`（Qt 窗口构造 + 截图）。

运行时按这个顺序找 adb：**随包附带的** → 设置里手动指定 → `ADB_PATH` → `ANDROID_HOME` / `ANDROID_SDK_ROOT` → `%LOCALAPPDATA%\Android\Sdk` → PATH。

aapt2 同理：**随包附带的** → 设置里手动指定 → `AAPT2_PATH` → SDK `build-tools` → PATH。两者都不需要目标电脑装 Android SDK。

### 开发期自检

```bash
python main.py --selftest                       # 无界面自检
python main.py --gui-smoke --demo --shot=x.png  # 构造窗口并存图
python -m unittest discover -s tests -p "test_*.py" -v   # 31 项单测
python tests/smoke.py                           # 21 段脚本在假命令桩上跑，73 条回执
```

---

## 已知限制

- 签名级 / 系统专属权限 shell 也无权授予，报告里的「失败」属正常。
- 「恢复」只对预装应用有效；第三方应用 `pm uninstall --user 0` 是真删。
- 冻结的「隐藏 / 挂起」依 ROM 而异，部分深度定制系统会拦截或重启后回滚。
- 应用名需要把 `base.apk` 拉到电脑本地读标签，首次批量解析会占一些 USB 流量与时间；结果写入缓存后不再重复拉取。
- 各通道主要在脚本层与单元层验证过，不同机型请自行实测。

---

## 应用名解析：原理与排查

`adb shell` 拿不到 `ApplicationInfo.label`（那是 PackageManager 解析 `resources.arsc` 后的结果），所以 PC 侧走：

```
dumpsys package <pkg> 中的 nonLocalizedLabel（零传输，少数 ROM 命中）
  → 未命中：pm path <pkg> → adb pull base.apk → aapt2 dump badging
  → application-label-zh-CN / -zh-rCN / application-label
  → 写入 %APPDATA%\GuangLab\labels.json（按 设备序列号+包名 缓存）
```

**「获取不了应用名称」按顺序查这几处**（失败原因会直接写进「运行日志」）：

| 现象 | 原因 / 处理 |
|---|---|
| 状态栏 `aapt2 未就绪` | exe 不完整或杀软删了内置 `aapt2.exe`；到「设置」手动指定，或设 `AAPT2_PATH` |
| 日志 `adb shell 失败：device offline` | 设备 offline：解锁手机、重新插拔 USB，点设备栏「重连」；必要时重新授权 USB 调试 |
| 日志 `unauthorized` | 手机上没点「允许 USB 调试」，勾选「一律允许」后点「重连」|
| 日志 `pm path 没有返回 APK 路径` | 应用已卸载或对 shell 不可见，属正常 |
| 日志 `adb pull 失败` | 存储/权限/断线；检查数据线与 `adb devices` 状态 |
| 日志 `aapt2 退出码 N` | APK 损坏或 split APK；可点「解析当前」重试 |
| 单个应用始终为空 | 该 APK 确实没有 `application-label`（少见），或 aapt2 输出非 UTF-8（已做 GBK 兜底）|

刷新列表后默认自动解析第三方应用名（上限 60 个，可在「设置」关闭），系统应用在**选中时按需解析**；也可点「解析全部名称」全量补齐，再点一次即停止。整个过程都在后台线程，不阻塞界面，且只做只读 `pull`，不改设备。

---

## 协议

- 本项目代码：**GPL-3.0**，沿用原仓库 [LICENSE](../LICENSE)，© 2026 Yukstarlight；PC 移植部分同样以 GPL-3.0 提供。
- 随包附带的 `adb.exe` / `AdbWinApi.dll` / `AdbWinUsbApi.dll` 来自 Android SDK Platform Tools，`aapt2.exe` 来自 Android SDK Build Tools，均属 AOSP / Apache-2.0，版权归 The Android Open Source Project；`build-tools/NOTICE.txt` 一并打包保留许可声明。
- Qt for Python（PySide6-Essentials）按 LGPL 动态链接使用。

本工具会修改系统的应用状态与权限配置，属于**高风险操作**。请只在你自己的设备上、明确知道每个按钮含义的前提下使用；由此造成的数据丢失、应用异常、系统不稳定等后果由使用者自行承担。
