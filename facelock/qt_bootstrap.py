"""Keep Qt plugins off Documents file-provider metadata for source runs."""

import os
from pathlib import Path
import shutil
import sys
import tempfile


def prepare_plugins():
    if sys.platform != "darwin" or getattr(sys, "frozen", False):
        return
    import PySide6

    source = Path(PySide6.__file__).parent / "Qt" / "plugins" / "platforms"
    destination = Path(tempfile.mkdtemp(prefix="face-lock-qt-"))
    for path in source.glob("*.dylib"):
        shutil.copyfile(path, destination / path.name)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(destination)
    import atexit

    atexit.register(shutil.rmtree, destination, ignore_errors=True)
