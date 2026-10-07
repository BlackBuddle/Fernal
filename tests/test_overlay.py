import pytest
from PySide6.QtCore import QEvent, QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from fernal.overlay import Bridge, OverlayWindow, build_menu

app = QApplication.instance() or QApplication([])

DEFAULTS = {
    "sunElevation": 45.0,
    "sunAzimuth": 180.0,
    "dayFactor": 1.0,
    "theme": "normal",
    "glowEnabled": False,
    "particlesEnabled": True,
    "potSource": "",
    "barkColor": "#5A4030",
    "emissiveColor": "#000000",
    "leafColor": "#4F8A3A",
    "leafEmissive": "#000000",
    "fruitColor": "#D9452B",
    "accentColor": "#5FA85A",
    "vitality": 1.0,
    "windStrength": 0.4,
    "cameraYaw": 0.0,
    "cameraPitch": 8.0,
    "cameraDistance": 650.0,
}
THEME_KEYS = ("theme:erdtree", "theme:normal", "theme:fruit")


def test_bridge_defaults():
    bridge = Bridge()
    for name, value in DEFAULTS.items():
        assert getattr(bridge, name) == value, name


@pytest.mark.parametrize("name,value", [("theme", "fruit"), ("sunElevation", 12.5), ("glowEnabled", True)])
def test_bridge_emits_only_on_change(name, value):
    bridge = Bridge()
    seen = []
    getattr(bridge, name + "Changed").connect(seen.append)
    setattr(bridge, name, DEFAULTS[name])  # same as default: no signal
    assert seen == []
    setattr(bridge, name, value)
    setattr(bridge, name, value)  # repeated write: still one signal
    assert seen == [value]
    assert getattr(bridge, name) == value


def test_build_menu_keys_and_checked_state():
    menu, actions = build_menu(None, "fruit", True)
    expected = {"water", "nutrients", "climate", "spray", "settings", "pot", "clickthrough", "quit", *THEME_KEYS}
    assert set(actions) == expected
    assert [actions[k].isChecked() for k in THEME_KEYS] == [False, False, True]
    assert actions["clickthrough"].isChecked()
    actions["theme:erdtree"].trigger()  # exclusive group: the previous choice is unchecked
    assert [actions[k].isChecked() for k in THEME_KEYS] == [True, False, False]
    _, plain = build_menu(None, "normal", False)
    assert not plain["clickthrough"].isChecked()
    assert plain["theme:normal"].isChecked()


@pytest.fixture
def window(tmp_path):
    """An OverlayWindow on a trivial scene: key and mouse handling need no 3D content."""
    qml = tmp_path / "Empty.qml"
    qml.write_text("import QtQuick\nItem {}\n", encoding="utf-8")
    geometries = {k: QObject() for k in ("branch", "leaf", "fruit")}
    win = OverlayWindow(Bridge(), geometries, QUrl(), source=qml)
    win._keep = geometries
    return win


def _key(key, modifiers):
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers)


def _right_click(modifiers):
    pos = QPointF(10, 10)
    return QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.RightButton,
                       Qt.MouseButton.RightButton, modifiers)


def test_debug_shortcut_key_requests_the_panel(window):
    seen = []
    window.debugRequested.connect(lambda: seen.append("debug"))
    both = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    window.keyPressEvent(_key(Qt.Key.Key_D, both))
    assert seen == ["debug"]
    window.keyPressEvent(_key(Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier))   # Ctrl alone: not it
    window.keyPressEvent(_key(Qt.Key.Key_A, both))
    assert seen == ["debug"]


def test_ctrl_shift_right_click_opens_debug_plain_right_click_opens_menu(window):
    debug, menu = [], []
    window.debugRequested.connect(lambda: debug.append(1))
    window.menuRequested.connect(menu.append)
    window.mousePressEvent(_right_click(Qt.KeyboardModifier.NoModifier))
    assert (len(debug), len(menu)) == (0, 1)
    window.mousePressEvent(_right_click(Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
    assert (len(debug), len(menu)) == (1, 1)
    window.mousePressEvent(_right_click(Qt.KeyboardModifier.ShiftModifier))
    assert (len(debug), len(menu)) == (1, 2)
