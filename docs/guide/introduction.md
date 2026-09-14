# pywaylandauto

在 Wayland 合成器下注入全局键盘和鼠标输入的 Python 工具，主要面向 Kylin OS V11（kylin-wlcom）。

---

## 为什么需要它

Wayland 协议出于安全考虑，不允许传统的 X11 输入自动化方式（如 `xdotool`、`pynput`）。pywaylandauto 通过合成器官方提供的输入扩展协议来实现安全的自动化控制：

- **Kylin Wlcom** 上通过 EIS（Emulated Input Server）协议
- **其它 wlroots 合成器**上通过 `zwlr_virtual_pointer` / `zwp_virtual_keyboard` 协议

## 架构概览

```
┌─────────────┐    UNIX Socket + JSON ────▶  ┌──────────┐
│   Client    │                               │  Daemon   │
│  (CLI/API)  │                               │  (GLib)   │
└─────────────┘                               └────┬─────┘
                                                   │
                              ┌────────────────────┼────────────────────┐
                              ▼                                         ▼
                     ┌───────────────┐                         ┌────────────────┐
                     │  EIS Backend  │  (fallback)             │ Wlroots Backend│
                     │ (Kylin Wlcom) │ ◀──────────────────────  │ (wl_compositor)│
                     └───────────────┘                         └────────────────┘
```

- **Client**：CLI 工具或 Python API，通过 UNIX 域套接字以 JSON 行协议与守护进程通信
- **Daemon**：后台守护进程，使用 GLib 主循环处理请求并驱动后端（空闲 2 小时自动退出）
- **EIS Backend**：通过 Kylin 的 `com.kylin.Wlcom.EIS.RemoteDesktop` D-Bus 接口获取 EIS 套接字
- **Wlroots Backend**：当 EIS 不可用时，直接连接 Wayland 显示器套接字

## 支持平台

| 平台 | 后端 | 状态 |
|------|------|------|
| Kylin OS V11 (kylin-wlcom) | EIS | 已完成 |
| Sway / Hyprland (wlroots) | wlroots | 计划中 |
| UOS / Deepin | EIS / wlroots | 计划中 |

---

## 安装

### 环境要求

- Python >= 3.12
- Kylin OS V11（kylin-wlcom）

### 系统依赖

```bash
sudo apt-get install -y libdbus-1-dev libgirepository-2.0-dev
```

| 系统包 | 用途 |
|--------|------|
| `libdbus-1-dev` | DBus 开发头文件（`dbus-python` 编译所需） |
| `libgirepository-2.0-dev` | GIObject 2.0 开发头文件（`PyGObject` 编译所需） |

### 常见安装问题

**`dbus-python` 构建失败**（pkg-config 找不到 `dbus-1`）→ `sudo apt-get install -y libdbus-1-dev`

**`PyGObject` 构建失败**（`Dependency 'girepository-2.0' is required but not found`）→ `sudo apt-get install -y libgirepository-2.0-dev`

### 安装项目

```bash
git clone <repo-url>
cd pywaylandauto
python3 -m venv venv
./venv/bin/python3 -m pip install -e .
```

---

## 快速开始

守护进程在首次调用 CLI 命令或 Python API 时自动启动，无需手动 `daemon start`。

### CLI 基本用法

```bash
# 鼠标移动
pywaylandauto move 960 540          # 移动到 (960, 540)
pywaylandauto move-rel 10 -5        # 相对移动

# 鼠标点击
pywaylandauto click 500 300                         # 左键点击
pywaylandauto right-click 500 300                   # 右键点击
pywaylandauto double-click 500 300                  # 双击
pywaylandauto mouse-down 100 100                    # 按住
pywaylandauto mouse-up 500 300                      # 释放
pywaylandauto drag 100 100 500 300                  # 拖拽
pywaylandauto scroll 300 200 --dy 3                 # 滚动

# 键盘
pywaylandauto input "Hello World"   # 输入文本
pywaylandauto key Return            # 单键
pywaylandauto key ctrl c            # 组合键
pywaylandauto key-down shift        # 按住
pywaylandauto key-up shift          # 释放
```

### Python API

```python
import pywaylandauto

# 鼠标
pywaylandauto.move(960, 540)
pywaylandauto.move_rel(10, -5)
pywaylandauto.click(500, 300)
pywaylandauto.right_click(500, 300)
pywaylandauto.middle_click(500, 300)
pywaylandauto.double_click(500, 300)
pywaylandauto.mouse_down(100, 100)
pywaylandauto.mouse_up(500, 300)
pywaylandauto.drag(100, 100, 500, 300)
pywaylandauto.scroll(300, 200, dy=3)

# 键盘
pywaylandauto.input("Hello")
pywaylandauto.key("ctrl", "c")
pywaylandauto.key_down("shift")
pywaylandauto.key_up("shift")

# 查询
pywaylandauto.mouse_position()  # {'x': 500.0, 'y': 300.0}
```

### 守护进程管理

```bash
pywaylandauto daemon start                 # 后台启动
pywaylandauto daemon start --foreground    # 前台调试
pywaylandauto daemon stop                  # 停止
pywaylandauto daemon status                # 状态
pywaylandauto status                       # 完整状态（守护进程+后端+鼠标+显示器）
```

---

## CLI 命令参考

格式：`pywaylandauto <命令> [参数] [--socket PATH] [--no-spawn]`

### 鼠标命令

| 命令 | 参数 | 说明 |
|------|------|------|
| `move X Y` | X Y (float) | 移动到绝对坐标 |
| `move-rel DX DY` | DX DY (float) | 相对移动 |
| `click X Y` | X Y (float) `--button left\|right\|middle` | 移动并单击 |
| `right-click X Y` | X Y (float) | 移动并右键点击 |
| `middle-click X Y` | X Y (float) | 移动并中键点击 |
| `double-click X Y` | X Y (float) `--button left\|right\|middle` | 移动并双击 |
| `mouse-down X Y` | X Y (float) `--button left\|right\|middle` | 移动并按下 |
| `mouse-up X Y` | X Y (float) `--button left\|right\|middle` | 移动并释放 |
| `drag X1 Y1 X2 Y2` | 起点终点 (float) `--button left\|right\|middle` | 拖拽 |
| `scroll X Y` | X Y (float) `--dx N` `--dy N` | 定点滚动 |

### 键盘命令

| 命令 | 参数 | 说明 |
|------|------|------|
| `input TEXT` | TEXT (str) | 输入文本（ASCII 直接键入，非 ASCII 剪贴板粘贴） |
| `key KEY...` | KEY (str, 可多个) | 单键或组合键 |
| `key-down KEY` | KEY (str) | 按住按键 |
| `key-up KEY` | KEY (str) | 释放按键 |

### 支持的键名

| 类别 | 键名 |
|------|------|
| 字符键 | `a`-`z`, `0`-`9`, 标点符号等 |
| 修饰键 | `ctrl`, `shift`, `alt`, `super` / `win` / `cmd` |
| 功能键 | `F1`-`F12` |
| 特殊键 | `Return`, `Tab`, `Escape`, `BackSpace`, `Delete`, `Space`, `CapsLock` |
| 方向键 | `Left`, `Up`, `Right`, `Down` |
| 导航键 | `Home`, `End`, `PageUp`, `PageDown` |

---

## Python API 参考

`import pywaylandauto` 自动创建客户端单例，守护进程未运行时自动后台启动。

### 鼠标操作

| 函数 | 参数 | 说明 |
|------|------|------|
| `move(x, y)` | x, y: float | 移动到绝对坐标 |
| `move_rel(dx, dy)` | dx, dy: float | 相对移动 |
| `click(x, y, button="left")` | x, y: float; button: str | 移动并单击 |
| `right_click(x, y)` | x, y: float | 移动并右键点击 |
| `middle_click(x, y)` | x, y: float | 移动并中键点击 |
| `double_click(x, y, button="left")` | x, y: float; button: str | 移动并双击 |
| `mouse_down(x, y, button="left")` | x, y: float; button: str | 移动并按下 |
| `mouse_up(x, y, button="left")` | x, y: float; button: str | 移动并释放 |
| `drag(x1, y1, x2, y2, button="left")` | 起点终点: float; button: str | 拖拽 |
| `scroll(x, y, dx=0, dy=0)` | x, y: float; dx, dy: int | 定点滚动 |
| `mouse_position()` | — | 返回 `{'x': float, 'y': float}` |

### 键盘操作

| 函数 | 参数 | 说明 |
|------|------|------|
| `input(text)` | text: str | 输入文本 |
| `key(*keys)` | keys: str | 单键或组合键 |
| `key_down(key)` | key: str | 按住按键 |
| `key_up(key)` | key: str | 释放按键 |