# PyInstaller spec for Fernal: onedir, windowed. Build with packaging/build.py (or
# `pyinstaller packaging/fernal.spec --noconfirm --clean --distpath dist --workpath build` from the repo root).
from pathlib import Path

import pefile
import PySide6
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is the folder of this spec file (packaging/)
PKG = ROOT / "packaging"

VERSION = (1, 0, 0, 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION, prodvers=VERSION, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1,
                      subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Fernal"),
            StringStruct("FileDescription", "Fernal desktop plant"),
            StringStruct("FileVersion", ".".join(map(str, VERSION))),
            StringStruct("InternalName", "Fernal"),
            StringStruct("OriginalFilename", "Fernal.exe"),
            StringStruct("ProductName", "Fernal"),
            StringStruct("ProductVersion", ".".join(map(str, VERSION))),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

# ---- pruning: unused PySide6 Python modules ------------------------------------------------------------------
# What fernal imports, plus QtNetwork and QtOpenGL, which QtQml.pyd and QtQuick.pyd import themselves. Every
# other PySide6 module found in the installed package is excluded, so a newer PySide6 needs no list update.
PYSIDE_USED = {"QtCore", "QtGui", "QtWidgets", "QtQml", "QtQuick", "QtQuick3D", "QtNetwork", "QtOpenGL"}
PYSIDE_DIR = Path(PySide6.__file__).resolve().parent
EXCLUDES = sorted(
    f"PySide6.{pyd.stem}" for pyd in PYSIDE_DIR.glob("*.pyd") if pyd.stem not in PYSIDE_USED
) + ["tkinter", "unittest", "pydoc", "doctest"]

a = Analysis(
    [str(PKG / "launcher.py")],
    pathex=[str(ROOT)],
    # RuntimeLoader (a user's .glb pot) needs Qt Quick 3D's assimp importer; no hook collects it.
    binaries=[(str(PYSIDE_DIR / "plugins" / "assetimporters" / "assimp.dll"), "PySide6/plugins/assetimporters")],
    # Package-relative paths in the app (Path(__file__).parent / "qml", "assets") resolve to _internal/fernal/...
    datas=[
        (str(ROOT / "fernal" / "qml"), "fernal/qml"),
        (str(ROOT / "fernal" / "assets"), "fernal/assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

# ---- pruning: Qt files the app never loads -----------------------------------------------------------------
# PyInstaller's QtQml hook bundles the whole PySide6/qml tree and every Qt library behind it (WebEngine, Qt3D,
# Charts, Multimedia ...), about 440 MB. Scene.qml imports QtQuick, QtQuick3D, QtQuick3D.Helpers,
# QtQuick3D.Particles3D and QtQuick3D.AssetUtils, so only those modules and what they depend on stay.
QML_ROOT = "PySide6/qml/"
QML_KEEP = (
    "QtCore/", "QtQml/Models/", "QtQml/WorkerScript/", "QtQuick/Window/",
    "QtQuick3D/AssetUtils/", "QtQuick3D/Helpers/", "QtQuick3D/Particles3D/",
)
QML_KEEP_TOP = {  # loose files that sit directly in a kept module folder
    "QtQml": None, "QtQuick": {"qmldir", "qtquick2plugin.dll"}, "QtQuick3D": {"qmldir", "qquick3dplugin.dll"},
}


def keep_qml(rel):
    """rel is the path below PySide6/qml/."""
    if rel.endswith(".qmltypes") or "/designer/" in rel or "/tooling/" in rel:
        return False  # IDE metadata, never read by the QML engine
    if rel.startswith(QML_KEEP):
        return True
    top, _, rest = rel.partition("/")
    if "/" in rest or top not in QML_KEEP_TOP:
        return False
    return QML_KEEP_TOP[top] is None or rest in QML_KEEP_TOP[top]


# Qt plugins: the Windows platform plugin, the Windows 11 widget style, JPEG decoding (textures of a user's .glb
# pot) and the assimp importer. Not needed: other platforms, Qt Quick debugger, virtual keyboard, TLS backends
# (weather goes through Python's urllib), SVG, GIF and the other image formats.
PLUGIN_ROOT = "PySide6/plugins/"
PLUGIN_KEEP = {
    "platforms/qwindows.dll", "styles/qmodernwindowsstyle.dll", "imageformats/qjpeg.dll",
    "assetimporters/assimp.dll",
}
# The app installs no QTranslator, Direct3D 11 (Qt Quick's default on Windows) needs no software OpenGL, and the
# x64 OpenSSL pair was only a dependency of Qt's TLS plugin (Python ships its own libssl-3.dll / libcrypto-3.dll).
DROP_PREFIX = ("PySide6/translations/",)
DROP_FILES = {"PySide6/opengl32sw.dll", "libssl-3-x64.dll", "libcrypto-3-x64.dll"}


def keep_entry(entry):
    dest = entry[0].replace("\\", "/")
    if dest in DROP_FILES or dest.startswith(DROP_PREFIX):
        return False
    if dest.startswith(PLUGIN_ROOT):
        return dest[len(PLUGIN_ROOT):] in PLUGIN_KEEP
    return not dest.startswith(QML_ROOT) or keep_qml(dest[len(QML_ROOT):])


a.binaries = [e for e in a.binaries if keep_entry(e)]
a.datas = [e for e in a.datas if keep_entry(e)]


def pe_imports(path):
    """Lower-case names of the DLLs a PE file imports."""
    pe = pefile.PE(path, fast_load=True)
    try:
        pe.parse_data_directories([pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        return {imp.dll.decode().lower() for imp in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])}
    finally:
        pe.close()


def prune_unused_qt_libraries(binaries):
    """Keep a PySide6/Qt6*.dll only if the kept Python modules, plugins and QML plugins (transitively) import it."""
    def is_qt_lib(dest):
        d = dest.replace("\\", "/")
        return d.startswith("PySide6/Qt6") and d.endswith(".dll") and d.count("/") == 1

    libs = {Path(e[0]).name.lower(): e for e in binaries if is_qt_lib(e[0])}
    needed, todo = set(), [e[1] for e in binaries if not is_qt_lib(e[0])]
    while todo:
        for name in pe_imports(todo.pop()):
            if name in libs and name not in needed:
                needed.add(name)
                todo.append(libs[name][1])
    print(f"Qt libraries: keeping {len(needed)} of {len(libs)}")
    return [e for e in binaries if not is_qt_lib(e[0]) or Path(e[0]).name.lower() in needed]


a.binaries = prune_unused_qt_libraries(a.binaries)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Fernal",
    console=False,
    icon=str(PKG / "fernal.ico"),
    version=version_info,
    debug=False,
    strip=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Fernal")
