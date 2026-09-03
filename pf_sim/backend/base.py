from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Backend(ABC):
    @abstractmethod
    def up(self, **kwargs) -> Path: ...

    @abstractmethod
    def down(self, instance: str) -> bool: ...

    @abstractmethod
    def status(self, instance: str) -> dict: ...

    @abstractmethod
    def capture_hint(self, instance: str) -> str: ...

    @abstractmethod
    def shell_display_env(self, socket: str) -> dict[str, str]: ...
