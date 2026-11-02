#!/usr/bin/env python3
"""
Modal Notebook  -  desktop GUI for running notebooks on Modal (PySide6)
Run:  start_gui.bat   (or:  python modal_gui.py)
"""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib
import importlib.util
import json
import operator
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from functools import reduce
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QEvent, QObject, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation,
    QLockFile, QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl, QVariantAnimation, Property, Signal,
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QDesktopServices, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QKeySequence,
    QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHeaderView, QMenu, QGraphicsOpacityEffect, QHBoxLayout, QInputDialog,
    QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

# =============================================================================
#  Paths / constants
# =============================================================================
APP_DIR = Path(__file__).resolve().parent
def find_script() -> Path:
    """The launcher script next to this app (modal_jupyter.py, or any file that defines the Modal app)."""
    for name in ("modal_jupyter.py", "jupyter_modal.py"):
        if (APP_DIR / name).exists():
            return APP_DIR / name
    for cand in sorted(APP_DIR.glob("*.py")):
        if cand.name == Path(__file__).name:
            continue
        try:
            t = cand.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "modal.App(" in t and "run_jupyter" in t:
            return cand
    return APP_DIR / "modal_jupyter.py"


SCRIPT = find_script()
APP_NAME = "modal-jupyter"
SETTINGS_ORG = "ModalStudio"
APP_TITLE = "Modal Notebook"
DEFAULT_NOTEBOOK = "lora-trainer-backend-2.ipynb"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
URL_RE = re.compile(r"https://\S+?\?token=[A-Za-z0-9_\-]{16,}")

GPUS = [
    ("T4  ·  16 GB", "T4"),
    ("L4  ·  24 GB", "L4"),
    ("A10G  ·  24 GB", "A10G"),
    ("L40S  ·  48 GB", "L40S"),
    ("A100  ·  40 GB", "A100-40GB"),
    ("A100  ·  80 GB", "A100-80GB"),
    ("H100  ·  80 GB", "H100"),
    ("H200  ·  141 GB", "H200"),
    ("B200  ·  180 GB", "B200"),
    ("No GPU", "__cpu__"),
]
THEMES = [
    ("Dark", "JupyterLab Dark"),
    ("Light", "JupyterLab Light"),
    ("Dark high contrast", "JupyterLab Dark High Contrast"),
    ("JupyterLab default", "__none__"),
]
PY_VERSIONS = ["3.10", "3.11", "3.12"]


def python_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        cand = exe.with_name("python.exe")
        if cand.exists():
            return str(cand)
    return str(exe)


PY = python_exe()

# =============================================================================
#  Colors / fonts / icons
# =============================================================================
BG = "#202020"
PANEL = "#272727"
CARD = "#2f2f2f"
STROKE = "#3a3a3a"
TEXT = "#ffffff"
TEXT2 = "#c9c9c9"
TEXT3 = "#8f8f8f"
ACCENT = "#60cdff"
ACCENT_H = "#7bd7ff"
GREEN = "#6ccb5f"
RED = "#ff6b6b"
YELLOW = "#fce100"
GREY = "#8a8a8a"

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"]


def mix(a, b, t: float) -> QColor:
    a, b = QColor(a), QColor(b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def font(px: int = 14, semi: bool = False, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(UI_FAMILIES)
    f.setPixelSize(px)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    elif semi:
        f.setWeight(QFont.Weight.DemiBold)
    return f


ICON_FONT: str | None = None
ICONS = {
    "home": ("\uE80F", "⌂"), "setup": ("\uE8FD", "☰"), "files": ("\uE8B7", "▤"),
    "settings": ("\uE713", "⚙"), "log": ("\uE756", ">_"), "play": ("\uE768", "▶"),
    "stop": ("\uE71A", "■"), "open": ("\uE8A7", "↗"), "copy": ("\uE8C8", "⧉"),
    "download": ("\uE896", "⇩"), "upload": ("\uE898", "⇧"), "link": ("\uE71B", "↗"), "folder": ("\uE8B7", "▤"),
    "min": ("\uE921", "–"), "max": ("\uE922", "□"), "restore": ("\uE923", "❐"),
    "close": ("\uE8BB", "✕"), "check": ("\uE73E", "✓"), "cloud": ("\uE753", "☁"),
    "notebook": ("\uE7C3", "▭"), "accounts": ("\uE77B", "☺"), "switch": ("\uE8AB", "⇄"), "add": ("\uE710", "+"),
    "chevron": ("\uE70D", "⌄"), "chevup": ("\uE70E", "⌃"), "chevdown": ("\uE70D", "⌄"),
    "trash": ("\uE74D", "✕"), "up": ("\uE74A", "↑"), "secret": ("\uE72E", "⚿"), "refresh": ("\uE72C", "⟳"), "list": ("\uE8FD", "☰"),
}


def init_icons() -> None:
    global ICON_FONT
    fams = set(QFontDatabase.families())
    for name in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if name in fams:
            ICON_FONT = name
            return


def glyph(name: str) -> str:
    g, fb = ICONS[name]
    return g if ICON_FONT else fb


def icon_font(px: int = 16) -> QFont:
    if ICON_FONT:
        f = QFont(ICON_FONT)
        f.setPixelSize(px)
        return f
    return font(px)


def label(text="", px=14, color=TEXT, semi=False, bold=False, wrap=False) -> QLabel:
    lb = QLabel(text)
    lb.setFont(font(px, semi, bold))
    lb.setStyleSheet(f"color:{color};background:transparent;")
    lb.setWordWrap(wrap)
    return lb


# =============================================================================
#  Settings file (modal_jupyter.py) read / write
# =============================================================================
def _rx(key: str):
    return re.compile(
        rf"^({re.escape(key)}[ \t]*=[ \t]*)([^\r\n#]*?)([ \t]*#[^\r\n]*)?(?=\r?$)", re.M)


def _literal(v) -> str:
    if v is None:
        return "None"
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return json.dumps(list(v))
    return repr(v)


WRITE_ERROR_HOOK = None   # set by the main window: shows a message when saving a setting fails
LAST_WRITE_ERROR = ""


def set_write_hook(fn) -> None:
    global WRITE_ERROR_HOOK
    WRITE_ERROR_HOOK = fn


def _read_script():
    """Returns (text, encoding, has_bom, newline) so the file can be written back unchanged."""
    raw = SCRIPT.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    try:
        text, enc = body.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, enc = body.decode("cp1252", errors="replace"), "cp1252"
    nl = "\r\n" if b"\r\n" in raw else "\n"
    return text.replace("\r\n", "\n"), enc, bom, nl


def read_setting(key: str, default=None):
    try:
        text = _read_script()[0]
        m = _rx(key).search(text)
        if not m:
            return default
        return ast.literal_eval(m.group(2).strip())
    except Exception:  # noqa: BLE001
        return default


def _write_failed(msg: str) -> bool:
    global LAST_WRITE_ERROR
    LAST_WRITE_ERROR = msg
    if WRITE_ERROR_HOOK is not None:
        WRITE_ERROR_HOOK(msg)
    return False


def write_setting(key: str, value) -> bool:
    try:
        text, enc, bom, nl = _read_script()
    except FileNotFoundError:
        return _write_failed(f"{SCRIPT.name} was not found next to this app")
    except Exception as exc:  # noqa: BLE001
        return _write_failed(f"Could not read {SCRIPT.name}: {exc}")
    rx = _rx(key)
    if not rx.search(text):
        return _write_failed(f"Could not find {key} in {SCRIPT.name}")
    try:
        new = rx.sub(lambda m: m.group(1) + _literal(value) + (m.group(3) or ""), text, count=1)
        data = new.replace("\n", nl).encode(enc, errors="replace")
        if bom:
            data = b"\xef\xbb\xbf" + data
        tmp = SCRIPT.with_name(SCRIPT.name + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, SCRIPT)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            SCRIPT.write_bytes(data)
        return True
    except Exception as exc:  # noqa: BLE001
        return _write_failed(f"Could not save {SCRIPT.name}: {exc}")


_MODAL_OK = False


def modal_installed() -> bool:
    global _MODAL_OK
    if _MODAL_OK:
        return True
    importlib.invalidate_caches()
    _MODAL_OK = importlib.util.find_spec("modal") is not None
    return _MODAL_OK


def modal_logged_in() -> bool:
    if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET"):
        return True
    try:
        p = Path.home() / ".modal.toml"
        return p.exists() and "token_id" in p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def fmt_idle(v: int) -> str:
    if v <= 0:
        return "Never"
    if v < 60:
        return f"{v} min"
    h, m = divmod(v, 60)
    return f"{h} h" if m == 0 else f"{h} h {m} min"


def _pe(profile):
    """Environment that pins a command to one Modal account (without switching the active one)."""
    return {"MODAL_PROFILE": profile} if profile else None


def fmt_time(secs: float) -> str:
    secs = int(max(0, secs))
    return f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


# =============================================================================
#  Background process (no console window, live output)
# =============================================================================
class Proc(QObject):
    line = Signal(str)
    done = Signal(int)
    _raw_line = Signal(str)
    _raw_done = Signal(int)

    def __init__(self, parent=None, log=None):
        super().__init__(parent)
        self._p = None
        self._cb = None
        self._gen = 0
        self._raw_line.connect(self._emit_line)
        self._raw_done.connect(self._emit_done)
        if log is not None:
            self.line.connect(log)

    def running(self) -> bool:
        return self._p is not None and self._p.poll() is None

    def start(self, args, show=None, on_done=None, env=None) -> bool:
        if self.running():
            return False
        self._cb = on_done
        full_env = os.environ.copy()
        full_env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", NO_COLOR="1", TERM="dumb")
        if env:
            full_env.update(env)
        self.line.emit("› " + (show or "python " + " ".join(args)))
        try:
            self._p = subprocess.Popen(
                [PY] + list(args), cwd=str(APP_DIR), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=full_env,
                creationflags=NO_WINDOW)
        except Exception as exc:  # noqa: BLE001
            self.line.emit(f"Could not start the command: {exc}")
            self._p = None
            if on_done:
                on_done(-1)
            return False
        self._gen += 1
        threading.Thread(target=self._pump, args=(self._p, self._gen), daemon=True).start()
        return True

    def _pump(self, p, gen) -> None:
        buf = ""
        fd = p.stdout.fileno()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("utf-8", "replace")
            parts = re.split(r"\r\n|\r|\n", buf)
            buf = parts.pop()
            for part in parts:
                part = ANSI_RE.sub("", part).rstrip()
                if part and gen == self._gen:
                    self._raw_line.emit(part)
        tail = ANSI_RE.sub("", buf).strip()
        if tail and gen == self._gen:
            self._raw_line.emit(tail)
        code = p.wait()
        if gen == self._gen:
            self._raw_done.emit(code)

    def _emit_line(self, text: str) -> None:
        self.line.emit(text)

    def _emit_done(self, code: int) -> None:
        self.done.emit(code)
        cb, self._cb = self._cb, None
        if cb:
            cb(code)

    def kill(self) -> None:
        p = self._p
        if p is None or p.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                               creationflags=NO_WINDOW, capture_output=True, timeout=10)
            else:
                p.kill()
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass


# =============================================================================
#  Animated widgets
# =============================================================================
class Btn(QPushButton):
    KINDS = {
        "primary": dict(bg="#60cdff", hv="#7bd7ff", fg="#000000"),
        "default": dict(bg="#3a3a3a", hv="#454545", fg="#ffffff"),
        "danger": dict(bg="#c42b1c", hv="#d9473a", fg="#ffffff"),
        "ghost": dict(bg="#00ffffff", hv="#18ffffff", fg="#ffffff"),
        "warn": dict(bg="#8a6a00", hv="#a07c00", fg="#ffffff"),
    }

    def __init__(self, text="", kind="default", icon=None, h=36, parent=None):
        super().__init__(text, parent)
        self.kind = kind
        self.icon_name = icon
        self._h = 0.0
        self._busy = False
        self._bt = 0.0
        self._plain_text = None
        self.setFont(font(14, semi=True) if kind == "primary" else font(14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedHeight(h)
        self._anim = QPropertyAnimation(self, b"hover", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._banim = QVariantAnimation(self)
        self._banim.setStartValue(0.0)
        self._banim.setEndValue(1.0)
        self._banim.setDuration(1300)
        self._banim.setLoopCount(-1)
        self._banim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._banim.valueChanged.connect(self._busy_tick)

    def _busy_tick(self, v):
        self._bt = float(v)
        self.update()

    def set_busy(self, on: bool, text=None):
        """Shows a moving light across the button (a loading bar) and an optional temporary text."""
        if on == self._busy:
            if on and text and self.text() != text:
                self.setText(text)
            return
        self._busy = on
        if on:
            self._plain_text = self.text()
            if text:
                self.setText(text)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._banim.start()
        else:
            self._banim.stop()
            if self._plain_text is not None:
                self.setText(self._plain_text)
                self._plain_text = None
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update()

    def _get_h(self):
        return self._h

    def _set_h(self, v):
        self._h = v
        self.update()

    hover = Property(float, _get_h, _set_h)

    def _to(self, v: float):
        self._anim.stop()
        self._anim.setStartValue(self._h)
        self._anim.setEndValue(v)
        self._anim.start()

    def enterEvent(self, e):
        self._to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._to(0.0)
        super().leaveEvent(e)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        w = fm.horizontalAdvance(self.text()) + 40
        if self.icon_name:
            w += QFontMetrics(icon_font(15)).horizontalAdvance(glyph(self.icon_name)) + 8
        return QSize(max(w, 40), self.height())

    def paintEvent(self, _):
        k = self.KINDS[self.kind]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        live = self.isEnabled() or self._busy
        if live:
            bg = mix(k["bg"], k["hv"], self._h)
            if self._busy:
                bg = bg.darker(122)
            elif self.isDown():
                bg = QColor("#2affffff") if self.kind == "ghost" else bg.darker(112)
            fg = QColor(k["fg"])
        else:
            bg = QColor("#00ffffff") if self.kind == "ghost" else QColor("#2b2b2b")
            fg = QColor("#6e6e6e")
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor("#22ffffff"), 1) if self.kind == "default" and live
                 else Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 6, 6)
        if self._busy:
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            p.save()
            p.setClipPath(path)
            band = max(70.0, r.width() * 0.35)
            x = (r.width() + band) * self._bt - band
            grad = QLinearGradient(x, 0, x + band, 0)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 95))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRect(QRectF(x, 0, band, r.height()))
            p.restore()

        text = self.text()
        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(text)
        ic = glyph(self.icon_name) if self.icon_name else ""
        ifont = icon_font(15)
        iw = QFontMetrics(ifont).horizontalAdvance(ic) if ic else 0
        gap = 8 if (ic and text) else 0
        x = (self.width() - (iw + gap + tw)) / 2
        p.setPen(fg)
        al = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if ic:
            p.setFont(ifont)
            p.drawText(QRectF(x, 0, iw + 2, self.height()), al, ic)
            x += iw + gap
        p.setFont(self.font())
        p.drawText(QRectF(x, 0, tw + 4, self.height()), al, text)


class NavButton(QPushButton):
    def __init__(self, text, icon, parent=None):
        super().__init__(text, parent)
        self.icon_name = icon
        self._h = 0.0
        self._s = 0.0
        self._compact = False
        self.setFont(font(14))
        self.setFixedHeight(42)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._ah = QPropertyAnimation(self, b"hover", self)
        self._ah.setDuration(140)
        self._as = QPropertyAnimation(self, b"sel", self)
        self._as.setDuration(260)
        self._as.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_h(self):
        return self._h

    def _set_h(self, v):
        self._h = v
        self.update()

    def _get_s(self):
        return self._s

    def _set_s(self, v):
        self._s = v
        self.update()

    hover = Property(float, _get_h, _set_h)
    sel = Property(float, _get_s, _set_s)

    def set_compact(self, on: bool):
        self._compact = on
        self.setToolTip(self.text() if on else "")
        self.update()

    def set_selected(self, on: bool, animate=True):
        self._as.stop()
        if animate:
            self._as.setStartValue(self._s)
            self._as.setEndValue(1.0 if on else 0.0)
            self._as.start()
        else:
            self._set_s(1.0 if on else 0.0)

    def enterEvent(self, e):
        self._ah.stop()
        self._ah.setStartValue(self._h)
        self._ah.setEndValue(1.0)
        self._ah.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._ah.stop()
        self._ah.setStartValue(self._h)
        self._ah.setEndValue(0.0)
        self._ah.start()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        a = int(14 * self._h + 20 * self._s)
        if self.isDown():
            a += 8
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, a))
        p.drawRoundedRect(r, 6, 6)
        ih = 16 * self._s
        if ih > 0.5:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(r.left() + 1, r.center().y() - ih / 2, 3, ih), 1.5, 1.5)
        col = mix(TEXT2, TEXT, self._s)
        p.setPen(col)
        p.setFont(icon_font(16))
        al = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if self._compact:
            p.drawText(QRectF(r), Qt.AlignmentFlag.AlignCenter, glyph(self.icon_name))
            return
        p.drawText(QRectF(r.left() + 16, 0, 26, self.height()), al, glyph(self.icon_name))
        p.setFont(self.font())
        p.drawText(QRectF(r.left() + 48, 0, r.width() - 48, self.height()), al, self.text())


class CapBtn(QPushButton):
    def __init__(self, icon, danger=False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.danger = danger
        self._h = 0.0
        self.setFixedSize(46, 40)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._a = QPropertyAnimation(self, b"hover", self)
        self._a.setDuration(120)

    def _get_h(self):
        return self._h

    def _set_h(self, v):
        self._h = v
        self.update()

    hover = Property(float, _get_h, _set_h)

    def set_icon(self, name):
        self.icon_name = name
        self.update()

    def _to(self, v):
        self._a.stop()
        self._a.setStartValue(self._h)
        self._a.setEndValue(v)
        self._a.start()

    def enterEvent(self, e):
        self._to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._to(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor("#c42b1c") if self.danger else QColor(255, 255, 255, 26)
        col.setAlpha(int(col.alpha() * self._h))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(3, 5, -3, -5), 6, 6)
        p.setPen(QColor(TEXT))
        p.setFont(icon_font(10))
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, glyph(self.icon_name))


class Toggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on = checked
        self._t = 1.0 if checked else 0.0
        self._h = 0.0
        self._at = QPropertyAnimation(self, b"tpos", self)
        self._at.setDuration(200)
        self._at.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._ah = QPropertyAnimation(self, b"hov", self)
        self._ah.setDuration(130)

    def _get_t(self):
        return self._t

    def _set_t(self, v):
        self._t = v
        self.update()

    def _get_h(self):
        return self._h

    def _set_h(self, v):
        self._h = v
        self.update()

    tpos = Property(float, _get_t, _set_t)
    hov = Property(float, _get_h, _set_h)

    def isChecked(self):
        return self._on

    def setChecked(self, on: bool, animate=False):
        self._on = on
        self._at.stop()
        if animate:
            self._at.setStartValue(self._t)
            self._at.setEndValue(1.0 if on else 0.0)
            self._at.start()
        else:
            self._set_t(1.0 if on else 0.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._on, animate=True)
            self.toggled.emit(self._on)

    def _hov_to(self, v):
        self._ah.stop()
        self._ah.setStartValue(self._h)
        self._ah.setEndValue(v)
        self._ah.start()

    def enterEvent(self, e):
        self._hov_to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hov_to(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        fill = mix("#10ffffff", ACCENT, self._t)
        border = mix("#9a9a9a", ACCENT, self._t)
        p.setPen(QPen(border, 1.2))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), (h - 2) / 2, (h - 2) / 2)
        d = 12 + 2 * self._h
        cx = 13 + (w - 26) * self._t
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix("#d0d0d0", "#000000", self._t))
        p.drawEllipse(QRectF(cx - d / 2, h / 2 - d / 2, d, d))


class Stepper(QWidget):
    changed = Signal(int)

    def __init__(self, lo, hi, step=1, value=0, fmt=None, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self.step = lo, hi, step
        self._v = value
        self._fmt = fmt or (lambda v: str(v))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.b_minus = Btn("−", "default", h=34)
        self.b_plus = Btn("+", "default", h=34)
        for b in (self.b_minus, self.b_plus):
            b.setFixedWidth(34)
        self.lbl = QLabel()
        self.lbl.setFont(font(14, semi=True))
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl.setFixedSize(96, 34)
        self.lbl.setStyleSheet("background:#2a2a2a;border-radius:6px;color:white;")
        lay.addWidget(self.b_minus)
        lay.addWidget(self.lbl)
        lay.addWidget(self.b_plus)
        self.b_minus.clicked.connect(lambda: self._bump(-self.step))
        self.b_plus.clicked.connect(lambda: self._bump(self.step))
        self._show()

    def _show(self):
        self.lbl.setText(self._fmt(self._v))

    def _bump(self, d):
        v = max(self.lo, min(self.hi, self._v + d))
        if v != self._v:
            self._v = v
            self._show()
            self.changed.emit(v)

    def value(self):
        return self._v

    def setValue(self, v):
        self._v = max(self.lo, min(self.hi, v))
        self._show()


class Combo(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(font(14))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(36)
        self.setMinimumWidth(260)
        self.setMaxVisibleItems(12)
        self.view().setFont(font(14))
        try:
            w = self.view().window()
            w.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                             | Qt.WindowType.NoDropShadowWindowHint)
            w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        except Exception:  # noqa: BLE001
            pass

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(TEXT2), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                      Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() - 20, self.height() / 2
        p.drawPolyline([QPoint(int(cx - 4), int(cy - 2)), QPoint(int(cx), int(cy + 2)),
                        QPoint(int(cx + 4), int(cy - 2))])


class Dot(QWidget):
    def __init__(self, size=18, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._c = QColor(GREY)
        self._p = 0.0
        self._pulse = False
        self._ac = QPropertyAnimation(self, b"color", self)
        self._ac.setDuration(350)
        self._ap = QVariantAnimation(self)
        self._ap.setStartValue(0.0)
        self._ap.setEndValue(1.0)
        self._ap.setDuration(1500)
        self._ap.setLoopCount(-1)
        self._ap.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._ap.valueChanged.connect(self._tick)

    def _tick(self, v):
        self._p = float(v)
        self.update()

    def _get_c(self):
        return self._c

    def _set_c(self, c):
        self._c = QColor(c)
        self.update()

    color = Property(QColor, _get_c, _set_c)

    def set_state(self, color, pulse):
        self._ac.stop()
        self._ac.setStartValue(self._c)
        self._ac.setEndValue(QColor(color))
        self._ac.start()
        self._pulse = pulse
        if pulse:
            if self._ap.state() != QVariantAnimation.State.Running:
                self._ap.start()
        else:
            self._ap.stop()
            self._p = 0.0
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        core = self.width() * 0.28
        if self._pulse:
            halo = QColor(self._c)
            halo.setAlpha(int(120 * (1 - self._p)))
            rad = core + (self.width() / 2 - core) * self._p
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(halo)
            p.drawEllipse(c, rad, rad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c)
        p.drawEllipse(c, core, core)


class Collapsible(QWidget):
    """Slides open/closed. `inner` must have a fixed height."""

    def __init__(self, inner: QWidget, height: int, parent=None):
        super().__init__(parent)
        self._full = height
        self._open = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner, 0, Qt.AlignmentFlag.AlignTop)
        inner.setFixedHeight(height)
        self.setMaximumHeight(0)
        self._a = QPropertyAnimation(self, b"maximumHeight", self)
        self._a.setDuration(380)
        self._a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._a.finished.connect(self._after)
        self.hide()

    def _after(self):
        if not self._open:
            self.hide()

    def set_open(self, on: bool):
        if on == self._open:
            return
        self._open = on
        self._a.stop()
        self._a.setStartValue(self.maximumHeight() if self.isVisible() else 0)
        self._a.setEndValue(self._full if on else 0)
        if on:
            self.show()
        self._a.start()


class ElidedLabel(QLabel):
    def __init__(self, text="", px=13, color=TEXT2, parent=None):
        super().__init__(parent)
        self._full = text
        self._color = QColor(color)
        self._align = Qt.AlignmentFlag.AlignLeft
        self.setFont(font(px))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)

    def setFull(self, text: str):
        self._full = text
        self.setToolTip(text)
        self.update()

    def sizeHint(self):
        return QSize(200, self.fontMetrics().height() + 4)

    def minimumSizeHint(self):
        return QSize(10, self.fontMetrics().height() + 4)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(self._color)
        p.setFont(self.font())
        txt = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | self._align, txt)


class Badge(QWidget):
    def __init__(self, n: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self._n = n
        self._ok = False
        self._t = 0.0
        self._a = QPropertyAnimation(self, b"prog", self)
        self._a.setDuration(420)
        self._a.setEasingCurve(QEasingCurve.Type.OutBack)

    def _get_t(self):
        return self._t

    def _set_t(self, v):
        self._t = v
        self.update()

    prog = Property(float, _get_t, _set_t)

    def set_ok(self, ok: bool):
        if ok == self._ok:
            return
        self._ok = ok
        self._a.stop()
        self._a.setStartValue(self._t)
        self._a.setEndValue(1.0 if ok else 0.0)
        self._a.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = max(0.0, min(1.0, self._t))
        p.setPen(QPen(mix("#6a6a6a", GREEN, t), 1.5))
        p.setBrush(mix("#00000000", GREEN, t))
        p.drawEllipse(QRectF(2, 2, self.width() - 4, self.height() - 4))
        p.setPen(QColor("#000000") if self._ok else QColor(TEXT))
        if self._ok:
            p.setFont(icon_font(14))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, glyph("check"))
        else:
            p.setFont(font(14, semi=True))
            p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, str(self._n))


class Toast(QWidget):
    COLORS = {"info": ACCENT, "success": GREEN, "error": RED}

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._kind = "info"
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        self.a_op = QPropertyAnimation(self.eff, b"opacity", self)
        self.a_pos = QPropertyAnimation(self, b"pos", self)
        self.a_op.finished.connect(self._after)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind="info"):
        self._text, self._kind = text, kind
        par = self.parentWidget()
        fm = QFontMetrics(font(14))
        w = min(fm.horizontalAdvance(text) + 64, max(240, par.width() - 120))
        self.setFixedSize(w, 46)
        x = (par.width() - w) // 2
        y = par.height() - 14 - self.height() - 26
        self.show()
        self.raise_()
        self.update()
        for a in (self.a_op, self.a_pos):
            a.stop()
            a.setDuration(260)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.a_op.setStartValue(self.eff.opacity())
        self.a_op.setEndValue(1.0)
        self.a_pos.setStartValue(QPoint(x, y + 18))
        self.a_pos.setEndValue(QPoint(x, y))
        self.a_op.start()
        self.a_pos.start()
        self.timer.start(2800)

    def _fade_out(self):
        self.a_op.stop()
        self.a_op.setDuration(420)
        self.a_op.setStartValue(self.eff.opacity())
        self.a_op.setEndValue(0.0)
        self.a_op.start()

    def _after(self):
        if self.eff.opacity() < 0.02:
            self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor("#505050"), 1))
        p.setBrush(QColor("#2e2e2e"))
        p.drawRoundedRect(r, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.COLORS.get(self._kind, ACCENT)))
        p.drawRoundedRect(QRectF(14, r.center().y() - 8, 4, 16), 2, 2)
        p.setPen(QColor(TEXT))
        p.setFont(font(14))
        p.drawText(QRectF(30, 0, self.width() - 40, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)


class FadeStack(QStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._keep = []

    def slide_to(self, index: int):
        if index == self.currentIndex():
            return
        new = self.widget(index)
        self.setCurrentIndex(index)
        eff = QGraphicsOpacityEffect(new)
        eff.setOpacity(0.0)
        new.setGraphicsEffect(eff)
        a1 = QPropertyAnimation(eff, b"opacity", new)
        a1.setDuration(260)
        a1.setStartValue(0.0)
        a1.setEndValue(1.0)
        a1.setEasingCurve(QEasingCurve.Type.OutCubic)
        a2 = QPropertyAnimation(new, b"pos", new)
        a2.setDuration(320)
        a2.setStartValue(QPoint(0, 22))
        a2.setEndValue(QPoint(0, 0))
        a2.setEasingCurve(QEasingCurve.Type.OutCubic)
        grp = QParallelAnimationGroup(new)
        grp.addAnimation(a1)
        grp.addAnimation(a2)

        def fin():
            new.setGraphicsEffect(None)

        grp.finished.connect(fin)
        self._keep = [grp]
        grp.start()


# =============================================================================
#  Layout helpers
# =============================================================================
class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps to the next line when there is no room."""

    def __init__(self, parent=None, hspacing=10, vspacing=8):
        super().__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        try:
            return Qt.Orientation(0)
        except Exception:  # noqa: BLE001
            try:
                return Qt.Orientation.Horizontal & Qt.Orientation.Vertical
            except Exception:  # noqa: BLE001
                return super().expandingDirections()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            if it.isEmpty():
                continue
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, test_only):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            hint = it.sizeHint()
            nxt = x + hint.width()
            if nxt > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y += line_h + self._v
                nxt = x + hint.width()
                line_h = 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nxt + self._h
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class Card(QFrame):
    def __init__(self, pad=(18, 16, 18, 16), spacing=10, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(*pad)
        self.v.setSpacing(spacing)


def divider() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet("background:rgba(255,255,255,18);border:none;")
    return f


class Row(QWidget):
    def __init__(self, title, desc, control, parent=None, tip=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 12, 18, 12)
        h.setSpacing(16)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = label(title, 14)
        col.addWidget(t)
        if desc:
            col.addWidget(label(desc, 12, TEXT3, wrap=True))
        if tip:
            for w in (t, control):
                w.setToolTip(tip)
        h.addLayout(col, 1)
        h.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)


class Field(QWidget):
    """A control with a small caption above it."""

    def __init__(self, caption: str, control, tip=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        cap = label(caption, 12, TEXT3)
        v.addWidget(cap)
        v.addWidget(control)
        if tip:
            cap.setToolTip(tip)
            control.setToolTip(tip)


def toggle_group(toggle, text: str, tip: str = "") -> QWidget:
    w = QWidget()
    g = QHBoxLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setSpacing(8)
    g.addWidget(toggle)
    g.addWidget(label(text, 13))
    if tip:
        w.setToolTip(tip)
    return w


class Page(QScrollArea):
    def __init__(self, title: str, subtitle: str, stretch=True):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("pagebody")
        body.setStyleSheet("#pagebody{background:transparent;}")
        self.setWidget(body)
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(36, 30, 36, 30)
        self.v.setSpacing(14)
        if title:
            self.v.addWidget(label(title, 28, semi=True))
            if subtitle:
                self.v.addWidget(label(subtitle, 14, TEXT2, wrap=True))
            self.v.addSpacing(8)
        self._stretch = stretch

    def finish(self):
        if self._stretch:
            self.v.addStretch(1)

    def on_show(self):
        pass


# =============================================================================
#  Pages
# =============================================================================
# =============================================================================
#  Session guard: never leave a session running by accident
# =============================================================================
APP_ID_RE = re.compile(r"\bap-[A-Za-z0-9]{8,}\b")


def running_app_ids(lines) -> list:
    """Ids of our session apps that are still running (from `modal app list --json`)."""
    data = _parse_json(lines)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    name = str(read_setting("APP_NAME", APP_NAME)).lower()
    stem = SCRIPT.stem.lower()
    ids = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        vals = [str(v) for v in item.values()]
        text = " ".join(vals).lower()
        if name not in text and stem not in text:
            continue
        state = next((str(v).lower() for k, v in item.items() if "state" in str(k).lower()), "")
        if (state and "stop" in state) or (not state and "stopped" in text):
            continue
        app_id = next((v for v in vals if APP_ID_RE.fullmatch(v)), None)
        if app_id:
            ids.append(app_id)
    return ids


def running_app_ids_table(lines) -> list:
    """Same as above for older Modal versions that print only a table."""
    name = str(read_setting("APP_NAME", APP_NAME)).lower()
    stem = SCRIPT.stem.lower()
    ids = []
    for line in lines:
        low = line.lower()
        if line.startswith("›") or (name not in low and stem not in low) or "stopped" in low or "stopping" in low:
            continue
        m = APP_ID_RE.search(line)
        if m:
            ids.append(m.group(0))
    return ids


class SessionGuard(QObject):
    """Finds and stops sessions on the active Modal account, so nothing keeps using credit."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._stopper = None
        self._finder = None

    def find(self, on_done, as_json=True, profile=None):
        """on_done(list_of_ids) or on_done(None) when Modal could not be asked."""
        out = []
        p = Proc(self)
        p.line.connect(out.append)
        self._finder = p

        def fin(code):
            if code != 0 and as_json:
                self.find(on_done, as_json=False, profile=profile)
                return
            if code != 0:
                on_done(None)
                return
            if as_json and _parse_json(out) is not None:
                on_done(running_app_ids(out))
            else:
                on_done(running_app_ids_table(out))

        p.start(["-m", "modal", "app", "list"] + (["--json"] if as_json else []), on_done=fin, env=_pe(profile))

    def stop_ids(self, ids, on_done, profile=None):
        """Stops each app. Newer Modal asks "are you sure?" and, with no keyboard attached, would
        abort, so --yes is passed (older versions do not have that option and do not ask)."""
        queue = list(dict.fromkeys(ids))
        bad = [0]

        def run(app_id, with_yes):
            out = []
            p = Proc(self, log=self.win.log)
            p.line.connect(out.append)
            self._stopper = p

            def fin(code):
                if code != 0 and with_yes and "No such option" in "\n".join(out):
                    run(app_id, False)
                    return
                if code != 0:
                    bad[0] += 1
                step()

            p.start(["-m", "modal", "app", "stop", app_id] + (["--yes"] if with_yes else []), on_done=fin,
                    env=_pe(profile))

        def step():
            if not queue:
                on_done(bad[0] == 0)
                return
            run(queue.pop(0), True)

        step()

    def ensure_clean(self, on_done, known_id=None, max_wait=60, profile=None):
        """Stops the session and keeps checking until Modal no longer lists it as running.
        A session that was killed while it was still starting may only show up a few seconds
        later, so it takes several empty checks in a row before this reports success."""
        deadline = time.time() + max_wait
        need = 1 if known_id else 3
        st = {"clean": 0, "first": True}

        def schedule():
            if time.time() > deadline:
                on_done(False)
            else:
                QTimer.singleShot(4000, loop)

        def loop():
            first_ids = [known_id] if (known_id and st["first"]) else []
            st["first"] = False

            def got(ids):
                if ids is None:                       # Modal could not be asked: still try the id we know
                    if first_ids:
                        self.stop_ids(first_ids, lambda ok: schedule(), profile=profile)
                    else:
                        schedule()
                    return
                todo = list(dict.fromkeys(first_ids + ids))
                if todo:
                    st["clean"] = 0
                    self.stop_ids(todo, lambda ok: schedule(), profile=profile)
                    return
                st["clean"] += 1
                if st["clean"] >= need:
                    on_done(True)
                else:
                    schedule()

            self.find(got, profile=profile)

        loop()


STATE_INFO = {
    "idle": ("Ready", GREY, False, "Press Start to launch JupyterLab on a Modal GPU."),
    "starting": ("Starting…", ACCENT, True,
                 "Building the environment and getting a GPU. The first start takes a few minutes."),
    "running": ("Running", GREEN, True, "JupyterLab is live. Keep this app open while you work."),
    "stopping": ("Stopping…", YELLOW, True, "Shutting the session down so billing stops."),
    "error": ("Stopped with an error", RED, False, "Open the log panel below to see what happened."),
}


class HomePage(Page):
    def __init__(self, win):
        super().__init__("", "")
        self.v.setContentsMargins(28, 22, 28, 22)
        self.v.setSpacing(12)
        self.win = win
        self.qs = QSettings(SETTINGS_ORG, "App")
        self.state = "idle"
        self.url = None
        self.t0 = 0.0
        self._profile = None
        self._stopping = False
        self._quit_after = False
        self._collect = ""
        self.app_id = None
        self._launched_at = None
        self._attempt = 0
        self.proc = Proc(self, log=win.log)
        self.proc.line.connect(self._on_line)
        self.proc.done.connect(self._on_done)

        # ---- session card: Start / Stop on top (Start also shows the loading bar), then status and link
        sc = Card(pad=(18, 14, 18, 14), spacing=8)
        act = QHBoxLayout()
        act.setSpacing(10)
        self.btn_start = Btn("Start session", "primary", "play", h=46)
        self.btn_stop = Btn("Stop", "danger", "stop", h=46)
        self.btn_stop.setMinimumWidth(120)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(lambda: self.stop())
        act.addWidget(self.btn_start, 1)
        act.addWidget(self.btn_stop)
        sc.v.addLayout(act)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.dot = Dot(16)
        self.status = label("Ready", 16, semi=True)
        self.elapsed = label("", 13, TEXT2)
        top.addWidget(self.dot)
        top.addWidget(self.status)
        top.addStretch(1)
        top.addWidget(self.elapsed)
        sc.v.addLayout(top)
        self.sub = ElidedLabel("", 13, TEXT2)
        sc.v.addWidget(self.sub)

        inner = QWidget()          # slides open under the buttons when JupyterLab is ready
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 6, 0, 0)
        iv.setSpacing(6)
        iv.addWidget(divider())
        row = QHBoxLayout()
        row.setSpacing(8)
        ok = QLabel(glyph("check"))
        ok.setFont(icon_font(16))
        ok.setStyleSheet(f"color:{GREEN};background:transparent;")
        row.addWidget(ok)
        row.addWidget(label("JupyterLab is ready", 15, semi=True))
        row.addStretch(1)
        self.b_open = Btn("Open JupyterLab", "primary", "open", h=34)
        self.b_copy = Btn("Copy link", "default", "copy", h=34)
        self.b_open.clicked.connect(self.open_url)
        self.b_copy.clicked.connect(self.copy_url)
        row.addWidget(self.b_open)
        row.addWidget(self.b_copy)
        iv.addLayout(row)
        self.url_lbl = ElidedLabel("", 12, TEXT2)
        iv.addWidget(self.url_lbl)
        self.link = Collapsible(inner, 84)
        sc.v.addWidget(self.link)
        self.v.addWidget(sc)

        # ---- settings for the next session: compact fields that wrap on narrow windows
        self.gpu = Combo()
        self.gpu.setMinimumWidth(220)
        cur = read_setting("GPU", "L40S")
        key = "__cpu__" if cur is None else cur
        for text, val in GPUS:
            self.gpu.addItem(text, val)
        idx = self.gpu.findData(key) if isinstance(key, str) else -1
        if idx < 0:
            self.gpu.addItem(f"Custom: {cur}", "__custom__")
            idx = self.gpu.count() - 1
        self.gpu.setCurrentIndex(idx)
        self.gpu.currentIndexChanged.connect(self._gpu_changed)

        m0 = read_setting("IDLE_MINUTES", 30)
        try:
            m0 = 30 if m0 is None else max(0, min(720, int(m0)))
        except (TypeError, ValueError):
            m0 = 30
        self.idle = Stepper(0, 720, 15, m0, fmt_idle)
        self.idle.changed.connect(self._idle_changed)

        cpu0 = read_setting("CPU_CORES", None) or 0
        self.cpu = Stepper(0, 64, 1, int(cpu0), lambda v: "Auto" if v == 0 else f"{v} cores")
        self.cpu.changed.connect(lambda v: write_setting("CPU_CORES", None if v == 0 else v))
        mem0 = read_setting("MEMORY_MB", None) or 0
        self.mem = Stepper(0, 512, 8, int(mem0) // 1024, lambda v: "Auto" if v == 0 else f"{v} GB")
        self.mem.changed.connect(lambda v: write_setting("MEMORY_MB", None if v == 0 else v * 1024))

        self.reset = Toggle(False)
        self.auto = Toggle(self.qs.value("auto_open", True, type=bool))
        self.auto.toggled.connect(lambda on: self.qs.setValue("auto_open", on))

        oc = Card(pad=(18, 14, 18, 14), spacing=12)
        fields = FlowLayout(hspacing=18, vspacing=12)
        fields.addWidget(Field("GPU", self.gpu,
                               "The graphics card your session runs on. The number is its memory in GB: "
                               "more memory fits bigger models, but costs more per hour."))
        fields.addWidget(Field("CPU cores", self.cpu, "Processor cores for the session. Auto = Modal's default."))
        fields.addWidget(Field("Memory (RAM)", self.mem, "Working memory of the computer. Auto = Modal's default."))
        fields.addWidget(Field("Stop when idle", self.idle,
                               "The session ends by itself after this long with no activity (no code running, "
                               "nothing typed), so a forgotten session cannot keep costing you. Never = it runs "
                               "until you stop it (Modal ends any session after 24 hours)."))
        oc.v.addLayout(fields)
        oc.v.addWidget(divider())
        toggles = FlowLayout(hspacing=24, vspacing=8)
        toggles.addWidget(toggle_group(self.auto, "Open browser when ready",
                                       "Opens JupyterLab in your web browser as soon as the session is ready."))
        toggles.addWidget(toggle_group(self.reset, "Reset default notebook",
                                       "For the next start only: your default notebook from the _notebook folder "
                                       "replaces the one on Modal."))
        oc.v.addLayout(toggles)
        self.v.addWidget(oc)

        # ---- account and usage
        self.v.addWidget(UsageCard(win, billing_btn=True))

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.set_state("idle")
        self.finish()

    # ---- helpers
    def _summary(self) -> str:
        gpu = "No GPU" if self.gpu.currentData() == "__cpu__" else self.gpu.currentText().split("  ")[0]
        m = self.idle.value()
        stop = "runs until you stop it" if m == 0 else f"stops after {fmt_idle(m)} idle"
        return f"{gpu} · {stop}. Press Start to launch JupyterLab."

    def _refresh_idle(self):
        if self.state == "idle":
            self.sub.setFull(self._summary())

    def _idle_changed(self, v):
        write_setting("IDLE_MINUTES", v)
        self._refresh_idle()

    def _gpu_changed(self, _):
        v = self.gpu.currentData()
        if v == "__custom__":
            return
        ok = write_setting("GPU", None if v == "__cpu__" else v)
        self._refresh_idle()
        if ok:
            self.win.toast(f"GPU set to {self.gpu.currentText().split('  ')[0]}", "success")

    def set_state(self, st: str):
        self.state = st
        title, color, pulse, sub = STATE_INFO[st]
        self.dot.set_state(color, pulse)
        self.status.setText(title)
        self.sub.setFull(self._summary() if st == "idle" else sub)
        self.btn_start.set_busy(st == "starting", "Starting…")
        self.btn_stop.set_busy(st == "stopping", "Stopping…")
        self.btn_start.setEnabled(st in ("idle", "error"))
        self.btn_stop.setEnabled(st in ("starting", "running"))
        self.link.set_open(st == "running")
        if st == "running":
            self.timer.start()
        else:
            self.timer.stop()
            self.elapsed.setText("")

    def _tick(self):
        self.elapsed.setText(f"Uptime {fmt_time(time.time() - self.t0)}")

    # ---- actions
    def start(self):
        if self.state not in ("idle", "error"):
            return
        if not SCRIPT.exists():
            self.win.toast(f"{SCRIPT.name} was not found next to this app", "error")
            return
        if not modal_installed():
            self.win.toast("Modal is not installed yet — open Setup first", "error")
            self.win.goto("setup")
            return
        args = ["-m", "modal", "run", SCRIPT.name, "--idle-minutes", str(self.idle.value())]
        if self.reset.isChecked():
            args.append("--reset")
        self._args = args
        self.url = None
        self.app_id = None
        self._launched_at = None
        self._profile = active_profile()
        self._collect = ""
        self._stopping = False
        self._attempt += 1
        att = self._attempt
        self.set_state("starting")
        self.win.goto("home")
        self.sub.setFull("Checking for sessions that are already running…")
        self.win.guard.find(lambda ids: self._preflight_done(ids, att))

    def _alive(self, att) -> bool:
        return att == self._attempt and self.state == "starting" and not self._stopping

    def _preflight_done(self, ids, att):
        if not self._alive(att):
            return
        if ids:
            r = QMessageBox.question(
                self.win, "A session is already running",
                "A session is already running on this Modal account (" + ", ".join(ids) + ").\n"
                "It keeps using credit until it is stopped.\n\nStop it and start a new one?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                self.set_state("idle")
                return
            self.sub.setFull("Stopping the old session…")
            self.win.guard.stop_ids(ids, lambda ok: self._begin(att))
            return
        self._begin(att)

    def _begin(self, att):
        if not self._alive(att):
            return
        if SyncService.auto() and SyncService.ready():
            self.sub.setFull("Syncing notebooks with Modal…")
            self.win.sync.sync_all(lambda: self._launch(att))
        else:
            self._launch(att)

    def _launch(self, att):
        if not self._alive(att):
            return
        self.sub.setFull("Checking your tokens…")
        self.win.secrets_page.ensure_active(lambda: self._launch_now(att))

    def _launch_now(self, att):
        if not self._alive(att):
            return
        self.win.secrets_page.prune()
        self._launched_at = time.time()
        if not self.proc.start(self._args, env=_pe(self._profile)):
            self._launched_at = None
            self.set_state("error")

    def stop(self, quit_after=False):
        if quit_after:
            self._quit_after = True
        if self.state == "stopping":
            return
        if self.state not in ("starting", "running") and not self.proc.running():
            if quit_after:
                self.win.finish_close()
            return
        self._attempt += 1                      # cancels anything still waiting to launch
        self._stopping = True
        self.set_state("stopping")
        self.sub.setFull("Making sure nothing keeps running…")
        launched = self._launched_at is not None
        self.proc.kill()
        if not launched:
            self._on_stopped(0)
            return
        self.win.guard.ensure_clean(lambda ok: self._on_stopped(0 if ok else 1), known_id=self.app_id,
                                    profile=self._profile)

    def _usage_later(self):
        self.win.usage.refresh()
        QTimer.singleShot(90000, self.win.usage.refresh)
        QTimer.singleShot(4000, self.win.sync.pull_if_auto)

    def _on_stopped(self, code: int):
        self._stopping = False
        self.set_state("idle")
        self._usage_later()
        if code == 0:
            self.win.toast("Session stopped — billing has ended", "success")
        else:
            self.win.toast("Stop was sent, but Modal still lists a running app — check modal.com/apps", "error")
        if self._quit_after:
            self.win.finish_close()

    def _on_line(self, text: str):
        if text.startswith("›"):
            return
        if self.app_id is None:
            m = APP_ID_RE.search(text)
            if m:
                self.app_id = m.group(0)
        if self.state == "starting":
            self.sub.setFull(text)
        if self.url:
            return
        if "Open JupyterLab" in text and "JupyterLab:" in text:
            self._collect = text.split("JupyterLab:", 1)[1].strip()
        elif self._collect and " " not in text.strip():
            self._collect += text.strip()
        else:
            self._collect = ""
        m = URL_RE.search(self._collect) if self._collect else None
        if m:
            self.url = m.group(0)
            self._collect = ""
            self.url_lbl.setFull(self.url)
            self.t0 = time.time()
            self.set_state("running")
            self._tick()
            self.win.toast("JupyterLab is ready", "success")
            if self.auto.isChecked():
                self.open_url()

    def _on_done(self, code: int):
        if self._stopping:
            return
        if self.state in ("idle",):
            return
        self._usage_later()
        self.win.guard.ensure_clean(lambda ok: None, known_id=self.app_id, max_wait=30, profile=self._profile)
        if code == 0:
            self.set_state("idle")
            self.win.toast("Session ended", "info")
        else:
            self.set_state("error")
            self.win.toast("The session stopped with an error — see the log panel", "error")

    def open_url(self):
        if self.url:
            QDesktopServices.openUrl(QUrl(self.url))

    def copy_url(self):
        if self.url:
            QGuiApplication.clipboard().setText(self.url)
            self.win.toast("Link copied", "success")


class SetupPage(Page):
    def __init__(self, win):
        super().__init__("Setup", "Do these 3 steps once.")
        self.win = win
        self.procs = {k: Proc(self, log=win.log) for k in ("pip", "login")}

        def step(n, title, desc):
            card = Card()
            h = QHBoxLayout()
            h.setSpacing(16)
            badge = Badge(n)
            h.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(label(title, 16, semi=True))
            col.addWidget(label(desc, 13, TEXT2, wrap=True))
            col.addSpacing(6)
            h.addLayout(col, 1)
            card.v.addLayout(h)
            self.v.addWidget(card)
            return badge, col

        self.bd1, c1 = step(1, "Install Modal", "Downloads the Modal tool into this Python.")
        self.b1 = Btn("Install / update Modal", "primary", "download")
        r1 = QHBoxLayout()
        r1.addWidget(self.b1)
        r1.addStretch(1)
        c1.addLayout(r1)
        self.b1.clicked.connect(lambda: self.run_task(
            "pip", ["-m", "pip", "install", "--upgrade", "modal"], self.b1, "Installing…", "Modal installed"))

        self.bd2, c2 = step(2, "Log in to Modal",
                            "A browser tab opens. Approve the login, then come back here.")
        self.b2 = Btn("Log in to Modal", "primary", "link")
        r2 = QHBoxLayout()
        r2.addWidget(self.b2)
        r2.addStretch(1)
        c2.addLayout(r2)
        self.b2.clicked.connect(lambda: self.run_task(
            "login", ["-m", "modal", "setup"], self.b2, "Waiting for browser…", "Logged in to Modal"))

        self.bd3, c3 = step(3, "Add tokens (optional)",
                            "Hugging Face, Civitai and other API keys. They are kept safely in Modal and given to "
                            "your notebooks as environment variables.")
        self.b3 = Btn("Manage tokens", "primary", "secret")
        r3 = QHBoxLayout()
        r3.addWidget(self.b3)
        r3.addStretch(1)
        c3.addLayout(r3)
        self.b3.clicked.connect(lambda: self.win.goto("secrets"))
        self.finish()

    def on_show(self):
        self.refresh()

    def refresh(self):
        inst = modal_installed()
        logged = modal_logged_in()
        self.bd1.set_ok(inst)
        self.bd2.set_ok(logged)
        page = getattr(self.win, "secrets_page", None)
        if inst and logged and page is not None:
            page.refresh(lambda names: self.bd3.set_ok(bool(names)))
        else:
            self.bd3.set_ok(False)

    def run_task(self, key, args, btn, busy, ok_msg, show=None):
        proc = self.procs[key]
        if proc.running():
            return
        btn.set_busy(True, busy)
        btn.setEnabled(False)

        def fin(code):
            btn.set_busy(False)
            btn.setEnabled(True)
            if code == 0:
                self.win.toast(ok_msg, "success")
            else:
                self.win.toast("That didn't work — check the log panel", "error")
            self.refresh()

        if not proc.start(args, show=show, on_done=fin):
            btn.set_busy(False)
            btn.setEnabled(True)


# =============================================================================
#  Tokens (Modal secrets): several, named by you
# =============================================================================
SECRET_PRESETS = [
    ("Hugging Face", "huggingface", "HF_TOKEN", "https://huggingface.co/settings/tokens"),
    ("Civitai", "civitai", "CIVITAI_API_KEY", "https://civitai.com/user/account"),
    ("Weights & Biases", "wandb", "WANDB_API_KEY", "https://wandb.ai/authorize"),
    ("OpenAI", "openai", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ("Anthropic", "anthropic", "ANTHROPIC_API_KEY", "https://console.anthropic.com/settings/keys"),
    ("GitHub", "github", "GITHUB_TOKEN", "https://github.com/settings/tokens"),
    ("Google AI", "google-ai", "GOOGLE_API_KEY", "https://aistudio.google.com/app/apikey"),
    ("Custom…", "", "", ""),
]
_SECRET_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def parse_secret_names(lines) -> list:
    """Reads the output of `modal secret list` (JSON when available, otherwise the table)."""
    data = _parse_json(lines)
    names = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                nm = next((str(v) for k, v in item.items() if str(k).strip().lower() in ("name", "secret name", "label")), None)
                if nm is None:
                    nm = next((str(v) for v in item.values() if isinstance(v, str)), None)
                if nm:
                    names.append(nm)
            elif isinstance(item, str):
                names.append(item)
        return names
    for line in lines:
        if line.startswith("›") or ("│" not in line and "┃" not in line):
            continue
        cells = [c.strip() for c in re.split(r"[│┃]", line) if c.strip()]
        if not cells or cells[0].lower() in ("name", "secret", "label"):
            continue
        if re.fullmatch(r"[─━┏┓┗┛┡┩╇┯┷┼ ]+", cells[0]):
            continue
        names.append(cells[0])
    return names


TOKENS_FILE = APP_DIR / ".tokens.json"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows data protection: only your Windows user on this PC can read the result."""
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("Windows could not protect the token" if protect else "Windows could not read the saved token")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(out.pbData, ctypes.c_void_p))


class TokenStore:
    """Keeps a protected copy of your tokens on this PC, so the app can give them to EVERY Modal account.
    (Modal cannot show a saved token again, so without this copy a token could not be shared.)"""

    def __init__(self):
        self.data = {"tokens": {}, "synced": {}}
        self.load()

    def load(self):
        try:
            d = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                self.data = {"tokens": d.get("tokens", {}) or {}, "synced": d.get("synced", {}) or {}}
        except Exception:  # noqa: BLE001
            self.data = {"tokens": {}, "synced": {}}

    def _save(self):
        TOKENS_FILE.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        if os.name != "nt":
            try:
                os.chmod(TOKENS_FILE, 0o600)
            except OSError:
                pass

    def names(self) -> list:
        return sorted(self.data["tokens"], key=str.lower)

    def has(self, name: str) -> bool:
        return name in self.data["tokens"]

    def var(self, name: str) -> str:
        return str(self.data["tokens"].get(name, {}).get("var", ""))

    def rev(self, name: str) -> int:
        return int(self.data["tokens"].get(name, {}).get("rev", 0))

    def synced_rev(self, acct, name: str) -> int:
        return int(self.data["synced"].get(acct or "", {}).get(name, 0))

    def mark_synced(self, acct, name: str, rev: int):
        self.data["synced"].setdefault(acct or "", {})[name] = rev
        self._save()

    def set(self, name: str, var: str, value: str) -> int:
        raw = value.encode("utf-8")
        blob = _dpapi(raw, True) if os.name == "nt" else raw
        rev = self.rev(name) + 1
        self.data["tokens"][name] = {"var": var, "blob": base64.b64encode(blob).decode("ascii"),
                                     "rev": rev, "protected": os.name == "nt"}
        self._save()
        return rev

    def value(self, name: str):
        t = self.data["tokens"].get(name)
        if not t:
            return None
        try:
            blob = base64.b64decode(t["blob"])
            return (_dpapi(blob, False) if t.get("protected") else blob).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None

    def delete(self, name: str):
        self.data["tokens"].pop(name, None)
        for per in self.data["synced"].values():
            per.pop(name, None)
        self._save()


class SecretRow(QWidget):
    toggled = Signal(str, bool)
    delete = Signal(str)

    def __init__(self, name: str, on: bool, shared: bool):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 8, 18, 8)
        h.setSpacing(12)
        tg = Toggle(on)
        tg.toggled.connect(lambda v: self.toggled.emit(name, v))
        tg.setToolTip("Give this token to your notebooks")
        h.addWidget(tg)
        h.addWidget(ElidedLabel(name, 15, TEXT), 1)
        tag = QLabel("All accounts" if shared else "This account only")
        tag.setFont(font(12, semi=True))
        col, bg = (GREEN, "rgba(108,203,95,36)") if shared else (TEXT3, "rgba(255,255,255,18)")
        tag.setStyleSheet(f"color:{col};background:{bg};border-radius:4px;padding:3px 10px;")
        tag.setToolTip("A copy of this token is on every Modal account." if shared else
                       "Saved only on the account you were using. Save it again here to give it to every account.")
        h.addWidget(tag)
        b = Btn("Delete", "ghost", "trash", h=30)
        b.clicked.connect(lambda: self.delete.emit(name))
        h.addWidget(b)


class SecretsPage(Page):
    def __init__(self, win):
        super().__init__("Tokens", "Keep API keys for all your Modal accounts. Turn on the ones your notebooks need: "
                                   "each one becomes an environment variable.")
        self.win = win
        self.store = TokenStore()
        self.known = []
        self.loaded = False
        self._lister = None
        self._waiters = []
        self._gen = 0
        self.proc = Proc(self, log=win.log)

        card = Card()
        card.v.addWidget(label("Add a token", 16, semi=True))
        self.preset = Combo()
        for title, _s, _v, _u in SECRET_PRESETS:
            self.preset.addItem(title)
        card.v.addLayout(self._field("Service", self.preset))
        row = QHBoxLayout()
        row.setSpacing(12)
        self.f_var = QLineEdit()
        self.f_var.setFont(font(14))
        self.f_var.setPlaceholderText("MY_API_KEY")
        self.f_var.setToolTip("The name your notebook uses to read the token, for example HF_TOKEN.")
        self.f_secret = QLineEdit()
        self.f_secret.setFont(font(14))
        self.f_secret.setPlaceholderText("my-api-key")
        self.f_secret.setToolTip("The name Modal stores the token under. Letters, numbers, - . _ only.")
        row.addLayout(self._field("Variable name (what your notebook reads)", self.f_var), 1)
        row.addLayout(self._field("Secret name (how Modal stores it)", self.f_secret), 1)
        card.v.addLayout(row)
        self.f_val = QLineEdit()
        self.f_val.setFont(font(14))
        self.f_val.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_val.setPlaceholderText("Paste the token here")
        self.f_val.setToolTip("Sent to Modal for every account. A protected copy stays on this PC (only your "
                              "Windows user can read it) so new accounts get the token too.")
        card.v.addLayout(self._field("Token", self.f_val))
        btns = FlowLayout(hspacing=10, vspacing=8)
        self.b_save = Btn("Save token", "primary", "add")
        self.b_get = Btn("Get a token", "default", "open")
        self.b_save.clicked.connect(self.save_token)
        self.b_get.clicked.connect(self._open_url)
        btns.addWidget(self.b_save)
        btns.addWidget(self.b_get)
        card.v.addLayout(btns)
        card.v.addWidget(label("A saved token is copied to every Modal account automatically. Use “Custom…” for other "
                               "services. Saving with a name that already exists replaces the old token.",
                               12, TEXT3, wrap=True))
        self.v.addWidget(card)

        lc = Card(pad=(0, 14, 0, 10), spacing=0)
        head = QHBoxLayout()
        head.setContentsMargins(18, 0, 18, 8)
        head.addWidget(label("Your tokens", 16, semi=True))
        head.addStretch(1)
        self.b_sref = IconBtn("refresh", "Reload your tokens")
        self.b_sref.clicked.connect(lambda: self.refresh())
        head.addWidget(self.b_sref)
        lc.v.addLayout(head)
        self.s_line = ProgressLine()
        lc.v.addWidget(self.s_line)
        self.list_v = QVBoxLayout()
        self.list_v.setSpacing(0)
        lc.v.addLayout(self.list_v)
        self.note = label("", 12, YELLOW, wrap=True)
        self.note.setContentsMargins(18, 8, 18, 0)
        self.note.hide()
        lc.v.addWidget(self.note)
        self.v.addWidget(lc)

        self.preset.currentIndexChanged.connect(self._preset)
        self._preset(0)
        self._rebuild()
        self.finish()

    @staticmethod
    def _field(caption: str, widget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        box.addWidget(label(caption, 12, TEXT3))
        box.addWidget(widget)
        return box

    def on_show(self):
        self.refresh()

    def account_changed(self):
        """Another account is active: forget its list, then give it every token it is missing."""
        self._gen += 1
        self._lister = None
        self._waiters = []
        self.known, self.loaded = [], False
        self._set_loading(False)
        self._rebuild()
        self.ensure_active()

    # ---- form
    def _preset(self, i: int):
        _t, secret, var, url = SECRET_PRESETS[i]
        self.f_secret.setText(secret)
        self.f_var.setText(var)
        self.b_get.setVisible(bool(url))
        if not secret:
            self.f_var.setFocus()

    def _open_url(self):
        url = SECRET_PRESETS[self.preset.currentIndex()][3]
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def save_token(self):
        name = self.f_secret.text().strip()
        var = self.f_var.text().strip()
        tok = self.f_val.text().strip()
        if not _VAR_NAME_RE.match(var):
            self.win.toast("Variable name: letters, numbers and _ only (for example HF_TOKEN)", "error")
            return
        if not _SECRET_NAME_RE.match(name):
            self.win.toast("Secret name: letters, numbers, - . _ only (for example huggingface)", "error")
            return
        if not tok:
            self.win.toast("Paste the token first", "error")
            return
        if not (modal_installed() and modal_logged_in()):
            self.win.toast("Install Modal and log in first (Setup)", "error")
            self.win.goto("setup")
            return
        if self.proc.running():
            return
        acct = active_profile()
        self.b_save.set_busy(True, "Saving…")
        self.b_save.setEnabled(False)

        def fin(code):
            self.b_save.set_busy(False)
            self.b_save.setEnabled(True)
            if code != 0:
                self.win.toast("That didn't work — check the log panel", "error")
                return
            try:
                rev = self.store.set(name, var, tok)
                self.store.mark_synced(acct, name, rev)
            except OSError as exc:
                self.win.toast(f"Saved on Modal, but not remembered on this PC ({exc})", "error")
            self._enable(name, True)
            self.f_val.clear()
            self.refresh()
            self.push_other_accounts(lambda n: self.win.toast(
                f"Token “{name}” saved for all accounts" if n else f"Token “{name}” saved and switched on",
                "success"))

        if not self.proc.start(["-m", "modal", "secret", "create", name, f"{var}={tok}", "--force"],
                               show=f"modal secret create {name} {var}=•••••• --force", on_done=fin, env=_pe(acct)):
            fin(-1)

    # ---- giving tokens to accounts
    def _create_many(self, acct, names, then=None):
        """Creates the listed tokens on one account (it never has to be the active one)."""
        queue = [n for n in names if self.store.has(n)]
        made = [0]

        def step(code=0, prev=None):
            if prev is not None and code == 0:
                self.store.mark_synced(acct, prev, self.store.rev(prev))
                made[0] += 1
            if not queue:
                if then:
                    then(made[0])
                return
            n = queue.pop(0)
            val = self.store.value(n)
            if val is None:
                self.win.log(f"Token “{n}” could not be read from this PC. Save it again on the Tokens page.")
                step(1, None)
                return
            var = self.store.var(n)
            if not self.proc.start(["-m", "modal", "secret", "create", n, f"{var}={val}", "--force"],
                                   show=f"modal secret create {n} {var}=•••••• --force  (account: {acct or 'active'})",
                                   on_done=lambda c, nn=n: step(c, nn), env=_pe(acct)):
                step(1, None)

        step()

    def push_other_accounts(self, then=None):
        """Right after saving: copy every token that is out of date to the other saved accounts."""
        active = active_profile()
        others = [pr["name"] for pr in read_profiles() if pr["name"] != active]
        total = [0]

        def next_account(_n=0):
            total[0] += _n or 0
            if not others:
                if then:
                    then(total[0])
                return
            acct = others.pop(0)
            need = [n for n in self.store.names() if self.store.synced_rev(acct, n) != self.store.rev(n)]
            self._create_many(acct, need, next_account)

        next_account()

    def ensure_active(self, then=None):
        """Makes sure the active account has every saved token (missing or out of date ones are created)."""
        acct = active_profile()
        if not (modal_installed() and modal_logged_in()) or not self.store.names():
            if then:
                then()
            return

        def go(known):
            need = [n for n in self.store.names()
                    if self.store.synced_rev(acct, n) != self.store.rev(n) or n not in known]
            if not need:
                if then:
                    then()
                return
            def done(made):
                if made:                                    # the list changed: reload it, then carry on
                    self.refresh(lambda _k: then() if then else None)
                elif then:
                    then()

            self._create_many(acct, need, done)

        self.refresh(go)

    # ---- which tokens a session receives
    @staticmethod
    def enabled() -> list:
        cur = read_setting("SECRETS", [])
        return [str(x) for x in cur] if isinstance(cur, (list, tuple)) else []

    def _enable(self, name: str, on: bool) -> bool:
        names = self.enabled()
        if on and name not in names:
            names.append(name)
        elif not on and name in names:
            names.remove(name)
        return write_setting("SECRETS", names)

    def prune(self):
        """Before a session starts: drop tokens that no longer exist on this account."""
        if not self.loaded:
            return
        names = self.enabled()
        keep = [n for n in names if n in self.known]
        if keep != names:
            write_setting("SECRETS", keep)
            self.win.toast("Skipped missing token(s): " + ", ".join(n for n in names if n not in keep), "info")

    def _delete(self, name: str):
        shared = self.store.has(name)
        where = "from ALL your Modal accounts" if shared else "from this account"
        r = QMessageBox.question(self, "Delete token", f"Delete the token “{name}” {where}?\n"
                                 "Notebooks will no longer receive it.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes or self.proc.running():
            return
        accounts = [pr["name"] for pr in read_profiles()] if shared else [active_profile()]
        queue = list(accounts) or [None]

        def step(_code=0):
            if not queue:
                if shared:
                    self.store.delete(name)
                self._enable(name, False)
                self.win.toast("Token deleted", "success")
                self.refresh()
                return
            acct = queue.pop(0)
            if not self.proc.start(["-m", "modal", "secret", "delete", name, "--yes"], on_done=step, env=_pe(acct)):
                step(1)

        step()

    # ---- list from Modal
    def refresh(self, on_done=None):
        if not (modal_installed() and modal_logged_in()):
            self.known, self.loaded = [], False
            self._rebuild()
            if on_done:
                on_done([])
            return
        if on_done:
            self._waiters.append(on_done)
        if self._lister is not None and self._lister.running():
            return
        self._set_loading(True)
        self._list(True)

    def _set_loading(self, on: bool):
        self.s_line.set_active(on)
        self.b_sref.set_spinning(on)

    def _list(self, as_json: bool):
        out = []
        gen = self._gen
        acct = active_profile()
        p = Proc(self)
        p.line.connect(out.append)
        self._lister = p

        def fin(code):
            if gen != self._gen:
                return                              # this answer belongs to the previous account
            if code != 0 and as_json:
                self._list(False)
                return
            if code == 0:
                self.known = sorted(set(parse_secret_names(out)), key=str.lower)
                self.loaded = True
                self._seed_default()
            else:
                self.loaded = False
            self._set_loading(False)
            self._rebuild()
            waiters, self._waiters = self._waiters, []
            for cb in waiters:
                cb(self.known)

        p.start(["-m", "modal", "secret", "list"] + (["--json"] if as_json else []), on_done=fin, env=_pe(acct))

    def _seed_default(self):
        """First run: keep giving your existing 'huggingface' secret to notebooks, as before."""
        qs = QSettings(SETTINGS_ORG, "App")
        if qs.value("secrets_seeded", False, type=bool):
            return
        qs.setValue("secrets_seeded", True)
        if not self.enabled() and "huggingface" in self.known:
            write_setting("SECRETS", ["huggingface"])

    def _rebuild(self):
        _clear_layout(self.list_v)
        on = set(self.enabled())
        if not self.known:
            lb = label("No tokens yet. Add one above." if self.loaded else
                       "Log in to Modal (Setup) to see your tokens.", 13, TEXT2)
            lb.setContentsMargins(18, 6, 18, 6)
            self.list_v.addWidget(lb)
        for i, name in enumerate(self.known):
            if i:
                self.list_v.addWidget(divider())
            row = SecretRow(name, name in on, self.store.has(name))
            row.toggled.connect(lambda n, v: self._enable(n, v))
            row.delete.connect(self._delete)
            self.list_v.addWidget(row)
        missing = [n for n in sorted(on) if self.loaded and n not in self.known]
        self.note.setVisible(bool(missing))
        if missing:
            self.note.setText("Switched on but not found on this account: " + ", ".join(missing) +
                              ". They are skipped when a session starts.")


def fmt_size(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v) if v not in (None, "") else ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def parse_volume_entries(lines, base: str) -> list:
    """Reads `modal volume ls` output (JSON, or one path per line) into a sorted list of entries."""
    base = "/" + base.strip("/")
    data = _parse_json(lines)
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    rows = []
    if isinstance(data, list):
        for it in data:
            if not isinstance(it, dict):
                continue
            name = next((str(v) for k, v in it.items() if str(k).lower() in ("filename", "name", "path")), None)
            if not name:
                continue
            typ = str(next((v for k, v in it.items() if str(k).lower() == "type"), "")).lower()
            size = next((v for k, v in it.items() if "size" in str(k).lower()), None)
            rows.append((name, typ, size))
    else:
        for line in lines:
            t = line.strip()
            if not t or t.startswith(("›", "Error", "Usage", "│", "┃", "┏", "┡", "└", "Traceback")):
                continue
            rows.append((t, "dir" if t.endswith("/") else "file", None))
    out = []
    for name, typ, size in rows:
        p = name.strip().rstrip("/").strip("/")
        if not p:
            continue
        full = "/" + p if ("/" in p or base == "/") else base.rstrip("/") + "/" + p
        if full == base:
            continue
        out.append({"name": full.rsplit("/", 1)[-1], "path": full,
                    "dir": "dir" in typ or name.strip().endswith("/"), "size": size})
    out.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    return out


class VolumePage(Page):
    """Browse, view, edit, upload, download and delete the files saved on Modal."""

    def __init__(self, win):
        super().__init__("Volume", "See and manage the files saved on Modal. Everything here is kept between sessions.")
        self.win = win
        self.path = "/"
        self.entries = []
        self.proc = Proc(self, log=win.log)
        self._busy = False
        self._gen = 0
        self._lister = None
        self._edit_remote = None
        self._edit_local = None
        self._edit_nl = "\n"
        self._baseline = ""
        self._hl = None

        # ---- browser
        card = Card(pad=(14, 12, 14, 12), spacing=8)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.b_up = IconBtn("up", "Up one folder")
        self.b_up.clicked.connect(self.go_up)
        self.path_lbl = ElidedLabel("/", 14, TEXT)
        self.b_ref = IconBtn("refresh", "Reload")
        self.b_ref.clicked.connect(lambda: self.load(self.path))
        top.addWidget(self.b_up)
        top.addWidget(self.path_lbl, 1)
        top.addWidget(self.b_ref)
        card.v.addLayout(top)
        self.progress = ProgressLine()
        card.v.addWidget(self.progress)

        self.tree = QTreeWidget()
        self.tree.setObjectName("voltree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Name", "Size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setMinimumHeight(260)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._activate(it.data(0, Qt.ItemDataRole.UserRole)))
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        card.v.addWidget(self.tree, 1)
        self.skel = SkeletonList()
        card.v.addWidget(self.skel, 1)
        self._dim_eff = QGraphicsOpacityEffect(self.tree)
        self._dim_eff.setOpacity(1.0)
        self.tree.setGraphicsEffect(self._dim_eff)
        self._dim_anim = QPropertyAnimation(self._dim_eff, b"opacity", self)
        self._dim_anim.setDuration(200)
        self.status = label("", 12, TEXT3)
        card.v.addWidget(self.status)

        acts = FlowLayout(hspacing=8, vspacing=8)
        self.b_open = Btn("Open", "primary", "open", h=34)
        self.b_dl = Btn("Download", "default", "download", h=34)
        self.b_del = Btn("Delete", "default", "trash", h=34)
        self.b_upf = Btn("Upload files…", "default", "upload", h=34)
        self.b_upd = Btn("Upload folder…", "default", "upload", h=34)
        b_dir = Btn("Downloads folder", "ghost", "folder", h=34)
        self.b_open.setToolTip("Open a folder, or view and edit a text file here.")
        self.b_dl.setToolTip("Save the selected files to the modal_downloads folder on this PC.")
        self.b_del.setToolTip("Delete the selected files from Modal for good. This cannot be undone.")
        self.b_upf.setToolTip("Add files from this PC to the folder you are looking at.")
        self.b_upd.setToolTip("Add a whole folder from this PC to the folder you are looking at.")
        self.b_open.clicked.connect(self.open_selected)
        self.b_dl.clicked.connect(self.download_selected)
        self.b_del.clicked.connect(self.delete_selected)
        self.b_upf.clicked.connect(self.upload_files)
        self.b_upd.clicked.connect(self.upload_folder)
        b_dir.clicked.connect(self.open_downloads)
        for b in (self.b_open, self.b_dl, self.b_del, self.b_upf, self.b_upd, b_dir):
            acts.addWidget(b)
        card.v.addLayout(acts)
        self.v.addWidget(card)

        # ---- text editor (appears when you open a text file)
        self.ecard = Card(pad=(14, 12, 14, 12), spacing=8)
        eh = QHBoxLayout()
        eh.setSpacing(8)
        self.e_name = ElidedLabel("", 15, TEXT)
        self.e_dirty = label("", 13, YELLOW)
        self.b_save = Btn("Save to Modal", "primary", "upload", h=32)
        self.b_close = Btn("Close", "default", h=32)
        self.b_save.clicked.connect(self.save_file)
        self.b_close.clicked.connect(lambda: self.close_editor())
        eh.addWidget(self.e_name, 1)
        eh.addWidget(self.e_dirty)
        eh.addWidget(self.b_save)
        eh.addWidget(self.b_close)
        self.ecard.v.addLayout(eh)
        self.editor = QPlainTextEdit()
        f = QFont()
        f.setFamilies(MONO_FAMILIES)
        f.setPixelSize(13)
        self.editor.setFont(f)
        self.editor.setMinimumHeight(260)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setStyleSheet("QPlainTextEdit{background:#1e1e1e;border:1px solid #333333;border-radius:6px;"
                                  "padding:6px;color:#d4d4d4;selection-background-color:#264f78;}")
        self.editor.textChanged.connect(self._text_changed)
        self.ecard.v.addWidget(self.editor)
        self.ecard.hide()
        self.v.addWidget(self.ecard)
        self.finish()
        self._sel_changed()

    # ---- which volume / which path
    @staticmethod
    def vol() -> str:
        return read_setting("STORAGE_VOLUME", "modal-root")

    @staticmethod
    def rp(path: str) -> str:
        """Path inside your drive -> path inside the Modal Volume (the volume IS the drive)."""
        p = path.strip().replace("\\", "/").strip("/")
        drive = str(read_setting("DRIVE_FOLDER", "drive") or "drive").strip("/")
        for prefix in (f"root/{drive}", drive, "root"):
            if p == prefix:
                p = ""
                break
            if p.startswith(prefix + "/"):
                p = p[len(prefix) + 1:]
                break
        return "/" + p

    def on_show(self):
        self.load(self.path)

    def account_changed(self):
        """Another Modal account is active now: start from its top folder, with nothing left open."""
        self._gen += 1
        self.close_editor(force=True)
        self.path = "/"
        self.entries = []
        self.tree.clear()
        self.path_lbl.setFull("/")
        self.b_up.setEnabled(False)
        self._set_busy(False)
        self.status.setText("")

    def _set_busy(self, on: bool, text: str = ""):
        """One place for everything that moves while the page waits for Modal."""
        self._busy = on
        if on and text:
            self.status.setText(text)
        self.progress.set_active(on)
        self.b_ref.set_spinning(on)
        first = on and self.tree.topLevelItemCount() == 0
        self.skel.setVisible(first)
        self.tree.setVisible(not first)
        self._dim_anim.stop()
        self._dim_anim.setStartValue(self._dim_eff.opacity())
        self._dim_anim.setEndValue(0.45 if (on and not first) else 1.0)
        self._dim_anim.start()

    @staticmethod
    def _ready() -> bool:
        return modal_installed() and modal_logged_in()

    def open_downloads(self):
        d = APP_DIR / "modal_downloads"
        if not d.is_dir():
            self.win.toast("Nothing downloaded yet", "info")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ---- listing
    def load(self, path: str, as_json: bool = True):
        path = "/" + path.strip("/")
        if self._busy and as_json:
            return
        if not self._ready():
            self.tree.clear()
            self.status.setText("Log in to Modal first (Setup), then your files show up here.")
            return
        self._set_busy(True, "Loading…")
        out = []
        gen = self._gen
        p = Proc(self)
        p.line.connect(out.append)
        self._lister = p

        def fin(code):
            if gen != self._gen:
                return                                  # the account changed while this was loading
            text = "\n".join(out)
            if code != 0 and as_json and "No such option" in text:
                self._busy = False
                self.load(path, as_json=False)
                return
            self._set_busy(False)
            if code != 0:
                for line in out:
                    self.win.log(line)
                missing = ("not found" in text.lower() or "no volume" in text.lower()) and path == "/"
                self.status.setText("Your drive does not exist yet. It is created the first time you start a session."
                                    if missing else "Could not read this folder — see the log panel.")
                if missing:
                    self.tree.clear()
                return
            self.path = path
            self.entries = parse_volume_entries(out, path)
            self._fill()

        p.start(["-m", "modal", "volume", "ls", self.vol(), path] + (["--json"] if as_json else []), on_done=fin)

    def _fill(self):
        self.tree.clear()
        for e in self.entries:
            it = QTreeWidgetItem([e["name"] + ("/" if e["dir"] else ""), "" if e["dir"] else fmt_size(e["size"])])
            it.setData(0, Qt.ItemDataRole.UserRole, e)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if e["dir"]:
                it.setForeground(0, QBrush(QColor(ACCENT)))
            self.tree.addTopLevelItem(it)
        self.path_lbl.setFull(self.path)
        self.b_up.setEnabled(self.path != "/")
        n = len(self.entries)
        self.status.setText("This folder is empty." if n == 0 else f"{n} item{'s' if n != 1 else ''}")
        self._sel_changed()

    def go_up(self):
        if self.path != "/":
            self.load(self.path.rsplit("/", 1)[0] or "/")

    def _selected(self) -> list:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]

    def _sel_changed(self):
        n = len(self._selected())
        self.b_open.setEnabled(n == 1)
        self.b_dl.setEnabled(n >= 1)
        self.b_del.setEnabled(n >= 1)

    def _activate(self, e):
        if not e:
            return
        if e["dir"]:
            self.load(e["path"])
        else:
            self.open_file(e)

    def open_selected(self):
        sel = self._selected()
        if len(sel) == 1:
            self._activate(sel[0])

    # ---- running Modal commands one after another
    def _run_jobs(self, jobs, busy: str, ok_msg: str, then=None):
        if not jobs or self._busy:
            return
        if not self._ready():
            self.win.toast("Log in to Modal first (Setup)", "error")
            return
        self._set_busy(True, busy)
        st = {"i": 0, "bad": False}

        def step(code=0):
            if code != 0:
                st["bad"] = True
            if st["bad"] or st["i"] >= len(jobs):
                self._set_busy(False)
                self.win.toast(ok_msg if not st["bad"] else "That didn't work — see the log panel",
                               "success" if not st["bad"] else "error")
                if then:
                    then()
                return
            args = jobs[st["i"]]
            st["i"] += 1
            self.proc.start(args, on_done=step)

        step()

    # ---- upload / download / delete
    def upload_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files to upload", str(Path.home()))
        dest = self.path.rstrip("/") + "/"
        jobs = [["-m", "modal", "volume", "put", self.vol(), f, dest, "--force"] for f in files]
        self._run_jobs(jobs, "Uploading…", "Files uploaded", lambda: self.load(self.path))

    def upload_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder to upload", str(Path.home()))
        if not folder:
            return
        dest = self.path.rstrip("/") + "/" + Path(folder).name
        self._run_jobs([["-m", "modal", "volume", "put", self.vol(), folder, dest, "--force"]],
                       "Uploading…", "Folder uploaded", lambda: self.load(self.path))

    def download_selected(self):
        base = APP_DIR / "modal_downloads"
        jobs = []
        for e in self._selected():
            dest = base / e["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            jobs.append(["-m", "modal", "volume", "get", self.vol(), e["path"], str(dest), "--force"])
        self._run_jobs(jobs, "Downloading…", "Saved to the modal_downloads folder", self._reset_status)

    def delete_selected(self):
        sel = self._selected()
        if not sel:
            return
        names = ", ".join(e["name"] for e in sel[:3]) + (" …" if len(sel) > 3 else "")
        r = QMessageBox.question(
            self, "Delete from Modal",
            f"Delete {len(sel)} item{'s' if len(sel) != 1 else ''} from Modal for good?\n\n{names}\n\n"
            "This cannot be undone. Copies on this PC are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        if self._edit_remote and any(self._edit_remote == e["path"] or self._edit_remote.startswith(e["path"] + "/")
                                     for e in sel):
            self.close_editor(force=True)
        jobs = [["-m", "modal", "volume", "rm", self.vol(), e["path"]] + (["-r"] if e["dir"] else []) for e in sel]
        self._run_jobs(jobs, "Deleting…", "Deleted", lambda: self.load(self.path))

    def _reset_status(self):
        n = len(self.entries)
        self.status.setText("This folder is empty." if n == 0 else f"{n} item{'s' if n != 1 else ''}")

    # ---- view / edit a text file
    def open_file(self, e):
        name = e["name"]
        if name.lower().endswith(".ipynb"):
            self.win.toast("Notebooks are edited on the Notebooks page. They sync with Modal by themselves.", "info")
            self.win.goto("notebooks")
            return
        try:
            if e["size"] is not None and float(e["size"]) > 1_000_000:
                self.win.toast("Too big to edit here. Use Download instead.", "info")
                return
        except (TypeError, ValueError):
            pass
        if self._busy or not self.close_editor():
            return
        td = tempfile.mkdtemp(prefix="modalvol_")
        local = Path(td) / name
        self._set_busy(True, "Opening…")

        def fin(code):
            self._set_busy(False)
            self._reset_status()
            f = local if local.is_file() else next((x for x in Path(td).rglob("*") if x.is_file()), None)
            if code != 0 or f is None:
                shutil.rmtree(td, ignore_errors=True)
                self.win.toast("Could not open that file — see the log panel", "error")
                return
            data = f.read_bytes()
            try:
                if b"\x00" in data[:8192]:
                    raise UnicodeDecodeError("utf-8", b"", 0, 1, "binary")
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                shutil.rmtree(td, ignore_errors=True)
                self.win.toast("This is not a text file. Use Download instead.", "info")
                return
            self._edit_remote = e["path"]
            self._edit_local = f
            self._edit_nl = "\r\n" if "\r\n" in text else "\n"
            text = text.replace("\r\n", "\n")
            self.editor.blockSignals(True)
            if self._hl is not None:
                self._hl.setDocument(None)
                self._hl.deleteLater()
                self._hl = None
            self.editor.setPlainText(text)
            low = name.lower()
            if low.endswith(".py"):
                self._hl = PyHighlighter(self.editor.document())
            elif low.endswith((".md", ".markdown")):
                self._hl = MdHighlighter(self.editor.document())
            self.editor.blockSignals(False)
            self._baseline = text
            self.e_name.setFull(e["path"])
            self.e_dirty.setText("")
            self.ecard.show()
            QTimer.singleShot(80, lambda: self.ensureWidgetVisible(self.ecard))

        self.proc.start(["-m", "modal", "volume", "get", self.vol(), e["path"], str(local), "--force"], on_done=fin)

    def _text_changed(self):
        if self._edit_remote:
            self.e_dirty.setText("● unsaved" if self.editor.toPlainText() != self._baseline else "")

    def confirm_leave(self) -> bool:
        return self.close_editor(check_only=True)

    def close_editor(self, force: bool = False, check_only: bool = False) -> bool:
        """Closes the text editor. Asks first when there are unsaved changes."""
        if not self._edit_remote:
            return True
        if not force and self.editor.toPlainText() != self._baseline:
            r = QMessageBox.question(self, "Unsaved changes", f"Save changes to {self._edit_remote}?",
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                     | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Save:
                self.save_file(then_close=not check_only)
                return False            # closes itself once the upload has finished
        if check_only:
            return True
        if self._edit_local is not None:
            shutil.rmtree(self._edit_local.parent, ignore_errors=True)
        self._edit_remote = self._edit_local = None
        self.ecard.hide()
        return True

    def save_file(self, then_close: bool = False):
        if not self._edit_remote or self._edit_local is None or self._busy:
            return
        text = self.editor.toPlainText()
        try:
            self._edit_local.write_bytes(text.replace("\n", self._edit_nl).encode("utf-8"))
        except OSError as exc:
            self.win.toast(f"Could not save: {exc}", "error")
            return
        remote = self._edit_remote
        self._set_busy(True, "Saving to Modal…")

        def fin(code):
            self._set_busy(False)
            self._reset_status()
            if code == 0:
                self._baseline = text
                self.e_dirty.setText("")
                self.win.toast("Saved to Modal", "success")
                if then_close:
                    self.close_editor(force=True)
                self.load(self.path)
            else:
                self.win.toast("Could not save to Modal — see the log panel", "error")

        self.proc.start(["-m", "modal", "volume", "put", self.vol(), str(self._edit_local), remote, "--force"],
                        on_done=fin)


FilesPage = VolumePage      # older code refers to it by this name


class SettingsPage(Page):
    def __init__(self, win):
        super().__init__("Settings", f"Saved into {SCRIPT.name}. GPU, CPU, memory and session length are on the Home page.")
        self.win = win
        card = Card(pad=(0, 4, 0, 4), spacing=0)

        self.theme = Combo()
        cur = read_setting("THEME", "JupyterLab Dark")
        key = "__none__" if cur is None else cur
        for t, v in THEMES:
            self.theme.addItem(t, v)
        i = self.theme.findData(key)
        self.theme.setCurrentIndex(max(0, i))
        self.theme.currentIndexChanged.connect(self._theme)

        self.pyv = Combo()
        for v in PY_VERSIONS:
            self.pyv.addItem(v, v)
        i = self.pyv.findData(str(read_setting("PYTHON_VERSION", "3.11")))
        self.pyv.setCurrentIndex(max(0, i))
        self.pyv.currentIndexChanged.connect(self._pyv)

        self.caches = Toggle(bool(read_setting("KEEP_CACHES", False)))
        self.caches.toggled.connect(lambda on: self._save("KEEP_CACHES", on))

        asv = read_setting("AUTOSAVE_SECONDS", 30) or 0
        self.autosave = Stepper(0, 600, 10, int(asv), lambda v: "Default" if v == 0 else f"{v} s")
        self.autosave.changed.connect(lambda v: self._save("AUTOSAVE_SECONDS", v))

        self.credit = Stepper(0, 100000, 5, int(Usage.total()), lambda v: "Off" if v == 0 else f"${v:,}")
        self.credit.changed.connect(self._credit)

        self.zoom = Stepper(70, 160, 10, int(QSettings(SETTINGS_ORG, "App").value("ui_zoom", 100, type=int)),
                            lambda v: f"{v}%")
        self.zoom.changed.connect(self._zoom)


        card.v.addWidget(Row("JupyterLab theme", "Look of the JupyterLab page.", self.theme,
                             tip="Dark or light colors for JupyterLab. Applies from the next start."))
        card.v.addWidget(divider())
        card.v.addWidget(Row("Notebook autosave", "How often your notebook is saved. The app then copies it to this PC.",
                             self.autosave, tip="JupyterLab saves open notebooks on its own every few seconds. Default = JupyterLab's own timing."))
        card.v.addWidget(divider())
        card.v.addWidget(Row("Python version", "Changing it makes the next start slower.", self.pyv,
                             tip="The environment is rebuilt once for a new Python version, then it is fast again."))
        card.v.addWidget(divider())
        card.v.addWidget(Row("Keep downloads", "Saves downloaded models in a .cache folder of your drive, so they are not downloaded again.",
                             self.caches, tip="Off by default: nothing extra is created in your drive. Turn on to keep Hugging Face, torch and pip downloads."))
        card.v.addWidget(divider())
        card.v.addWidget(Row("Interface size", "Make the app bigger or smaller. Restart to apply.", self.zoom,
                             tip="Scales the whole app. Useful on very large or very small screens."))
        card.v.addWidget(divider())
        card.v.addWidget(Row("Monthly credits", "Your free credit per month on the active account (see Modal's usage page).", self.credit,
                             tip="Used for the progress bar and the “Credits left” number. Set 0 to hide the bar."))
        self.v.addWidget(card)

        row = QHBoxLayout()
        row.setSpacing(10)
        b1 = Btn(f"Open {SCRIPT.name}", "default", "open")
        b2 = Btn("Reload from file", "default", "refresh")
        b1.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(SCRIPT))))
        b2.clicked.connect(self.reload)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        self.v.addLayout(row)
        info = ElidedLabel(f"Folder: {APP_DIR}", 12, TEXT3)
        self.v.addWidget(info)
        self.finish()

    def _save(self, key, value):
        ok = write_setting(key, value)
        if ok:
            self.win.toast("Saved", "success")
        return ok

    def _theme(self, _):
        v = self.theme.currentData()
        self._save("THEME", None if v == "__none__" else v)

    def _zoom(self, v):
        QSettings(SETTINGS_ORG, "App").setValue("ui_zoom", int(v))
        self.win.toast("Restart the app to apply the new interface size", "info")

    def _credit(self, v):
        acct = active_profile()
        QSettings(SETTINGS_ORG, "App").setValue(f"credit_total/{acct}" if acct else "credit_total", float(v))
        self.win.usage.updated.emit()

    def on_show(self):
        self.credit.setValue(int(Usage.total()))      # it can differ per account

    def _pyv(self, _):
        self._save("PYTHON_VERSION", self.pyv.currentData())

    def reload(self):
        cur = read_setting("THEME", "JupyterLab Dark")
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(max(0, self.theme.findData("__none__" if cur is None else cur)))
        self.theme.blockSignals(False)
        self.pyv.blockSignals(True)
        self.pyv.setCurrentIndex(max(0, self.pyv.findData(str(read_setting("PYTHON_VERSION", "3.11")))))
        self.pyv.blockSignals(False)
        self.caches.setChecked(bool(read_setting("KEEP_CACHES", False)), animate=True)
        self.autosave.setValue(int(read_setting("AUTOSAVE_SECONDS", 30) or 0))
        self.win.home.reload_from_file()
        self.win.toast(f"Reloaded from {SCRIPT.name}", "info")


# reload helper for the Home page (GPU / idle time changed in the file by hand)
def _home_reload(self: HomePage):
    cur = read_setting("GPU", "L40S")
    key = "__cpu__" if cur is None else cur
    i = self.gpu.findData(key) if isinstance(key, str) else -1
    if i >= 0:
        self.gpu.blockSignals(True)
        self.gpu.setCurrentIndex(i)
        self.gpu.blockSignals(False)
    try:
        v = read_setting("IDLE_MINUTES", 30)
        self.idle.setValue(30 if v is None else int(v))
    except Exception:  # noqa: BLE001
        pass
    self.cpu.setValue(int(read_setting("CPU_CORES", None) or 0))
    self.mem.setValue(int(read_setting("MEMORY_MB", None) or 0) // 1024)


HomePage.reload_from_file = _home_reload


# =============================================================================
#  Window
# =============================================================================
# =============================================================================
#  Notebooks: local list, in-app editor, automatic sync with Modal
# =============================================================================
NB_DIR = APP_DIR / str(read_setting("LOCAL_NOTEBOOK_DIR", "_notebook") or "_notebook")
SYNC_STATE = NB_DIR / ".sync_state.json"
SYNC_SECONDS = 60


def _migrate_notebook_folder() -> None:
    """Moves older layouts into the _notebook folder (runs once, harmless afterwards)."""
    try:
        old = APP_DIR / "notebooks"
        if old.is_dir() and not NB_DIR.exists():
            old.rename(NB_DIR)
        NB_DIR.mkdir(parents=True, exist_ok=True)
        old_state = APP_DIR / ".notebook_sync.json"
        if old_state.exists() and not SYNC_STATE.exists():
            shutil.move(str(old_state), str(SYNC_STATE))
        nb = read_setting("NOTEBOOK_FILE", DEFAULT_NOTEBOOK)
        loose = APP_DIR / nb if nb else None
        if loose is not None and loose.is_file() and not (NB_DIR / loose.name).exists():
            shutil.move(str(loose), str(NB_DIR / loose.name))
    except OSError:
        pass


_migrate_notebook_folder()


_HASH_CACHE = {}


def file_hash(path: Path) -> str:
    """SHA-256 of a file, remembered until the file changes (the lists ask for it very often)."""
    try:
        st = path.stat()
    except OSError:
        return ""
    key = (str(path), st.st_mtime_ns, st.st_size)
    h = _HASH_CACHE.get(key)
    if h:
        return h
    try:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""
    if len(_HASH_CACHE) > 400:
        _HASH_CACHE.clear()
    _HASH_CACHE[key] = h
    return h


def _state_file(acct=None) -> Path:
    acct = re.sub(r"[^A-Za-z0-9._-]+", "_", str(acct or active_profile() or "default"))
    return NB_DIR / f".sync_state.{acct}.json"


def load_state(acct=None) -> dict:
    f = _state_file(acct)
    try:
        if not f.exists() and SYNC_STATE.exists():      # the first account takes over the older single file
            shutil.move(str(SYNC_STATE), str(f))
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(st: dict, acct=None) -> None:
    try:
        _state_file(acct).write_text(json.dumps(st, indent=1), encoding="utf-8")
    except OSError:
        pass


CONFLICT_RE = re.compile(r"^(?P<base>.+)\.modal-\d{6}\.ipynb$")


def is_conflict(name: str) -> bool:
    return bool(CONFLICT_RE.match(name))


def conflict_pairs() -> list:
    """[(copy, original)] for every notebook that was changed on this PC AND on Modal."""
    out = []
    if NB_DIR.is_dir():
        for p in NB_DIR.rglob("*.ipynb"):
            m = CONFLICT_RE.match(p.name)
            if m and ".ipynb_checkpoints" not in p.parts:
                orig = p.with_name(m.group("base") + ".ipynb")
                out.append((p.relative_to(NB_DIR).as_posix(), orig.relative_to(NB_DIR).as_posix()))
    return sorted(out)


def local_notebooks() -> list:
    NB_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in NB_DIR.rglob("*.ipynb"):
        if ".ipynb_checkpoints" in p.parts or is_conflict(p.name):
            continue
        out.append(p.relative_to(NB_DIR).as_posix())
    out.sort(key=lambda r: (NB_DIR / r).stat().st_mtime, reverse=True)
    return out


def nb_status(rel: str, state: dict):
    s = state.get(rel)
    if s is None:
        return "Not on this account yet", ACCENT
    if file_hash(NB_DIR / rel) == s:
        return "Synced", GREEN
    return "Edited on this PC", YELLOW


def new_cell(kind: str, minor: int = 5, text: str = "") -> dict:
    c = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
    if kind == "code":
        c["execution_count"] = None
        c["outputs"] = []
    if minor >= 5:
        c["id"] = uuid.uuid4().hex[:8]
    return c


def blank_notebook() -> dict:
    return {
        "cells": [new_cell("code")],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                     "language_info": {"name": "python"}},
        "nbformat": 4, "nbformat_minor": 5,
    }


def cell_text(cell: dict) -> str:
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else str(src)


class SyncService(QObject):
    """Keeps the local notebooks folder and the notebooks folder of your Modal drive in step.
    Nothing is ever overwritten silently: if both sides changed, the Modal
    version is saved next to yours as  name.modal-HHMMSS.ipynb ."""
    changed = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.proc = Proc(self, log=win.log)
        self.busy = False
        self.msg = ""
        NB_DIR.mkdir(parents=True, exist_ok=True)
        self._seed_once()
        self.timer = QTimer(self)
        self.timer.setInterval(SYNC_SECONDS * 1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    @staticmethod
    def auto() -> bool:
        return QSettings(SETTINGS_ORG, "App").value("auto_sync", True, type=bool)

    @staticmethod
    def push_on_save() -> bool:
        return QSettings(SETTINGS_ORG, "App").value("push_on_save", False, type=bool)

    @staticmethod
    def ready() -> bool:
        return modal_installed() and modal_logged_in()

    def _seed_once(self):
        st = load_state()
        if st.get("_seeded"):
            return
        nb = read_setting("NOTEBOOK_FILE", DEFAULT_NOTEBOOK)
        src = APP_DIR / nb if nb else None
        if src is not None and src.exists() and not (NB_DIR / src.name).exists():
            shutil.copy2(src, NB_DIR / src.name)
        st["_seeded"] = True
        save_state(st)

    def _set(self, msg: str):
        self.msg = msg
        self.changed.emit()

    def _tick(self):
        h = getattr(self.win, "home", None)
        if self.auto() and h is not None and h.state == "running" and not self.busy:
            self.pull()

    def pull_if_auto(self):
        if self.auto():
            self.pull()

    # ---- Modal -> PC
    def pull(self, then=None):
        if self.busy or not self.ready():
            if then:
                then()
            return
        tmp = APP_DIR / ".sync_tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)
        self.busy = True
        self._set("Syncing…")
        acct = active_profile()
        args = ["-m", "modal", "volume", "get", FilesPage.vol(), FilesPage.rp("notebooks"), str(tmp), "--force"]
        self.proc.start(args, on_done=lambda code: self._pulled(code, tmp, then, acct), env=_pe(acct))

    def _pulled(self, code, tmp, then, acct=None):
        upd = conf = 0
        if code == 0:
            try:
                upd, conf = self._merge(tmp, acct)
            except Exception as exc:  # noqa: BLE001
                self.win.log(f"Notebook sync error: {exc}")
        shutil.rmtree(tmp, ignore_errors=True)
        self.busy = False
        if code != 0:
            self._set("Nothing on Modal yet (or not reachable)")
        else:
            msg = "Synced " + time.strftime("%H:%M")
            if upd:
                msg += f"  ·  {upd} updated"
            self._set(msg)
            if conf:
                self.win.toast("A notebook was changed on both sides. Press “conflicts” to choose.", "info")
        if then:
            then()

    def _merge(self, tmp: Path, acct=None):
        base = tmp
        kids = list(tmp.iterdir())
        if len(kids) == 1 and kids[0].is_dir() and kids[0].name == "notebooks":
            base = kids[0]
        state = load_state(acct)
        upd = conf = 0
        for src in base.rglob("*.ipynb"):
            if ".ipynb_checkpoints" in src.parts or is_conflict(src.name):
                continue
            rel = src.relative_to(base).as_posix()
            dst = NB_DIR / rel
            rh = file_hash(src)
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                state[rel] = rh
                upd += 1
                continue
            lh = file_hash(dst)
            if lh == rh:
                state[rel] = rh
                continue
            known = state.get(rel)
            if lh == known:                      # only Modal changed it
                shutil.copy2(src, dst)
                state[rel] = rh
                upd += 1
            elif rh == known:                    # only this PC changed it: will be sent later
                pass
            elif not any(file_hash(c) == rh for c in dst.parent.glob(f"{dst.stem}.modal-*.ipynb")):
                # both changed: keep both (one copy per Modal version, not a new one at every sync)
                copy = dst.with_name(f"{dst.stem}.modal-{time.strftime('%H%M%S')}.ipynb")
                shutil.copy2(src, copy)
                conf += 1
        save_state(state, acct)
        return upd, conf

    # ---- PC -> Modal
    def push(self, rels, then=None, acct=None):
        jobs = list(rels)
        acct = acct or active_profile()
        if not jobs or self.busy or not self.ready():
            if then:
                then()
            return
        self.busy = True
        self._set("Sending to Modal…")
        sent = [0]

        def step(code=0, prev=None):
            if prev is not None and code == 0:
                st = load_state(acct)
                st[prev] = file_hash(NB_DIR / prev)
                save_state(st, acct)
                sent[0] += 1
            if code != 0 or not jobs:
                self.busy = False
                self._set(f"Sent {sent[0]} notebook(s) to Modal" if code == 0 else "Could not send to Modal (see the log panel)")
                if then:
                    then()
                return
            rel = jobs.pop(0)
            parent = Path(rel).parent.as_posix()
            remote = FilesPage.rp("notebooks" if parent == "." else "notebooks/" + parent).rstrip("/") + "/"
            self.proc.start(["-m", "modal", "volume", "put", FilesPage.vol(), str(NB_DIR / rel), remote, "--force"],
                            on_done=lambda c, r=rel: step(c, r), env=_pe(acct))

        step()

    def push_changed(self, then=None):
        acct = active_profile()
        st = load_state(acct)
        rels = [r for r in local_notebooks() if file_hash(NB_DIR / r) != st.get(r)]
        self.push(rels, then, acct)

    def sync_all(self, then=None):
        self.pull(lambda: self.push_changed(then))


class NbItem(QWidget):
    def __init__(self, rel: str, state: dict):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 6)
        v.setSpacing(0)
        v.addWidget(ElidedLabel(rel, 14, TEXT))
        txt, col = nb_status(rel, state)
        when = time.strftime("%d %b %H:%M", time.localtime((NB_DIR / rel).stat().st_mtime))
        v.addWidget(label(f"{txt}  ·  {when}", 12, col))


class CellEdit(QPlainTextEdit):
    def __init__(self, text="", lang="python"):
        super().__init__()
        self._hl = None
        f = QFont()
        f.setFamilies(MONO_FAMILIES)
        f.setPixelSize(13)
        self.setFont(f)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setStyleSheet("QPlainTextEdit{background:#1e1e1e;border:1px solid #333333;border-radius:6px;"
                           "padding:6px;color:#d4d4d4;selection-background-color:#264f78;}")
        self.setPlainText(text)
        self.set_lang(lang)
        self.textChanged.connect(self._fit)
        self._fit()

    def set_lang(self, lang: str):
        if self._hl is not None:
            self._hl.setDocument(None)
            self._hl.deleteLater()
        if len(self.toPlainText()) > 40000:
            self._hl = None
            return
        self._hl = MdHighlighter(self.document()) if lang == "markdown" else PyHighlighter(self.document())

    def _fit(self):
        h = max(1, self.document().blockCount()) * self.fontMetrics().lineSpacing() + 42
        self.setFixedHeight(max(60, min(h, 600)))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded if h > 600
                                        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


class CellWidget(QFrame):
    changed = Signal()
    move = Signal(object, int)
    remove = Signal(object)
    add_below = Signal(object, str)

    def __init__(self, cell: dict):
        super().__init__()
        self.setObjectName("cell")
        self.cell = cell
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)
        h = QHBoxLayout()
        h.setSpacing(4)
        self.kind = Btn(self._kind_text(), "default", h=28)
        self.kind.setFixedWidth(104)
        self.kind.clicked.connect(self.toggle_kind)
        self.kind.setToolTip("Switch this cell between code and text")
        ac = Btn("+ Code", "ghost", h=28)
        at = Btn("+ Text", "ghost", h=28)
        for b in (ac, at):
            b.setFixedWidth(66)
        ac.setToolTip("Add a code cell directly below this one")
        at.setToolTip("Add a text cell directly below this one")
        ac.clicked.connect(lambda: self.add_below.emit(self, "code"))
        at.clicked.connect(lambda: self.add_below.emit(self, "markdown"))
        up = Btn("↑", "ghost", h=28)
        dn = Btn("↓", "ghost", h=28)
        rm = Btn("✕", "ghost", h=28)
        for b in (up, dn, rm):
            b.setFixedWidth(32)
        up.setToolTip("Move this cell up")
        dn.setToolTip("Move this cell down")
        rm.setToolTip("Delete this cell")
        up.clicked.connect(lambda: self.move.emit(self, -1))
        dn.clicked.connect(lambda: self.move.emit(self, 1))
        rm.clicked.connect(lambda: self.remove.emit(self))
        h.addWidget(self.kind)
        h.addStretch(1)
        h.addWidget(ac)
        h.addWidget(at)
        h.addSpacing(6)
        h.addWidget(up)
        h.addWidget(dn)
        h.addWidget(rm)
        v.addLayout(h)
        self.edit = CellEdit(cell_text(cell), "python" if cell.get("cell_type") == "code" else "markdown")
        self.edit.textChanged.connect(self.changed.emit)
        v.addWidget(self.edit)

    def _kind_text(self) -> str:
        return "Code" if self.cell.get("cell_type") == "code" else "Text"

    def toggle_kind(self):
        c = self.cell
        if c.get("cell_type") == "code":
            c["cell_type"] = "markdown"
            c.pop("outputs", None)
            c.pop("execution_count", None)
        else:
            c["cell_type"] = "code"
            c["outputs"] = []
            c["execution_count"] = None
        self.kind.setText(self._kind_text())
        self.edit.set_lang("python" if c["cell_type"] == "code" else "markdown")
        self.changed.emit()

    def to_dict(self) -> dict:
        c = dict(self.cell)
        c["source"] = self.edit.toPlainText().splitlines(keepends=True)
        return c


class NotebookEditor(QWidget):
    dirty_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.path = None
        self.nb = {}
        self.cells = []
        self._dirty = False
        self._loading = False
        self._baseline = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.scroll.viewport().setAutoFillBackground(False)
        body = QWidget()
        body.setObjectName("nbbody")
        body.setStyleSheet("#nbbody{background:transparent;}")
        self.cv = QVBoxLayout(body)
        self.cv.setContentsMargins(0, 0, 8, 0)
        self.cv.setSpacing(10)
        foot = QHBoxLayout()
        foot.setSpacing(8)
        b1 = Btn("Add code cell", "default", "add", h=32)
        b2 = Btn("Add text cell", "default", "add", h=32)
        b1.clicked.connect(lambda: self.add_cell("code"))
        b2.clicked.connect(lambda: self.add_cell("markdown"))
        foot.addWidget(b1)
        foot.addWidget(b2)
        foot.addStretch(1)
        self.cv.addLayout(foot)
        self.cv.addStretch(1)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll)

    # ---- state
    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, d: bool):
        if d != self._dirty:
            self._dirty = d
            self.dirty_changed.emit(d)

    def _signature(self):
        return [(w.cell.get("cell_type"), w.edit.toPlainText()) for w in self.cells]

    def _on_change(self):
        # The syntax highlighter also fires "text changed" signals, so compare real content instead.
        if not self._loading:
            self._set_dirty(self._signature() != self._baseline)

    def _minor(self) -> int:
        try:
            return int(self.nb.get("nbformat_minor", 5))
        except (TypeError, ValueError):
            return 5

    # ---- load / save
    def clear(self):
        for w in self.cells:
            self.cv.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.cells = []
        self._baseline = []

    def load(self, path: Path) -> bool:
        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(nb, dict):
                raise ValueError("not a notebook")
        except Exception as exc:  # noqa: BLE001
            self.path = None
            self.clear()
            self.nb = {}
            self._set_dirty(False)
            raise ValueError(str(exc))
        self._loading = True
        self.path = path
        self.nb = nb
        self.clear()
        for c in nb.get("cells", []):
            self._add_widget(c, len(self.cells))
        self._loading = False
        self._baseline = self._signature()
        self._set_dirty(False)
        self.scroll.verticalScrollBar().setValue(0)
        return True

    def save(self) -> bool:
        if self.path is None:
            return False
        nb = dict(self.nb)
        nb["cells"] = [w.to_dict() for w in self.cells]
        self.path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        self.nb = nb
        self._baseline = self._signature()
        self._set_dirty(False)
        return True

    # ---- cells
    def _add_widget(self, cell: dict, index: int) -> CellWidget:
        w = CellWidget(cell)
        w.changed.connect(self._on_change)
        w.move.connect(self._move)
        w.remove.connect(self._remove)
        w.add_below.connect(self._add_below)
        self.cv.insertWidget(index, w)
        self.cells.insert(index, w)
        return w

    def add_cell(self, kind: str):
        if self.path is None:
            return
        w = self._add_widget(new_cell(kind, self._minor()), len(self.cells))
        self._on_change()
        QTimer.singleShot(60, lambda: self.scroll.ensureWidgetVisible(w))

    def _add_below(self, w, kind: str):
        """Inserts an empty cell directly under the cell whose + button was pressed."""
        if w not in self.cells:
            return
        new = self._add_widget(new_cell(kind, self._minor()), self.cells.index(w) + 1)
        self._on_change()

        def reveal():
            self.scroll.ensureWidgetVisible(new)
            new.edit.setFocus()

        QTimer.singleShot(60, reveal)

    def _move(self, w, d: int):
        i = self.cells.index(w)
        j = i + d
        if j < 0 or j >= len(self.cells):
            return
        self.cells.pop(i)
        self.cells.insert(j, w)
        self.cv.removeWidget(w)
        self.cv.insertWidget(j, w)
        self._on_change()

    def _remove(self, w):
        if w in self.cells:
            self.cells.remove(w)
        self.cv.removeWidget(w)
        w.setParent(None)
        w.deleteLater()
        self._on_change()


class ConflictDialog(QDialog):
    """Notebooks changed on this PC AND on Modal. Pick which version to keep, one by one."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("Notebook conflicts")
        self.setMinimumWidth(560)
        self.setStyleSheet("QDialog{background:#202020;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)
        v.addWidget(label("Both this PC and Modal changed these notebooks", 15, semi=True))
        v.addWidget(label("Choose which version to keep. Nothing is lost until you choose.", 12, TEXT3))
        self.box = QVBoxLayout()
        self.box.setSpacing(8)
        v.addLayout(self.box)
        row = QHBoxLayout()
        row.addStretch(1)
        b = Btn("Close", "default", h=34)
        b.clicked.connect(self.accept)
        row.addWidget(b)
        v.addLayout(row)
        self.rebuild()

    def rebuild(self):
        _clear_layout(self.box)
        pairs = conflict_pairs()
        if not pairs:
            self.accept()
            return
        for copy_rel, orig_rel in pairs:
            card = Card(pad=(14, 10, 14, 10), spacing=6)
            card.v.addWidget(label(orig_rel, 14, semi=True))
            btns = FlowLayout(hspacing=8, vspacing=6)
            keep = Btn("Keep mine", "default", h=32)
            keep.setToolTip("Keep the version on this PC. It replaces Modal's version at the next sync.")
            theirs = Btn("Use Modal's", "default", h=32)
            theirs.setToolTip("Replace the version on this PC with the one from Modal.")
            opn = Btn("Open Modal's copy", "ghost", "open", h=32)
            opn.setToolTip("Look at Modal's version in the editor before deciding.")
            keep.clicked.connect(lambda _=False, c=copy_rel, o=orig_rel: self._do(c, o, True))
            theirs.clicked.connect(lambda _=False, c=copy_rel, o=orig_rel: self._do(c, o, False))
            opn.clicked.connect(lambda _=False, c=copy_rel: self._open(c))
            for b in (keep, theirs, opn):
                btns.addWidget(b)
            card.v.addLayout(btns)
            self.box.addWidget(card)

    def _do(self, copy_rel, orig_rel, mine):
        self.page.resolve_conflict(copy_rel, orig_rel, mine)
        self.rebuild()

    def _open(self, copy_rel):
        self.accept()
        self.page.open_copy(copy_rel)


class NotebooksPage(QScrollArea):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.cur = None
        self.loaded_hash = ""
        self._suppress = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.viewport().setAutoFillBackground(False)
        inner = QWidget()
        inner.setObjectName("nbinner")
        inner.setStyleSheet("#nbinner{background:transparent;}")
        inner.setMinimumHeight(560)
        self.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(36, 30, 36, 22)
        root.setSpacing(14)
        # ---- compact toolbar: sync status, conflicts, Sync, options (the two switches live in a small menu)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(label("Notebooks", 22, semi=True))
        self.sync_msg = ElidedLabel("", 12, TEXT3)
        self.sync_msg._align = Qt.AlignmentFlag.AlignRight
        bar.addWidget(self.sync_msg, 1)
        self.b_conf = Btn("", "warn", h=30)
        self.b_conf.setToolTip("Both this PC and Modal changed these notebooks. Click to choose which version to keep.")
        self.b_conf.clicked.connect(self.show_conflicts)
        self.b_conf.hide()
        self.b_sync = Btn("Sync", "ghost", "refresh", h=30)
        self.b_sync.setToolTip("Copy notebooks between this PC and your Modal drive now")
        self.b_sync.clicked.connect(lambda: self.win.sync.sync_all())
        self.b_opts = IconBtn("settings", "Sync options")
        self.b_opts.clicked.connect(self._show_menu)
        bar.addWidget(self.b_conf)
        bar.addWidget(self.b_sync)
        bar.addWidget(self.b_opts)
        root.addLayout(bar)
        self.sync_line = ProgressLine()
        root.addWidget(self.sync_line)

        self.menu = QMenu(self)
        self.menu.setToolTipsVisible(True)
        self.act_auto = QAction("Sync automatically", self.menu)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(SyncService.auto())
        self.act_auto.setToolTip("Before a session, every minute while it runs, and after it ends")
        self.act_auto.toggled.connect(lambda on: QSettings(SETTINGS_ORG, "App").setValue("auto_sync", on))
        self.act_push = QAction("Send to Modal when I save", self.menu)
        self.act_push.setCheckable(True)
        self.act_push.setChecked(SyncService.push_on_save())
        self.act_push.setToolTip("Upload a notebook each time you press Save here")
        self.act_push.toggled.connect(lambda on: QSettings(SETTINGS_ORG, "App").setValue("push_on_save", on))
        self.menu.addAction(self.act_auto)
        self.menu.addAction(self.act_push)

        # ---- list + editor
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        left = Card(pad=(10, 12, 10, 10), spacing=8)
        left.setMinimumWidth(250)
        left.setMaximumWidth(380)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        b_new = Btn("New", "primary", "add", h=32)
        b_imp = Btn("Import", "default", "upload", h=32)
        b_new.clicked.connect(self.new_notebook)
        b_imp.clicked.connect(self.import_notebooks)
        top.addWidget(b_new, 1)
        top.addWidget(b_imp, 1)
        left.v.addLayout(top)
        self.list = QListWidget()
        self.list.setObjectName("nblist")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(self._row_changed)
        left.v.addWidget(self.list, 1)
        body.addWidget(left, 1)

        right = Card(pad=(16, 14, 16, 12), spacing=10)
        right.setMinimumHeight(300)
        hh = QHBoxLayout()
        hh.setSpacing(6)
        self.name = ElidedLabel("", 16, TEXT)
        self.dirty_lbl = label("", 13, YELLOW)
        hh.addWidget(self.name, 1)
        hh.addWidget(self.dirty_lbl)
        right.v.addLayout(hh)
        bar = FlowLayout(hspacing=6, vspacing=6)
        self.b_save = Btn("Save", "primary", h=32)
        self.b_ext = Btn("Open in other app", "default", "open", h=32)
        self.b_push = Btn("Send to Modal", "default", "upload", h=32)
        self.b_ren = Btn("Rename", "ghost", h=32)
        self.b_del = Btn("Delete", "ghost", h=32)
        self.b_dir = Btn("Folder", "ghost", "folder", h=32)
        self.b_save.clicked.connect(self.save)
        self.b_ext.clicked.connect(self.open_external)
        self.b_push.clicked.connect(self.push_current)
        self.b_ren.clicked.connect(self.rename)
        self.b_del.clicked.connect(self.delete)
        self.b_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(NB_DIR))))
        for b in (self.b_save, self.b_ext, self.b_push, self.b_ren, self.b_del, self.b_dir):
            bar.addWidget(b)
        self.bar_w = QWidget()
        self.bar_w.setLayout(bar)
        right.v.addWidget(self.bar_w)
        self.editor = NotebookEditor()
        self.editor.dirty_changed.connect(self._dirty_changed)
        right.v.addWidget(self.editor, 1)
        self.hint = label("Pick a notebook on the left, or press New.", 14, TEXT3)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.v.addWidget(self.hint, 1)
        body.addWidget(right, 3)

        sc_save = QShortcut(QKeySequence.StandardKey.Save, self)
        sc_save.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_save.activated.connect(self.save)
        win.sync.changed.connect(self._sync_changed)
        self._show_editor(False)
        self.refresh()
        self._sync_changed()

    # ---- UI state
    def _show_editor(self, on: bool):
        self.editor.setVisible(on)
        self.bar_w.setVisible(on)
        self.name.setVisible(on)
        self.dirty_lbl.setVisible(on)
        self.hint.setVisible(not on)

    def on_show(self):
        self.refresh()

    def _dirty_changed(self, d: bool):
        self.dirty_lbl.setText("● unsaved" if d else "")

    def _sync_changed(self):
        self.sync_msg.setFull(self.win.sync.msg)
        n = len(conflict_pairs())
        self.b_conf.setVisible(n > 0)
        if n:
            self.b_conf.setText(f"{n} conflict{'s' if n != 1 else ''}")
        busy = self.win.sync.busy
        self.b_sync.set_busy(busy, "Syncing…")
        self.b_sync.setEnabled(not busy)
        self.sync_line.set_active(busy)
        self.refresh()
        if self.cur and not self.editor.is_dirty():
            p = NB_DIR / self.cur
            if p.exists() and file_hash(p) != self.loaded_hash:
                self._open(self.cur)

    def _show_menu(self):
        self.menu.exec(self.b_opts.mapToGlobal(QPoint(0, self.b_opts.height())))

    def show_conflicts(self):
        ConflictDialog(self).exec()
        self._sync_changed()

    def resolve_conflict(self, copy_rel: str, orig_rel: str, mine: bool):
        copy, orig = NB_DIR / copy_rel, NB_DIR / orig_rel
        try:
            if not mine:                                  # take Modal's version
                shutil.copy2(copy, orig)
                st = load_state()
                st[orig_rel] = file_hash(orig)
                save_state(st)
            copy.unlink()
        except OSError as exc:
            self.win.toast(f"Could not finish: {exc}", "error")
            return
        if not mine and self.cur == orig_rel and not self.editor.is_dirty():
            self._open(orig_rel)
        self._list_sig = None
        self.refresh()

    def open_copy(self, copy_rel: str):
        if self.confirm_leave():
            self._open(copy_rel)

    def refresh(self):
        rels = local_notebooks()
        state = load_state()
        try:   # nothing changed since the last time: leave the list alone (no flicker, no extra work)
            sig = tuple((r, nb_status(r, state)[0], int((NB_DIR / r).stat().st_mtime)) for r in rels)
        except OSError:
            sig = None
        if sig is not None and sig == getattr(self, "_list_sig", None) and self.list.count() == len(rels):
            self._sync_selection()
            return
        self._list_sig = sig
        self._suppress = True
        self.list.clear()
        sel = -1
        for i, rel in enumerate(rels):
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, rel)
            it.setSizeHint(QSize(0, 56))
            self.list.addItem(it)
            self.list.setItemWidget(it, NbItem(rel, state))
            if rel == self.cur:
                sel = i
        if sel >= 0:
            self.list.setCurrentRow(sel)
        self._suppress = False

    # ---- selection / open
    def _sync_selection(self):
        """Keep the highlighted row on the notebook that is really open."""
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == self.cur:
                self._suppress = True
                self.list.setCurrentRow(i)
                self._suppress = False
                return

    def confirm_leave(self) -> bool:
        if not (self.cur and self.editor.is_dirty()):
            return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save changes to {self.cur}?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def _row_changed(self, row: int):
        if self._suppress or row < 0:
            return
        rel = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        if rel == self.cur:
            return
        if not self.confirm_leave():
            self._suppress = True
            self.refresh()
            self._suppress = False
            return
        self._open(rel)

    def _open(self, rel: str):
        path = NB_DIR / rel
        try:
            self.editor.load(path)
        except ValueError as exc:
            self.win.toast(f"Could not open {rel}: {exc}", "error")
            self.cur = None
            self._show_editor(False)
            return
        self.cur = rel
        self.loaded_hash = file_hash(path)
        self.name.setFull(rel)
        self._show_editor(True)
        self._dirty_changed(False)
        self._sync_selection()

    # ---- actions
    def save(self) -> bool:
        if not self.cur:
            return False
        try:
            self.editor.save()
        except OSError as exc:
            self.win.toast(f"Could not save: {exc}", "error")
            return False
        self.loaded_hash = file_hash(NB_DIR / self.cur)
        self.refresh()
        self.win.toast("Saved", "success")
        if SyncService.push_on_save():
            self.win.sync.push([self.cur])
        return True

    def push_current(self):
        if not self.cur:
            return
        if self.editor.is_dirty() and not self.save():
            return
        if not self.win.sync.ready():
            self.win.toast("Log in to Modal first (Setup)", "error")
            return
        self.win.sync.push([self.cur])

    def open_external(self):
        if self.cur:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(NB_DIR / self.cur)))

    def _unique(self, name: str) -> Path:
        p = NB_DIR / name
        i = 2
        while p.exists():
            p = NB_DIR / f"{Path(name).stem} ({i}).ipynb"
            i += 1
        return p

    @staticmethod
    def _clean(name: str) -> str:
        name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
        if not name:
            return ""
        return name if name.lower().endswith(".ipynb") else name + ".ipynb"

    def new_notebook(self):
        if not self.confirm_leave():
            return
        text, ok = QInputDialog.getText(self, "New notebook", "Name:", text="untitled")
        name = self._clean(text) if ok else ""
        if not name:
            return
        path = self._unique(name)
        path.write_text(json.dumps(blank_notebook(), indent=1) + "\n", encoding="utf-8")
        self.cur = path.relative_to(NB_DIR).as_posix()
        self.refresh()
        self._open(self.cur)

    def import_notebooks(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import notebooks", str(Path.home()),
                                                "Notebooks (*.ipynb);;All files (*)")
        last = None
        for f in files:
            dst = self._unique(Path(f).name)
            shutil.copy2(f, dst)
            last = dst
        if last is not None:
            if not self.confirm_leave():
                self.refresh()
                return
            self.cur = last.relative_to(NB_DIR).as_posix()
            self.refresh()
            self._open(self.cur)
            self.win.toast(f"Imported {len(files)} notebook(s)", "success")

    def rename(self):
        if not self.cur or not self.confirm_leave():
            return
        text, ok = QInputDialog.getText(self, "Rename notebook", "New name:", text=Path(self.cur).stem)
        name = self._clean(text) if ok else ""
        if not name:
            return
        old = NB_DIR / self.cur
        new = old.with_name(name)
        if new.exists():
            self.win.toast("A notebook with that name already exists", "error")
            return
        old.rename(new)
        st = load_state()
        st.pop(self.cur, None)
        save_state(st)
        self.cur = new.relative_to(NB_DIR).as_posix()
        self.refresh()
        self._open(self.cur)
        self.win.toast("Renamed here — the old name stays on Modal", "info")

    def delete(self):
        if not self.cur:
            return
        r = QMessageBox.question(self, "Delete notebook",
                                 f"Delete {self.cur} from this PC?\nThe copy on Modal is not deleted.",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        try:
            (NB_DIR / self.cur).unlink()
        except OSError as exc:
            self.win.toast(f"Could not delete: {exc}", "error")
            return
        st = load_state()
        st.pop(self.cur, None)
        save_state(st)
        self.cur = None
        self.editor.clear()
        self.editor._set_dirty(False)
        self._show_editor(False)
        self.refresh()
        self.win.toast("Deleted", "info")


# =============================================================================
#  Accounts (Modal profiles) + usage
# =============================================================================
def modal_config_path() -> Path:
    return Path(os.environ.get("MODAL_CONFIG_PATH") or (Path.home() / ".modal.toml"))


def read_profiles():
    """Reads the profile sections of ~/.modal.toml (no extra libraries needed)."""
    profiles = []
    try:
        text = modal_config_path().read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return profiles
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^\[(.+)\]$", line)
        if m:
            cur = {"name": m.group(1).strip().strip('"').strip("'"), "active": False}
            profiles.append(cur)
            continue
        if cur is not None:
            m = re.match(r"^active\s*=\s*(true|false)", line, re.I)
            if m:
                cur["active"] = m.group(1).lower() == "true"
    return profiles


def active_profile():
    env = os.environ.get("MODAL_PROFILE")
    if env:
        return env
    ps = read_profiles()
    for p in ps:
        if p["active"]:
            return p["name"]
    return ps[0]["name"] if len(ps) == 1 else None


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def _parse_json(lines):
    text = "\n".join(l for l in lines if not l.startswith("›"))
    dec = json.JSONDecoder()
    tries = 0
    for i, ch in enumerate(text):
        if ch in "[{":
            tries += 1
            if tries > 60:
                break
            try:
                obj, _ = dec.raw_decode(text[i:])
                return obj
            except ValueError:
                continue
    return None


def _sum_cost(data) -> float:
    rows = data
    if isinstance(data, dict):
        rows = next((v for v in data.values() if isinstance(v, list)), [])
    total = 0.0
    if isinstance(rows, list):
        for r in rows:
            if isinstance(r, dict):
                try:
                    total += float(r.get("cost", 0) or 0)
                except (TypeError, ValueError):
                    pass
    return total


def _find_credit(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "credit" in str(k).lower() and isinstance(v, (int, float, str)):
                return v
        for v in obj.values():
            r = _find_credit(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_credit(v)
            if r is not None:
                return r
    return None


class Usage(QObject):
    """Spend numbers for the active Modal account (from `modal billing`)."""
    updated = Signal()

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.month = None
        self.today = None
        self.credit = None
        self.credit_text = ""
        self.msg = ""
        self.loading = False
        self.needs_update = False
        self.summary_cost = None
        self._pending = 0
        self._gen = 0
        self._procs = {}
        self.timer = QTimer(self)
        self.timer.setInterval(600000)
        self.timer.timeout.connect(self._auto)
        self.timer.start()

    @staticmethod
    def total() -> float:
        """Monthly credit of the ACTIVE account (each account can have its own)."""
        try:
            qs = QSettings(SETTINGS_ORG, "App")
            acct = active_profile()
            v = qs.value(f"credit_total/{acct}", None) if acct else None
            if v in (None, ""):
                v = qs.value("credit_total", 30)
            return float(v)
        except Exception:  # noqa: BLE001
            return 30.0

    def reset(self):
        """Forget the numbers (the account changed) and ignore anything still on its way."""
        self._gen += 1
        self.loading = False
        self.month = self.today = self.credit = self.summary_cost = None
        self.credit_text = ""
        self.msg = ""
        self.updated.emit()

    def used(self):
        """Credits used. Modal reports credits as a negative number, so use its size."""
        if self.credit is not None:
            return abs(self.credit)
        return self.month

    def left(self):
        t, u = self.total(), self.used()
        if u is None or t <= 0:
            return None
        return max(0.0, t - u)

    def _auto(self):
        h = getattr(self.win, "home", None)
        if h is not None and h.state == "running":
            self.refresh()

    def refresh(self):
        if self.loading:
            return
        if not (modal_installed() and modal_logged_in()):
            self.month = self.today = self.credit = None
            self.credit_text = ""
            self.msg = "Log in to Modal to see usage"
            self.updated.emit()
            return
        self.loading = True
        self.msg = "Updating…"
        self._pending = 3
        self.updated.emit()
        gen, acct = self._gen, active_profile()
        self._fetch("month", ["-m", "modal", "billing", "report", "--for", "this month", "-r", "h", "--json"], gen, acct)
        self._fetch("today", ["-m", "modal", "billing", "report", "--for", "today", "-r", "h", "--json"], gen, acct)
        self._fetch("summary", ["-m", "modal", "billing", "summary", "--json"], gen, acct)

    def _fetch(self, key, args, gen, acct):
        lines = []
        p = Proc(self)
        p.line.connect(lines.append)
        self._procs[key] = p
        p.start(args, on_done=lambda code: self._got(key, args, code, lines, gen, acct), env=_pe(acct))

    def _got(self, key, args, code, lines, gen, acct):
        if gen != self._gen:
            return                                     # the account changed meanwhile
        text = "\n".join(lines)
        no_command = code != 0 and "No such command" in text
        if code != 0 and "No such command 'billing'" in text:
            self.needs_update = True      # this Modal version has no billing commands
        data = _parse_json(lines) if code == 0 else None
        if key == "summary" and code == 0:
            for l in lines:
                if not l.startswith("›"):
                    self.win.log(l)
        if key == "month" and data is not None:
            self.needs_update = False
        if data is None and not no_command and key in ("month", "today") and "-r" in args:
            a = list(args)
            i = a.index("-r")
            del a[i:i + 2]
            self._fetch(key, a, gen, acct)
            return
        if key == "month":
            self.month = _sum_cost(data) if data is not None else None
        elif key == "today":
            self.today = _sum_cost(data) if data is not None else None
        else:
            self.summary_cost = None
            if isinstance(data, dict):
                try:
                    self.summary_cost = float(data.get("metered_cost"))
                except (TypeError, ValueError):
                    pass
            val = _find_credit(data) if data is not None else None
            self.credit, self.credit_text = None, ""
            if val is not None:
                try:
                    self.credit = float(val)
                except (TypeError, ValueError):
                    self.credit_text = str(val)
        self._pending -= 1
        if self._pending <= 0:
            self.loading = False
            if self.month is None and self.summary_cost is not None:
                self.month = self.summary_cost
            failed = self.month is None and self.today is None
            if self.needs_update:
                self.msg = "Your Modal is too old for billing info"
            else:
                self.msg = "Could not read usage — see the log panel" if failed else "Updated " + time.strftime("%H:%M")
            self.updated.emit()


class UsageBar(QWidget):
    """Animated progress bar: how much of the monthly credit is used."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._f = 0.0
        self._a = QPropertyAnimation(self, b"frac", self)
        self._a.setDuration(900)
        self._a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._loading = False
        self._lt = 0.0
        self._la = QVariantAnimation(self)
        self._la.setStartValue(0.0)
        self._la.setEndValue(1.0)
        self._la.setDuration(1200)
        self._la.setLoopCount(-1)
        self._la.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._la.valueChanged.connect(self._load_tick)

    def _load_tick(self, v):
        self._lt = float(v)
        self.update()

    def set_loading(self, on: bool):
        if on == self._loading:
            return
        self._loading = on
        if on:
            self._la.start()
        else:
            self._la.stop()
        self.update()

    def _get_f(self):
        return self._f

    def _set_f(self, v):
        self._f = v
        self.update()

    frac = Property(float, _get_f, _set_f)

    def set_frac(self, f: float):
        f = max(0.0, min(1.0, f))
        self._a.stop()
        self._a.setStartValue(self._f)
        self._a.setEndValue(f)
        self._a.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor("#3a3a3a"))
        if self._loading:
            p.save()
            p.setClipPath(path)
            band = max(60.0, r.width() * 0.3)
            x = (r.width() + band) * self._lt - band
            grad = QLinearGradient(x, 0, x + band, 0)
            grad.setColorAt(0.0, QColor(255, 255, 255, 0))
            grad.setColorAt(0.5, QColor(255, 255, 255, 70))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(grad))
            p.drawRect(QRectF(x, 0, band, r.height()))
            p.restore()
        f = max(0.0, min(1.0, self._f))
        if f <= 0.0:
            return
        if f < 0.75:
            col = QColor(ACCENT)
        elif f < 0.9:
            col = mix(ACCENT, YELLOW, (f - 0.75) / 0.15)
        else:
            col = mix(YELLOW, RED, min(1.0, (f - 0.9) / 0.1))
        p.setClipPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        w = max(r.height(), r.width() * f)
        p.drawRoundedRect(QRectF(0, 0, w, r.height()), r.height() / 2, r.height() / 2)


class UsageCard(Card):
    """Account switcher and credit usage in one compact card."""

    def __init__(self, win, billing_btn=False):
        super().__init__(pad=(16, 12, 16, 12), spacing=8)
        self.win = win
        top = QHBoxLayout()
        top.setSpacing(6)
        self.account_bar = AccountBar(win)
        top.addWidget(self.account_bar, 1)
        self.b_upd = Btn("Update Modal", "primary", "download", h=30)
        self.b_upd.clicked.connect(self.update_modal)
        self.b_upd.hide()
        top.addWidget(self.b_upd)
        self.upd = Proc(self, log=win.log)
        self.b_ref = IconBtn("refresh", "Refresh usage")
        self.b_ref.clicked.connect(win.usage.refresh)
        top.addWidget(self.b_ref)
        if billing_btn:
            b = IconBtn("open", "Open your usage and billing page on modal.com")
            b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://modal.com/settings/usage")))
            top.addWidget(b)
        self.v.addLayout(top)

        self.bar = UsageBar()
        self.v.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.bar_l = label("", 12, TEXT2)
        self.bar_r = label("", 12, TEXT2)
        row.addWidget(self.bar_l)
        row.addStretch(1)
        row.addWidget(self.bar_r)
        self.v.addLayout(row)
        self.msg = ElidedLabel("", 12, YELLOW)
        self.msg.hide()
        self.v.addWidget(self.msg)
        win.usage.updated.connect(self.sync)
        self.sync()

    def update_modal(self):
        if self.upd.running():
            return
        self.b_upd.set_busy(True, "Updating…")
        self.b_upd.setEnabled(False)

        def fin(code):
            self.b_upd.set_busy(False)
            self.b_upd.setEnabled(True)
            if code == 0:
                self.win.toast("Modal updated", "success")
                self.win.usage.needs_update = False
                self.win.usage.refresh()
                self.win.setup.refresh()
            else:
                self.win.toast("Update failed — check the log panel", "error")

        if not self.upd.start(["-m", "pip", "install", "--upgrade", "modal"], on_done=fin):
            fin(-1)

    def sync(self):
        u = self.win.usage
        used, total, left = u.used(), u.total(), u.left()
        self.b_upd.setVisible(u.needs_update)
        self.bar.set_loading(u.loading)
        self.b_ref.set_spinning(u.loading)

        def money(x):
            return "—" if x is None else f"${x:,.2f}"

        if used is not None and total > 0:
            self.bar.show()
            self.bar.set_frac(used / total)
            self.bar_l.setText(f"{money(used)} used of ${total:,.0f}")
            self.bar_r.setText(f"{money(left)} left")
        elif u.loading and u.month is None:
            self.bar.show()
            self.bar.set_frac(0.0)
            self.bar_l.setText("Loading usage…")
            self.bar_r.setText("")
        else:
            self.bar.hide()
            self.bar_l.setText(f"{money(u.month)} spent this month" if u.month is not None else "Usage not loaded yet")
            self.bar_r.setText("")
        tip = (f"This month before credits: {money(u.month)}  ·  today: {money(u.today)}\n"
               "Credits come from Modal's billing and can lag a few minutes. "
               "Set your monthly total in Settings.")
        for w in (self.bar, self.bar_l, self.bar_r):
            w.setToolTip(tip)
        problem = u.needs_update or u.msg.startswith(("Could not", "Log in", "Your Modal"))
        self.msg.setVisible(bool(problem))
        self.msg.setFull(u.msg)
        self.b_ref.setToolTip("Refresh usage" + (f" ({u.msg})" if u.msg else ""))


class AccountBar(QWidget):
    """The active Modal account: switch to another saved account, or add one, without logging out."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.proc = Proc(self, log=win.log)
        lay = FlowLayout(self, hspacing=10, vspacing=8)
        self.combo = Combo()
        self.combo.setMinimumWidth(210)
        self.combo.setToolTip("Switch Modal account. Each account has its own drive and tokens.")
        self.b_add = Btn("Add account", "default", "add", h=36)
        self.b_add.setToolTip("Sign in to the other account in your browser first (or use a private window), "
                              "then press this. Your saved accounts stay in the list.")
        lay.addWidget(self.combo)
        lay.addWidget(self.b_add)
        self.combo.currentIndexChanged.connect(self._picked)
        self.b_add.clicked.connect(self.add_account)
        self.rebuild()

    def rebuild(self):
        profs = read_profiles()
        active = active_profile()
        self.combo.blockSignals(True)
        self.combo.clear()
        if not profs:
            self.combo.addItem("Not logged in", None)
            self.combo.setEnabled(False)
        else:
            self.combo.setEnabled(True)
            for pr in profs:
                self.combo.addItem(pr["name"], pr["name"])
            self.combo.setCurrentIndex(max(0, self.combo.findData(active)))
        self.combo.blockSignals(False)

    def _busy(self) -> bool:
        if self.win.home.state in ("starting", "running", "stopping"):
            self.win.toast("Stop the running session before changing accounts", "error")
            return True
        if self.proc.running():
            return True
        if self.win.sync.busy or self.win.volume_page._busy:
            self.win.toast("Wait for the transfer in progress to finish first", "info")
            return True
        if not self.win.volume_page.confirm_leave():
            return True
        if not modal_installed():
            self.win.toast("Modal is not installed yet — open Setup first", "error")
            self.win.goto("setup")
            return True
        return False

    def _picked(self, i: int):
        name = self.combo.itemData(i)
        if not name or name == active_profile():
            return
        if self._busy():
            self.rebuild()          # put the selection back
            return
        self.combo.setEnabled(False)           # greyed out until the switch is done
        self.proc.start(["-m", "modal", "profile", "activate", name],
                        on_done=self._after(f"Switched to {name}"))

    def _after(self, ok_msg):
        def fin(code):
            self.b_add.set_busy(False)
            self.b_add.setEnabled(True)
            self.rebuild()
            if code == 0:
                self.win.toast(ok_msg, "success")
                self.win.usage.reset()
                self.win.usage.refresh()
                self.win.setup.refresh()
                self.win.secrets_page.account_changed()
                self.win.volume_page.account_changed()
                self.win.settings.on_show()
                self.win.notebooks._list_sig = None
                self.win.notebooks.refresh()
            else:
                self.win.toast("That didn't work — check the log panel", "error")
        return fin

    def add_account(self):
        if self._busy():
            return
        self.b_add.set_busy(True, "Waiting for browser…")
        self.b_add.setEnabled(False)
        if not self.proc.start(["-m", "modal", "token", "new"], on_done=self._after("Account added and activated")):
            self.b_add.set_busy(False)
            self.b_add.setEnabled(True)


# =============================================================================
#  Code colors (VS Code "Dark+") for notebook cells
# =============================================================================
def _fmt(color: str, bold=False, italic=False, underline=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    if underline:
        f.setFontUnderline(True)
    return f


_Q3 = "'" * 3
_QQ3 = '"' * 3


class PyHighlighter(QSyntaxHighlighter):
    CONTROL = {"if", "elif", "else", "for", "while", "break", "continue", "return", "import", "from", "try",
               "except", "finally", "raise", "with", "as", "yield", "assert", "async", "await", "pass", "del"}
    KEYWORD = {"def", "class", "lambda", "None", "True", "False", "and", "or", "not", "in", "is", "global",
               "nonlocal", "self", "cls"}
    TYPES = {"int", "str", "float", "bool", "list", "dict", "set", "tuple", "bytes", "object", "type",
             "Exception", "ValueError", "TypeError", "KeyError", "OSError", "RuntimeError"}
    BUILTINS = {"print", "len", "range", "open", "enumerate", "zip", "map", "filter", "sorted", "sum", "min", "max",
                "abs", "round", "isinstance", "super", "input", "getattr", "setattr", "hasattr", "any", "all",
                "reversed", "iter", "next", "repr", "format", "vars", "dir", "id", "hash", "chr", "ord", "eval", "exec"}
    TOKEN = re.compile(
        r"(?P<comment>#.*)"
        r"|(?P<tstr>[rRbBuUfF]{0,2}(?:" + _Q3 + "|" + _QQ3 + "))"
        r"|(?P<str>[rRbBuUfF]{0,2}(?:'(?:\\.|[^'\\])*'?|\"(?:\\.|[^\"\\])*\"?))"
        r"|(?P<num>\b0[xX][0-9a-fA-F_]+\b|\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b)"
        r"|(?P<deco>@[A-Za-z_][\w.]*)"
        r"|(?P<id>[A-Za-z_][A-Za-z_0-9]*)")
    MAGIC = re.compile(r"^\s*([!%]{1,2}[A-Za-z_]*)")

    def __init__(self, doc):
        super().__init__(doc)
        self.f_comment = _fmt("#6A9955", italic=True)
        self.f_str = _fmt("#CE9178")
        self.f_num = _fmt("#B5CEA8")
        self.f_ctrl = _fmt("#C586C0")
        self.f_kw = _fmt("#569CD6")
        self.f_type = _fmt("#4EC9B0")
        self.f_func = _fmt("#DCDCAA")
        self.f_var = _fmt("#9CDCFE")
        self.f_magic = _fmt("#C586C0", bold=True)

    def highlightBlock(self, text: str):
        n = len(text)
        pos = 0
        self.setCurrentBlockState(0)
        prev = self.previousBlockState()
        if prev in (1, 2):
            delim = _Q3 if prev == 1 else _QQ3
            end = text.find(delim)
            if end == -1:
                self.setFormat(0, n, self.f_str)
                self.setCurrentBlockState(prev)
                return
            self.setFormat(0, end + 3, self.f_str)
            pos = end + 3
        magic = False
        m = self.MAGIC.match(text) if pos == 0 else None
        if m:
            magic = True
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.f_magic)
            pos = m.end(1)
        last_word = ""
        while pos < n:
            m = self.TOKEN.search(text, pos)
            if not m:
                break
            kind = m.lastgroup
            s0, e0 = m.span()
            if kind == "comment":
                self.setFormat(s0, n - s0, self.f_comment)
                return
            if kind == "tstr":
                delim = m.group()[-3:]
                end = text.find(delim, e0)
                if end == -1:
                    self.setFormat(s0, n - s0, self.f_str)
                    self.setCurrentBlockState(1 if delim == _Q3 else 2)
                    return
                self.setFormat(s0, end + 3 - s0, self.f_str)
                pos = end + 3
                continue
            if kind == "str":
                self.setFormat(s0, e0 - s0, self.f_str)
            elif kind == "num":
                self.setFormat(s0, e0 - s0, self.f_num)
            elif kind == "deco":
                self.setFormat(s0, e0 - s0, self.f_func)
            elif kind == "id" and not magic:
                w = m.group()
                if w in self.CONTROL:
                    f = self.f_ctrl
                elif w in self.KEYWORD:
                    f = self.f_kw
                elif last_word == "def":
                    f = self.f_func
                elif last_word == "class":
                    f = self.f_type
                elif w in self.TYPES:
                    f = self.f_type
                elif w in self.BUILTINS or text[e0:e0 + 1] == "(":
                    f = self.f_func
                else:
                    f = self.f_var
                self.setFormat(s0, e0 - s0, f)
                last_word = w
            pos = e0


class MdHighlighter(QSyntaxHighlighter):
    RULES = [
        (re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__"), "f_bold"),
        (re.compile(r"(?<![*\w])\*[^*\n]+\*(?!\*)"), "f_it"),
        (re.compile(r"`[^`\n]+`"), "f_code"),
        (re.compile(r"\[[^\]\n]+\]\([^)\n]+\)"), "f_link"),
    ]

    def __init__(self, doc):
        super().__init__(doc)
        self.f_head = _fmt("#569CD6", bold=True)
        self.f_code = _fmt("#CE9178")
        self.f_list = _fmt("#6796E6", bold=True)
        self.f_quote = _fmt("#6A9955")
        self.f_bold = _fmt("#DCDCAA", bold=True)
        self.f_link = _fmt("#4FC1FF", underline=True)
        self.f_it = _fmt("#D4D4D4", italic=True)

    def highlightBlock(self, text: str):
        fence = text.strip().startswith("```")
        in_fence = self.previousBlockState() == 1
        if fence:
            self.setFormat(0, len(text), self.f_code)
            self.setCurrentBlockState(0 if in_fence else 1)
            return
        if in_fence:
            self.setFormat(0, len(text), self.f_code)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)
        if re.match(r"^\s{0,3}#{1,6}\s", text):
            self.setFormat(0, len(text), self.f_head)
            return
        if re.match(r"^\s*>", text):
            self.setFormat(0, len(text), self.f_quote)
            return
        m = re.match(r"^\s*([-*+]|\d+[.)])\s", text)
        if m:
            self.setFormat(m.start(1), m.end(1) - m.start(1), self.f_list)
        for rx, name in self.RULES:
            for mm in rx.finditer(text):
                self.setFormat(mm.start(), mm.end() - mm.start(), getattr(self, name))


# =============================================================================
#  Log panel (always visible at the bottom, colored output)
# =============================================================================
_ERR_RE = re.compile(r"(?i)(error|exception|traceback|failed|failure|fatal|denied|unauthorized|forbidden|"
                     r"no such|not found|cannot|can't|could not|couldn't|refused|invalid)")
_WARN_RE = re.compile(r"(?i)(warn|deprecat|retrying)")
_OK_RE = re.compile(r"(?i)(\b(success|successfully|done|created|saved|complete|completed|ready|stopped|installed|"
                    r"updated|synced|logged in|switched|downloaded|uploaded)\b|✓)")


def classify_log(text: str):
    """Returns (color, bold, kind) for one log line."""
    t = text.strip()
    if text.startswith("›"):
        return ACCENT, False, "cmd"
    if ">>>" in text or t.startswith("https://"):
        return "#4FC1FF", True, "link"
    if t.startswith(("Traceback", 'File "')) or _ERR_RE.search(text):
        return "#F14C4C", False, "error"
    if _WARN_RE.search(text):
        return "#E5C07B", False, "warn"
    if _OK_RE.search(text):
        return "#6CCB5F", False, "ok"
    return "#CCCCCC", False, "text"


class LogView(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        f = QFont()
        f.setFamilies(MONO_FAMILIES)
        f.setPixelSize(13)
        self.setFont(f)
        self.setStyleSheet("QPlainTextEdit{background:#1e1e1e;border:1px solid #333333;border-radius:8px;"
                           "padding:6px 8px;color:#cccccc;selection-background-color:#264f78;}")

    def add(self, text: str) -> str:
        color, bold, kind = classify_log(text)
        bar = self.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cur = QTextCursor(self.document())
        cur.movePosition(QTextCursor.MoveOperation.End)
        if self.document().characterCount() > 1:
            cur.insertBlock()
        cur.insertText(text, _fmt(color, bold=bold))
        if at_bottom:
            bar.setValue(bar.maximum())
        return kind


class ProgressLine(QWidget):
    """A thin loading line that glides along. It never changes the layout: it only fades in and out."""

    def __init__(self, height=3):
        super().__init__()
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._v = 0.0
        self._op = 0.0
        self._active = False
        self._loop = QVariantAnimation(self)
        self._loop.setStartValue(0.0)
        self._loop.setEndValue(1.0)
        self._loop.setDuration(1300)
        self._loop.setLoopCount(-1)
        self._loop.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._loop.valueChanged.connect(self._tick)
        self._fade = QPropertyAnimation(self, b"fade", self)
        self._fade.setDuration(240)
        self._fade.finished.connect(self._after)

    def _tick(self, v):
        self._v = float(v)
        self.update()

    def _get_fade(self):
        return self._op

    def _set_fade(self, v):
        self._op = v
        self.update()

    fade = Property(float, _get_fade, _set_fade)

    def _after(self):
        if not self._active:
            self._loop.stop()
            self.update()

    def set_active(self, on: bool):
        if on == self._active:
            return
        self._active = on
        self._fade.stop()
        self._fade.setStartValue(self._op)
        self._fade.setEndValue(1.0 if on else 0.0)
        if on:
            self._loop.start()
        self._fade.start()

    def paintEvent(self, _):
        if self._op <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._op)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        p.fillPath(path, QColor(255, 255, 255, 22))
        p.setClipPath(path)
        cw = r.width() * 0.34
        x = (r.width() + cw) * self._v - cw
        grad = QLinearGradient(x, 0, x + cw, 0)
        grad.setColorAt(0.0, QColor(96, 205, 255, 0))
        grad.setColorAt(0.5, QColor(96, 205, 255, 255))
        grad.setColorAt(1.0, QColor(96, 205, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(x, 0, cw, r.height()))


class SkeletonList(QWidget):
    """Grey placeholder rows with a light shimmer, shown while a list loads for the first time."""
    WIDTHS = (0.52, 0.38, 0.66, 0.30, 0.58, 0.44, 0.50, 0.36)

    def __init__(self, min_height=260):
        super().__init__()
        self.setMinimumHeight(min_height)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1400)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._tick)
        self.hide()

    def _tick(self, v):
        self._t = float(v)
        self.update()

    def showEvent(self, e):
        self._anim.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._anim.stop()
        super().hideEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        rows = max(1, min(10, (h - 8) // 34))
        path = QPainterPath()
        for i in range(rows):
            y = 8 + i * 34
            path.addRoundedRect(QRectF(12, y, max(40.0, (w - 110) * self.WIDTHS[i % len(self.WIDTHS)]), 16), 6, 6)
            path.addRoundedRect(QRectF(w - 78, y, 56, 16), 6, 6)
        p.fillPath(path, QColor(255, 255, 255, 18))
        p.setClipPath(path)
        band = max(120.0, w * 0.3)
        x = (w + band) * self._t - band
        grad = QLinearGradient(x, 0, x + band, 0)
        grad.setColorAt(0.0, QColor(255, 255, 255, 0))
        grad.setColorAt(0.5, QColor(255, 255, 255, 46))
        grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(x, 0, band, h))


class IconBtn(QPushButton):
    def __init__(self, icon: str, tip: str, size=28):
        super().__init__()
        self.icon_name = icon
        self._h = 0.0
        self._spin = 0.0
        self._spinning = False
        self.setFixedSize(size, size)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._a = QPropertyAnimation(self, b"hover", self)
        self._a.setDuration(130)
        self._spin_anim = QVariantAnimation(self)
        self._spin_anim.setStartValue(0.0)
        self._spin_anim.setEndValue(360.0)
        self._spin_anim.setDuration(900)
        self._spin_anim.setLoopCount(-1)
        self._spin_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._spin_anim.valueChanged.connect(self._spin_tick)
        self._settle = QVariantAnimation(self)           # finishes the turn smoothly when loading ends
        self._settle.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._settle.valueChanged.connect(self._spin_tick)
        self._settle.finished.connect(self._spin_done)

    def _spin_tick(self, v):
        self._spin = float(v)
        self.update()

    def _spin_done(self):
        self._spin = 0.0
        self.update()

    def set_spinning(self, on: bool):
        if on == self._spinning:
            return
        self._spinning = on
        if on:
            self._settle.stop()
            self._spin_anim.start()
        else:
            cur = self._spin
            self._spin_anim.stop()
            if cur > 1.0:
                self._settle.setStartValue(cur)
                self._settle.setEndValue(360.0)
                self._settle.setDuration(int(280 + (360.0 - cur) / 360.0 * 420))
                self._settle.start()
            else:
                self._spin_done()

    def _get_h(self):
        return self._h

    def _set_h(self, v):
        self._h = v
        self.update()

    hover = Property(float, _get_h, _set_h)

    def set_icon(self, name: str):
        self.icon_name = name
        self.update()

    def _to(self, v):
        self._a.stop()
        self._a.setStartValue(self._h)
        self._a.setEndValue(v)
        self._a.start()

    def enterEvent(self, e):
        self._to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._to(0.0)
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(26 * self._h + (14 if self.isDown() else 0))))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        p.setPen(mix(TEXT2, TEXT, max(self._h, 1.0 if self._spinning else 0.0)))
        p.setFont(icon_font(14))
        if self._spin:
            cx, cy = self.width() / 2, self.height() / 2
            p.translate(cx, cy)
            p.rotate(self._spin)
            p.translate(-cx, -cy)
        p.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, glyph(self.icon_name))


class LogDock(QFrame):
    COMPACT = 112

    def __init__(self):
        super().__init__()
        self.setObjectName("logdock")
        self._open = QSettings(SETTINGS_ORG, "App").value("log_open", False, type=bool)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 10)
        v.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        ic = QLabel(glyph("log"))
        ic.setFont(icon_font(14))
        ic.setStyleSheet(f"color:{TEXT2};background:transparent;")
        head.addWidget(ic)
        head.addWidget(label("Log", 13, TEXT2, semi=True))
        self.err_dot = Dot(14)
        self.err_dot.set_state("#F14C4C", True)
        self.err_dot.hide()
        head.addWidget(self.err_dot)
        head.addStretch(1)
        self.b_clear = IconBtn("trash", "Clear the log")
        self.b_copy = IconBtn("copy", "Copy the whole log")
        self.b_exp = IconBtn("chevup", "Show more lines")
        self.b_clear.clicked.connect(self._clear)
        self.b_copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.view.toPlainText()))
        self.b_exp.clicked.connect(lambda: self.set_expanded(not self._open))
        for b in (self.b_clear, self.b_copy, self.b_exp):
            head.addWidget(b)
        v.addLayout(head)
        self.view = LogView()
        v.addWidget(self.view)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda x: self.view.setFixedHeight(int(x)))
        self.view.setFixedHeight(self._target())
        self.b_exp.set_icon("chevdown" if self._open else "chevup")
        self.b_exp.setToolTip("Show fewer lines" if self._open else "Show more lines")

    def _target(self) -> int:
        win = self.window()
        h = win.height() if win is not None else 800
        if not self._open:
            return self.COMPACT if h >= 700 else 80
        return max(160, min(420, int(h * 0.40)))

    def refit(self):
        if self._anim.state() != QVariantAnimation.State.Running:
            self.view.setFixedHeight(self._target())

    def _clear(self):
        self.view.clear()
        self.err_dot.hide()

    def set_expanded(self, on: bool, animate=True):
        self._open = on
        QSettings(SETTINGS_ORG, "App").setValue("log_open", on)
        self.b_exp.set_icon("chevdown" if on else "chevup")
        self.b_exp.setToolTip("Show fewer lines" if on else "Show more lines")
        if on:
            self.err_dot.hide()
        end = self._target()
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self.view.height())
            self._anim.setEndValue(end)
            self._anim.start()
        else:
            self.view.setFixedHeight(end)

    def add(self, text: str):
        kind = self.view.add(text)
        if kind == "error" and not self._open:
            self.err_dot.show()


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedHeight(40)
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 0, 4, 0)
        h.setSpacing(10)
        logo = QLabel(glyph("cloud"))
        logo.setFont(icon_font(16))
        logo.setStyleSheet(f"color:{ACCENT};background:transparent;")
        h.addWidget(logo)
        h.addWidget(label(APP_TITLE, 13, TEXT2))
        h.addStretch(1)
        self.b_min = CapBtn("min")
        self.b_max = CapBtn("max")
        self.b_close = CapBtn("close", danger=True)
        self.b_min.clicked.connect(win.showMinimized)
        self.b_max.clicked.connect(self.toggle_max)
        self.b_close.clicked.connect(win.close)
        for b in (self.b_min, self.b_max, self.b_close):
            h.addWidget(b)

    def toggle_max(self):
        if self.win.isMaximized():
            self.win.showNormal()
        else:
            self.win.showMaximized()

    def set_maximized(self, mx: bool):
        self.b_max.set_icon("restore" if mx else "max")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_max()


class MainWindow(QWidget):
    M = 14
    SIDE_W = 232
    SIDE_C = 64
    COMPACT_BELOW = 980

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
                         | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(APP_TITLE)
        self.setMouseTracking(True)
        scr = QGuiApplication.primaryScreen()
        avail = scr.availableGeometry() if scr is not None else None
        aw, ah = (avail.width(), avail.height()) if avail is not None else (1366, 768)
        w = max(600, min(1160, int(aw * 0.88) - 2 * self.M))
        h = max(460, min(780, int(ah * 0.88) - 2 * self.M))
        self.resize(w + 2 * self.M, h + 2 * self.M)
        self.setMinimumSize(min(720, w) + 2 * self.M, min(520, h) + 2 * self.M)
        if avail is not None:
            self.move(avail.x() + (aw - self.width()) // 2, avail.y() + (ah - self.height()) // 2)
        self._shown = False
        self._closing = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.M, self.M, self.M, self.M)
        outer.setSpacing(0)
        shell = QWidget()
        shell.setCursor(Qt.CursorShape.ArrowCursor)
        outer.addWidget(shell)
        sl = QVBoxLayout(shell)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        self.titlebar = TitleBar(self)
        sl.addWidget(self.titlebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 10, 8)
        body.setSpacing(0)
        sl.addLayout(body, 1)

        # sidebar (status badge is created first: pages update it while loading)
        side = QWidget()
        self.side = side
        side.setFixedWidth(self.SIDE_W)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 4, 10, 10)
        sv.setSpacing(2)
        self.log_dock = LogDock()
        wrap = QHBoxLayout()
        wrap.setContentsMargins(10, 0, 10, 10)
        wrap.addWidget(self.log_dock)
        sl.addLayout(wrap)
        self.usage = Usage(self)
        self.sync = SyncService(self)
        self.guard = SessionGuard(self)
        self.home = HomePage(self)
        self.notebooks = NotebooksPage(self)
        self.setup = SetupPage(self)
        self.secrets_page = SecretsPage(self)
        self.volume_page = VolumePage(self)
        self.settings = SettingsPage(self)
        self.pages = [("home", "Home", "home", self.home),
                      ("notebooks", "Notebooks", "notebook", self.notebooks),
                      ("setup", "Setup", "setup", self.setup),
                      ("secrets", "Tokens", "secret", self.secrets_page),
                      ("volume", "Volume", "files", self.volume_page),
                      ("settings", "Settings", "settings", self.settings)]
        self.nav = []
        self.stack = FadeStack()
        for i, (key, text, icon, page) in enumerate(self.pages):
            nb = NavButton(text, icon)
            nb.clicked.connect(lambda _=False, k=key: self.goto(k))
            sv.addWidget(nb)
            self.nav.append(nb)
            self.stack.addWidget(page)
        self.nav[0].set_selected(True, animate=False)
        sv.addStretch(1)
        body.addWidget(side)

        panel = QFrame()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.stack)
        body.addWidget(panel, 1)

        self.toast_w = Toast(self)
        set_write_hook(lambda msg: self.toast(msg, "error"))
        QTimer.singleShot(1500, self.usage.refresh)
        QTimer.singleShot(2500, lambda: self.secrets_page.ensure_active())
        QTimer.singleShot(4000, self._startup_check)

    def _startup_check(self):
        """A session left over from an earlier run (crash, closed terminal…) still costs credit.
        Every saved account is checked, not only the active one."""
        if self.home.state != "idle" or not (modal_installed() and modal_logged_in()):
            return
        names = [pr["name"] for pr in read_profiles()] or [None]
        queue = list(names)

        def next_account():
            if not queue or self.home.state != "idle":
                return
            prof = queue.pop(0)

            def got(ids):
                if ids and self.home.state == "idle":
                    who = f" on account “{prof}”" if prof and len(names) > 1 else ""
                    r = QMessageBox.question(
                        self, "A session is still running",
                        f"A session is still running{who} (" + ", ".join(ids) + ") and keeps using "
                        "credit.\n\nStop it now?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                    if r == QMessageBox.StandardButton.Yes:
                        self.guard.stop_ids(ids, lambda ok: (self.toast(
                            "Old session stopped" if ok else "Could not stop it — check modal.com/apps",
                            "success" if ok else "error"), next_account()), profile=prof)
                        return
                next_account()

            self.guard.find(got, profile=prof)

        next_account()

    # ---- api for pages
    # ---- api for pages
    def log(self, text: str):
        self.log_dock.add(text)

    def toast(self, text: str, kind="info"):
        self.toast_w.show_message(text, kind)

    def goto(self, key: str):
        if key == "log":
            self.log_dock.set_expanded(True)
            return
        for i, (k, _t, _i, page) in enumerate(self.pages):
            if k == key:
                for j, nb in enumerate(self.nav):
                    nb.set_selected(j == i)
                self.stack.slide_to(i)
                page.on_show()
                return

    # ---- responsive layout
    def _apply_compact(self, on: bool):
        first = not hasattr(self, "_compact")
        if not first and on == self._compact:
            return
        self._compact = on
        for nb in self.nav:
            nb.set_compact(on)
        target = self.SIDE_C if on else self.SIDE_W
        if first or not self.isVisible():
            self.side.setFixedWidth(target)
            return
        anim = QVariantAnimation(self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(self.side.width())
        anim.setEndValue(target)
        anim.valueChanged.connect(lambda v: self.side.setFixedWidth(int(v)))
        anim.start()
        self._side_anim = anim

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "side") and hasattr(self, "nav") and self.layout() is not None:
            m = self.layout().contentsMargins().left()
            self._apply_compact(self.width() - 2 * m < self.COMPACT_BELOW)
        dock = getattr(self, "log_dock", None)
        if dock is not None:
            dock.refit()

    # ---- painting
    def _shadow_pixmap(self) -> QPixmap:
        """The soft shadow is drawn once per window size and then reused."""
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if getattr(self, "_sh_key", None) == key:
            return self._sh_pm
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setBrush(Qt.BrushStyle.NoBrush)
        r = QRectF(self.rect()).adjusted(self.M, self.M, -self.M, -self.M)
        for i in range(1, self.M + 1):
            a = int(52 * (1 - i / (self.M + 1)) ** 2.4)
            q.setPen(QPen(QColor(0, 0, 0, a), 1))
            q.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), 10 + i, 10 + i)
        q.end()
        self._sh_key, self._sh_pm = key, pm
        return pm

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mx = self.isMaximized()
        m = 0 if mx else self.M
        rad = 0 if mx else 10
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        if not mx:
            p.drawPixmap(0, 0, self._shadow_pixmap())
        p.setPen(QPen(QColor("#3c3c3c"), 1))
        p.setBrush(QColor(BG))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.WindowStateChange and hasattr(self, "titlebar"):
            mx = self.isMaximized()
            m = 0 if mx else self.M
            self.layout().setContentsMargins(m, m, m, m)
            self.titlebar.set_maximized(mx)
            self.update()
        super().changeEvent(e)

    # ---- edge resize (invisible ring around the window)
    def _edge_list(self, pt):
        if self.isMaximized():
            return []
        m = self.M
        ed = []
        if pt.x() < m:
            ed.append(Qt.Edge.LeftEdge)
        if pt.x() >= self.width() - m:
            ed.append(Qt.Edge.RightEdge)
        if pt.y() < m:
            ed.append(Qt.Edge.TopEdge)
        if pt.y() >= self.height() - m:
            ed.append(Qt.Edge.BottomEdge)
        return ed

    def mouseMoveEvent(self, e):
        ed = self._edge_list(e.position().toPoint())
        L = Qt.Edge.LeftEdge in ed
        R = Qt.Edge.RightEdge in ed
        T = Qt.Edge.TopEdge in ed
        B = Qt.Edge.BottomEdge in ed
        if (L and T) or (R and B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (R and T) or (L and B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif L or R:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif T or B:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            ed = self._edge_list(e.position().toPoint())
            if ed and self.windowHandle():
                self.windowHandle().startSystemResize(reduce(operator.or_, ed))

    # ---- show / close animations
    def showEvent(self, e):
        super().showEvent(e)
        if not self._shown:
            self._shown = True
            self.setWindowOpacity(0.0)
            a = QPropertyAnimation(self, b"windowOpacity", self)
            a.setDuration(320)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setEasingCurve(QEasingCurve.Type.OutCubic)
            a.start()
            self._fade_in = a

    def closeEvent(self, e):
        if self._closing:
            e.accept()
            return
        if not self.notebooks.confirm_leave() or not self.volume_page.confirm_leave():
            e.ignore()
            return
        e.ignore()
        h = self.home
        if h.state in ("starting", "running", "stopping") or h.proc.running():
            self.toast("Stopping your session before closing…", "info")
            h.stop(quit_after=True)
            QTimer.singleShot(75000, self.finish_close)
        else:
            self.finish_close()

    def finish_close(self):
        if self._closing:
            return
        self._closing = True
        a = QPropertyAnimation(self, b"windowOpacity", self)
        a.setDuration(200)
        a.setStartValue(self.windowOpacity())
        a.setEndValue(0.0)
        a.finished.connect(QApplication.quit)
        a.start()
        self._fade_out = a


# =============================================================================
#  Global style
# =============================================================================
QSS = """
QToolTip { background:#2c2c2c; color:white; border:1px solid #454545; padding:5px 9px; }
QFrame#card { background:@CARD@; border:1px solid @STROKE@; border-radius:8px; }
QListWidget#nblist { background:transparent; border:none; outline:0; }
QListWidget#nblist::item { border-radius:6px; margin:1px 0; }
QListWidget#nblist::item:hover { background:rgba(255,255,255,14); }
QListWidget#nblist::item:selected { background:rgba(255,255,255,26); }
QFrame#cell { background:#262626; border:1px solid #3a3a3a; border-radius:8px; }
QTreeWidget#voltree { background:#262626; border:1px solid #333333; border-radius:8px; outline:0; padding:4px; color:white; }
QTreeWidget#voltree::item { height:30px; border-radius:5px; padding-left:4px; }
QTreeWidget#voltree::item:hover { background:rgba(255,255,255,14); }
QTreeWidget#voltree::item:selected { background:rgba(96,205,255,46); color:white; }
QHeaderView { background:#262626; border:none; }
QHeaderView::section { background:#262626; color:#8f8f8f; border:none; border-bottom:1px solid #333333; padding:6px 8px; }
QMenu { background:#2c2c2c; border:1px solid #454545; border-radius:8px; padding:6px; color:white; }
QMenu::item { padding:7px 26px 7px 12px; border-radius:5px; }
QMenu::item:selected { background:#3d3d3d; }
QFrame#logdock { background:#252526; border:1px solid #333333; border-radius:8px; }
QFrame#panel { background:@PANEL@; border:1px solid #333333; border-radius:8px; }
QScrollBar:vertical { background:transparent; width:12px; margin:4px 2px 4px 2px; }
QScrollBar::handle:vertical { background:#5c5c5c; border-radius:3px; min-height:36px; margin:0 3px 0 3px; }
QScrollBar::handle:vertical:hover { background:#8a8a8a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { background:transparent; height:12px; margin:2px 4px 2px 4px; }
QScrollBar::handle:horizontal { background:#5c5c5c; border-radius:3px; min-width:36px; margin:3px 0 3px 0; }
QScrollBar::handle:horizontal:hover { background:#8a8a8a; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background:transparent; }
QComboBox { background:#363636; border:1px solid #454545; border-bottom:1px solid #8a8a8a;
            border-radius:6px; padding:0 34px 0 12px; color:white; }
QComboBox:hover { background:#3d3d3d; }
QComboBox::drop-down { border:none; width:0px; }
QComboBox QAbstractItemView { background:#2c2c2c; border:1px solid #454545; border-radius:8px;
            padding:4px; outline:0; color:white; selection-background-color:#3d3d3d; selection-color:white; }
QComboBox QAbstractItemView::item { min-height:32px; padding-left:10px; border-radius:5px; }
QComboBox QAbstractItemView::item:hover { background:#3a3a3a; }
QComboBox QAbstractItemView::item:selected { background:#3d3d3d; }
QLineEdit { background:#363636; border:1px solid #454545; border-bottom:1px solid #8a8a8a;
            border-radius:6px; padding:0 12px; min-height:34px; color:white;
            selection-background-color:@ACCENT@; selection-color:black; }
QLineEdit:focus { background:#2b2b2b; border-bottom:2px solid @ACCENT@; }
"""
for _k, _v in dict(CARD=CARD, STROKE=STROKE, PANEL=PANEL, ACCENT=ACCENT).items():
    QSS = QSS.replace(f"@{_k}@", _v)


def main():
    try:
        zoom = int(QSettings(SETTINGS_ORG, "App").value("ui_zoom", 100, type=int))
        if zoom and zoom != 100:
            os.environ["QT_SCALE_FACTOR"] = f"{zoom / 100:.2f}"
    except Exception:  # noqa: BLE001
        pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    lock = QLockFile(os.path.join(tempfile.gettempdir(), "modal_notebook_gui.lock"))
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_TITLE, f"{APP_TITLE} is already open.\nUse the open window instead — "
                                "two copies could start two sessions and use credit twice.")
        return
    app.setStyle("Fusion")
    init_icons()
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor("#2b2b2b"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#2f2f2f"))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor("#363636"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#000000"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2c2c2c"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT3))
    app.setPalette(pal)
    app.setFont(font(14))
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    code = app.exec()
    lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
