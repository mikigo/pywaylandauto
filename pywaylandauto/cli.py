"""Command-line interface for pywaylandauto — built with Typer."""

import os
import subprocess
import sys
import time
from typing import Optional

import typer
import typer.core

from . import __version__, protocol
from .client import Client
from .daemon import AlreadyRunningError, Daemon, default_pid_path, default_socket_path


class _OrderedGroup(typer.core.TyperGroup):
    def list_commands(self, ctx):
        commands = list(super().list_commands(ctx))
        for name in ("daemon",):
            if name in commands:
                commands.remove(name)
                commands.insert(0, name)
        return commands


app = typer.Typer(
    name="pywaylandauto",
    help="Wayland keyboard/mouse input injection tool",
    add_completion=False,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    cls=_OrderedGroup,
)

daemon_app = typer.Typer(help="Daemon lifecycle management", context_settings={"help_option_names": ["-h", "--help"]})
app.add_typer(daemon_app, name="daemon")


def _die(message: str, code: int = 1) -> None:
    typer.echo(f"pywaylandauto: {message}", err=True)
    raise typer.Exit(code)


def _read_pid(pid_path: str) -> Optional[str]:
    try:
        with open(pid_path) as f:
            return f.read().strip()
    except OSError:
        return None


def _client(socket_path: str = None, auto_spawn: bool = True) -> Client:
    return Client(socket_path=socket_path, auto_spawn=auto_spawn)


# -- common option decorator -------------------------------------------------

socket_opt = typer.Option(None, help="Daemon socket path")
no_spawn_opt = typer.Option(False, "--no-spawn", help="Don't auto-spawn the daemon")


# ============================================================================
#  Daemon commands
# ============================================================================

@daemon_app.command(name="start")
def daemon_start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    pid_file: str = typer.Option(None, help="PID file path"),
):
    """Start the daemon (background by default)."""
    socket_path = socket or default_socket_path()
    pid_path = pid_file or default_pid_path()

    if not foreground:
        cmd = [sys.executable, "-m", "pywaylandauto", "daemon", "start", "--foreground"]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if os.path.exists(socket_path):
                pid = _read_pid(pid_path)
                typer.echo(f"daemon started (pid {pid or '?'})")
                return
            time.sleep(0.1)
        _die("daemon did not start within 3s")

    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        daemon = Daemon(socket_path=socket_path, pid_path=pid_path)
        daemon.run()
    except AlreadyRunningError as e:
        _die(str(e))


@daemon_app.command(name="stop")
def daemon_stop(
    socket: str = typer.Option(None, help="Daemon socket path"),
):
    """Stop the daemon."""
    c = Client(socket_path=socket or default_socket_path(), auto_spawn=False)
    try:
        c.daemon_stop()
    except (ConnectionError, FileNotFoundError) as e:
        _die(f"no running daemon ({e})")
    except protocol.RemoteError as e:
        _die(f"daemon reported: {e}")
    typer.echo("daemon stopped")


@daemon_app.command(name="status")
def daemon_pid_status(
    pid_file: str = typer.Option(None, help="PID file path"),
):
    """Show daemon process status."""
    pid_path = pid_file or default_pid_path()
    if os.path.exists(pid_path):
        console.print(f"pid: [bold]{_read_pid(pid_path)}[/]")
        return
    _die("no running daemon (no pid file)")


# ============================================================================
#  Status
# ============================================================================

@app.command()
def status(
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Show daemon, backend, display, and mouse status."""
    c = _client(socket, auto_spawn=not no_spawn)
    try:
        result = c.status()
    except (ConnectionError, protocol.RemoteError) as e:
        _die(str(e))

    daemon_info = result.get("daemon", {})
    backend = result.get("backend", {})
    mouse = result.get("mouse", {})
    scale = result.get("scale", 1.0)
    regions = backend.get("regions", [])

    typer.echo(f"daemon:  pid={daemon_info.get('pid','?')}  socket={daemon_info.get('socket','?')}")
    typer.echo(f"backend: state={backend.get('state')}  transport={backend.get('transport')}")
    typer.echo(f"mouse:   x={mouse.get('x',0):.0f}  y={mouse.get('y',0):.0f}  scale={scale}")
    for r in regions:
        typer.echo(f"region:  {r[0]}+{r[1]} {r[2]}x{r[3]} @ {r[4]}x")


# ============================================================================
#  Mouse commands
# ============================================================================

@app.command()
def move(
    x: float = typer.Argument(..., help="X coordinate (physical pixels)"),
    y: float = typer.Argument(..., help="Y coordinate (physical pixels)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Move the mouse pointer to absolute coordinates."""
    _client(socket, auto_spawn=not no_spawn).move_abs(x, y)


@app.command()
def move_rel(
    dx: float = typer.Argument(..., help="Delta X"),
    dy: float = typer.Argument(..., help="Delta Y"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Move the mouse pointer relative to current position."""
    _client(socket, auto_spawn=not no_spawn).move_rel(dx, dy)


@app.command()
def click(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    button: str = typer.Option("left", help="Button: left, right, middle"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Click at position (move + click)."""
    _client(socket, auto_spawn=not no_spawn).click(x, y, button)


@app.command()
def right_click(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Right-click at position."""
    _client(socket, auto_spawn=not no_spawn).click(x, y, "right")


@app.command()
def middle_click(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Middle-click at position."""
    _client(socket, auto_spawn=not no_spawn).click(x, y, "middle")


@app.command()
def double_click(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    button: str = typer.Option("left", help="Button: left, right, middle"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Double-click at position."""
    _client(socket, auto_spawn=not no_spawn).double_click(x, y, button)


@app.command()
def mouse_down(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    button: str = typer.Option("left", help="Button: left, right, middle"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Press and hold a mouse button at position."""
    _client(socket, auto_spawn=not no_spawn).mouse_down(x, y, button)


@app.command()
def mouse_up(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    button: str = typer.Option("left", help="Button: left, right, middle"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Release a mouse button at position."""
    _client(socket, auto_spawn=not no_spawn).mouse_up(x, y, button)


@app.command()
def drag(
    x1: float = typer.Argument(..., help="Start X"),
    y1: float = typer.Argument(..., help="Start Y"),
    x2: float = typer.Argument(..., help="End X"),
    y2: float = typer.Argument(..., help="End Y"),
    button: str = typer.Option("left", help="Button: left, right, middle"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Drag from start to end position."""
    _client(socket, auto_spawn=not no_spawn).drag(x1, y1, x2, y2, button)


@app.command()
def scroll(
    x: float = typer.Argument(..., help="X coordinate"),
    y: float = typer.Argument(..., help="Y coordinate"),
    dx: int = typer.Option(0, help="Horizontal scroll steps"),
    dy: int = typer.Option(-1, help="Vertical scroll steps (negative = up)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Scroll at position."""
    _client(socket, auto_spawn=not no_spawn).scroll(x, y, dx, dy)


# ============================================================================
#  Keyboard commands
# ============================================================================

@app.command()
def input(
    text: str = typer.Argument(..., help="Text to type (ASCII via keyboard, Unicode via clipboard)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Input text. ASCII typed directly; non-ASCII copied via clipboard and pasted with Ctrl+V."""
    _client(socket, auto_spawn=not no_spawn).type_text(text)


@app.command()
def key(
    keys: list[str] = typer.Argument(..., help="Key name(s). One key = tap; multiple = combo (e.g. ctrl c)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Press key(s). Single key = tap; multiple keys = held combo."""
    _client(socket, auto_spawn=not no_spawn).key(*keys)


@app.command()
def key_down(
    key_name: str = typer.Argument(..., help="Key name (e.g. shift, ctrl, a)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Press and hold a key (must release with key-up)."""
    _client(socket, auto_spawn=not no_spawn).key_down(key_name)


@app.command()
def key_up(
    key_name: str = typer.Argument(..., help="Key name (e.g. shift, ctrl, a)"),
    socket: str = typer.Option(None, help="Daemon socket path"),
    no_spawn: bool = typer.Option(False, "--no-spawn", help="Don't auto-spawn daemon"),
):
    """Release a pressed key."""
    _client(socket, auto_spawn=not no_spawn).key_up(key_name)


# ============================================================================
#  Entry point
# ============================================================================

def main(argv=None):
    import sys
    if argv is None:
        argv = sys.argv[1:]
    # Click treats negative-positional-args like `-200` as option `-2 0 0`.
    # Detect commands that take float args and insert `--` before them.
    _neg_cmds = frozenset(("move", "move-rel", "scroll"))
    if len(argv) >= 2 and argv[0] in _neg_cmds:
        for i in range(1, len(argv)):
            a = argv[i]
            if a.startswith("-") and not a.startswith("--"):
                try:
                    float(a)
                    argv = list(argv[:i]) + ["--"] + list(argv[i:])
                    break
                except ValueError:
                    continue
        sys.argv[1:] = argv
    try:
        app()
    except Exception as e:
        _die(str(e))


if __name__ == "__main__":
    main()