---
pageType: home

hero:
  name: pywaylandauto
  text: Wayland 键盘鼠标输入注入工具
  tagline: 基于 EIS 和 wlroots 协议，为 Kylin OS 及其他 Wayland 桌面提供键盘鼠标自动化控制
  actions:
    - theme: brand
      text: 阅读文档
      link: /guide/introduction
  image:
    src: /rspress-icon.png
    alt: pywaylandauto
features:
  - title: EIS 协议支持
    details: 通过 Kylin Wlcom 的 EIS RemoteDesktop D-Bus 接口连接，支持精确的绝对坐标定位和帧式输入
    icon: 🖥️
  - title: wlroots 协议回退
    details: 当 EIS 不可用时，自动回退到 wlroots 虚拟输入协议，兼容 Sway、Hyprland 等合成器
    icon: 🔄
  - title: 命令行工具
    details: 完整的 CLI 接口，支持鼠标移动/点击/拖拽/滚动、键盘输入/组合键、守护进程生命周期管理
    icon: ⌨️
  - title: Python API
    details: 提供简洁的 Python 编程接口，`import pywaylandauto` 即可在脚本中使用所有自动化功能
    icon: 🐍
  - title: 自动守护进程
    details: 首次调用 API 或 CLI 时自动后台启动守护进程，无需手动管理。支持前台调试模式
    icon: 🔧
  - title: 坐标缩放
    details: 用户侧使用物理像素坐标，守护进程自动根据显示器缩放因子转换为逻辑坐标
    icon: 📐
---