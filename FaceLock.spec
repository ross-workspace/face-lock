from pathlib import Path
import sys
import json
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH)
model_entries = json.loads((root / "models" / "models.json").read_text())
model_paths = [root / "models" / entry["name"] for entry in model_entries]
model_paths += [
    root / "models" / name
    for name in (
        "models.json",
        "face_detection_yunet-LICENSE.txt",
        "face_recognition_sface-LICENSE.txt",
    )
]
model_data = [(str(path), "models") for path in model_paths]
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=collect_dynamic_libs("mediapipe"),
    datas=model_data
    + collect_data_files("mediapipe", excludes=["**/*.dll", "**/*.dylib", "**/*.so"]),
    hiddenimports=(["Security", "Foundation"] if sys.platform == "darwin" else [])
    + ["mediapipe.tasks.python.vision.face_landmarker"],
    hookspath=[],
    excludes=[
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FaceLock" if sys.platform == "win32" else "Face Lock",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch="arm64" if sys.platform == "darwin" else None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Face Lock")
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Face Lock.app",
        bundle_identifier="local.face-lock.prototype",
        info_plist={
            "NSCameraUsageDescription": "Face Lock uses your camera locally to draw your face mesh and match your enrolled profile.",
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "0.3.0",
            "CFBundleVersion": "3",
        },
    )
