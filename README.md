# pywaylandauto

Wayland 键盘鼠标输入注入工具。通过 EIS (Emulated Input Server) 或 wlroots 虚拟输入协议实现全局鼠标键盘控制，支持 Kylin / Ubuntu GNOME / wlroots 等多种 Wayland 环境。

## 安装

```bash
pip install pywaylandauto
```

或开发模式：

```bash
git clone https://github.com/.../pywaylandauto.git
cd pywaylandauto
pip install -e .
```

## 快速开始

```bash
pywaylandauto daemon start          # 启动后台 daemon
pywaylandauto move 960 540          # 移动鼠标
pywaylandauto click 500 300         # 左键点击
pywaylandauto right-click 500 300   # 右键点击
pywaylandauto input "Hello 世界"    # 输入文本（中文通过剪贴板粘贴）
pywaylandauto key ctrl c            # 组合键 Ctrl+C
pywaylandauto get-clipboard         # 获取剪贴板内容
pywaylandauto daemon stop           # 停止 daemon
```

## CLI 命令

### Daemon

| 命令 | 说明 |
|---|---|
| `pywaylandauto daemon start` | 启动 daemon（后台运行） |
| `pywaylandauto daemon stop` | 停止 daemon |
| `pywaylandauto daemon status` | daemon 进程状态 |
| `pywaylandauto status` | 完整状态：daemon、backend、坐标、缩放比、keymap |
| `pywaylandauto session-start [--wait]` | Portal 会话重授权（GNOME 授权弹窗） |

### 鼠标

| 命令 | 说明 |
|---|---|
| `move X Y` | 绝对移动 |
| `move-rel DX DY` | 相对移动 |
| `click X Y [--button]` | 点击 |
| `right-click X Y` | 右键点击 |
| `middle-click X Y` | 中键点击 |
| `double-click X Y` | 双击 |
| `mouse-down X Y [--button]` | 按下 |
| `mouse-up X Y [--button]` | 释放 |
| `drag X1 Y1 X2 Y2` | 拖拽 |
| `scroll X Y [--dx] [--dy]` | 滚轮 |

### 键盘

| 命令 | 说明 |
|---|---|
| `input TEXT` | 输入文本（ASCII 直接键入，中文/Unicode 通过剪贴板粘贴） |
| `key KEY [KEY...]` | 按键（多键=组合键，如 `ctrl c`） |
| `key-down KEY` | 按下不放 |
| `key-up KEY` | 释放 |
| `get-clipboard` | 获取当前剪贴板内容 |

## Python API

```python
import pywaylandauto

pywaylandauto.move(960, 540)
pywaylandauto.click(500, 300)
pywaylandauto.right_click(500, 300)
pywaylandauto.double_click(500, 300)
pywaylandauto.mouse_down(100, 100)
pywaylandauto.mouse_up(500, 300)
pywaylandauto.drag(100, 100, 500, 300)
pywaylandauto.scroll(300, 200, dy=3)
pywaylandauto.input("Hello")
pywaylandauto.key("ctrl", "c")
pywaylandauto.key_down("shift")
pywaylandauto.key_up("shift")

pos = pywaylandauto.mouse_position()  # {'x': 500.0, 'y': 300.0}
text = pywaylandauto.get_clipboard()  # {'text': '剪贴板内容'}
```

首次调用自动启动 daemon。坐标使用物理像素，daemon 自动按缩放比转换。

## 后端

| 后端 | 平台 | 说明 |
|---|---|---|
| EIS (Kylin) | Kylin V11 | 直接通过 kylin-wlcom D-Bus 连接 EIS |
| EIS (Portal) | Ubuntu / GNOME | 通过 XDG Desktop Portal RemoteDesktop 获取 EIS 连接 |
| Wlroots | Sway / Hyprland | zwlr_virtual_pointer + zwp_virtual_keyboard |

启动 daemon 时自动探测后端：Kylin EIS → Portal EIS → Wlroots。

## 平台支持

| 平台 | 状态 |
|---|---|
| Kylin V11 (kylin-wlcom) | ✅ 完整支持 |
| Ubuntu / GNOME | ✅ 完整支持 |
| Deepin / UOS | 规划中 |
| Sway / Hyprland | ✅ Wlroots 后端 |

## 许可

MIT