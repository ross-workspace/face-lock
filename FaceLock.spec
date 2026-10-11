from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'models'), 'models')] + collect_data_files('mediapipe', includes=['**/*.dylib', '**/*.so']),
    hiddenimports=['Security', 'Foundation', 'mediapipe.tasks.python.vision.face_landmarker'],
    hookspath=[],
    excludes=['pytest', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Face Lock',
          debug=False, strip=False, upx=False, console=False,
          argv_emulation=False, target_arch='arm64', codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Face Lock')
app = BUNDLE(coll, name='Face Lock.app', bundle_identifier='local.face-lock.prototype',
             info_plist={
                 'NSCameraUsageDescription': 'Face Lock uses your camera locally to draw your face mesh and match your enrolled profile.',
                 'NSHighResolutionCapable': True,
                 'CFBundleShortVersionString': '0.3.0',
                 'CFBundleVersion': '3',
             })
