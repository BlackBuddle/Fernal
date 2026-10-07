import pytest
from PySide6.QtWidgets import QApplication

from fernal.overlay import Bridge, build_menu

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
