"""claude-indicator: always-on-top status pill for Claude Code.

Claude-themed: warm cream capsule, a spinning spark while working, one row
per active session with project name and elapsed time.

  terracotta spark (spinning) = working   (whimsical labels: Ruminating...)
  green spark                 = ready
  amber spark                 = needs you (permission / input) + chime

The pill hides while your IDE/terminal is focused (you can see Claude there
already) and fades back in when you alt-tab away. Amber always shows.
Click a row to bring that session's IDE/terminal to the front.

Reads per-session status files from runtime/sessions/, written by
hook_handler.py.
"""

import ctypes
import json
import os
import sys
import time

import psutil
import win32con
import win32gui
import win32process
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

# Runtime files live next to the scripts, NOT in %LOCALAPPDATA%: Microsoft
# Store Python virtualizes AppData writes per package context, so the hook
# and the indicator can otherwise end up reading two different files.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "runtime")
SESSIONS_DIR = os.path.join(APP_DIR, "sessions")
LOG_FILE = os.path.join(APP_DIR, "indicator.log")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

STALE_AFTER_S = 24 * 3600  # ignore sessions with no events for a day
# A genuinely working session emits tool-use events constantly. If one has
# been silent this long, it was likely closed without SessionEnd (terminal
# killed) — treat it as done instead of pinning the pill orange forever.
WORKING_SILENT_S = 10 * 60

POLL_MS = 100
ENDED_GRACE_MS = 3000

# Claude palette
CREAM = QColor(240, 238, 230)          # capsule body
CREAM_BORDER = QColor(208, 203, 188)   # 1px capsule outline
INK = QColor(61, 57, 41)               # primary text
INK_SOFT = QColor(61, 57, 41, 150)     # secondary text (elapsed, project)
TERRACOTTA = QColor(217, 119, 87)      # working spark
GREEN = QColor(46, 125, 79)            # ready spark
AMBER = QColor(199, 132, 28)           # needs-you spark

STATUS_COLOR = {"working": TERRACOTTA, "waiting": AMBER, "done": GREEN}
STATUS_LABEL = {"done": "Ready", "waiting": "Needs you"}

# Claude Code's whimsical working gerunds; one is picked per work stretch
# and rotated every few seconds.
WORKING_WORDS = [
    "Lollygagging", "Ruminating", "Pondering", "Percolating", "Noodling",
    "Brewing", "Marinating", "Simmering", "Conjuring", "Scheming",
    "Caramelizing", "Sketching", "Pouncing", "Whirring", "Vibing",
    "Mustering", "Puttering", "Tinkering", "Churning", "Incubating",
]

ROW_H = 34
PILL_W = 190
PAD = 4  # transparent margin around the capsule for the shadow


def log(msg: str) -> None:
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def load_config() -> dict:
    cfg = {
        "hide_on_processes": [
            "Code.exe", "cursor.exe", "Kiro.exe", "WindowsTerminal.exe",
            "wt.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
        ],
        "position": None,
        "margin": 16,
        "sound_on_needs_you": True,
    }
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            user = json.load(f)
        for key, value in user.items():
            cfg[key] = value
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_position(pos: QPoint) -> None:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}
    cfg["position"] = [pos.x(), pos.y()]
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


def foreground_process_name() -> str:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid <= 0:
            return ""
        return psutil.Process(pid).name()
    except (psutil.Error, OSError):
        return ""


def focus_session_window(claude_pid: int) -> None:
    """Bring the IDE/terminal hosting this claude.exe to the foreground.

    claude.exe itself has no window; walk its ancestors (terminal, IDE) and
    raise the first ancestor that owns a visible top-level window.
    """
    try:
        ancestors = []
        p = psutil.Process(claude_pid)
        for _ in range(8):
            p = p.parent()
            if p is None:
                break
            ancestors.append(p.pid)
    except psutil.Error:
        return
    if not ancestors:
        return

    target = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindowText(hwnd) == "":
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid in ancestors and not target:
            target.append(hwnd)

    try:
        win32gui.EnumWindows(cb, None)
        if target:
            hwnd = target[0]
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
    except OSError:
        pass


def chime() -> None:
    try:
        import winsound

        winsound.PlaySound("SystemExclamation",
                           winsound.SND_ALIAS | winsound.SND_ASYNC)
    except (ImportError, RuntimeError):
        pass


def spark_path(cx: float, cy: float, r: float, inner: float = 0.34) -> QPainterPath:
    """Claude's four-lobed spark: rounded rays via a squished-diamond star.

    `inner` sets the ray pinch (0.2 = spiky twinkle, 0.55 = plump bloom);
    animating it morphs the spark like Claude Code's terminal spinner.
    """
    import math

    path = QPainterPath()
    points = 8
    for i in range(points * 2):
        angle = math.pi * i / points
        radius = r if i % 2 == 0 else r * inner
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


class Pill(QWidget):
    def __init__(self, config: dict):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.config = config
        self.status = "done"          # aggregated across sessions
        self.rows = []                # [{status,label,project,since,pid,color}]
        self._spin = 0.0              # spark rotation angle while working
        self._phase = 0.0             # twinkle phase (drives morph/breath/halo)
        self._sweep = 1.0             # color sweep progress on status change
        self._sweep_from = QColor(GREEN)
        self._attention = 0.0         # scale kick when flipping to waiting
        self._drag_offset = None
        self._dragging = False
        self._hidden_by_focus = False
        self._last_pid_check = 0.0
        self._word_index = 0
        self._word_rotated = 0.0
        self._ended_since = None

        self.resize(PILL_W + PAD * 2, ROW_H + PAD * 2)
        self._place()

        self.fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self.fade_anim.setDuration(220)

        self.sweep_anim = QPropertyAnimation(self, b"sweep", self)
        self.sweep_anim.setDuration(420)
        self.sweep_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.attention_anim = QPropertyAnimation(self, b"attention", self)
        self.attention_anim.setDuration(900)
        self.attention_anim.setStartValue(0.0)
        self.attention_anim.setKeyValueAt(0.15, 1.0)
        self.attention_anim.setKeyValueAt(0.3, 0.2)
        self.attention_anim.setKeyValueAt(0.45, 0.9)
        self.attention_anim.setKeyValueAt(0.6, 0.1)
        self.attention_anim.setKeyValueAt(0.75, 0.5)
        self.attention_anim.setEndValue(0.0)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(POLL_MS)

        self.setWindowOpacity(0.0)
        self.show()
        self._fade_to(1.0)

    # --- animated properties -------------------------------------------------

    def get_sweep(self) -> float:
        return self._sweep

    def set_sweep(self, v: float) -> None:
        self._sweep = v
        self.update()

    sweep = Property(float, get_sweep, set_sweep)

    def get_attention(self) -> float:
        return self._attention

    def set_attention(self, v: float) -> None:
        self._attention = v
        self.update()

    attention = Property(float, get_attention, set_attention)

    # --- layout / painting ---------------------------------------------------

    def _place(self) -> None:
        pos = self.config.get("position")
        screen = QApplication.primaryScreen().availableGeometry()
        if isinstance(pos, list) and len(pos) == 2:
            x = max(screen.left(), min(int(pos[0]), screen.right() - self.width()))
            y = max(screen.top(), min(int(pos[1]), screen.bottom() - self.height()))
            self.move(x, y)
        else:
            margin = self.config.get("margin", 16)
            self.move(screen.right() - self.width() - margin, screen.top() + margin)

    def _resize_rows(self, n: int) -> None:
        h = max(1, n) * ROW_H + PAD * 2
        if self.height() != h:
            old_top = self.y()
            self.resize(PILL_W + PAD * 2, h)
            self.move(self.x(), old_top)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(PAD, PAD - 1, -PAD, -PAD - 1)
        radius = min(ROW_H / 2 + 2, rect.height() / 2)

        # Soft shadow: expanding translucent outlines below the capsule.
        painter.setPen(Qt.PenStyle.NoPen)
        for i, alpha in enumerate((26, 16, 8)):
            sp = QPainterPath()
            sr = rect.adjusted(-i, 1 - i, i, 2 + i)
            sp.addRoundedRect(sr, radius + i, radius + i)
            painter.fillPath(sp, QColor(60, 50, 40, alpha))

        # Cream capsule + hairline border
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        painter.fillPath(body, CREAM)
        painter.setPen(QPen(CREAM_BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)

        rows = self.rows or [{
            "status": "done", "label": "Ready", "project": "", "elapsed": "",
            "color": GREEN,
        }]
        for i, row in enumerate(rows):
            top = rect.top() + i * ROW_H
            self._paint_row(painter, QRectF(rect.left(), top, rect.width(), ROW_H), row)
            if i:
                painter.setPen(QPen(QColor(0, 0, 0, 18), 1))
                painter.drawLine(int(rect.left() + 14), int(top),
                                 int(rect.right() - 14), int(top))

    def _paint_row(self, painter: QPainter, r: QRectF, row: dict) -> None:
        import math

        color = QColor(row["color"])
        cx = r.left() + 19
        cy = r.center().y()
        working = row["status"] == "working"

        # Twinkle: while working the spark breathes in size, its rays pinch
        # and bloom, and the whole thing slowly spins — like the terminal
        # spinner. Idle sparks sit still at the resting shape.
        if working:
            breath = 1.0 + 0.10 * math.sin(self._phase * 1.7)
            inner = 0.34 + 0.16 * math.sin(self._phase * 2.6)
            glow = 0.55 + 0.45 * math.sin(self._phase * 2.6)
        else:
            breath, inner, glow = 1.0, 0.34, 0.0
        spark_r = (8.0 + self._attention * 2.5) * breath

        painter.save()
        painter.translate(cx, cy)
        if working:
            painter.rotate(self._spin)
            # soft halo behind the spark, brightening with the twinkle
            halo = QColor(color)
            halo.setAlpha(int(28 + 36 * glow))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            hr = spark_r * 1.65
            painter.drawEllipse(QRectF(-hr, -hr, hr * 2, hr * 2))
        painter.setPen(Qt.PenStyle.NoPen)

        # Color sweep: old color base, new color revealed by a growing clip.
        if self._sweep < 1.0 and row is (self.rows[0] if self.rows else None):
            painter.setBrush(self._sweep_from)
            painter.drawPath(spark_path(0, 0, spark_r, inner))
            clip = QPainterPath()
            clip.addEllipse(QRectF(-spark_r, -spark_r, spark_r * 2, spark_r * 2)
                            .adjusted(0, 0, -(1 - self._sweep) * spark_r * 2, 0))
            painter.setClipPath(clip)
        painter.setBrush(color)
        painter.drawPath(spark_path(0, 0, spark_r, inner))
        painter.restore()

        # Label
        painter.setPen(INK)
        font = QFont("Segoe UI", 9)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        text_rect = r.adjusted(36, 0, -8, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         row["label"])

        # Right-aligned secondary: elapsed time (or project when idle)
        secondary = row.get("elapsed") or row.get("project", "")
        if secondary:
            painter.setPen(INK_SOFT)
            font2 = QFont("Segoe UI", 8)
            painter.setFont(font2)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             secondary)

    # --- input ---------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None:
            new_top_left = event.globalPosition().toPoint() - self._drag_offset
            if (new_top_left - self.frameGeometry().topLeft()).manhattanLength() > 3:
                self._dragging = True
            if self._dragging:
                self.move(new_top_left)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is None:
            return
        if self._dragging:
            save_position(self.pos())
        else:
            row_i = int((event.position().y() - PAD) // ROW_H)
            if 0 <= row_i < len(self.rows):
                pid = self.rows[row_i].get("pid") or 0
                if pid:
                    focus_session_window(pid)
        self._drag_offset = None
        self._dragging = False

    # --- state machine -------------------------------------------------------

    def _tick(self) -> None:
        self._read_status()
        self._update_visibility()
        now = time.time()
        if self.status == "working":
            self._spin = (self._spin + 1.2) % 360  # ~12 deg/s spin at 10Hz
            self._phase += 0.35                    # twinkle tempo
            if now - self._word_rotated > 6:
                self._word_rotated = now
                self._word_index += 1
            self.update()
        elif self.rows:
            # repaint each second so elapsed times stay fresh
            if int(now * 10) % 10 == 0:
                self.update()

    def _read_status(self) -> None:
        sessions = {}
        now = time.time()
        check_pids = now - self._last_pid_check > 5
        if check_pids:
            self._last_pid_check = now
        try:
            names = os.listdir(SESSIONS_DIR)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(SESSIONS_DIR, name)
            try:
                with open(path, encoding="utf-8") as f:
                    s = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if now - s.get("ts", 0) > STALE_AFTER_S:
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            # Drop sessions whose Claude process is gone (killed terminal,
            # crashed, or ended without a SessionEnd hook). Checked at most
            # every few seconds — pid probes are not free at 10Hz.
            pid = s.get("pid") or 0
            if pid and check_pids:
                try:
                    alive = psutil.Process(pid).name().lower().startswith("claude")
                except psutil.Error:
                    alive = False
                if not alive:
                    log(f"drop dead session {name[:12]} (pid {pid} gone)")
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    continue
            if s.get("status") == "working" and now - s.get("ts", 0) > WORKING_SILENT_S:
                s["status"] = "done"
            # Store Python's virtualization can surface duplicate shadow
            # copies of the same file; keep only the newest per session.
            prev = sessions.get(name)
            if prev is None or s.get("ts", 0) > prev.get("ts", 0):
                s["_path"] = path
                sessions[name] = s

        # One Claude process = one live session. Resuming a conversation
        # changes the session id without a SessionEnd for the old id, so
        # when two session files share a pid, only the newest is real.
        by_pid = {}
        for name, s in list(sessions.items()):
            pid = s.get("pid") or 0
            if not pid:
                continue
            other = by_pid.get(pid)
            if other is None:
                by_pid[pid] = name
            else:
                loser = name if s.get("ts", 0) < sessions[other].get("ts", 0) else other
                winner = other if loser == name else name
                by_pid[pid] = winner
                log(f"drop superseded session {loser[:12]} (same pid as {winner[:12]})")
                try:
                    os.remove(sessions[loser]["_path"])
                except OSError:
                    pass
                del sessions[loser]

        # Build display rows, most urgent first.
        urgency = {"waiting": 0, "working": 1, "done": 2}
        ordered = sorted(sessions.values(),
                         key=lambda s: (urgency.get(s.get("status"), 3), -s.get("ts", 0)))
        rows = []
        for s in ordered:
            st = s.get("status", "done")
            if st == "working":
                word = WORKING_WORDS[self._word_index % len(WORKING_WORDS)]
                label = f"{word}…"
            else:
                label = STATUS_LABEL.get(st, st.title())
            since = s.get("since") or s.get("ts", now)
            elapsed = ""
            if st in ("working", "waiting"):
                mins, secs = divmod(int(now - since), 60)
                elapsed = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            rows.append({
                "status": st,
                "label": label,
                "project": os.path.basename(s.get("cwd", "")) or "",
                "elapsed": elapsed,
                "pid": s.get("pid", 0),
                "color": STATUS_COLOR.get(st, GREEN),
            })
        self.rows = rows
        self._resize_rows(len(rows))

        # Aggregate for visibility rules + transitions.
        if not sessions:
            status = "ended"
        elif any(s.get("status") == "waiting" for s in sessions.values()):
            status = "waiting"
        elif any(s.get("status") == "working" for s in sessions.values()):
            status = "working"
        else:
            status = "done"

        if status == self.status:
            return
        old = self.status
        log(f"status: {old} -> {status} ({len(sessions)} session(s))")
        self.status = status

        if status == "ended":
            QTimer.singleShot(ENDED_GRACE_MS, self._quit_if_still_ended)
            return
        if old == "ended":
            pass  # revived before the grace timer fired

        # Color sweep from the old aggregate color to the new one.
        self._sweep_from = QColor(STATUS_COLOR.get(old, GREEN))
        self.sweep_anim.stop()
        self.sweep_anim.setStartValue(0.0)
        self.sweep_anim.setEndValue(1.0)
        self.sweep_anim.start()

        if status == "waiting":
            self.attention_anim.start()
            if self.config.get("sound_on_needs_you", True):
                chime()
        if status == "working" and old != "working":
            self._word_index = int(now) % len(WORKING_WORDS)
            self._word_rotated = now
        self.update()

    def _quit_if_still_ended(self) -> None:
        if self.status == "ended":
            self._fade_to(0.0)
            QTimer.singleShot(self.fade_anim.duration() + 50, QApplication.quit)

    def _update_visibility(self) -> None:
        if self.status == "ended":
            return
        proc = foreground_process_name().lower()
        hide_list = [p.lower() for p in self.config["hide_on_processes"]]
        should_hide = proc in hide_list and self.status != "waiting"
        if should_hide and not self._hidden_by_focus:
            self._hidden_by_focus = True
            log(f"hide (focus: {proc})")
            self._fade_to(0.0)
        elif not should_hide and self._hidden_by_focus:
            self._hidden_by_focus = False
            log(f"show (focus: {proc})")
            self._fade_to(1.0)

    def _fade_to(self, opacity: float) -> None:
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(opacity)
        self.fade_anim.start()


def acquire_singleton() -> bool:
    """Create the named mutex; False if another instance already holds it.

    A named mutex is used instead of a lock file because the hook handler's
    liveness probe (try-delete the lock file) could race a starting instance
    and let two indicators run at once.
    """
    ctypes.windll.kernel32.CreateMutexW(None, False, "claude_indicator_singleton")
    ERROR_ALREADY_EXISTS = 183
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def main() -> int:
    if not acquire_singleton():
        return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pill = Pill(load_config())  # noqa: F841 -- kept alive for app lifetime
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
