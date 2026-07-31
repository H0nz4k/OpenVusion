from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import AppState, UiSnapshot


@dataclass
class UiAction:
    name: str
    payload: dict[str, Any] | None = None


class TouchUI:
    """Pygame fullscreen UI for 480x320 touchscreens."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.full_config = config
        self.config = config.get("display") or {}
        self.ui_config = config.get("ui") or {}
        self.width = int(self.config.get("width", 480))
        self.height = int(self.config.get("height", 320))
        self._pygame = None
        self._screen = None
        self._font = None
        self._font_big = None
        self._clock = None
        self._buttons: list[tuple[Any, str, dict]] = []

    def start(self) -> None:
        import pygame

        self._pygame = pygame
        pygame.init()
        flags = pygame.FULLSCREEN if self.config.get("fullscreen", True) else 0
        self._screen = pygame.display.set_mode((self.width, self.height), flags)
        pygame.display.set_caption("OpenVusion HWSniff")
        if self.config.get("hide_cursor", True):
            pygame.mouse.set_visible(False)
        self._font = pygame.font.SysFont("DejaVu Sans", 22)
        self._font_big = pygame.font.SysFont("DejaVu Sans", 32, bold=True)
        self._clock = pygame.time.Clock()

    def stop(self) -> None:
        if self._pygame:
            self._pygame.quit()

    def poll_actions(self) -> list[UiAction]:
        if not self._pygame:
            return []
        actions: list[UiAction] = []
        for event in self._pygame.event.get():
            if event.type == self._pygame.QUIT:
                actions.append(UiAction("quit"))
            elif event.type == self._pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                for rect, name, payload in self._buttons:
                    if rect.collidepoint(x, y):
                        actions.append(UiAction(name, payload))
        return actions

    def draw(self, snap: UiSnapshot) -> None:
        if not self._pygame or not self._screen:
            return
        pg = self._pygame
        bg = (20, 20, 20)
        if snap.banner == "ok":
            bg = (12, 90, 30)
        elif snap.banner == "error":
            bg = (110, 20, 20)
        self._screen.fill(bg)
        self._buttons = []

        def text(line: str, y: int, big: bool = False, color=(240, 240, 240)) -> None:
            font = self._font_big if big else self._font
            surface = font.render(line[:48], True, color)
            self._screen.blit(surface, (16, y))

        text("OpenVusion HWSniff", 8, big=True)
        text(snap.message or snap.state.value, 48, big=True)
        if snap.reader_label:
            text(snap.reader_label[:40], 90)
        text(snap.storage_text or "", 118)
        text(f"Last UID: {snap.last_uid}", 148)
        text(f"OK: {snap.ok_count}    Errors: {snap.error_count}", 176)
        if snap.progress:
            text(snap.progress[:40], 204)

        y_btn = self.height - 70

        def button(label: str, action: str, x: int, color=(40, 120, 220), payload=None, w=140):
            rect = pg.Rect(x, y_btn, w, 54)
            pg.draw.rect(self._screen, color, rect, border_radius=8)
            label_s = self._font.render(label, True, (255, 255, 255))
            self._screen.blit(label_s, (rect.x + 16, rect.y + 14))
            self._buttons.append((rect, action, payload or {}))

        state = snap.state
        if state == AppState.READY:
            button("START", "start", self.width // 2 - 70, (20, 150, 60))
            if self.ui_config.get("allow_shutdown_button", True):
                button("OFF", "shutdown", self.width - 90, (90, 90, 90), w=70)
        elif state in (
            AppState.READER_MISSING,
            AppState.READER_DISCONNECTED,
            AppState.STORAGE_ERROR,
        ):
            button("RETRY", "retry", self.width // 2 - 70, (180, 120, 20))
        elif state == AppState.MULTIPLE_READERS:
            button("RETRY", "retry", 16, (180, 120, 20), w=100)
            for index, _label in enumerate(snap.candidates[:2]):
                button(
                    f"USE {index + 1}",
                    "select",
                    130 + index * 160,
                    payload={"index": index},
                    w=140,
                )
        elif state == AppState.SHUTDOWN_CONFIRM:
            button("ZRUŠIT", "shutdown_cancel", 40, (80, 80, 80))
            button("VYPNOUT", "shutdown_confirm", 260, (160, 30, 30))
        elif state not in (
            AppState.BOOTING,
            AppState.INITIALIZING,
            AppState.STOPPED,
            AppState.FATAL_ERROR,
        ):
            button("STOP", "stop", self.width // 2 - 70, (180, 40, 40))

        pg.display.flip()
        if self._clock:
            self._clock.tick(30)


class HeadlessUI:
    """Test double / non-graphical UI."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.actions: list[UiAction] = []
        self.last_snapshot: UiSnapshot | None = None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def poll_actions(self) -> list[UiAction]:
        actions = list(self.actions)
        self.actions.clear()
        return actions

    def draw(self, snap: UiSnapshot) -> None:
        self.last_snapshot = snap

    def push(self, name: str, payload: dict | None = None) -> None:
        self.actions.append(UiAction(name, payload))
