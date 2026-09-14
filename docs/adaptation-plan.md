# pywaylandauto 多平台适配开发计划

> 目标：将 pywaylandauto 从 Kylin V11 专用扩展为支持 **Ubuntu/GNOME、UOS、Sway/Hyprland** 等多 Wayland 环境的通用输入注入工具。
>
> **原则：Kylin 已有实现不动，每一层通过抽象接口扩展。**

---

## 一、环境探测结果（Ubuntu 26.04 / GNOME Shell 50.1）

| 项目 | 状态 |
|---|---|
| GNOME Shell | 50.1 |
| xdg-desktop-portal + -gnome | 1.21.1 / 50.0 |
| RemoteDesktop.ConnectToEIS | ✅ 可用，返回 fd (h) |
| RemoteDesktop.Notify* | ✅ 全套 D-Bus 方法 |
| mutter.DisplayConfig.GetCurrentState | ✅ 可用 |
| libei 1.5.0 | ✅ 已安装 |
| libpipewire 1.6.2 | ✅ 已安装 |
| Kylin Wlcom D-Bus | ❌ 不存在 |
| UOS/Deepin Wlcom D-Bus | ❌ 不存在 |
| dbus-python 1.4.0 | ✅ 已安装 |
| PyGObject | ✅ 已安装 |
| Python | 3.14.4 |

---

## 二、架构设计

### 2.1 后端分层

```
┌──────────────────────────────────────────────────────┐
│                    Daemon / CLI                       │
├──────────────────────────────────────────────────────┤
│                     Backend ABC                       │
│  (base.py: move_abs, move_rel, button, key, scroll)  │
├───────────────┬──────────────┬───────────────────────┤
│  EisBackend   │ PortalBackend│  WlrootsBackend       │
│  (已有)       │  (新增)      │  (已有)               │
├───────────────┤              │                       │
│ EisConnection │              │                       │
│ (connect_fn)  │              │                       │
├───────┬───────┤              │                       │
│ Kylin │ Portal│              │                       │
│ EIS   │ EIS   │              │                       │
│(已有) │(移植) │              │                       │
└───────┴───────┴──────────────┴───────────────────────┘
```

### 2.2 平台 → 后端映射

| 平台 | EIS 入口 | 后端 | 优先级 |
|---|---|---|---|
| Kylin V11 | `com.kylin.Wlcom.EIS.RemoteDesktop` | `EisBackend(kylin)` | 1 (不变) |
| Ubuntu/GNOME | Portal `ConnectToEIS` | `PortalBackend` → EIS | 2 |
| UOS/Deepin | `com.deepin.Wlcom.*` (待确认) | `EisBackend(uos)` | 3 |
| Sway/Hyprland | zwlr 协议 | `WlrootsBackend` | 4 (已有) |
| 其他 wlroots | zwlr 协议 | `WlrootsBackend` | 5 (已有) |

### 2.3 后端选择逻辑（Daemon 启动时）

```
1. 尝试 Kylin EIS (现有 kylin_connect)
   ↓ 失败
2. 尝试 Portal RemoteDesktop → ConnectToEIS (新增)
   ↓ 失败
3. 尝试 wlroots zwlr_virtual_pointer/keyboard (已有)
   ↓ 失败
4. 报错退出
```

用户可显式指定：`--backend portal-eis | kylin-eis | wlroots`

---

## 三、任务分解

### Phase 1 — Portal 后端（GNOME/Ubuntu 适配）

#### 1.1 移植 Token Cache
- [ ] 从 `pywaylandauto_old/pywaylandauto/token_cache.py` 移植到 `pywaylandauto/token_cache.py`
- 几乎不需要改，原有实现已完整（原子写入 + fsync）
- 路径：`$XDG_STATE_HOME/pywaylandauto/portal.token`，权限 0600

#### 1.2 新增 Portal EIS 连接入口
- [ ] 新建 `pywaylandauto/backends/eis/portal.py`
- 通过 XDG Desktop Portal `ConnectToEIS` 拿到 EIS fd
- 复用已有 `EisBackend` + `_EisClient`，不需要新 EIS 客户端
- 接口签名：`def connect(session_path: str) -> int`（返回 socket fd）

```python
# backends/eis/portal.py 核心逻辑
import dbus
PORTAL_DEST = "org.freedesktop.portal.Desktop"
RD_IFACE = "org.freedesktop.portal.RemoteDesktop"

def connect(session_path: str) -> int:
    bus = dbus.SessionBus()
    obj = bus.get_object(PORTAL_DEST, "/org/freedesktop/portal/desktop")
    iface = dbus.Interface(obj, RD_IFACE)
    return iface.ConnectToEIS(session_path, {}).take()
```

#### 1.3 新增 PortalBackend
- [ ] 新建 `pywaylandauto/backends/portal/__init__.py`
- [ ] 新建 `pywaylandauto/backends/portal/backend.py`
  - 实现 `Backend` 抽象接口
  - 包裹 Portal 会话状态机（CreateSession → SelectDevices → Start）
  - 内部持有 `EisBackend` 实例，通过 `connect_fn` 注入 portal 连接函数
  - 支持 `notify` 传输作为 EIS 失败的降级（但绝对移动受限）
  - 实现 `key_sequence` 委托给内部 `EisBackend`

**portal/backend.py 结构概览：**

```python
class PortalBackend(Backend):
    name = "portal-eis"

    def __init__(self):
        self._portal = PortalClient()          # D-Bus glue (从 old 移植)
        self._token_cache = TokenCache()
        self._state = "init"
        self._session_path = None
        self._eis: EisBackend | None = None    # 复用已有 EisBackend
        self._transport = None                  # "eis" or "notify"
        self.regions = []

    def start(self):
        # 1. CreateSession (如已有 token 则跳过弹窗)
        # 2. SelectDevices (persist_mode=2 + restore_token)
        # 3. Start → 拿到 devices
        # 4. ConnectToEIS → fd → 创建 EisBackend(fd)
        # 5. eis.start() → 完成 EIS 握手
        ...
```

#### 1.4 移植 PortalClient (D-Bus glue)
- [ ] 从 `old/backends/portal.py` 的 `PortalClient` 类移植
- 提供 D-Bus 调用封装：
  - `create_session(options)` → request path
  - `select_devices(session_path, options)`
  - `start(session_path, parent_window, options)`
  - `connect_to_eis(session_path)` → fd
  - `notify_pointer_motion/button/keycode/keysym(...)`
  - `close_session(session_path)`
  - `add_response_listener(token, callback)`
  - `add_session_closed_listener(session_path, callback)`

#### 1.5 协议错误码补全
- [ ] 在 `protocol.py` 中加入 portal 特有错误码：
  - `ERR_PERMISSION_PENDING` — 等待用户授权
  - `ERR_PERMISSION_DENIED` — 用户拒绝
  - `ERR_SESSION_NOT_STARTED` — 未启动会话
  - `ERR_PORTAL_UNAVAILABLE` — Portal 不可用

#### 1.6 Daemon 集成
- [ ] 修改 `daemon.py` 的 `_start_backend()` 方法：
  ```python
  def _start_backend(self):
      # 1. 尝试 Kylin EIS (已有)
      try: be = EisBackend(connect_fn=kylin_connect); be.start(); ...
      # 2. 尝试 Portal (新增)
      except: be = PortalBackend(); be.start(); ...
      # 3. 尝试 wlroots (已有)
      except: be = WlrootsBackend(); be.start(); ...
      # 4. 全失败
      except: self._backend = None
  ```
- [ ] `PortalBackend` 内含 `EisBackend`，事件 pump 在 `daemon.py` 中统一处理
- [ ] 如果有 EIS fd，注册 `_start_eis_pump()`

#### 1.7 CLI 扩展
- [ ] 在 `cli.py` 中新增 `session-start` 命令（重新弹出授权窗）
- [ ] `daemon start` 增加 `--backend` 参数（`kylin-eis | portal-eis | wlroots | auto`）
- [ ] `status` 命令适配多后端输出

#### 1.8 Client API 扩展
- [ ] `client.py` 新增 `session_start()` 方法

---

### Phase 2 — Monitor 布局（移植 + 统一）

#### 2.1 已有实现
- Kylin EIS：regions 来自 `_EisClient.regions` → 已有 `layout_from_regions()`
- wlroots：outputs 来自 `wl_output` global → 已在 status 中

#### 2.2 新增 mutter DisplayConfig
- [ ] 从 `old/monitors.py` 移植 `get_monitor_layout()` + `parse_display_config()`
- [ ] 统一为 `Monitors` 数据结构，各后端提供相同格式

#### 2.3 Data class 统一
- [ ] 定义 `MonitorInfo` 结构（bbox, monitors list）

---

### Phase 3 — UOS/Deepin 适配（轻量）

#### 3.1 EIS 连接入口
- [ ] 新建 `backends/eis/uos.py`
- 等有 UOS 真机后确认 D-Bus 接口名（预计类似 kylin-wlcom 的格式，如 `com.deepin.Wlcom.EIS.RemoteDesktop`）
- 代码量与 `kylin.py` 相近（约 20 行）

#### 3.2 后端选择集成
- [ ] 在 Daemon 启动时探测 `com.deepin.Wlcom` 是否存在
- [ ] 添加 `uos-eis` 到 `--backend` 选项

---

### Phase 4 — 测试

#### 4.1 单元测试
- [ ] 移植 old 的 portal 相关测试：
  - `test_portal.py` → 测试 portal 状态机
  - `test_token_cache.py` → 测试 token 读写
  - `test_daemon_dispatch.py`（已有）
  - `test_eis_messages.py`（已有）
- [ ] 新增 `test_portal_backend.py` — PortalBackend mock 测试
- [ ] 新增 `test_platform_detect.py` — 后端自动选择逻辑

#### 4.2 集成测试（真机）
- [ ] **Ubuntu 26.04 GNOME**：portal 会话 + EIS 输入完整流程
  - `daemon start` 弹窗授权
  - `move` / `click` / `key` / `input` / `scroll` / `drag`
  - token 缓存在第二次 `start` 时跳过弹窗
  - `daemon stop` / 重启
- [ ] **Kylin V11**：回归测试，确保原有功能不变

---

### Phase 5 — 文档

- [ ] 更新 `README.md`：添加 Ubuntu/GNOME 快速开始
- [ ] 更新 `docs/` 目录（rspress）：
  - 安装指南（Ubuntu、Kylin、UOS）
  - 平台兼容表
  - 后端选择说明

---

## 四、文件变更对照

| 操作 | 文件 | 来源 |
|---|---|---|
| **移植** | `pywaylandauto/token_cache.py` | `old/token_cache.py` |
| **移植** | `pywaylandauto/monitors.py` (merge) | `old/monitors.py` + 现有 |
| **新建** | `pywaylandauto/backends/eis/portal.py` | 基于 portal 规范新写 |
| **新建** | `pywaylandauto/backends/portal/__init__.py` | 新模块 |
| **新建** | `pywaylandauto/backends/portal/backend.py` | 移植 old `portal.py` 的 PortalBackend |
| **新建** | `pywaylandauto/backends/portal/client.py` | 移植 old `portal.py` 的 PortalClient |
| **新建** | `pywaylandauto/backends/eis/uos.py` | 新写（参考 kylin.py） |
| **修改** | `pywaylandauto/protocol.py` | 补全 portal 错误码 |
| **修改** | `pywaylandauto/daemon.py` | 扩展 `_start_backend()` 选择逻辑 |
| **修改** | `pywaylandauto/cli.py` | 新增命令 + `--backend` 参数 |
| **修改** | `pywaylandauto/client.py` | 新增 `session_start()` |
| **修改** | `pywaylandauto/backends/__init__.py` | 导出新后端 |
| **勿动** | `pywaylandauto/backends/eis/kylin.py` | Kylin 保持原样 |
| **勿动** | `pywaylandauto/backends/eis/backend.py` | 已有 EisBackend 保持 |
| **勿动** | `pywaylandauto/backends/eis/messages.py` | EIS 协议不变 |
| **勿动** | `pywaylandauto/backends/wlroots/` | wlroots 后端不变 |
| **勿动** | `pywaylandauto/keysyms.py` | 无需改 |
| **勿动** | `pywaylandauto/backends/xkb.py` | 无需改 |

---

## 五、执行顺序与依赖

```
Phase 1.1 (Token Cache)   ──┐
Phase 1.2 (Portal EIS)    ──┤
Phase 1.3 (PortalBackend) ──┼── 串行，有依赖顺序
Phase 1.4 (PortalClient)  ──┤
Phase 1.5 (Error codes)   ──┘
Phase 1.6 (Daemon)        ── 依赖 1.3
Phase 1.7 (CLI)           ── 依赖 1.6 (可并行)
Phase 1.8 (Client API)    ──┘

Phase 2   (Monitor)       ── 独立，可与 Phase 1 并行

Phase 3   (UOS)           ── 独立，需要真机

Phase 4   (Tests)         ── 与开发同步进行
Phase 5   (Docs)          ── 最后
```

---

## 六、风险与注意事项

1. **GNOME 50 Portal 的已知坑**（已在 old 项目中验证）：
   - `SelectDevices` 的 `types` 参数取 `1|2`（keyboard+pointer），不能超过 `AvailableDeviceTypes`
   - `restore_token` 只能包含 `[A-Za-z0-9_]`，不能有 `-`
   - `ConnectToEIS` 之后 `Notify*` 全部失效
   - `Response` 信号在 `PersistentRequest` 接口上多一个 token 参数

2. **Token 缓存安全**：权限严格 0600/0700，同 uid 可访问 — 与 X11 XTest 同级安全模型

3. **Python 版本**：本项目 requires `>=3.12`，Ubuntu 26.04 自带 3.14，没问题

4. **dbus-python 依赖**：已存在，但需要确认 `dbus.mainloop.glib` 与 GLib 主循环兼容

5. **Portal EIS 连接**：`EisBackend` 已有 `connect_fn` 参数完美支持注入不同的连接函数