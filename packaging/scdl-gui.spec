# PyInstaller build for the Windows app.  Build:  pyinstaller packaging/scdl-gui.spec --noconfirm
# Produces dist/scdl-gui/scdl-gui.exe (one folder, so Qt's LGPL libraries stay replaceable).
# The same exe runs the download worker when started with --worker.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is provided by PyInstaller

datas = [(str(ROOT / "assets"), "assets"), (str(ROOT / "LICENSE"), ".")]
binaries = []
hiddenimports = ["docopt"]
for package in ("yt_dlp", "yt_dlp_ejs", "scdl", "soundcloud", "mutagen", "curl_cffi"):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("scdl")  # scdl reads its own version with importlib.metadata

a = Analysis(
    [str(ROOT / "scdl-gui.pyw")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "qt_material", "PyQt5", "PyQt6", "unittest", "pydoc_data", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="scdl-gui",
    icon=str(ROOT / "assets" / "icon.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="scdl-gui", upx=False)
