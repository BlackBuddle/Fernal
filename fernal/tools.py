"""Glass tool panels: the frosted window base (GlassPanel), the four care tools (ToolPanel) and settings.

Every panel is an independent frameless Qt.Tool window with a translucent background, painted in paintEvent.
The design (docs/design/design-plan.md) gives each care panel one memorable element, the *reading*: a serif
sentence that says how the plant is, computed from the simulation's comfort ranges (sim.OPTIMUM). Below it a
quiet comfort-band gauge shows the evidence, and the action sits at the foot of the card and answers in words
("물을 줬어요"). Everything else stays small and sans.

A Windows 11 DWM acrylic backdrop (DWMWA_SYSTEMBACKDROP_TYPE) was tried and rejected: DWM rounds the window
with its own ~8 px radius, which leaves a light halo outside the painted corners, and its tint turns the dark
card grey. The panels therefore use plain per-pixel translucency.
"""
from __future__ import annotations

from PySide6.QtCore import (QElapsedTimer, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from .sim import OPTIMUM
from .themes import THEMES

# ---------------------------------------------------------------------------------------------------------------
# Look and feel (tokens; see docs/design/design-plan.md)

PANEL_WIDTH = 288
SETTINGS_WIDTH = 312
RADIUS = 16.0           # the window; actions use 10, fields 8, the comfort band is fully round
ACTION_RADIUS = 10.0
FIELD_RADIUS = 8.0
PAD_X = 20
PAD_TOP = 12
PAD_BOTTOM = 18
FOOTER_H = 46

GLASS = QColor(18, 22, 21)          # mixed GLASS_TINT toward the theme accent: moss, umber or clay glass
GLASS_ALPHA = 0.80
GLASS_TINT = 0.07
BORDER = QColor(255, 255, 255, round(0.09 * 255))
TEXT = QColor(236, 238, 232)
TEXT_DIM = QColor(236, 238, 232, 153)
TEXT_FAINT = QColor(236, 238, 232, 104)
COOL = QColor("#86BCE0")            # cooling side of the climate slider
WARM = QColor("#F0A35E")            # heating side

READING_PX = 20
TITLE_PX = 13
CONTROL_PX = 14
SMALL_PX = 12

CONFIRM_MS = 1600                   # how long an action button shows its done phrase

THEME_CHOICES = tuple((key, t["label"]) for key, t in THEMES.items())    # (key, Korean label), themes.py order

_SANS = ("Noto Sans KR", "Malgun Gothic", "Segoe UI")
_SERIF = ("Noto Serif KR", "Batang", "Georgia")
_FAMILY_CACHE: dict[bool, list[str]] = {}


def _families(serif: bool = False) -> list[str]:
    """Installed families for the role, best first; Malgun Gothic always backs up Hangul."""
    if serif not in _FAMILY_CACHE:
        installed = set(QFontDatabase.families())
        fams = [f for f in (_SERIF if serif else _SANS) if f in installed] + ["Malgun Gothic"]
        _FAMILY_CACHE[serif] = list(dict.fromkeys(f for f in fams if f in installed)) or ["Sans Serif"]
    return _FAMILY_CACHE[serif]


def ui_font(px: int, weight: QFont.Weight = QFont.Weight.Normal, serif: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(_families(serif))
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def _rgba(c: QColor, alpha: float | None = None) -> str:
    a = c.alphaF() if alpha is None else alpha
    return f"rgba({c.red()},{c.green()},{c.blue()},{a:.3f})"


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(a.redF() + (b.redF() - a.redF()) * t, a.greenF() + (b.greenF() - a.greenF()) * t,
                           a.blueF() + (b.blueF() - a.blueF()) * t, a.alphaF() + (b.alphaF() - a.alphaF()) * t)


def _with_alpha(c: QColor, alpha: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(max(0.0, min(1.0, alpha)))
    return out


def _label(text: str, px: int, color: QColor, weight: QFont.Weight = QFont.Weight.Normal) -> QLabel:
    lab = QLabel(text)
    lab.setFont(ui_font(px, weight))
    lab.setStyleSheet(f"color: {_rgba(color)}; background: transparent;")
    return lab


def _ease(owner, slot, duration: int = 140) -> QVariantAnimation:
    anim = QVariantAnimation(owner, duration=duration, easingCurve=QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(slot)
    return anim


def _run(anim: QVariantAnimation, start: float, end: float) -> None:
    anim.stop()
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.start()


_KEYBOARD_REASONS = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                     Qt.FocusReason.ShortcutFocusReason)


class _FocusVisible:
    """Mixin: `self._kb_focus` is True only while focus came from the keyboard (like CSS :focus-visible)."""

    _kb_focus = False

    def focusInEvent(self, e):
        self._kb_focus = e.reason() in _KEYBOARD_REASONS
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        self._kb_focus = False
        super().focusOutEvent(e)
        self.update()

    def keyPressEvent(self, e):
        if not self._kb_focus and e.key() not in (Qt.Key.Key_Escape,):
            self._kb_focus = True
            self.update()
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if self._kb_focus:
            self._kb_focus = False
            self.update()
        super().mousePressEvent(e)

    def _focus_pen(self, accent: QColor) -> QPen:
        return QPen(_with_alpha(_mix(accent, QColor(255, 255, 255), 0.35), 0.95), 1.5)


# ---------------------------------------------------------------------------------------------------------------
# Readings: the plant's state in one plain sentence

_GAUGE_SPEC = {
    # kind: (sim field, gauge label, sentences for: far below, below, inside, above)
    "water": ("water", "토양 수분", ("흙이 바싹 말랐어요", "흙이 말라 가요", "흙이 알맞게 촉촉해요", "흙이 너무 젖었어요")),
    "nutrients": ("nutrients", "영양 상태",
                  ("영양이 많이 모자라요", "영양이 조금 모자라요", "영양이 넉넉해요", "영양이 넘쳐요")),
    "spray": ("humidity", "공기 습도",
              ("공기가 많이 건조해요", "공기가 조금 건조해요", "공기가 알맞게 촉촉해요", "공기가 너무 습해요")),
}


def comfort_band(kind: str) -> tuple[float, float]:
    """The healthy range (0..1) of the value a care tool shows, straight from sim.OPTIMUM."""
    return OPTIMUM[_GAUGE_SPEC[kind][0]]


def reading_for(kind: str, value: float) -> str:
    """One plain Korean sentence about the plant for a care tool's 0..1 value, or the heater offset (climate)."""
    if kind == "climate":
        v = round(value)
        if v > 0:
            return f"난방으로 {v}°C 올리는 중"
        if v < 0:
            return f"냉방으로 {-v}°C 내리는 중"
        return "냉난방이 꺼져 있어요"
    lo, hi = comfort_band(kind)
    far, below, inside, above = _GAUGE_SPEC[kind][2]
    if value < lo - 0.15:
        return far
    if value < lo:
        return below
    return inside if value <= hi else above


# ---------------------------------------------------------------------------------------------------------------
# Small custom-painted controls


class _CloseGlyph(QAbstractButton):
    """A thin x that brightens on hover. Not in the tab order: Esc closes the panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("닫기 (Esc)")
        self._hover = 0.0
        self._anim = _ease(self, self._on_anim, 120)

    def _on_anim(self, v):
        self._hover = float(v)
        self.update()

    def enterEvent(self, e):
        _run(self._anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _run(self._anim, self._hover, 0.0)
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(26, 26)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover
        if h > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, round(20 * h)))
            p.drawEllipse(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        pen = QPen(_with_alpha(TEXT, 0.42 + 0.5 * h), 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        d = 4.0
        p.drawLine(c + QPointF(-d, -d), c + QPointF(d, d))
        p.drawLine(c + QPointF(-d, d), c + QPointF(d, -d))


class _Reading(QWidget):
    """The plant's state as one serif sentence. A changed sentence fades in over 220 ms."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._color = QColor(TEXT)
        self._fade = 1.0
        self._anim = _ease(self, self._on_anim, 220)
        self._font = ui_font(READING_PX, QFont.Weight.Normal, serif=True)
        fm = QFontMetricsF(self._font)
        self._baseline = fm.ascent()
        self.setFixedHeight(int(fm.ascent() + fm.descent() + 2))

    def _on_anim(self, v):
        self._fade = float(v)
        self.update()

    def text(self) -> str:
        return self._text

    def set_text(self, text: str, color: QColor | None = None) -> None:
        if color is not None:
            self._color = QColor(color)
        if text == self._text:
            self.update()
            return
        self._text = text
        if self.isVisible():
            _run(self._anim, 0.25, 1.0)
        else:
            self._fade = 1.0
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(self._font)
        # A long sentence steps the size down instead of wrapping (never below 17 px).
        px = READING_PX
        while px > 17 and QFontMetricsF(font).horizontalAdvance(self._text) > self.width():
            px -= 1
            font.setPixelSize(px)
        p.setFont(font)
        p.setPen(_with_alpha(self._color, self._color.alphaF() * self._fade))
        p.drawText(QPointF(0, self._baseline), self._text)


class _Gauge(QWidget):
    """Comfort-band gauge: a hairline track, the healthy range as a soft band that lights up while the needle is
    inside it, a thin needle at the value, and a 12 px readout ("토양 수분 35%" left, the range right).

    The needle eases to new values in 250 ms.
    """

    TRACK_Y = 9.0
    BAND_H = 6.0

    def __init__(self, label: str, accent: QColor, band: tuple[float, float] = (0.0, 1.0), parent=None):
        super().__init__(parent)
        self._label = label
        self._accent = QColor(accent)
        self._band = band
        self._value = 0.0
        self._shown = 0.0
        self._anim = _ease(self, self._on_anim, 250)
        self._small = ui_font(SMALL_PX)
        self._small_strong = ui_font(SMALL_PX, QFont.Weight.Medium)
        fm = QFontMetricsF(self._small)
        self._text_base = self.TRACK_Y * 2 + 10 + fm.ascent()
        self.setFixedHeight(int(self._text_base + fm.descent() + 1))

    def _on_anim(self, v):
        self._shown = float(v)
        self.update()

    def value(self) -> float:
        return self._value

    def set_value(self, value: float, animate: bool = True) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._value = value
        self._anim.stop()
        if animate and self.isVisible():
            _run(self._anim, self._shown, value)
        else:
            self._shown = value
            self.update()

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w = float(self.width())
        y = self.TRACK_Y
        lo, hi = self._band
        inside = lo <= self._value <= hi
        a = self._accent
        # hairline track
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(0, y - 1, w, 2), 1, 1)
        # comfort band
        band = QRectF(w * lo, y - self.BAND_H / 2, w * (hi - lo), self.BAND_H)
        p.setBrush(_with_alpha(a, 0.62 if inside else 0.2))
        p.drawRoundedRect(band, self.BAND_H / 2, self.BAND_H / 2)
        # needle
        x = max(1.5, min(w - 1.5, w * self._shown))
        p.setBrush(QColor(18, 22, 21, 150))     # a dark halo keeps the needle legible on the band
        p.drawRoundedRect(QRectF(x - 2.5, y - 9, 5, 18), 2.5, 2.5)
        p.setBrush(TEXT)
        p.drawRoundedRect(QRectF(x - 1.25, y - 8, 2.5, 16), 1.25, 1.25)
        # readout
        base = self._text_base
        p.setFont(self._small)
        p.setPen(TEXT_DIM)
        p.drawText(QPointF(0, base), self._label)
        x_val = QFontMetricsF(self._small).horizontalAdvance(self._label + " ")
        p.setFont(self._small_strong)
        p.setPen(TEXT)
        p.drawText(QPointF(x_val, base), f"{round(self._shown * 100)}%")
        hint = f"알맞은 범위 {round(lo * 100)}–{round(hi * 100)}%"
        p.setFont(self._small)
        p.setPen(TEXT_FAINT)
        p.drawText(QPointF(w - QFontMetricsF(self._small).horizontalAdvance(hint), base), hint)


class _Button(_FocusVisible, QPushButton):
    """Accent-tinted action. `footer=True` makes it the full-width foot of a card (square top, rounded bottom).

    `done` is the short phrase shown for CONFIRM_MS after a click ("물을 줬어요"); the fill brightens briefly.
    """

    def __init__(self, text: str, accent: QColor, primary: bool = True, height: int = 34, footer: bool = False,
                 done: str = "", parent=None):
        super().__init__(text, parent)
        self._accent = QColor(accent)
        self._primary = primary
        self._footer = footer
        self._rest = text
        self._done = done
        self._hover = self._press = self._flash = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(ui_font(CONTROL_PX if footer else 13, QFont.Weight.Medium))
        self.setFixedHeight(FOOTER_H if footer else height)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hover_anim = _ease(self, lambda v: self._set("_hover", v), 140)
        self._press_anim = _ease(self, lambda v: self._set("_press", v), 110)
        self._flash_anim = _ease(self, lambda v: self._set("_flash", v), 700)
        self._restore = QTimer(self, singleShot=True, interval=CONFIRM_MS)
        self._restore.timeout.connect(self._back_to_rest)
        self.pressed.connect(lambda: _run(self._press_anim, self._press, 1.0))
        self.released.connect(lambda: _run(self._press_anim, self._press, 0.0))
        if done:
            self.clicked.connect(lambda _checked=False: self.confirm())

    def _set(self, name: str, v):
        setattr(self, name, float(v))
        self.update()

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def confirm(self) -> None:
        """Show the done phrase for CONFIRM_MS, then the action's name again."""
        if self._done:
            self.setText(self._done)
            self._restore.start()
        _run(self._flash_anim, 1.0, 0.0)

    def _back_to_rest(self) -> None:
        self.setText(self._rest)

    def enterEvent(self, e):
        _run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        _run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        widest = max(fm.horizontalAdvance(t) for t in (self._rest, self._done or self._rest))
        return QSize(int(widest + 28), self.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _shape(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        if self._footer:
            r = RADIUS - 1.0
            path.addRoundedRect(rect.adjusted(0, -r, 0, 0), r, r)
            clip = QPainterPath()
            clip.addRect(rect)
            return path.intersected(clip)
        path.addRoundedRect(rect, ACTION_RADIUS, ACTION_RADIUS)
        return path

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, pr, fl = self._hover, self._press, self._flash
        a = self._accent
        rect = QRectF(self.rect()) if self._footer else QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        shape = self._shape(rect)
        if self._primary:
            fill = _with_alpha(a, 0.17 + 0.07 * h + 0.08 * pr + 0.22 * fl)
            text = _mix(_mix(a, QColor(255, 255, 255), 0.55), QColor(255, 255, 255), 0.25 * h + 0.5 * fl)
        else:
            fill = QColor(255, 255, 255, round(12 + 10 * h + 10 * pr + 30 * fl))
            text = _with_alpha(TEXT, 0.82 + 0.18 * h)
        if not self.isEnabled():
            text = TEXT_FAINT
        p.fillPath(shape, fill)
        if self._footer:
            p.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
            p.drawLine(QPointF(rect.left(), 0.5), QPointF(rect.right(), 0.5))
        else:
            p.setPen(QPen(_with_alpha(a, 0.4 + 0.2 * h) if self._primary else QColor(255, 255, 255, 30), 1.0))
            p.drawPath(shape)
        if self.hasFocus() and self._kb_focus:
            p.setPen(self._focus_pen(a))
            p.setBrush(Qt.BrushStyle.NoBrush)
            inset = 4.5 if self._footer else 2.5
            p.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset), ACTION_RADIUS - 2, ACTION_RADIUS - 2)
        p.setPen(text)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class _ClimateSlider(_FocusVisible, QSlider):
    """Horizontal -10..+10 heater slider: a thin groove, a fill that grows from the center notch in a cool (left)
    or warm (right) tone, and a small light handle. Mouse x maps directly onto the painted groove.
    """

    HANDLE = 16.0
    GROOVE = 4.0

    def __init__(self, accent: QColor, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._accent = QColor(accent)
        self._hover = 0.0
        self.setRange(-10, 10)
        self.setPageStep(1)
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hover_anim = _ease(self, self._on_hover, 140)

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def enterEvent(self, e):
        _run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self.isSliderDown():
            _run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(e)

    def _span(self) -> tuple[float, float]:
        m = self.HANDLE / 2 + 2
        return m, self.width() - m

    def _x_for(self, value: int) -> float:
        x0, x1 = self._span()
        return x0 + (x1 - x0) * (value - self.minimum()) / max(1, self.maximum() - self.minimum())

    def _value_at(self, x: float) -> int:
        x0, x1 = self._span()
        t = (x - x0) / max(1.0, x1 - x0)
        return round(self.minimum() + max(0.0, min(1.0, t)) * (self.maximum() - self.minimum()))

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(e)
        self._kb_focus = False
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.setSliderDown(True)
        self.setValue(self._value_at(e.position().x()))
        e.accept()

    def mouseMoveEvent(self, e):
        if self.isSliderDown():
            self.setValue(self._value_at(e.position().x()))
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.isSliderDown():
            self.setSliderDown(False)
            if not self.underMouse():
                _run(self._hover_anim, self._hover, 0.0)
            e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x0, x1 = self._span()
        g = self.GROOVE
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(QRectF(x0 - 2, cy - g / 2, (x1 - x0) + 4, g), g / 2, g / 2)
        xc, xv = self._x_for(0), self._x_for(self.value())
        if abs(xv - xc) > 0.5:
            tone = WARM if self.value() > 0 else COOL
            strength = 0.45 + 0.55 * abs(self.value()) / 10
            grad = QLinearGradient(QPointF(xc, cy), QPointF(xv, cy))
            grad.setColorAt(0.0, _with_alpha(tone, 0.25))
            grad.setColorAt(1.0, _with_alpha(tone, strength))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(min(xc, xv), cy - g / 2, abs(xv - xc), g), g / 2, g / 2)
        # center notch: "off"
        p.setBrush(QColor(255, 255, 255, 110))
        p.drawRoundedRect(QRectF(xc - 1, cy - 6, 2, 12), 1, 1)
        # handle
        r = self.HANDLE / 2 + 1.0 * max(self._hover, 1.0 if self.isSliderDown() else 0.0)
        center = QPointF(xv, cy)
        p.setBrush(QColor(10, 12, 12, 110))
        p.drawEllipse(center, r + 1.5, r + 1.5)
        p.setBrush(TEXT)
        p.drawEllipse(center, r, r)
        if self.hasFocus() and self._kb_focus:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(self._focus_pen(self._accent))
            p.drawEllipse(center, r + 4.5, r + 4.5)


class _ThemeChoice(_FocusVisible, QComboBox):
    """A QComboBox painted as a segmented row (all three trees visible at once, no popup).

    Click a segment, or use Left/Right while focused. The combo API (itemData, findData, currentIndexChanged)
    is unchanged, so callers keep treating it as a combo box.
    """

    def __init__(self, accent: QColor, parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._hover_index = -1
        self.setMouseTracking(True)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def _segment_at(self, x: float) -> int:
        n = max(1, self.count())
        return max(0, min(n - 1, int(x / max(1.0, self.width() / n))))

    def showPopup(self):
        pass

    def wheelEvent(self, e):
        e.ignore()     # scrolling past the settings must not switch the tree

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._kb_focus = False
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCurrentIndex(self._segment_at(e.position().x()))
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        i = self._segment_at(e.position().x())
        if i != self._hover_index:
            self._hover_index = i
            self.update()

    def leaveEvent(self, e):
        self._hover_index = -1
        self.update()
        super().leaveEvent(e)

    def keyPressEvent(self, e):
        step = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1, Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(e.key())
        if step is not None:
            self._kb_focus = True
            self.setCurrentIndex(max(0, min(self.count() - 1, self.currentIndex() + step)))
            e.accept()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.setBrush(QColor(255, 255, 255, 12))
        p.drawRoundedRect(rect, FIELD_RADIUS, FIELD_RADIUS)
        n = max(1, self.count())
        seg_w = rect.width() / n
        a = self._accent
        p.setFont(self.font())
        for i in range(n):
            seg = QRectF(rect.left() + i * seg_w, rect.top(), seg_w, rect.height())
            chosen = i == self.currentIndex()
            if chosen:
                p.setPen(QPen(_with_alpha(a, 0.55), 1.0))
                p.setBrush(_with_alpha(a, 0.2))
                p.drawRoundedRect(seg.adjusted(2.5, 2.5, -2.5, -2.5), FIELD_RADIUS - 2.5, FIELD_RADIUS - 2.5)
            elif i == self._hover_index:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 14))
                p.drawRoundedRect(seg.adjusted(2.5, 2.5, -2.5, -2.5), FIELD_RADIUS - 2.5, FIELD_RADIUS - 2.5)
            p.setPen(TEXT if chosen else TEXT_DIM)
            p.drawText(seg, Qt.AlignmentFlag.AlignCenter, self.itemText(i))
        if self.hasFocus() and self._kb_focus:
            p.setPen(self._focus_pen(a))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), FIELD_RADIUS, FIELD_RADIUS)


# ---------------------------------------------------------------------------------------------------------------
# Panels


class GlassPanel(QWidget):
    """Frameless translucent glass window: a small title (the drag handle), a close glyph, content in `self.body`
    and an optional full-width action in `self.footer` (the foot of the card).
    """

    def __init__(self, title: str, accent: str = "#8FBF7C", parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self.setFixedWidth(PANEL_WIDTH)
        self._accent = QColor(accent)
        self._drag_offset: QPoint | None = None
        self._fade: QPropertyAnimation | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QWidget(self)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(PAD_X, PAD_TOP, PAD_X - 8, 0)
        hl.setSpacing(8)
        self.title_label = _label(title, TITLE_PX, TEXT_DIM, QFont.Weight.Medium)
        hl.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = _CloseGlyph(self._header)
        self.close_button.clicked.connect(self.close)
        hl.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._header)
        root.addSpacing(10)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(PAD_X, 0, PAD_X, PAD_BOTTOM)
        self._content.setSpacing(0)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        self._content.addLayout(self.body)
        root.addLayout(self._content)

        self.footer = QVBoxLayout()
        self.footer.setContentsMargins(1, 0, 1, 1)   # inside the 1 px border
        self.footer.setSpacing(0)
        root.addLayout(self.footer)

    # -- accent ---------------------------------------------------------------------------------------------
    def accent(self) -> QColor:
        return QColor(self._accent)

    def set_accent(self, color: str) -> None:
        c = QColor(color)
        if not c.isValid():
            return
        self._accent = c
        self._apply_accent()
        self.update()

    def _apply_accent(self) -> None:
        """Hook for subclasses to restyle accent-colored children."""

    # -- showing --------------------------------------------------------------------------------------------
    def show_animated(self) -> None:
        if self._fade is not None:
            self._fade.stop()
        self.adjustSize()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(150)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    # -- painting -------------------------------------------------------------------------------------------
    def glass_color(self) -> QColor:
        """The panel body: dark glass tinted a little toward the theme accent."""
        return _with_alpha(_mix(GLASS, self._accent, GLASS_TINT), GLASS_ALPHA)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        p.fillPath(path, self.glass_color())
        # one border, brighter along the top edge where light would catch the glass
        edge = QLinearGradient(card.topLeft(), card.bottomLeft())
        edge.setColorAt(0.0, QColor(255, 255, 255, 40))
        edge.setColorAt(min(1.0, 40.0 / max(1.0, card.height())), BORDER)
        edge.setColorAt(1.0, BORDER)
        p.setPen(QPen(QBrush(edge), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    # -- header drag ----------------------------------------------------------------------------------------
    def _in_header(self, pos: QPoint) -> bool:
        return pos.y() <= self._header.geometry().bottom() + 4 and not self.close_button.geometry().translated(
            self._header.pos()).contains(pos)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._in_header(e.position().toPoint()):
            handle = self.windowHandle()
            if handle is not None and handle.startSystemMove():
                e.accept()
                return
            self._drag_offset = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_offset is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(e)


_TOOL_SPEC = {
    # kind: (title, button text, done phrase, action name, amount)
    "water": ("물 주기", "물 주기", "물을 줬어요", "water", 0.2),
    "nutrients": ("영양제", "영양제 주기", "영양제를 줬어요", "feed", 0.3),
    "spray": ("스프레이", "스프레이 뿌리기", "스프레이를 뿌렸어요", "spray", 0.15),
    "climate": ("온도 조절", "", "", "heater", 0.0),
}

_HEATER_INTERVAL_MS = 100  # at most ~10 heater updates per second while dragging


class ToolPanel(GlassPanel):
    """One care tool: the reading, a comfort-band gauge and an action at the foot, or (climate) the reading and
    a cooling/heating slider."""

    action = Signal(str, float)

    def __init__(self, kind: str, accent: str = "#8FBF7C", parent=None):
        if kind not in _TOOL_SPEC:
            raise ValueError(f"unknown tool kind: {kind!r}")
        title, button_text, done, self._action_name, self._amount = _TOOL_SPEC[kind]
        super().__init__(title, accent, parent)
        self.kind = kind
        self.gauge: _Gauge | None = None
        self.button: _Button | None = None
        self.slider: _ClimateSlider | None = None
        self.reading = _Reading()
        self.body.addWidget(self.reading)
        self.body.addSpacing(6)

        if kind == "climate":
            self._build_climate()
        else:
            self.gauge = _Gauge(_GAUGE_SPEC[kind][1], self._accent, comfort_band(kind))
            self.body.addWidget(self.gauge)
            self.caption_label = _label("", SMALL_PX, TEXT_FAINT)
            self.caption_label.hide()
            self.body.addWidget(self.caption_label)
            self.button = _Button(button_text, self._accent, footer=True, done=done)
            self.button.clicked.connect(lambda: self.action.emit(self._action_name, float(self._amount)))
            self.footer.addWidget(self.button)
            self.reading.set_text(reading_for(kind, 0.0))
        self.adjustSize()

    # -- climate --------------------------------------------------------------------------------------------
    def _build_climate(self) -> None:
        self.slider = _ClimateSlider(self._accent)
        ends = QHBoxLayout()
        ends.setContentsMargins(0, 0, 0, 0)
        ends.addWidget(_label("냉방", SMALL_PX, TEXT_DIM))
        ends.addStretch(1)
        ends.addWidget(_label("난방", SMALL_PX, TEXT_DIM))
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(0)
        group.addWidget(self.slider)
        group.addLayout(ends)
        self.body.addLayout(group)

        info = QHBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        self.caption_label = _label("", SMALL_PX, TEXT_DIM)
        self.caption_label.hide()
        info.addWidget(self.caption_label)
        info.addStretch(1)
        lo, hi = OPTIMUM["temperature"]
        info.addWidget(_label(f"알맞은 온도 {lo:.0f}–{hi:.0f}°C", SMALL_PX, TEXT_FAINT))
        self.body.addLayout(info)

        self._suppress = False
        self._pending: float | None = None
        self._clock = QElapsedTimer()
        self._throttle = QTimer(self, singleShot=True)
        self._throttle.timeout.connect(self._flush_heater)
        self.slider.valueChanged.connect(self._on_slider)
        self._update_climate_text(0)

    def _update_climate_text(self, v: int) -> None:
        color = TEXT if v == 0 else _mix(TEXT, WARM if v > 0 else COOL, min(1.0, abs(v) / 10 * 0.6 + 0.25))
        self.reading.set_text(reading_for("climate", v), color)

    def _on_slider(self, v: int) -> None:
        self._update_climate_text(v)
        if self._suppress:
            return
        self._pending = float(v)
        if not self._clock.isValid() or self._clock.elapsed() >= _HEATER_INTERVAL_MS:
            self._flush_heater()
        elif not self._throttle.isActive():
            self._throttle.start(max(1, _HEATER_INTERVAL_MS - int(self._clock.elapsed())))

    def _flush_heater(self) -> None:
        if self._pending is None:
            return
        value, self._pending = self._pending, None
        self._throttle.stop()
        self._clock.restart()
        self.action.emit("heater", value)

    # -- public ---------------------------------------------------------------------------------------------
    def set_value(self, value: float) -> None:
        """Gauge level 0..1. For climate, 0..1 maps onto the -10..+10 heater offset (0.5 = off)."""
        value = max(0.0, min(1.0, float(value)))
        if self.slider is not None:
            self._suppress = True
            try:
                self.slider.setValue(round(-10 + 20 * value))
            finally:
                self._suppress = False
        elif self.gauge is not None:
            self.gauge.set_value(value)
            self.reading.set_text(reading_for(self.kind, value))

    def set_caption(self, text: str) -> None:
        """Secondary line under the gauge (for example the current temperature). Empty hides it."""
        self.caption_label.setText(text)
        self.caption_label.setVisible(bool(text))
        self.adjustSize()

    def _apply_accent(self) -> None:
        for w in (self.gauge, self.button, self.slider):
            if w is not None:
                w.set_accent(self._accent)


class SettingsPanel(GlassPanel):
    """City, theme, pot model and window size."""

    themeChanged = Signal(str)
    potChosen = Signal(str)
    cityChanged = Signal(str)
    sizeChanged = Signal(int, int)

    def __init__(self, accent: str = "#8FBF7C", parent=None):
        super().__init__("설정", accent, parent)
        self.setFixedWidth(SETTINGS_WIDTH)
        self.body.setSpacing(0)
        self._pot_path = ""

        # city
        self._section("도시", top=0)
        self.city_edit = QLineEdit()
        self.city_edit.setPlaceholderText("예: 서울, 부산, Tokyo")
        self.city_apply = _Button("찾기", self._accent)
        self.city_apply.setFixedWidth(64)
        self.city_apply.clicked.connect(self._emit_city)
        self.city_edit.returnPressed.connect(self._emit_city)
        self._row(self.city_edit, self.city_apply)
        self.status_label = _label("", SMALL_PX, TEXT_DIM)
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.body.addSpacing(6)
        self.body.addWidget(self.status_label)

        # theme
        self._section("테마")
        self.theme_combo = _ThemeChoice(self._accent)
        for key, name in THEME_CHOICES:
            self.theme_combo.addItem(name, key)
        self.theme_combo.currentIndexChanged.connect(
            lambda i: self.themeChanged.emit(str(self.theme_combo.itemData(i))))
        self.body.addWidget(self.theme_combo)

        # pot
        self._section("화분")
        self.pot_label = _label("", SMALL_PX, TEXT_DIM)
        self.pot_label.setMinimumWidth(10)
        self.body.addWidget(self.pot_label)
        self.body.addSpacing(8)
        self.pot_button = _Button("화분 바꾸기…", self._accent)
        self.pot_button.clicked.connect(self._choose_pot)
        self.pot_default = _Button("기본 화분", self._accent, primary=False)
        self.pot_default.clicked.connect(lambda: self.potChosen.emit(""))
        self._row(self.pot_button, self.pot_default, stretch=(3, 2))
        self.set_pot_path("")

        # window size
        self._section("창 크기 (px)")
        self.width_spin = self._spin(240, 900, "가로 ")
        self.height_spin = self._spin(360, 1400, "세로 ")
        self.size_apply = _Button("적용", self._accent, done="적용됨")
        self.size_apply.setFixedWidth(64)
        self.size_apply.clicked.connect(
            lambda: self.sizeChanged.emit(self.width_spin.value(), self.height_spin.value()))
        self._row(self.width_spin, self.height_spin, self.size_apply, stretch=(1, 1, 0))

        self._apply_accent()
        self.adjustSize()

    # -- building helpers -----------------------------------------------------------------------------------
    def _section(self, text: str, top: int = 18) -> None:
        if top:
            self.body.addSpacing(top)
        self.body.addWidget(_label(text, SMALL_PX, TEXT_DIM))
        self.body.addSpacing(7)

    def _row(self, *widgets, stretch=None) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for i, w in enumerate(widgets):
            row.addWidget(w, (stretch or [1] + [0] * (len(widgets) - 1))[i])
        self.body.addLayout(row)

    @staticmethod
    def _spin(lo: int, hi: int, prefix: str) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(10)
        s.setPrefix(prefix)
        s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s.setAccelerated(True)
        return s

    def _apply_accent(self) -> None:
        a = self._accent
        for w in (getattr(self, n, None) for n in ("city_apply", "pot_button", "pot_default", "size_apply",
                                                   "theme_combo")):
            if w is not None:
                w.set_accent(a)
        focus = _rgba(_mix(a, QColor(255, 255, 255), 0.35), 0.95)
        sel = _rgba(a, 0.35)
        css = f"""
            QLineEdit, QSpinBox {{
                background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.10);
                border-radius: {FIELD_RADIUS:.0f}px; color: {_rgba(TEXT)}; padding: 0 10px;
                min-height: 32px; max-height: 32px;
                selection-background-color: {sel}; selection-color: white; }}
            QLineEdit:hover, QSpinBox:hover {{
                background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.16); }}
            QLineEdit:focus, QSpinBox:focus {{ border: 1.5px solid {focus}; background: rgba(255,255,255,0.07); }}
        """
        font = ui_font(13)
        for w in (self.city_edit, self.width_spin, self.height_spin):
            w.setStyleSheet(css)
            w.setFont(font)
        self.theme_combo.setFont(font)
        self.theme_combo.view().setFont(font)

    # -- signals --------------------------------------------------------------------------------------------
    def _emit_city(self) -> None:
        text = self.city_edit.text().strip()
        if text:
            self.cityChanged.emit(text)

    def _choose_pot(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "화분 바꾸기", self._pot_path, "3D 모델 (*.glb *.gltf)")
        if path:
            self.potChosen.emit(path)

    # -- public ---------------------------------------------------------------------------------------------
    def set_values(self, theme: str, pot_path: str, city: str, w: int, h: int) -> None:
        """Fill every field from the current state without emitting any signal."""
        widgets = (self, self.theme_combo, self.city_edit, self.width_spin, self.height_spin)
        old = [x.blockSignals(True) for x in widgets]
        try:
            i = self.theme_combo.findData(theme)
            if i >= 0:
                self.theme_combo.setCurrentIndex(i)
            self.city_edit.setText(city or "")
            self.width_spin.setValue(int(w))
            self.height_spin.setValue(int(h))
            self.set_pot_path(pot_path)
        finally:
            for x, o in zip(widgets, old):
                x.blockSignals(o)
        self.theme_combo.update()

    def set_pot_path(self, path: str) -> None:
        self._pot_path = path or ""
        if path:
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            fm = QFontMetricsF(self.pot_label.font())
            width = SETTINGS_WIDTH - 2 * PAD_X
            self.pot_label.setText(fm.elidedText(name, Qt.TextElideMode.ElideMiddle, width))
            self.pot_label.setToolTip(path)
        else:
            self.pot_label.setText("기본 화분 사용 중")
            self.pot_label.setToolTip("")

    def set_status(self, text: str) -> None:
        """One-line status under the city field (for example the geocoding result). Empty hides it."""
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))
        self.adjustSize()
