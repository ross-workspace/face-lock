import os

os.environ.setdefault("QT_QPA_PLATFORM", "minimal")

import time
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from facelock.ui import Window
from facelock.vault import create_vault
from test_profile import MemoryKeychain


def spin(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert predicate()


def test_background_open_export_lock_and_recovery_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("example")
    destination = tmp_path / "test.facevault"
    _, key = create_vault(source, destination)
    window = Window(tmp_path / "state", MemoryKeychain(), camera_on=False)
    window.vault = destination
    window.open_session(key)
    spin(app, lambda: window.task is None)
    assert window.session is not None
    assert window.file_list.count() == 1
    assert not window.unlock_button.isEnabled()
    assert window.lock_button.isEnabled()
    window.file_list.setCurrentRow(0)
    assert window.export_button.isEnabled()
    session = window.session
    target = tmp_path / "export.txt"
    thread_checks = []

    def done(result):
        thread_checks.append(QThread.currentThread() == app.thread())

    window.run_task(lambda progress: session.export(0, target), done)
    spin(app, lambda: window.task is None)
    assert thread_checks == [True]
    assert target.read_text() == "example"
    window.lock()
    assert window.session is None and session.key is None
    assert window.file_list.count() == 0
    assert not window.export_button.isEnabled()
    assert target.exists()
    window.open_session(key)
    spin(app, lambda: window.task is None)
    window.last_activity = time.monotonic() - 121
    window.check_idle()
    assert window.session is None
    window.close()


def test_stale_camera_success_cannot_unlock(tmp_path, monkeypatch):
    import facelock.ui as module
    from PySide6.QtCore import Signal
    import threading

    app = QApplication.instance() or QApplication([])
    release = threading.Event()

    class FakeCamera(QThread):
        frame_ready = Signal(object)
        status = Signal(str)
        score = Signal(float)
        enrolled = Signal(object)
        accepted = Signal()
        failed = Signal(str)
        gesture_recorded = Signal(object)
        capture_finished = Signal()
        lock_progress = Signal(int, int)

        def __init__(self, *args):
            super().__init__()

        def run(self):
            release.wait(2)
            self.accepted.emit()

    monkeypatch.setattr(module, "CameraWorker", FakeCamera)
    window = Window(tmp_path / "state", MemoryKeychain(), camera_on=False)
    accepted = []
    window.face_accepted = lambda: accepted.append(True)
    window.start_camera("unlock")
    window.stop_camera()
    release.set()
    spin(app, lambda: window.worker is None)
    assert accepted == []
    window.close()


def test_folder_ui_restores_and_reencrypts_same_path(tmp_path):
    from facelock import folder_vault as fv

    app = QApplication.instance() or QApplication([])
    root = tmp_path / "My folder"
    root.mkdir()
    (root / "actual.txt").write_text("original")
    prepared = fv.prepare(root)
    key = prepared["key"]
    fv.commit(prepared)
    keychain = MemoryKeychain()
    keychain.put("vault:" + prepared["id"], key)
    window = Window(tmp_path / "state", keychain, camera_on=False)
    window.folder = root
    window.vault = fv.archive_path(root)
    window.open_session(key)
    spin(app, lambda: window.task is None)
    assert window.folder_is_readable
    assert (root / "actual.txt").read_text() == "original"
    assert window.open_folder_button.isEnabled()
    assert not window.create_button.isEnabled()
    window.start_camera("record")
    assert window.worker is None and window.task is None
    (root / "actual.txt").write_text("user edit")
    window.lock()
    spin(app, lambda: window.task is None)
    assert not window.folder_is_readable
    assert not (root / "actual.txt").exists()
    window.open_session(key)
    spin(app, lambda: window.task is None)
    assert (root / "actual.txt").read_text() == "user edit"
    window.close()
    spin(app, lambda: window.task is None and not window.folder_is_readable)
    assert fv.folder_state(root) == "locked"


def test_close_cleanup_warning_keeps_app_open_with_locked_state(tmp_path, monkeypatch):
    from facelock import folder_vault as fv

    app = QApplication.instance() or QApplication([])
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "example.txt").write_text("synthetic contents")
    prepared = fv.prepare(root)
    key = prepared["key"]
    fv.commit(prepared)
    keychain = MemoryKeychain()
    keychain.put("vault:" + prepared["id"], key)
    window = Window(tmp_path / "state", keychain, camera_on=False)
    window.folder = root
    window.vault = fv.archive_path(root)
    window.show()
    window.open_session(key)
    spin(app, lambda: window.task is None)
    warnings = []
    monkeypatch.setattr(window, "error", warnings.append)
    original_rmtree = fv.shutil.rmtree

    def deny_readable_backup_removal(path, *args, **kwargs):
        if path.name.startswith(".face-lock-originals-"):
            raise PermissionError("simulated backup cleanup failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(fv.shutil, "rmtree", deny_readable_backup_removal)
    window.close()
    spin(app, lambda: window.task is None)
    assert fv.folder_state(root) == "locked"
    assert not window.folder_is_readable
    assert window.session is None
    assert not window.quit_after_lock
    assert window.isVisible()
    assert window.recovery_button.isEnabled()
    assert not window.lock_button.isEnabled()
    assert len(warnings) == 1 and "readable originals remain" in warnings[0]
    backups = list(tmp_path.glob(".face-lock-originals-*"))
    assert len(backups) == 1
    assert (backups[0] / "example.txt").read_text() == "synthetic contents"
    assert str(backups[0]) in warnings[0]
    monkeypatch.setattr(fv.shutil, "rmtree", original_rmtree)
    window.close()
    assert not window.isVisible()
