"""Glass tool panels: the frosted card base (GlassPanel), the four care tools (ToolPanel) and settings.

Every panel is an independent frameless Qt.Tool window with a translucent background. The card itself is
painted in paintEvent; child controls are custom painted (gauge, pill buttons, slider) or styled through a
stylesheet built from the panel's accent color (line edit, combo box, spin boxes).

A Windows 11 DWM acrylic backdrop (DWMWA_SYSTEMBACKDROP_TYPE) was tried and rejected: DWM rounds the window
with its own ~8 px radius, which leaves a light halo outside the 14 px painted corners, and its tint turns
the dark card grey. The panels therefore use plain per-pixel translucency.
"""
from __future__ import annotations

from PySide6.QtCore import (QElapsedTimer, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

# ---------------------------------------------------------------------------------------------------------------
# Look and feel

PANEL_WIDTH = 280
SETTINGS_WIDTH = 304
RADIUS = 14.0
PAD_X = 18
PAD_TOP = 14
PAD_BOTTOM = 18

FILL = QColor(18, 20, 28, round(0.78 * 255))
BORDER = QColor(255, 255, 255, round(0.08 * 255))
TEXT = QColor(236, 238, 242)
TEXT_DIM = QColor(255, 255, 255, 140)
TEXT_FAINT = QColor(255, 255, 255, 96)

THEME_CHOICES = (("erdtree", "세계수"), ("normal", "일반 나무"), ("fruit", "열매 나무"))

_FAMILY_CACHE: list[str] = []


def _families() -> list[str]:
    """Preferred UI family first (Pretendard, Segoe UI, Malgun Gothic), then Malgun Gothic for Hangul."""
    if not _FAMILY_CACHE:
        installed = set(QFontDatabase.families())
        first = next((f for f in ("Pretendard", "Segoe UI", "Malgun Gothic") if f in installed), "")
        fams = [f for f in (first, "Malgun Gothic") if f]
        _FAMILY_CACHE.extend(dict.fromkeys(fams) or ["Sans Serif"])
    return _FAMILY_CACHE


def ui_font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(_families())
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


# ---------------------------------------------------------------------------------------------------------------
# Small custom-painted controls


class _CloseGlyph(QAbstractButton):
    """A thin x that brightens on hover, on a faint round chip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("닫기")
        self._hover = 0.0
        self._anim = QVariantAnimation(self, duration=120, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def _on_anim(self, v):
        self._hover = float(v)
        self.update()

    def _fade(self, target: float):
        self._anim.stop()
        self._anim.setStartValue(self._hover)
        self._anim.setEndValue(target)
        self._anim.start()

    def enterEvent(self, e):
        self._fade(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._fade(0.0)
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:
        return QSize(24, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover
        if h > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, round(22 * h)))
            p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        pen = QPen(QColor(255, 255, 255, round(110 + 135 * h)), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        d = 4.25
        p.drawLine(c + QPointF(-d, -d), c + QPointF(d, d))
        p.drawLine(c + QPointF(-d, d), c + QPointF(d, -d))


class _Gauge(QWidget):
    """Label and big value on one baseline, a rounded accent bar below. Animates to new values in 250 ms."""

    BAR_H = 8.0

    def __init__(self, label: str, accent: QColor, parent=None):
        super().__init__(parent)
        self._label = label
        self._accent = QColor(accent)
        self._value = 0.0
        self._shown = 0.0
        self._anim = QVariantAnimation(self, duration=250, easingCurve=QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)
        self._label_font = ui_font(12)
        self._value_font = ui_font(20, QFont.Weight.DemiBold)
        self._unit_font = ui_font(12, QFont.Weight.DemiBold)
        vm = QFontMetricsF(self._value_font)
        self._baseline = vm.ascent()
        self._bar_top = self._baseline + vm.descent() + 8
        self.setFixedHeight(int(self._bar_top + self.BAR_H + 1))

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
            self._anim.setStartValue(self._shown)
            self._anim.setEndValue(value)
            self._anim.start()
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
        base = self._baseline
        # label (left) and value (right) share one baseline
        p.setFont(self._label_font)
        p.setPen(TEXT_DIM)
        p.drawText(QPointF(0, base), self._label)
        pct = f"{round(self._shown * 100)}"
        um = QFontMetricsF(self._unit_font)
        vm = QFontMetricsF(self._value_font)
        unit_w = um.horizontalAdvance("%")
        x_unit = w - unit_w
        p.setFont(self._unit_font)
        p.setPen(TEXT_DIM)
        p.drawText(QPointF(x_unit, base), "%")
        p.setFont(self._value_font)
        p.setPen(TEXT)
        p.drawText(QPointF(x_unit - 2 - vm.horizontalAdvance(pct), base), pct)
        # bar
        track = QRectF(0, self._bar_top, w, self.BAR_H)
        r = self.BAR_H / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(track, r, r)
        fill_w = track.width() * self._shown
        if fill_w > 0.5:
            fill = QRectF(track.left(), track.top(), max(fill_w, self.BAR_H), self.BAR_H)
            a = self._accent
            g = QLinearGradient(fill.topLeft(), fill.topRight())
            g.setColorAt(0.0, _with_alpha(a.darker(135), 0.85))
            g.setColorAt(1.0, _with_alpha(a.lighter(118), 1.0))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(fill, r, r)
            # soft top sheen
            sheen = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 60))
            sheen.setColorAt(0.55, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(sheen))
            p.drawRoundedRect(fill, r, r)


class _ValueRow(QWidget):
    """A dim 12 px label on the left and a 20 px value on the right, painted on one shared baseline."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._text = ""
        self._color = QColor(TEXT)
        self._label_font = ui_font(12)
        self._value_font = ui_font(20, QFont.Weight.DemiBold)
        vm = QFontMetricsF(self._value_font)
        self._baseline = vm.ascent()
        self.setFixedHeight(int(vm.ascent() + vm.descent() + 1))

    def text(self) -> str:
        return self._text

    def set_text(self, text: str, color: QColor) -> None:
        self._text = text
        self._color = QColor(color)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self._label_font)
        p.setPen(TEXT_DIM)
        p.drawText(QPointF(0, self._baseline), self._label)
        p.setFont(self._value_font)
        p.setPen(self._color)
        x = self.width() - QFontMetricsF(self._value_font).horizontalAdvance(self._text)
        p.drawText(QPointF(x, self._baseline), self._text)


class _PillButton(QPushButton):
    """Pill-shaped accent-tinted button with hover brightening and a 120 ms press animation."""

    def __init__(self, text: str, accent: QColor, primary: bool = True, height: int = 38, parent=None):
        super().__init__(text, parent)
        self._accent = QColor(accent)
        self._primary = primary
        self._hover = 0.0
        self._press = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(ui_font(13 if height >= 36 else 12, QFont.Weight.DemiBold))
        self.setFixedHeight(height)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._hover_anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(lambda v: self._set("_hover", v))
        self._press_anim = QVariantAnimation(self, duration=120, easingCurve=QEasingCurve.Type.OutCubic)
        self._press_anim.valueChanged.connect(lambda v: self._set("_press", v))
        self.pressed.connect(lambda: self._run(self._press_anim, self._press, 1.0))
        self.released.connect(lambda: self._run(self._press_anim, self._press, 0.0))

    def _set(self, name: str, v):
        setattr(self, name, float(v))
        self.update()

    @staticmethod
    def _run(anim: QVariantAnimation, start: float, end: float):
        anim.stop()
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def enterEvent(self, e):
        self._run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(e)

    def sizeHint(self) -> QSize:
        fm = QFontMetricsF(self.font())
        return QSize(int(fm.horizontalAdvance(self.text()) + 32), self.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, pr = self._hover, self._press
        inset = 0.5 + 1.5 * pr
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        rad = rect.height() / 2
        a = self._accent
        if self._primary:
            top = _with_alpha(a.lighter(112), 0.30 + 0.12 * h + 0.10 * pr)
            bottom = _with_alpha(a, 0.20 + 0.10 * h + 0.10 * pr)
            border = _with_alpha(a.lighter(125), 0.55 + 0.25 * h)
            text = _mix(a.lighter(160), QColor(255, 255, 255), 0.55 + 0.3 * h)
        else:
            top = QColor(255, 255, 255, round(16 + 12 * h + 10 * pr))
            bottom = QColor(255, 255, 255, round(9 + 10 * h + 10 * pr))
            border = QColor(255, 255, 255, round(28 + 26 * h))
            text = QColor(255, 255, 255, round(200 + 40 * h))
        if not self.isEnabled():
            text = TEXT_FAINT
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0.0, top)
        g.setColorAt(1.0, bottom)
        p.setBrush(QBrush(g))
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(rect, rad, rad)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(a.lighter(140), 0.8), 1.2))
            p.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), rad, rad)
        p.setPen(text)
        p.setFont(self.font())
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())


class _ClimateSlider(QSlider):
    """Horizontal -10..+10 slider: thin groove, accent fill growing from the center, a large round handle.

    Mouse handling maps x directly onto the painted groove (the style's own geometry is not used).
    """

    HANDLE = 20.0
    GROOVE = 6.0

    def __init__(self, accent: QColor, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._accent = QColor(accent)
        self._hover = 0.0
        self.setRange(-10, 10)
        self.setPageStep(1)
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hover_anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover)

    def _on_hover(self, v):
        self._hover = float(v)
        self.update()

    def set_accent(self, accent: QColor) -> None:
        self._accent = QColor(accent)
        self.update()

    def _fade(self, target: float):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(target)
        self._hover_anim.start()

    def enterEvent(self, e):
        self._fade(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self.isSliderDown():
            self._fade(0.0)
        super().leaveEvent(e)

    def _span(self) -> tuple[float, float]:
        m = self.HANDLE / 2 + 1
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
                self._fade(0.0)
            e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        x0, x1 = self._span()
        a = self._accent
        # groove
        groove = QRectF(x0 - 3, cy - self.GROOVE / 2, (x1 - x0) + 6, self.GROOVE)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(groove, self.GROOVE / 2, self.GROOVE / 2)
        # ticks at every 5 degrees
        p.setBrush(QColor(255, 255, 255, 46))
        for v in (-5, 5):
            p.drawEllipse(QPointF(self._x_for(v), cy), 1.4, 1.4)
        xc = self._x_for(0)
        xv = self._x_for(self.value())
        # fill from the center to the handle
        if abs(xv - xc) > 0.5:
            left, right = min(xc, xv), max(xc, xv)
            fill = QRectF(left, cy - self.GROOVE / 2, right - left, self.GROOVE)
            g = QLinearGradient(QPointF(xc, cy), QPointF(xv, cy))
            g.setColorAt(0.0, _with_alpha(a, 0.35))
            g.setColorAt(1.0, _with_alpha(a.lighter(118), 1.0))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(fill, self.GROOVE / 2, self.GROOVE / 2)
        # center notch
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRoundedRect(QRectF(xc - 1, cy - 6, 2, 12), 1, 1)
        # handle: soft glow, accent ring, light core
        h = max(self._hover, 1.0 if self.isSliderDown() else 0.0)
        r = self.HANDLE / 2
        center = QPointF(xv, cy)
        p.setBrush(_with_alpha(a, 0.16 + 0.14 * h))
        p.drawEllipse(center, r + 3 + 1.5 * h, r + 3 + 1.5 * h)
        core = QLinearGradient(QPointF(xv, cy - r), QPointF(xv, cy + r))
        core.setColorAt(0.0, QColor(255, 255, 255))
        core.setColorAt(1.0, _mix(QColor(232, 234, 240), a, 0.15))
        p.setBrush(QBrush(core))
        p.setPen(QPen(_with_alpha(a.lighter(110), 0.95), 2.0))
        p.drawEllipse(center, r - 1, r - 1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_with_alpha(a.darker(110), 0.9))
        p.drawEllipse(center, 3.0, 3.0)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(a.lighter(140), 0.6), 1.0))
            p.drawEllipse(center, r + 5.5, r + 5.5)


class _ChevronCombo(QComboBox):
    """QComboBox whose drop-down arrow is painted as a thin chevron (stylesheets need image files for it)."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(255, 255, 255, 170), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 18.0, self.height() / 2 + 1
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


# ---------------------------------------------------------------------------------------------------------------
# Panels


class GlassPanel(QWidget):
    """Frameless translucent card window with a title header, accent rule and a close glyph.

    Put content into `self.body`. Drag the header to move the window.
    """

    def __init__(self, title: str, accent: str = "#5FA85A", parent=None):
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
        root.setContentsMargins(PAD_X, PAD_TOP, PAD_X, PAD_BOTTOM)
        root.setSpacing(0)

        self._header = QWidget(self)
        self._header.setFixedHeight(30)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        self.title_label = _label(title, 15, TEXT, QFont.Weight.DemiBold)
        hl.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.close_button = _CloseGlyph(self._header)
        self.close_button.clicked.connect(self.close)
        hl.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._header)
        root.addSpacing(18)  # the accent rule is painted inside this gap

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(12)
        root.addLayout(self.body)

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
    def _rule_y(self) -> float:
        return self._header.geometry().bottom() + 1 + 8.0

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        # glass body: the spec fill with a faint vertical lift so the card reads as a surface
        g = QLinearGradient(card.topLeft(), card.bottomLeft())
        g.setColorAt(0.0, QColor(28, 31, 42, FILL.alpha()))
        g.setColorAt(0.35, FILL)
        g.setColorAt(1.0, QColor(14, 16, 23, FILL.alpha() + 6))
        p.fillPath(path, QBrush(g))
        # a whisper of accent light in the top-left corner
        glow = QLinearGradient(card.topLeft(), QPointF(card.left() + card.width() * 0.8, card.top() + 90))
        glow.setColorAt(0.0, _with_alpha(self._accent, 0.10))
        glow.setColorAt(1.0, _with_alpha(self._accent, 0.0))
        p.fillPath(path, QBrush(glow))
        # border, plus a brighter top edge highlight
        p.setPen(QPen(BORDER, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        edge = QLinearGradient(card.topLeft(), QPointF(card.left(), card.top() + RADIUS * 2))
        edge.setColorAt(0.0, QColor(255, 255, 255, 34))
        edge.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(QPen(QBrush(edge), 1.0))
        p.drawPath(path)
        # accent rule under the title: solid at the left, fading out to the right
        y = self._rule_y()
        x0, x1 = float(PAD_X), float(self.width() - PAD_X)
        rule = QLinearGradient(QPointF(x0, y), QPointF(x1, y))
        rule.setColorAt(0.0, _with_alpha(self._accent, 0.95))
        rule.setColorAt(0.35, _with_alpha(self._accent, 0.55))
        rule.setColorAt(1.0, _with_alpha(self._accent, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(rule))
        p.drawRoundedRect(QRectF(x0, y, x1 - x0, 2.0), 1.0, 1.0)

    # -- header drag ----------------------------------------------------------------------------------------
    def _in_header(self, pos: QPoint) -> bool:
        return pos.y() <= self._rule_y() + 4 and not self.close_button.geometry().translated(
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
    # kind: (title, gauge label, button text, action name, amount)
    "water": ("물 주기", "토양 수분", "물 주기", "water", 0.2),
    "nutrients": ("영양제", "영양 상태", "영양제 주기", "feed", 0.3),
    "spray": ("스프레이", "공기 습도", "스프레이 뿌리기", "spray", 0.15),
    "climate": ("온도 조절", "온도 보정", "", "heater", 0.0),
}

_HEATER_INTERVAL_MS = 100  # at most ~10 heater updates per second while dragging


class ToolPanel(GlassPanel):
    """One care tool: a gauge and an action button, or (climate) a heater/AC slider."""

    action = Signal(str, float)

    def __init__(self, kind: str, accent: str = "#5FA85A", parent=None):
        if kind not in _TOOL_SPEC:
            raise ValueError(f"unknown tool kind: {kind!r}")
        title, gauge_label, button_text, self._action_name, self._amount = _TOOL_SPEC[kind]
        super().__init__(title, accent, parent)
        self.kind = kind
        self.gauge: _Gauge | None = None
        self.button: _PillButton | None = None
        self.slider: _ClimateSlider | None = None

        if kind == "climate":
            self._build_climate(gauge_label)
        else:
            self.gauge = _Gauge(gauge_label, self._accent)
            self.body.addWidget(self.gauge)
            self.caption_label = _label("", 12, TEXT_FAINT)
            self.caption_label.hide()
            self.body.addWidget(self.caption_label)
            self.body.addSpacing(4)
            self.button = _PillButton(button_text, self._accent)
            self.button.clicked.connect(lambda: self.action.emit(self._action_name, float(self._amount)))
            self.body.addWidget(self.button)
        self.adjustSize()

    # -- climate --------------------------------------------------------------------------------------------
    def _build_climate(self, label: str) -> None:
        self.value_row = _ValueRow(label)
        self.body.addWidget(self.value_row)

        self.slider = _ClimateSlider(self._accent)
        ends = QHBoxLayout()
        ends.setContentsMargins(0, 0, 0, 0)
        ends.addWidget(_label("에어컨", 12, TEXT_DIM))
        ends.addStretch(1)
        ends.addWidget(_label("난방", 12, TEXT_DIM))
        group = QVBoxLayout()
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(0)
        group.addWidget(self.slider)
        group.addLayout(ends)
        self.body.addLayout(group)

        self.caption_label = _label("", 12, TEXT_FAINT)
        self.caption_label.hide()
        self.body.addWidget(self.caption_label)

        self._suppress = False
        self._pending: float | None = None
        self._clock = QElapsedTimer()
        self._throttle = QTimer(self, singleShot=True)
        self._throttle.timeout.connect(self._flush_heater)
        self.slider.valueChanged.connect(self._on_slider)
        self._update_climate_text(0)

    def _update_climate_text(self, v: int) -> None:
        if v > 0:
            text = f"난방 +{v}°C"
        elif v < 0:
            text = f"에어컨 {v}°C"
        else:
            text = "꺼짐"
        warm, cool = QColor("#F2A65A"), QColor("#7CC4F0")
        color = TEXT if v == 0 else _mix(TEXT, warm if v > 0 else cool, min(1.0, abs(v) / 10 + 0.35))
        self.value_row.set_text(text, color)

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

    def __init__(self, accent: str = "#5FA85A", parent=None):
        super().__init__("설정", accent, parent)
        self.setFixedWidth(SETTINGS_WIDTH)
        self.body.setSpacing(0)
        self.body.addSpacing(2)
        self._pot_path = ""

        # city
        self._section("도시")
        self.city_edit = QLineEdit()
        self.city_edit.setPlaceholderText("예: 서울")
        self.city_apply = _PillButton("적용", self._accent, height=34)
        self.city_apply.setFixedWidth(60)
        self.city_apply.clicked.connect(self._emit_city)
        self.city_edit.returnPressed.connect(self._emit_city)
        self._row(self.city_edit, self.city_apply)
        self.status_label = _label("", 12, TEXT_FAINT)
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        self.body.addSpacing(6)
        self.body.addWidget(self.status_label)

        # theme
        self._section("테마", top=16)
        self.theme_combo = _ChevronCombo()
        for key, name in THEME_CHOICES:
            self.theme_combo.addItem(name, key)
        self.theme_combo.currentIndexChanged.connect(
            lambda i: self.themeChanged.emit(str(self.theme_combo.itemData(i))))
        self.body.addWidget(self.theme_combo)

        # pot
        self._section("화분", top=16)
        self.pot_label = _label("", 12, TEXT_DIM)
        self.pot_label.setMinimumWidth(10)
        self.pot_button = _PillButton("화분 파일 선택…", self._accent, height=34)
        self.pot_button.clicked.connect(self._choose_pot)
        self.pot_default = _PillButton("기본 화분", self._accent, primary=False, height=34)
        self.pot_default.clicked.connect(lambda: self.potChosen.emit(""))
        self._row(self.pot_button, self.pot_default, stretch=(3, 2))
        self.body.addSpacing(6)
        self.body.addWidget(self.pot_label)
        self.set_pot_path("")

        # window size
        self._section("창 크기 (px)", top=16)
        self.width_spin = self._spin(240, 900, "가로 ")
        self.height_spin = self._spin(360, 1400, "세로 ")
        self.size_apply = _PillButton("적용", self._accent, height=34)
        self.size_apply.setFixedWidth(60)
        self.size_apply.clicked.connect(
            lambda: self.sizeChanged.emit(self.width_spin.value(), self.height_spin.value()))
        self._row(self.width_spin, self.height_spin, self.size_apply, stretch=(1, 1, 0))

        self._apply_accent()
        self.adjustSize()

    # -- building helpers -----------------------------------------------------------------------------------
    def _section(self, text: str, top: int = 0) -> None:
        if top:
            self.body.addSpacing(top)
        self.body.addWidget(_label(text, 12, TEXT_DIM))
        self.body.addSpacing(6)

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
        for b in (getattr(self, n, None) for n in ("city_apply", "pot_button", "pot_default", "size_apply")):
            if b is not None:
                b.set_accent(a)
        focus = _rgba(a.lighter(115), 0.85)
        sel = _rgba(a, 0.35)
        field = (
            "background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10);"
            "border-radius: 9px; color: rgb(236,238,242); padding: 0 10px; min-height: 32px; max-height: 32px;"
            f"selection-background-color: {sel}; selection-color: white;"
        )
        css = f"""
            QLineEdit, QSpinBox {{ {field} }}
            QComboBox {{ {field} padding-right: 30px; }}
            QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
                background: rgba(255,255,255,0.09); border-color: rgba(255,255,255,0.16); }}
            QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on {{
                border: 1px solid {focus}; background: rgba(255,255,255,0.08); }}
            QComboBox::drop-down {{ border: none; width: 30px; }}
            QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
            QComboBox QAbstractItemView {{
                background: rgb(26,29,38); color: rgb(236,238,242); border: 1px solid rgba(255,255,255,0.12);
                padding: 4px; outline: 0; selection-background-color: {sel}; selection-color: white; }}
            QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 0 8px; border-radius: 6px; }}
            QComboBox QAbstractItemView::item:hover {{ background: rgba(255,255,255,0.07); }}
            QComboBox QAbstractItemView::item:selected {{ background: {sel}; }}
        """
        font = ui_font(13)
        for w in (self.city_edit, self.theme_combo, self.width_spin, self.height_spin):
            w.setStyleSheet(css)
            w.setFont(font)
        self.theme_combo.view().setFont(font)

    # -- signals --------------------------------------------------------------------------------------------
    def _emit_city(self) -> None:
        text = self.city_edit.text().strip()
        if text:
            self.cityChanged.emit(text)

    def _choose_pot(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "화분 파일 선택", self._pot_path,
                                              "3D 모델 (*.glb *.gltf)")
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
