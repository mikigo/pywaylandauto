"""Backend abstraction for input injection."""
from abc import ABC, abstractmethod

class BackendError(Exception):
    pass

BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}
PRESS, RELEASE = 1, 0
AXIS_VERTICAL, AXIS_HORIZONTAL = 0, 1

class Backend(ABC):
    name = "base"
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def status(self) -> dict: ...
    @abstractmethod
    def move_abs(self, x: float, y: float) -> None: ...
    @abstractmethod
    def move_rel(self, dx: float, dy: float) -> None: ...
    @abstractmethod
    def button(self, button: str | int, press: int) -> None: ...
    @abstractmethod
    def scroll(self, dx: int, dy: int) -> None: ...
    @abstractmethod
    def key(self, keycode: int, press: int) -> None: ...
    def type_text(self, text: str) -> None:
        raise NotImplementedError