# 光 · 实验室

<p align="center">
  <img src="assets/cover.png" width="180" alt="光 · 实验室" />
</p>

<p align="center">
  <b>科技不再是高高在上，而是服务于人民</b><br />
  <b>让科技触手可及，终极 Android 工具箱</b>
</p>

<p align="center">
  <a href="https://nekotype.top/starlight/"><img src="https://img.shields.io/badge/%E5%AE%98%E7%BD%91-nekotype.top-4A7DFF?style=flat-square" alt="官网" /></a>
  <a href="https://github.com/Yukstarlight/guang-lab/releases/latest"><img src="https://img.shields.io/github/v/release/Yukstarlight/guang-lab?style=flat-square&label=Release&color=C8A2FF" alt="Release" /></a>
  <img src="https://img.shields.io/badge/minSdk-26%20(Android%208.0)-green?style=flat-square" alt="minSdk" />
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Yukstarlight/guang-lab?style=flat-square&color=blue" alt="GPL-3.0" /></a>
</p>

---

## 本 fork 新增：PC 桌面版（`pc/`）

> 本仓库是 [Yukstarlight/guang-lab](https://github.com/Yukstarlight/guang-lab) 的 fork。
> 下面的原 Android 版内容与 `app/` 源码**保持原样**；新增的 [`pc/`](pc/README.md)
> 是 **Windows 桌面移植版**：在电脑上运行，通过 USB / WiFi ADB 管理手机。

原版为了在手机上拿到 `uid=2000(shell)`，需要 Shizuku / 无线调试 ADB / Root 三条通道自动降级；
而电脑上的 `adb shell` **天生就是 shell 身份**，所以 PC 版只需要一条通道，手机端只要求开 USB 调试。

| | 原 Android 版 | PC 桌面版 |
|---|---|---|
| 运行位置 | 手机 APK（Kotlin） | Windows 单文件 `exe`（Python + Qt） |
| 权限通道 | 三通道自动降级 | 仅 `adb shell`，可选 `su -c` |
| 执行脚本 | `app/src/main/res/raw/*.sh` | **同一份脚本逐字节复用** |
| 回执协议 | `R\|分组\|条目\|状态\|详情` | **完全不变** |

功能、安全模型、构建与自检方式见 **[pc/README.md](pc/README.md)**。
快速使用：手机开 USB 调试并授权 → 双击 `pc/dist/GuangLabPC.exe` → 刷新应用 → 一键授权。

---

Android **系统级权限工具箱**（minSdk 26 / targetSdk 34）。所有操作都是 **shell 直写**：不弹设置页、不做模拟点击、不依赖无障碍去点开关。

装好之后大致能干这些事：**一次把某个应用的基础权限配齐**、**冻结 / 卸载平时不用的应用**（还能一键装回来）、**随手跑一条 shell** 验证系统行为——全过程**不需要连电脑**。

## 三条通道（自动降级）

| 通道 | 前提 | 实现 |
|---|---|---|
| **Shizuku** | 装好并启动 Shizuku，本应用获授权 | `IShizukuService.newProcess()` 让服务端以 shell 身份 fork `sh -c <脚本>` |
| **无线调试 ADB** | Android 11+，开发者选项开「无线调试」 | 用 6 位配对码与本机 adbd 做 SPAKE2 配对，之后本机直连 shell（`libadb-android`），**不需要 root、不需要电脑** |
| **Root** | 有 `su` | `su -c <脚本>` |

设置页可指定优先级；任一通道失败自动降级到下一条。

## 功能

**授权**

- 一键直写：解除停用 → 目标清单里可授予的权限（`pm grant`）→ 20 项 AppOps（`appops set`）→ 无障碍服务 → 通知使用权 → 设备管理员 → 电池白名单
- 每项写完都在同一段脚本里**回读系统真值**（`appops get` / `settings get` / `dumpsys`）再判定 ok/fail，不信退出码
- 反向「撤销」同法；详情页逐权限开关（Switch 勾选即 grant）

**应用管理**

- 冻结 / 解冻：`pm disable-user --user 0` / `pm enable`（Hail 的做法）
- 卸载 / 恢复：`pm uninstall --user 0` / `cmd package install-existing --user 0`（Canta 的做法），「已卸载」筛选可一键装回
- 强停 `am force-stop`、清数据 `pm clear`、启动 `monkey`

**实验台**

- 手动命令：走当前通道执行任意 shell，输出原样返回

**其他**

- 系统级（priv-app）：通道页可用 Root 生成 Magisk 模块（含 `privapp-permissions-guanglab.xml` 白名单），重启后冻结走系统 API
- 屏幕灰度：`accessibility_display_daltonizer` 单色开关，可逆、不改亮度与分辨率

## 结构

```
app/src/main/java/com/guang/lab/
├── MainPage.kt        5 页主界面（首页/应用/通道/记录/设置）+ 底部导航
├── DetailActivity.kt  单应用详情：操作网格 + 逐权限开关 + 组件能力
├── Priv.kt            通道门面：Shizuku / ADB / Root，自动降级
├── Adb.kt             无线调试：mDNS 找端口 + 6 位码配对 + ADB shell
├── Ops.kt             脚本工厂（字符集校验 + 占位符替换）+ 回执解析
├── Core.kt            AppEntry / Target / Repo（清单与状态）/ Log / Prefs
└── Ui.kt              控件工厂、结果对话框、选应用对话框
app/src/main/res/raw/
├── grant.sh           一键授权合并脚本
├── revoke.sh          撤销合并脚本
└── ops.sh             单动作脚本（冻结/卸载/无障碍/AppOps/权限…）
```

## 安全模型

脚本正文全在 `res/raw/*.sh`，Kotlin 侧只做两件事：**字符集校验**（包名 `[A-Za-z0-9._]`、组件名额外允许 `$`）+ **占位符替换**。任何用户输入都不可能变成任意命令；唯一的任意命令入口是「通道」页的手动命令台，属于显式功能。

## 构建

需要 JDK 17+ 与 Android SDK（`ANDROID_HOME` 指向 SDK 目录）。

```bash
# 1) 签名配置（本仓库不含任何签名文件）
cat > keystore.properties <<'EOF'
storeFile=your.jks
storePassword=******
keyAlias=******
keyPassword=******
EOF

# 2) 构建
./gradlew assembleRelease
```

> 仓库里**没有** `*.jks` 与 `keystore.properties`（签名口令不进版本库），自己生成一份就能本地构建。

`test/` 下是本地行为测试：把 `res/raw` 的脚本按 App 内同一套规则展开，在**假 `pm` / `appops` / `settings` / `dumpsys`** 上跑，检查回执协议与无障碍列表的追加/摘除回读。

```bash
node test/expand.mjs
bash test/run.sh
```

## 更新记录

### v1.42

- **守护进程启动脚本重做**：用 pm path 解析真实 APK 路径（失败写日志退出）、进程名固定 --nice-name=guang-daemon、日志统一 /data/local/tmp/guang-daemon.log\n- 界面文案无新增或删减；四通道与 1.40 的冻结 / 解冻修复保持一致

### v1.40

- **修复冻结 / 解冻模块**：冻结状态改读系统真值（显示「当前：已停用（冻结中）」/「当前：已启用」），不再按本地记录猜
- **解冻不再误判**：禁用 / 挂起 / 隐藏三种方式一起解，任一种残留都视为未解冻

### v1.39

- **新增通道「电脑 ADB 守护进程」**：电脑跑一行 `adb shell sh …/files/start.sh`，手机以 `uid=2000(shell)` 常驻并监听 `127.0.0.1:47901`；没无线调试（Android 10 及以下）、没 root 也能用。重启后重跑脚本即可
- **通道探测 15 秒 → 40 毫秒**：不再现场做 TLS 握手、线程池 1 → 4、端口先读缓存、`ps -A | grep` 换 `pidof`；每次 exec 日志带耗时
- **首页刷新按钮**（右上角 `⟳`）：重探通道 + 重读应用列表
- **应用列表加载动画**：转圈 + 7 行骨架流光
- **修复**：组件能力卡片重复、Shizuku+ADB 双申请时 ADB 级权限被漏补、授权改为一次批量补完

### v1.23

- **应用内语言选择器**：简体中文 / 繁體中文 / 跟随系统，整套界面补了繁体文案
- **Stellar 支持**：进程检测同时识别 Shizuku 与 Stellar
- **无线调试引导**：配对码配对后本机直连 adbd，拿到 `shell(2000)` 权限，不需要 root / 电脑
- **运营商相关模块下线**：国家/地区配置与 carrier_config 路径整段移除

### v1.13

- **应用预设 · 无障碍静默授权**：给指定应用绑定它的无障碍服务，那个应用一回到前台就静默把服务打开——走 Shizuku 直写 `secure settings`，不弹设置页
- 映射可增可删（添加时从已装应用里挑，「已绑定」列表可删）；本应用自己的监听服务会被自动开启

### v1.0.7

- **AppOps 写入兼容性**：同时执行 `appops set` 与 `cmd appops set`（部分 ROM 只有其中一条生效），回读改成**最多 6 次、间隔 0.5 秒轮询**——EMUI 一类的系统 AppOp 写入是异步的，一次读不到就报 `skip` 属于误判

## 已知限制

- **签名级 / 系统专属权限** shell 也无权授予，报告里的 ✕ 属正常
- **恢复只对预装（系统）应用有效**；第三方应用 `--user 0` 卸载是**真删**
- **无线调试通道需要 Android 11+**，且要求同一 Wi-Fi 下能连到本机 adbd
- 冻结的「隐藏 / 挂起」依 ROM 而异，部分深度定制系统会拦截或重启后回滚
- 各通道主要在脚本层与单元层验证过，**不同机型请自行实测**

## 免责声明

本工具会修改系统的应用状态与权限配置，属于**高风险操作**。请只在你自己的设备上、明确知道每个按钮含义的前提下使用；由此造成的数据丢失、应用异常、系统不稳定等后果由使用者自行承担。

## 协议

[GPL-3.0](LICENSE) © 2026 Yukstarlight
