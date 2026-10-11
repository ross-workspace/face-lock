"""Run Face Lock; no camera access in the explicit UI smoke-test mode."""

import argparse
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Render the real locked UI without accessing camera or Keychain, then quit",
    )
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument(
        "--check-models",
        action="store_true",
        help="Validate bundled assets and run blank-frame inference, then quit",
    )
    args = parser.parse_args()
    from facelock.qt_bootstrap import prepare_plugins

    prepare_plugins()
    # Matplotlib is an indirect MediaPipe dependency; keep its cache out of source/home.
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "face-lock-mpl"))
    if args.check_models:
        import numpy as np
        from facelock.vision import FaceEngine, MotionEngine

        engine = FaceEngine()
        try:
            _, result = engine.process(np.zeros((480, 640, 3), dtype=np.uint8))
            assert not result["valid"]
            motion = MotionEngine()
            try:
                frame = np.zeros((480, 640, 3), dtype=np.uint8)
                features = motion.process(frame, frame.copy(), engine.timestamp)
                assert not features["hands"] and not features["body"]
            finally:
                motion.close()
            print("Face, hand and body models loaded; blank-frame inference passed", flush=True)
        finally:
            engine.close()
        return 0
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from facelock.ui import STYLE, Window

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Face Lock")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    scratch = None
    if args.smoke_test:

        class EmptyKeychain:
            def get(self, account):
                return None

        scratch = tempfile.TemporaryDirectory(prefix="face-lock-smoke-")
        window = Window(Path(scratch.name), EmptyKeychain(), camera_on=False)
        window.status.setText("Ready to enroll your face")
        window.camera_view.setText("CAMERA PREVIEW\n\nCamera is off during the UI smoke test")
        window.camera_button.setText("Start camera")
    else:
        window = Window()
    window.show()
    if args.smoke_test:

        def finish():
            if args.screenshot:
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(args.screenshot))
            window.close()
            app.quit()

        QTimer.singleShot(900, finish)
    code = app.exec()
    if scratch:
        scratch.cleanup()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
