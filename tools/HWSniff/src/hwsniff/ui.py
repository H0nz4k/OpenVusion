from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import FIELD_ACTIVE_STATES, SWEETP_STATES, AppState, UiSnapshot


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
        self._pulse = 0

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
        elif snap.state in FIELD_ACTIVE_STATES and snap.state not in (
            AppState.SUCCESS,
            AppState.FAILURE,
            AppState.WARNING,
        ):
            bg = (10, 28, 48)
        self._screen.fill(bg)
        self._buttons = []
        self._pulse = (self._pulse + 1) % 60

        def text(line: str, y: int, big: bool = False, color=(240, 240, 240)) -> None:
            font = self._font_big if big else self._font
            surface = font.render(line[:48], True, color)
            self._screen.blit(surface, (16, y))

        state = snap.state
        if state in SWEETP_STATES:
            self._draw_sweetp(snap, text)
        elif state in FIELD_ACTIVE_STATES:
            self._draw_sniffing(snap, text)
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
        elif state == AppState.SWEETP_STARTING:
            button("ZRUŠIT", "sweetp_cancel", self.width // 2 - 70, (180, 40, 40))
        elif state == AppState.SWEETP_WAITING_FOR_TAG:
            button("ZRUŠIT", "sweetp_cancel", self.width // 2 - 70, (180, 40, 40))
        elif state in (
            AppState.SWEETP_CHECKING,
            AppState.SWEETP_UNSTABLE_POSITION,
            AppState.SWEETP_GOOD_POSITION,
        ):
            button("ZRUŠIT", "sweetp_cancel", 24, (180, 40, 40), w=140)
            if snap.sweetp_enough_samples or snap.sweetp_position_ok:
                button("HOTOVO", "sweetp_done", 300, (20, 150, 60), w=150)
        elif state == AppState.SWEETP_READER_ERROR:
            button("ZRUŠIT", "sweetp_cancel", 40, (180, 40, 40), w=150)
            button("ZNOVU", "sweetp_retry", 250, (180, 120, 20), w=150)
        elif state in FIELD_ACTIVE_STATES:
            button("STOP", "stop", self.width // 2 - 70, (180, 40, 40))
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

    def _draw_progress_bar(self, step: int, total: int, y: int = 210) -> None:
        pg = self._pygame
        total = max(1, total)
        step = max(0, min(step, total))
        x, w, h = 16, self.width - 32, 22
        pg.draw.rect(self._screen, (50, 50, 50), pg.Rect(x, y, w, h), border_radius=6)
        fill = int(w * (step / total))
        if fill > 0:
            color = (40, 170, 90) if step >= total else (40, 140, 220)
            pg.draw.rect(self._screen, color, pg.Rect(x, y, fill, h), border_radius=6)

    def _draw_sniffing(self, snap: UiSnapshot, text) -> None:
        dots = "." * (1 + (self._pulse // 15) % 3)
        title = snap.message or "SNIFFING ACTIVE"
        text(title[:28], 8, big=True, color=(120, 220, 255))
        if snap.state == AppState.WAITING_FOR_TAG:
            text(f"Přiložte štítek{dots}", 52, big=True)
            text("Sběr běží — čekám na tag", 96)
        else:
            text(snap.progress[:40] if snap.progress else snap.state.value, 52, big=True)
            if snap.capture_step_label:
                text(
                    f"Krok: {snap.capture_step_label}",
                    96,
                    color=(200, 220, 255),
                )
        text(f"UID: {snap.last_uid}", 130)
        text(f"OK: {snap.ok_count}    Errors: {snap.error_count}", 160)
        step = snap.capture_step or 0
        total = snap.capture_step_total or 6
        text(f"Progres: {step}/{total}", 188)
        self._draw_progress_bar(step, total, y=218)

    def _draw_sweetp(self, snap: UiSnapshot, text) -> None:
        pg = self._pygame
        state = snap.state
        if state == AppState.SWEETP_READER_ERROR:
            text("SWEETP", 8, big=True)
            text("READER ERROR", 48, big=True, color=(255, 180, 180))
            text(snap.progress[:40] if snap.progress else "Zkuste ZNOVU", 100)
            return
        if state in (AppState.SWEETP_WAITING_FOR_TAG, AppState.SWEETP_STARTING):
            text("SWEETP", 8, big=True)
            text("Hledejte polohu", 48, big=True)
            text("Pomalu posouvejte / otáčejte", 100)
            text("živá kvalita čtení (ne RSSI)", 130, color=(180, 200, 220))
            return

        q = snap.sweetp_current_quality
        if q >= 85 or snap.sweetp_position_ok:
            q_color = (80, 230, 120)
        elif q >= 50:
            q_color = (240, 170, 50)
        else:
            q_color = (240, 90, 90)

        text("SWEETP", 4, color=(180, 210, 230))
        title = "POSITION OK" if snap.sweetp_position_ok else "kvalita polohy"
        text(title, 28, big=True, color=q_color)
        text(f"{q:.0f}%", 62, big=True, color=q_color)

        trend = snap.sweetp_trend
        if trend == "improving":
            trend_txt, trend_col = "LEPŠÍ ↑", (80, 230, 120)
        elif trend == "worsening":
            trend_txt, trend_col = "HORŠÍ ↓", (240, 90, 90)
        else:
            trend_txt, trend_col = "STABILNÍ →", (220, 220, 220)
        text(trend_txt, 100, color=trend_col)

        # Quality bar
        x, y, w, h = 16, 132, self.width - 32, 20
        pg.draw.rect(self._screen, (45, 45, 45), pg.Rect(x, y, w, h), border_radius=6)
        fill = int(w * max(0.0, min(1.0, q / 100.0)))
        if fill > 0:
            pg.draw.rect(self._screen, q_color, pg.Rect(x, y, fill, h), border_radius=6)

        ok_n = snap.sweetp_window_successes
        tot = snap.sweetp_window_total
        text(f"{ok_n}/{tot}  best {snap.sweetp_best_quality:.0f}%", 158)
        uid = snap.sweetp_dominant_uid or snap.last_uid or "—"
        text(f"UID {str(uid)[:18]}", 182)
        if snap.sweetp_latency_available and snap.sweetp_average_latency_ms is not None:
            text(f"lat {snap.sweetp_average_latency_ms:.0f} ms", 206)
        else:
            text(
                f"OK {snap.sweetp_total_successes}  ERR {snap.sweetp_total_failures}",
                206,
            )


USER_FALLBACK = {
    AppState.SWEETP_WAITING_FOR_TAG: "Hledejte polohu",
    AppState.SWEETP_CHECKING: "SWEETP LIVE",
    AppState.SWEETP_GOOD_POSITION: "POSITION OK",
    AppState.SWEETP_UNSTABLE_POSITION: "SWEETP LIVE",
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
