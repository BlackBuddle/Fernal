import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from fernal.tools import GlassPanel, SettingsPanel, ToolPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _record(signal):
    got = []
    signal.connect(lambda *args: got.append(args))
    return got


@pytest.mark.parametrize("kind, expected", [
    ("water", ("water", 0.2)),
    ("nutrients", ("feed", 0.3)),
    ("spray", ("spray", 0.15)),
])
def test_button_emits_action(app, kind, expected):
    panel = ToolPanel(kind, "#5FA85A")
    got = _record(panel.action)
    QTest.mouseClick(panel.button, Qt.MouseButton.LeftButton)
    assert got == [expected]
    panel.set_value(0.4)
    panel.set_caption("현재 24.5°C")
    assert got == [expected]


def test_climate_slider_emits_heater_and_set_value_is_silent(app):
    panel = ToolPanel("climate", "#E8C06A")
    got = _record(panel.action)
    panel.slider.setValue(3)
    assert got == [("heater", 3.0)]
    panel.slider.setValue(-4)          # within the throttle window: delivered shortly after
    QTest.qWait(200)
    assert got[-1] == ("heater", -4.0)
    count = len(got)
    panel.set_value(0.9)
    QTest.qWait(150)
    assert len(got) == count
    assert panel.slider.value() == 8


def test_settings_set_values_is_silent_user_actions_emit(app):
    panel = SettingsPanel("#5FA85A")
    got = []
    for sig in (panel.themeChanged, panel.potChosen, panel.cityChanged, panel.sizeChanged):
        sig.connect(lambda *args, s=sig: got.append(args))
    panel.set_values("erdtree", "C:/pots/a.glb", "서울", 500, 700)
    assert got == []
    assert panel.theme_combo.currentData() == "erdtree"
    assert panel.city_edit.text() == "서울"
    assert (panel.width_spin.value(), panel.height_spin.value()) == (500, 700)

    panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("fruit"))
    panel.city_edit.setText("부산")
    QTest.mouseClick(panel.city_apply, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.pot_default, Qt.MouseButton.LeftButton)
    QTest.mouseClick(panel.size_apply, Qt.MouseButton.LeftButton)
    assert got == [("fruit",), ("부산",), ("",), (500, 700)]
    assert (panel.width_spin.minimum(), panel.width_spin.maximum()) == (240, 900)
    assert (panel.height_spin.minimum(), panel.height_spin.maximum()) == (360, 1400)
    panel.set_status("서울특별시")


def test_accent_and_show_animated_do_not_raise(app):
    panels = [GlassPanel("테스트"), ToolPanel("water", "#5FA85A"), ToolPanel("climate", "#5FA85A"),
              SettingsPanel()]
    for p in panels:
        p.set_accent("#E2563A")
        p.show_animated()
    for _ in range(40):  # wait for the 150 ms fade; a fixed wait is flaky with four windows
        QTest.qWait(50)
        if all(p.windowOpacity() >= 0.999 for p in panels):
            break
    for p in panels:
        assert p.windowOpacity() == pytest.approx(1.0)
        p.close()
