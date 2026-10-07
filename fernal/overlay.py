"""Overlay window, QML bridge, context menu and tray icon for Fernal.

Scene axes seen by Scene.qml: x = east, y = up, z = south (north is -z). The unit vector from the
origin toward the sun is (cos(el)*sin(az), sin(el), -cos(el)*cos(az)); the moon is opposite the sun.
"""
import logging
from pathlib import Path

from PySide6.QtCore import Property, QEvent, QObject, QPoint, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCursor, QIcon
from PySide6.QtQuick import QQuickView, QQuickWindow
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import themes

log = logging.getLogger(__name__)

DEFAULT_SCENE = Path(__file__).resolve().parent / "qml" / "Scene.qml"
DEFAULT_SIZE = (420, 640)
DRAG_THRESHOLD_PX = 4
DEBUG_MODIFIERS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier

# (theme key, Korean menu label) in menu order, straight from the theme table.
THEME_LABELS = tuple((key, t["label"]) for key, t in themes.THEMES.items())


def _prop(name, kind, default, notify):
    """Build a Qt Property backed by a plain attribute; the setter emits `notify` only on change."""
    attr = "_" + name

    def getter(self):
        return self.__dict__.get(attr, default)

    def setter(self, value):
        value = kind(value)
        if self.__dict__.get(attr, default) != value:
            self.__dict__[attr] = value
            getattr(self, name + "Changed").emit(value)

    return Property(kind, getter, setter, notify=notify)


class Bridge(QObject):
    """State shared with Scene.qml. Python writes (bridge.theme = "fruit"), QML reads and binds."""

    sunElevationChanged = Signal(float)
    sunElevation = _prop("sunElevation", float, 45.0, sunElevationChanged)  # degrees above horizon
    sunAzimuthChanged = Signal(float)
    sunAzimuth = _prop("sunAzimuth", float, 180.0, sunAzimuthChanged)  # degrees clockwise from north
    dayFactorChanged = Signal(float)
    dayFactor = _prop("dayFactor", float, 1.0, dayFactorChanged)  # 0 night .. 1 day
    themeChanged = Signal(str)
    theme = _prop("theme", str, "normal", themeChanged)
    glowEnabledChanged = Signal(bool)
    glowEnabled = _prop("glowEnabled", bool, False, glowEnabledChanged)
    particlesEnabledChanged = Signal(bool)
    particlesEnabled = _prop("particlesEnabled", bool, True, particlesEnabledChanged)
    potSourceChanged = Signal(str)
    potSource = _prop("potSource", str, "", potSourceChanged)  # file URL or empty
    barkColorChanged = Signal(str)
    barkColor = _prop("barkColor", str, "#5A4030", barkColorChanged)
    emissiveColorChanged = Signal(str)
    emissiveColor = _prop("emissiveColor", str, "#000000", emissiveColorChanged)
    leafColorChanged = Signal(str)
    leafColor = _prop("leafColor", str, "#4F8A3A", leafColorChanged)
    leafEmissiveChanged = Signal(str)
    leafEmissive = _prop("leafEmissive", str, "#000000", leafEmissiveChanged)
    fruitColorChanged = Signal(str)
    fruitColor = _prop("fruitColor", str, "#D9452B", fruitColorChanged)
    accentColorChanged = Signal(str)
    accentColor = _prop("accentColor", str, "#5FA85A", accentColorChanged)
    vitalityChanged = Signal(float)
    vitality = _prop("vitality", float, 1.0, vitalityChanged)
    windStrengthChanged = Signal(float)
    windStrength = _prop("windStrength", float, 0.4, windStrengthChanged)  # 0..1
    cameraYawChanged = Signal(float)
    cameraYaw = _prop("cameraYaw", float, 0.0, cameraYawChanged)  # degrees
    cameraPitchChanged = Signal(float)
    cameraPitch = _prop("cameraPitch", float, 8.0, cameraPitchChanged)  # degrees, -10..60
    cameraDistanceChanged = Signal(float)
    cameraDistance = _prop("cameraDistance", float, 650.0, cameraDistanceChanged)  # cm, 300..1200


class OverlayWindow(QQuickView):
    """Transparent, frameless, always-on-top window hosting Scene.qml."""

    hovered = Signal()
    clicked = Signal()
    menuRequested = Signal(QPoint)  # global position
    orbitRequested = Signal(float, float)  # dx, dy in pixels (Shift+drag)
    zoomRequested = Signal(float)  # wheel delta
    geometryChanged = Signal()
    debugRequested = Signal()  # Ctrl+Shift+D or Ctrl+Shift+right click

    def __init__(self, bridge, geometries, assets_url, source=None):
        # The alpha buffer must be requested before the first window exists.
        QQuickWindow.setDefaultAlphaBuffer(True)
        super().__init__()
        self._bridge = bridge
        self._geometries = geometries
        self._click_through = False
        self._pressed = False  # left button held after a press inside the window
        self._dragging = False
        self._orbiting = False  # drag mode, fixed once the threshold is crossed
        self._press_global = QPoint()
        self._press_window_pos = QPoint()
        self._last_global = QPoint()

        self.setTitle("Fernal")
        self.setColor(Qt.GlobalColor.transparent)
        self.setFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.resize(*DEFAULT_SIZE)

        ctx = self.rootContext()
        ctx.setContextProperty("bridge", bridge)
        ctx.setContextProperty("branchGeometry", geometries["branch"])
        ctx.setContextProperty("leafGeometry", geometries["leaf"])
        ctx.setContextProperty("fruitGeometry", geometries["fruit"])
        ctx.setContextProperty("assetsUrl", assets_url)

        if source is None:
            source = DEFAULT_SCENE
        self.setSource(source if isinstance(source, QUrl) else QUrl.fromLocalFile(str(source)))
        if self.status() == QQuickView.Status.Error:
            for err in self.errors():
                log.error("QML error: %s", err.toString())

    # ---- window state -------------------------------------------------------------------

    def set_click_through(self, on: bool) -> None:
        """Toggle WS_EX_TRANSPARENT in place (no re-show needed)."""
        self._click_through = bool(on)
        self.setFlag(Qt.WindowType.WindowTransparentForInput, self._click_through)

    def grab_png(self, path: str) -> bool:
        return self.grabWindow().save(str(path))

    # ---- events -------------------------------------------------------------------------

    def event(self, e):
        # Only hover needs the generic handler. Keep this override small: a Python event() is what forces
        # QSG_RENDER_LOOP=basic in __main__ (the threaded render loop hangs with it).
        if e.type() == QEvent.Type.Enter:
            self.hovered.emit()
        return super().event(e)

    def moveEvent(self, e):
        super().moveEvent(e)
        self.geometryChanged.emit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.geometryChanged.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_global = e.globalPosition().toPoint()
            self._last_global = self._press_global
            self._press_window_pos = self.position()
        elif e.button() == Qt.MouseButton.RightButton:
            if (e.modifiers() & DEBUG_MODIFIERS) == DEBUG_MODIFIERS:
                self.debugRequested.emit()
            else:
                self.menuRequested.emit(e.globalPosition().toPoint())
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_D and (e.modifiers() & DEBUG_MODIFIERS) == DEBUG_MODIFIERS:
            self.debugRequested.emit()
            e.accept()
            return
        super().keyPressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pressed and not (e.buttons() & Qt.MouseButton.LeftButton):
            self._pressed = False  # the release went elsewhere
        if self._pressed:
            pos = e.globalPosition().toPoint()
            delta = pos - self._press_global
            if not self._dragging and max(abs(delta.x()), abs(delta.y())) > DRAG_THRESHOLD_PX:
                self._dragging = True
                self._orbiting = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._dragging:
                if self._orbiting:
                    step = pos - self._last_global
                    self.orbitRequested.emit(float(step.x()), float(step.y()))
                else:
                    self.setPosition(self._press_window_pos + delta)
                self._last_global = pos
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            if not self._dragging:
                self.clicked.emit()
            self._dragging = False
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        self.zoomRequested.emit(float(e.angleDelta().y()))
        super().wheelEvent(e)


def build_menu(parent, state_theme: str, click_through: bool) -> tuple[QMenu, dict]:
    """Context menu shared by the overlay and the tray. Returns (menu, {key: QAction})."""
    menu = QMenu(parent)
    actions: dict[str, QAction] = {}

    def add(key, text, target=menu):
        action = target.addAction(text)
        actions[key] = action
        return action

    add("water", "물 주기")
    add("nutrients", "영양제")
    add("climate", "온도 조절")
    add("spray", "스프레이")
    add("settings", "설정")
    menu.addSeparator()

    theme_menu = menu.addMenu("테마")
    group = QActionGroup(theme_menu)
    group.setExclusive(True)
    for key, label in THEME_LABELS:
        action = add("theme:" + key, label, theme_menu)
        action.setCheckable(True)
        group.addAction(action)
        action.setChecked(key == state_theme)

    add("pot", "화분 바꾸기…")
    through = add("clickthrough", "클릭 통과")
    through.setCheckable(True)
    through.setChecked(bool(click_through))
    menu.addSeparator()
    add("quit", "종료")
    return menu, actions


class Tray(QSystemTrayIcon):
    """Tray icon sharing the overlay menu. The caller shows it (tray.show())."""

    def __init__(self, icon: QIcon, menu: QMenu):
        super().__init__(icon)
        self._menu = menu  # setContextMenu does not take ownership
        self.setToolTip("Fernal")
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # left click
            self._menu.popup(QCursor.pos())
            self._menu.activateWindow()  # lets an outside click dismiss the popup
