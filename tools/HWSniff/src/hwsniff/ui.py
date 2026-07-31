from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import SWEETP_STATES, AppState, UiSnapshot


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

        state = snap.state
        if state in SWEETP_STATES:
            self._draw_sweetp(snap, text)
        else:
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
            self._screen.blit(label_s, (rect.x + 12, rect.y + 14))
            self._buttons.append((rect, action, payload or {}))

        if state == AppState.READY:
            button("SWEETP", "sweetp", 40, (30, 100, 170), w=150)
            button("START", "start", 250, (20, 150, 60), w=150)
            if self.ui_config.get("allow_shutdown_button", True):
                button("OFF", "shutdown", self.width - 80, (90, 90, 90), w=64)
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
        elif state in (
            AppState.SWEETP_WAITING_FOR_TAG,
            AppState.SWEETP_CHECKING,
            AppState.SWEETP_STARTING,
        ):
            button("ZRUŠIT", "sweetp_cancel", self.width // 2 - 70, (180, 40, 40))
        elif state == AppState.SWEETP_GOOD_POSITION:
            button("HOTOVO", "sweetp_done", self.width // 2 - 70, (20, 150, 60))
        elif state == AppState.SWEETP_UNSTABLE_POSITION:
            button("ZRUŠIT", "sweetp_cancel", 40, (180, 40, 40), w=150)
            button("ZNOVU", "sweetp_retry", 250, (180, 120, 20), w=150)
        elif state == AppState.SWEETP_READER_ERROR:
            button("ZRUŠIT", "sweetp_cancel", 40, (180, 40, 40), w=150)
            button("ZNOVU", "sweetp_retry", 250, (180, 120, 20), w=150)
        elif state not in (
            AppState.BOOTING,
            AppState.INITIALIZING,
            AppState.STOPPED,
            AppState.FATAL_ERROR,
            AppState.SWEETP_CANCELLED,
        ):
            button("STOP", "stop", self.width // 2 - 70, (180, 40, 40))

        pg.display.flip()
        if self._clock:
            self._clock.tick(30)

    def _draw_sweetp(self, snap: UiSnapshot, text) -> None:
        state = snap.state
        text("SWEETP", 8, big=True)
        text(snap.message or USER_FALLBACK.get(state, state.value), 48, big=True)
        if state == AppState.SWEETP_WAITING_FOR_TAG:
            text("Přiložte čtečku ke štítku", 100)
            text("a pomalu hledejte polohu", 130)
        elif state == AppState.SWEETP_CHECKING:
            text(f"UID: {snap.last_uid}", 100)
            text("Kontroluji stabilitu...", 130)
            text(
                f"Pokus: {snap.sweetp_attempt} / {snap.sweetp_total or 10}",
                160,
            )
            if snap.sweetp_quality:
                text(f"Quality: {snap.sweetp_quality}", 190)
        elif state == AppState.SWEETP_GOOD_POSITION:
            text(
                f"Stabilní čtení: {snap.sweetp_successes} / {snap.sweetp_total}",
                100,
            )
            text("UID je konzistentní", 130)
            if snap.sweetp_quality:
                text(f"Quality: {snap.sweetp_quality}", 160)
        elif state == AppState.SWEETP_UNSTABLE_POSITION:
            text(
                f"Stabilní čtení: {snap.sweetp_successes} / {snap.sweetp_total}",
                100,
            )
            text("Posuňte nebo pootočte čtečku", 130)
            if snap.sweetp_quality:
                text(f"Quality: {snap.sweetp_quality}", 160)
        elif state == AppState.SWEETP_READER_ERROR:
            text("Čtečka neodpovídá", 100)
            text(snap.progress[:40] if snap.progress else "Zkuste ZNOVU", 130)
        if snap.progress and state not in (
            AppState.SWEETP_READER_ERROR,
            AppState.SWEETP_CHECKING,
        ):
            text(snap.progress[:40], 200)


USER_FALLBACK = {
    AppState.SWEETP_WAITING_FOR_TAG: "Přiložte čtečku ke štítku",
    AppState.SWEETP_CHECKING: "TAG DETECTED",
    AppState.SWEETP_GOOD_POSITION: "POSITION OK",
    AppState.SWEETP_UNSTABLE_POSITION: "MOVE READER",
    AppState.SWEETP_READER_ERROR: "SWEETP READER ERROR",
}


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
