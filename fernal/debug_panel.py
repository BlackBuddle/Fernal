"""Hidden debug panel (Ctrl+Shift+D): time scale, age, growth, reseed, pinned environment values, reset.

The panel only emits `changed` dicts, one key per user action, and never touches the plant state itself:

    {"time_scale": 8.0}          {"age": 120.0}            {"growth_percent": 50.0}
    {"reseed": True}             {"reset": True}
    {"force": {"water": 0.3}}    {"force": {"water": None}}   # None releases the pin

`set_state` mirrors a `sim.PlantState` into the controls without emitting anything.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QDoubleSpinBox, QHBoxLayout, QLabel, QSlider,
                               QWidget)

from .tools import TEXT, TEXT_DIM, GlassPanel, _label, _PillButton, _rgba, ui_font

DEBUG_WIDTH = 360
TIME_SCALE_RANGE = (0.1, 1000.0)    # log scale: four decades over the slider
TIME_SLIDER_STEPS = 1000
GROWTH_SLIDER_STEPS = 1000          # 0.1 % per step
FORCE_SLIDER_STEPS = 1000
MAX_AGE = 1_000_000.0

# (Env field, Korean label, slider range); temperature is in degC, every other value is 0..1.
FORCE_FIELDS = (
    ("water", "물", (0.0, 1.0)),
    ("nutrients", "영양제", (0.0, 1.0)),
    ("temperature", "온도", (-10.0, 45.0)),
    ("humidity", "습도", (0.0, 1.0)),
    ("light", "채광", (0.0, 1.0)),
    ("affection", "애정도", (0.0, 1.0)),
)


def scale_at(pos: int) -> float:
    """Time scale for a slider position (3 significant digits): 0 -> 0.1, 1000 -> 1000."""
    lo, hi = TIME_SCALE_RANGE
    value = lo * (hi / lo) ** (pos / TIME_SLIDER_STEPS)
    return float(f"{value:.3g}")


def pos_of_scale(scale: float) -> int:
    """Slider position of a time scale (clamped to the slider range)."""
    lo, hi = TIME_SCALE_RANGE
    scale = min(hi, max(lo, float(scale))) if math.isfinite(scale) else lo
    return round(math.log(scale / lo) / math.log(hi / lo) * TIME_SLIDER_STEPS)


def format_scale(scale: float) -> str:
    return f"×{scale:.2f}" if scale < 1 else f"×{scale:.1f}" if scale < 10 else f"×{scale:.0f}"


def _slider(steps: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(0, steps)
    s.setFixedHeight(22)
    s.setCursor(Qt.CursorShape.PointingHandCursor)
    return s


class _ForceRow(QWidget):
    """One environment value: name, slider, value text and a 고정 checkbox.

    Unchecked, the slider is a read-only live readout; checked, it is enabled and pins the value.
    `forced(name, value)` carries the pinned value, or None when the pin is released.
    """

    forced = Signal(str, object)

    def __init__(self, name: str, label: str, lo: float, hi: float, parent=None):
        super().__init__(parent)
        self.name, self._lo, self._hi = name, lo, hi
        self._loading = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        name_label = _label(label, 12, TEXT_DIM)
        name_label.setFixedWidth(44)
        row.addWidget(name_label)
        self.slider = _slider(FORCE_SLIDER_STEPS)
        self.slider.setEnabled(False)
        row.addWidget(self.slider, 1)
        self.value_label = _label("", 12, TEXT)
        self.value_label.setFixedWidth(50)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.value_label)
        self.check = QCheckBox("고정")
        self.check.setFont(ui_font(12))
        self.check.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.check)
        self.slider.valueChanged.connect(self._on_slider)
        self.check.toggled.connect(self._on_toggled)
        self._show_value()

    def value(self) -> float:
        return self._lo + (self._hi - self._lo) * self.slider.value() / FORCE_SLIDER_STEPS

    def _show_value(self) -> None:
        v = self.value()
        self.value_label.setText(f"{v:.1f}°C" if self.name == "temperature" else f"{round(v * 100)}%")

    def _on_slider(self, _pos: int) -> None:
        self._show_value()
        if not self._loading and self.check.isChecked():
            self.forced.emit(self.name, self.value())

    def _on_toggled(self, on: bool) -> None:
        self.slider.setEnabled(on)
        if not self._loading:
            self.forced.emit(self.name, self.value() if on else None)

    def load(self, value: float, pinned: bool) -> None:
        """Show `value` and the pin state without emitting; a slider being dragged is left alone."""
        self._loading = True
        try:
            self.check.setChecked(pinned)
            if not self.slider.isSliderDown():
                t = (float(value) - self._lo) / (self._hi - self._lo)
                self.slider.setValue(round(min(1.0, max(0.0, t)) * FORCE_SLIDER_STEPS))
            self._show_value()
        finally:
            self._loading = False


class DebugPanel(GlassPanel):
    """Developer controls for the plant. Hidden: opened with Ctrl+Shift+D or Ctrl+Shift+right click."""

    changed = Signal(dict)

    def __init__(self, accent: str = "#5FA85A", parent=None):
        super().__init__("디버그 도구", accent, parent)
        self.setFixedWidth(DEBUG_WIDTH)
        self._loading = False
        self._mature_age = 0.0
        self.body.setSpacing(0)

        # time scale (log slider)
        self.time_label = QLabel()
        self._section("시간 배속", self.time_label)
        self.time_slider = _slider(TIME_SLIDER_STEPS)
        self.time_slider.valueChanged.connect(self._on_time)
        self.body.addWidget(self.time_slider)

        # age in plant hours
        self.body.addSpacing(14)
        self.age_spin = QDoubleSpinBox()
        self.age_spin.setRange(0.0, MAX_AGE)
        self.age_spin.setDecimals(1)
        self.age_spin.setSingleStep(1.0)
        self.age_spin.setSuffix(" 시간")
        self.age_spin.setKeyboardTracking(False)
        self.age_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.age_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.age_spin.valueChanged.connect(self._on_age)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_label("나이", 12, TEXT_DIM))
        row.addStretch(1)
        row.addWidget(self.age_spin)
        self.body.addLayout(row)

        # growth percent of the current skeleton
        self.body.addSpacing(14)
        self.growth_label = QLabel()
        self._section("성장도", self.growth_label)
        self.growth_slider = _slider(GROWTH_SLIDER_STEPS)
        self.growth_slider.valueChanged.connect(self._on_growth)
        self.body.addWidget(self.growth_slider)

        # pinned environment values
        self.body.addSpacing(16)
        self.body.addWidget(_label("환경 값 고정", 12, TEXT_DIM))
        self.body.addSpacing(4)
        self.force_rows: dict[str, _ForceRow] = {}
        for name, label, (lo, hi) in FORCE_FIELDS:
            force_row = _ForceRow(name, label, lo, hi)
            force_row.forced.connect(self._on_forced)
            self.force_rows[name] = force_row
            self.body.addWidget(force_row)
            self.body.addSpacing(2)

        # actions
        self.body.addSpacing(14)
        self.reseed_button = _PillButton("시드 재추첨", self._accent, height=34)
        self.reseed_button.clicked.connect(lambda: self.changed.emit({"reseed": True}))
        self.reset_button = _PillButton("초기화", self._accent, primary=False, height=34)
        self.reset_button.clicked.connect(lambda: self.changed.emit({"reset": True}))
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self.reseed_button, 3)
        buttons.addWidget(self.reset_button, 2)
        self.body.addLayout(buttons)

        self._apply_accent()
        self._loading = True
        try:
            self.time_slider.setValue(pos_of_scale(1.0))
            self.time_label.setText(format_scale(1.0))
            self.growth_label.setText("0.0%")
        finally:
            self._loading = False
        self.adjustSize()

    # -- building helpers -----------------------------------------------------------------------------------
    def _section(self, text: str, value_label: QLabel) -> None:
        """A dim caption on the left and a live value on the right, above a slider."""
        value_label.setFont(ui_font(13, QFont.Weight.DemiBold))
        value_label.setStyleSheet(f"color: {_rgba(TEXT)}; background: transparent;")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_label(text, 12, TEXT_DIM))
        row.addStretch(1)
        row.addWidget(value_label)
        self.body.addLayout(row)
        self.body.addSpacing(4)

    def _apply_accent(self) -> None:
        a = self._accent
        accent = _rgba(a.lighter(112), 1.0)
        dim = _rgba(a, 0.38)
        slider_css = f"""
            QSlider::groove:horizontal {{ height: 6px; border-radius: 3px; background: rgba(255,255,255,0.10); }}
            QSlider::sub-page:horizontal {{ border-radius: 3px; background: {_rgba(a, 0.85)}; }}
            QSlider::add-page:horizontal {{ border-radius: 3px; background: transparent; }}
            QSlider::handle:horizontal {{ width: 12px; height: 12px; margin: -5px 0; border-radius: 8px;
                background: rgb(242,244,248); border: 2px solid {accent}; }}
            QSlider::handle:horizontal:hover {{ background: white; }}
            QSlider::sub-page:horizontal:disabled {{ background: {dim}; }}
            QSlider::handle:horizontal:disabled {{ background: rgba(255,255,255,0.40);
                border: 2px solid rgba(255,255,255,0.22); }}
        """
        sliders = [self.time_slider, self.growth_slider] + [r.slider for r in self.force_rows.values()]
        for s in sliders:
            s.setStyleSheet(slider_css)
        check_css = f"""
            QCheckBox {{ color: rgba(255,255,255,0.78); spacing: 6px; background: transparent; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;
                border: 1px solid rgba(255,255,255,0.30); background: rgba(255,255,255,0.06); }}
            QCheckBox::indicator:hover {{ border-color: rgba(255,255,255,0.55); }}
            QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
        """
        for r in self.force_rows.values():
            r.check.setStyleSheet(check_css)
        self.age_spin.setFont(ui_font(13))
        self.age_spin.setStyleSheet(f"""
            QDoubleSpinBox {{ background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10);
                border-radius: 9px; color: rgb(236,238,242); padding: 0 10px; min-height: 30px; max-height: 30px;
                min-width: 120px; selection-background-color: {_rgba(a, 0.35)}; selection-color: white; }}
            QDoubleSpinBox:hover {{ background: rgba(255,255,255,0.09); border-color: rgba(255,255,255,0.16); }}
            QDoubleSpinBox:focus {{ border: 1px solid {_rgba(a.lighter(115), 0.85)};
                background: rgba(255,255,255,0.08); }}
        """)
        for b in (self.reseed_button, self.reset_button):
            b.set_accent(a)

    # -- user input -----------------------------------------------------------------------------------------
    def _on_time(self, pos: int) -> None:
        if self._loading:
            return
        scale = scale_at(pos)
        self.time_label.setText(format_scale(scale))
        self.changed.emit({"time_scale": scale})

    def _on_age(self, value: float) -> None:
        if not self._loading:
            self.changed.emit({"age": float(value)})

    def _on_growth(self, pos: int) -> None:
        if self._loading:
            return
        percent = pos * 100.0 / GROWTH_SLIDER_STEPS
        self.growth_label.setText(f"{percent:.1f}%")
        self.changed.emit({"growth_percent": percent})

    def _on_forced(self, name: str, value) -> None:
        self.changed.emit({"force": {name: None if value is None else float(value)}})

    # -- public ---------------------------------------------------------------------------------------------
    def set_state(self, state, mature_age: float | None = None) -> None:
        """Fill every control from a sim.PlantState without emitting `changed`.

        `mature_age` (App.mature_age) is what 100 % growth means; it is remembered between calls.
        A slider being dragged and a spin box being typed into keep what the user is doing.
        """
        if mature_age is not None:
            self._mature_age = max(0.0, float(mature_age))
        self._loading = True
        try:
            scale = float(state.controls.time_scale)
            if not self.time_slider.isSliderDown():
                self.time_slider.setValue(pos_of_scale(scale))
            self.time_label.setText(format_scale(scale))
            if not self.age_spin.hasFocus():
                self.age_spin.setValue(float(state.age))
            percent = 100.0 * state.age / self._mature_age if self._mature_age > 0 else 0.0
            percent = min(100.0, max(0.0, percent))
            if not self.growth_slider.isSliderDown():
                self.growth_slider.setValue(round(percent * GROWTH_SLIDER_STEPS / 100.0))
            self.growth_label.setText(f"{percent:.1f}%")
            forced = state.controls.forced
            for name, row in self.force_rows.items():
                pinned = name in forced
                row.load(forced[name] if pinned else getattr(state.env, name), pinned)
        finally:
            self._loading = False
