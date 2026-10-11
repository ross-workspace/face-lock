from __future__ import annotations

import json
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .storage import Keychain, ProfileStore, data_dir
from .vault import (
    VaultSession,
    atomic_write,
    parse_recovery,
    recovery_text,
    replace_source,
    verify_source,
    vault_id,
)
from .vision import CameraWorker
from . import folder_vault

STYLE = """
QMainWindow, QWidget { background: #111418; color: #f0f2ed; font-family: 'Helvetica Neue'; font-size: 13px; }
QFrame#sidebar { background: #171a1f; border-right: 1px solid #292d32; }
QFrame#sidebar QLabel { background: transparent; }
QLabel#brand { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }
QLabel#logoMark { font-size: 32px; color: #c6f56d; }
QLabel#eyebrow { color: #7d8590; font-size: 10px; font-weight: 600; letter-spacing: 1.4px; }
QLabel#pageTitle { font-size: 27px; font-weight: 600; letter-spacing: -0.7px; }
QLabel#hero { font-size: 34px; font-weight: 600; letter-spacing: -1px; }
QLabel#scanTitle { font-size: 23px; font-weight: 600; }
QLabel#subtle { color: #a3abb6; font-size: 12px; }
QLabel#path { color: #e0e5d8; font-size: 13px; }
QLabel#section { color: #c6f56d; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
QLabel#cardTitle { font-size: 15px; font-weight: 600; }
QLabel#stepNumber { color: #c6f56d; font-size: 12px; font-weight: 600; }
QLabel#stepTitle { font-size: 18px; font-weight: 600; }
QLabel#badge { background: #21271c; color: #c6f56d; border: 1px solid #35432a; border-radius: 13px; padding: 7px 12px; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#local { color: #a3b589; font-size: 11px; }
QLabel#methodGlyph { color: #c6f56d; font-size: 30px; padding-right: 10px; }
QLabel#camera { background: #090c0f; border: 1px solid #30363f; border-radius: 14px; color: #8f98a5; }
QFrame#heroPanel { background: #1b211b; border: 1px solid #333e2c; border-radius: 18px; }
QFrame#heroPanel QLabel { background: transparent; }
QFrame#panel { background: #1a1e24; border: 1px solid #2c323a; border-radius: 14px; }
QFrame#panel QLabel, QFrame#identity QLabel, QFrame#method QLabel { background: transparent; }
QFrame#identity { background: #1d2229; border: 1px solid #2c323a; border-radius: 12px; }
QFrame#method { background: #191d23; border: 1px solid #2c323a; border-radius: 12px; }
QWidget#heroActions { background: transparent; }
QFrame#statusBar { border-top: 1px solid #2a3037; }
QLabel#state { color: #a3abb6; font-size: 12px; }
QLabel#statusDot { color: #c6f56d; font-size: 9px; padding-right: 4px; }
QPushButton { background: #262c34; color: #e7ebe3; border: 1px solid #38414b; border-radius: 8px; padding: 11px 14px; font-size: 12px; font-weight: 600; }
QPushButton:hover { background: #303942; border-color: #56626b; }
QPushButton:focus { border: 1px solid #c6f56d; }
QPushButton:disabled { color: #6c7581; background: #20252c; border-color: #2a3038; }
QPushButton#primary { background: #c6f56d; color: #182010; border: 1px solid #c6f56d; }
QPushButton#primary:hover { background: #d6ff8a; border-color: #d6ff8a; }
QPushButton#primary:disabled { background: #35412a; border-color: #35412a; color: #818e71; }
QPushButton#quiet { background: transparent; color: #aeb7c3; border: 1px solid transparent; }
QPushButton#quiet:hover { background: #252c34; color: #f0f2ed; }
QPushButton#nav { text-align: left; background: transparent; color: #a3abb6; border: 1px solid transparent; padding: 12px 10px; }
QPushButton#nav:hover { background: #242a32; }
QPushButton#nav:checked { background: #293222; color: #c6f56d; border-color: #3a482e; }
QPushButton#nav:disabled { color: #616974; background: transparent; }
QComboBox, QLineEdit, QTextEdit { background: #151a20; color: #e7ebe3; border: 1px solid #37404b; border-radius: 7px; padding: 9px; selection-background-color: #455936; }
QLineEdit:focus { border-color: #c6f56d; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #20262e; selection-background-color: #3a482e; }
QListWidget { background: #14191f; border: 1px solid #2d353f; border-radius: 8px; padding: 5px; outline: none; }
QListWidget::item { padding: 10px 8px; border-radius: 5px; margin-bottom: 3px; }
QListWidget::item:selected { background: #33402a; color: #d6f4ac; }
QListWidget::item:hover { background: #252d36; }
QCheckBox { background: transparent; color: #adb6c1; spacing: 7px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #4d5967; border-radius: 4px; background: #171d24; }
QCheckBox::indicator:checked { background: #c6f56d; border-color: #c6f56d; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #444e5b; border-radius: 3px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QMessageBox QLabel { min-width: 360px; }
"""


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, function):
        super().__init__()
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function(self.progress.emit))
        except Exception as error:
            self.failed.emit(str(error))


def label(text, name=None):
    item = QLabel(text)
    item.setWordWrap(
        name
        not in {
            "eyebrow",
            "brand",
            "pageTitle",
            "badge",
            "section",
            "cardTitle",
            "stepTitle",
            "local",
        }
    )
    item.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        item.setObjectName(name)
    return item


class Window(QMainWindow):
    def __init__(self, root=None, keychain=None, camera_on=True):
        super().__init__()
        self.setWindowTitle("Face Lock")
        self.setMinimumSize(1080, 760)
        self.resize(1240, 860)
        self.root = Path(root) if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.keychain = keychain or Keychain()
        self.store = ProfileStore(self.root, self.keychain)
        self.profile, self.session, self.vault = None, None, None
        self.worker, self.task, self.pending_camera = None, None, None
        self.busy, self.closing, self.camera_on = False, False, camera_on
        self.epoch = 0
        self.current_scan_mode = "preview"
        self.originals_removed = False
        self.folder = None
        self.folder_is_readable = False
        self.quit_after_lock = False
        self.sequence = []
        self.last_activity = time.monotonic()
        self.last_image = None
        self.make_ui()
        try:
            self.profile = self.store.load()
            self.sequence = self.store.load_sequence()
        except Exception as error:
            self.status.setText(str(error))
        config = self.root / "settings.json"
        if config.exists():
            try:
                data = json.loads(config.read_text())
                self.camera_choice.setCurrentIndex(max(0, min(int(data.get("camera", 0)), 3)))
                path = Path(data["vault"])
                if path.is_file():
                    vault_id(path)
                    self.vault = path
                    if data.get("folder"):
                        self.folder = Path(data["folder"])
                        self.folder_is_readable = (
                            folder_vault.folder_state(self.folder) == "unlocked"
                        )
                    self.originals_removed = bool(data.get("originals_removed", False))
            except Exception:
                pass
        self.refresh()
        QApplication.instance().installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_idle)
        self.timer.start(1000)
        self.status.setText(
            "Choose Unlock vault to scan your face."
            if self.vault
            else "Start by encrypting a folder, or open an existing vault."
        )

    def make_ui(self):
        from .layout import build

        build(self, label)

    def save_settings(self):
        data = {
            "camera": self.camera_choice.currentIndex(),
            "vault": str(self.vault) if self.vault else "",
            "folder": str(self.folder) if self.folder else "",
            "originals_removed": self.originals_removed,
        }
        atomic_write(self.root / "settings.json", json.dumps(data).encode(), replace=True)

    def refresh(self):
        self.update_navigation(self.pages.currentIndex())
        unlocked = self.session is not None
        readable = self.folder_is_readable
        self.profile_label.setText(
            "Face profile ready"
            if self.profile is not None
            else "Face setup needed before face unlock"
        )
        self.enroll_button.setText(
            "Face settings" if self.profile is not None else "Set up my face"
        )
        self.vault_label.setText(
            "Your folder is open."
            if readable
            else "Your files are unlocked."
            if unlocked
            else "Your folder is locked."
            if self.vault
            else "A home for your\nprivate files."
        )
        self.state_badge.setText(
            "DECRYPTED · READY TO USE"
            if readable or unlocked
            else "ENCRYPTED · LOCKED"
            if self.vault
            else "READY TO PROTECT"
        )
        self.vault_art.set_readable(readable or unlocked)
        self.setup_controls.setVisible(not unlocked and not readable)
        self.vault_hint.setText(
            str(self.folder)
            if self.folder
            else self.vault.name
            if self.vault
            else "Protect your files with your face and a sequence of gestures."
        )
        self.vault_hint.setToolTip(str(self.vault) if self.vault else "")
        self.source_note.setText(
            "Close any open files before locking. Lock encrypts this folder's current contents again."
            if readable
            else "This folder contains encrypted data, not readable originals. Unlock restores files at the same path."
            if self.folder
            else "Legacy archive: readable originals may still exist. Use Encrypt folder to protect the original folder in place."
            if self.vault
            else "You will save a recovery key before confirming encryption. Your folder keeps its name and location."
        )
        self.sequence_note.setText(
            f"Face match + {len(self.sequence)} recorded gesture locks"
            if self.sequence
            else "Face recognition, then two guided movement prompts"
        )
        self.sequence_button.setText(
            f"Gesture locks ({len(self.sequence)})" if self.sequence else "Gesture locks"
        )
        self.locked_controls.setVisible(not unlocked and self.vault is not None)
        self.unlocked_panel.setVisible(unlocked or readable)
        self.empty_panel.setVisible(not unlocked and not readable)
        self.unlock_button.setText(
            "Unlock folder" if self.profile is not None else "Set up face to unlock"
        )
        self.unlock_button.setEnabled(not self.busy and not unlocked and self.vault is not None)
        self.recovery_button.setEnabled(not self.busy and not unlocked and self.vault is not None)
        self.lock_button.setEnabled(not self.busy and (unlocked or readable))
        self.open_folder_button.setVisible(self.folder is not None)
        self.open_folder_button.setEnabled(not self.busy and readable)
        self.remove_originals_button.setEnabled(not self.busy and unlocked)
        self.remove_originals_button.setVisible(False)
        self.home_button.setEnabled(not self.busy)
        for item in (
            self.create_button,
            self.open_button,
            self.enroll_button,
            self.sequence_button,
            self.camera_choice,
            self.camera_button,
        ):
            item.setEnabled(not self.busy and not readable)
        self.refresh_export()

    def refresh_export(self):
        self.export_button.setEnabled(
            not self.busy and self.session is not None and self.file_list.currentRow() >= 0
        )

    def set_busy(self, value):
        self.busy = value
        self.refresh()

    def run_task(self, function, callback):
        if self.task is not None:
            return
        self.set_busy(True)
        task = Task(function)
        self.task = task
        task.progress.connect(self.status.setText)
        task.succeeded.connect(callback)
        task.failed.connect(self.error)
        task.finished.connect(self.task_finished)
        task.start()

    def task_finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        self.set_busy(False)
        if self.quit_after_lock and not self.folder_is_readable:
            QTimer.singleShot(0, self.close)

    def error(self, message):
        self.status.setText(message)
        QMessageBox.warning(self, "Face Lock", message)

    def camera_changed(self):
        if self.worker is not None or self.pending_camera is not None:
            self.start_camera(self.current_scan_mode)

    def go_home(self):
        if self.busy:
            return
        self.stop_camera()
        self.pages.setCurrentIndex(0)
        self.update_navigation(0)
        self.status.setText(
            "Vault is unlocked."
            if self.session
            else "Vault locked. Click Unlock vault when ready."
            if self.vault
            else "Start by encrypting a folder."
        )

    def start_camera(self, mode="preview"):
        if self.closing or self.busy:
            return
        if self.folder_is_readable:
            self.status.setText("Lock the folder before using camera settings.")
            return
        self.lock(clear_status=False)
        self.current_scan_mode = mode
        self.pages.setCurrentIndex(1)
        self.update_navigation(1)
        self.scan_title.setText(
            "Record your gesture locks"
            if mode == "record"
            else "Set up your face"
            if mode == "enroll"
            else "Unlock your vault"
            if mode == "unlock"
            else "Camera preview"
        )
        self.scan_help.setText(
            "Keep your face visible. Choose hands, body or both for each pose. Frames are not saved."
            if mode == "record"
            else "Stay alone in frame. Slowly vary your angle as samples are collected."
            if mode == "enroll"
            else "Keep your face visible and perform your recorded poses in order."
            if self.sequence
            else "Hold still for a match, then complete two short movement prompts."
        )
        self.record_editor.setVisible(mode == "record")
        self.lock_strip.setVisible(mode in ("record", "unlock"))
        self.lock_strip.configure(
            [s["name"] for s in self.sequence] if self.sequence else ["Movement 1", "Movement 2"]
        )
        self.epoch += 1
        self.pending_camera = mode
        self.camera_on = True
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText("Restarting camera…")
        else:
            self.launch_camera()

    def launch_camera(self):
        if self.pending_camera is None or self.closing:
            return
        mode, self.pending_camera = self.pending_camera, None
        token = self.epoch
        worker = CameraWorker(
            self.camera_choice.currentIndex(),
            mode,
            self.profile,
            self.sequence if mode == "unlock" else [],
        )
        self.worker = worker
        worker.frame_ready.connect(
            lambda image: self.show_frame(image) if token == self.epoch else None
        )
        worker.status.connect(
            lambda message: self.status.setText(message) if token == self.epoch else None
        )
        worker.score.connect(
            lambda score: (
                self.score_label.setText(
                    "Face matches" if score >= 0.55 else "Looking for your face"
                )
                if token == self.epoch
                else None
            )
        )
        worker.enrolled.connect(
            lambda vector: self.enrolled(vector) if token == self.epoch else None
        )
        worker.accepted.connect(lambda: self.face_accepted() if token == self.epoch else None)
        worker.failed.connect(
            lambda message: self.camera_failed(message) if token == self.epoch else None
        )
        worker.gesture_recorded.connect(
            lambda step: self.gesture_captured(step) if token == self.epoch else None
        )
        worker.capture_finished.connect(
            lambda: self.capture_completed() if token == self.epoch else None
        )
        worker.lock_progress.connect(
            lambda count, total: (
                self.lock_strip.configure(
                    [s["name"] for s in self.sequence]
                    if self.sequence
                    else ["Movement 1", "Movement 2"],
                    count,
                )
                if token == self.epoch
                else None
            )
        )
        worker.finished.connect(self.camera_finished)
        self.camera_button.setText("Cancel scan")
        worker.start()

    def camera_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.camera_button.setText("Back to vault")
        if self.pending_camera is not None:
            self.launch_camera()

    def camera_failed(self, message):
        self.status.setText(message)
        self.camera_view.setPixmap(QPixmap())
        self.camera_view.setText(message)

    def show_frame(self, image):
        self.last_image = image
        self.camera_view.setPixmap(
            QPixmap.fromImage(image).scaled(
                self.camera_view.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def stop_camera(self):
        self.epoch += 1
        self.pending_camera = None
        if self.worker is not None:
            self.worker.requestInterruption()
        self.camera_on = False
        self.last_image = None
        self.camera_view.setPixmap(QPixmap())
        self.camera_view.setText("Camera off")
        self.score_label.setText("")

    def toggle_camera(self):
        if self.worker is not None or self.pending_camera is not None:
            self.stop_camera()
            self.pages.setCurrentIndex(0)
            self.status.setText("Camera stopped")
        else:
            self.start_camera()

    def enroll(self):
        if self.profile is not None:
            answer = QMessageBox.question(
                self,
                "Replace face profile?",
                "Replace the enrolled face? Existing vaults and recovery keys will stay valid.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.start_camera("enroll")

    def configure_sequence(self):
        if self.profile is None:
            self.status.setText("Enroll your face before recording gesture locks.")
            self.enroll()
            return
        self.sequence_list.clear()
        for step in self.sequence:
            self.add_gesture_item(step)
        self.capture_button.setEnabled(self.sequence_list.count() < 12)
        self.save_sequence_button.setEnabled(self.sequence_list.count() > 0)
        self.start_camera("record")

    def add_gesture_item(self, step):
        item = QListWidgetItem(step["name"])
        item.setData(Qt.ItemDataRole.UserRole, step)
        self.sequence_list.addItem(item)

    def capture_pose(self):
        if self.worker is None or self.current_scan_mode != "record":
            return
        if not self.use_hands.isChecked() and not self.use_body.isChecked():
            self.error("Choose hands, body, or both before capturing.")
            return
        if self.sequence_list.count() >= 12:
            return
        name = self.gesture_name.text().strip() or f"Pose {self.sequence_list.count() + 1}"
        self.worker.commands.put(
            {"name": name, "hands": self.use_hands.isChecked(), "body": self.use_body.isChecked()}
        )
        self.capture_button.setEnabled(False)
        self.save_sequence_button.setEnabled(False)

    def gesture_captured(self, step):
        self.add_gesture_item(step)
        self.gesture_name.clear()
        self.save_sequence_button.setEnabled(True)
        self.lock_strip.configure(
            [self.sequence_list.item(i).text() for i in range(self.sequence_list.count())]
        )

    def capture_completed(self):
        self.capture_button.setEnabled(self.sequence_list.count() < 12)
        self.save_sequence_button.setEnabled(self.sequence_list.count() > 0)

    def delete_gesture_step(self):
        row = self.sequence_list.currentRow()
        if row >= 0:
            self.sequence_list.takeItem(row)
        self.capture_button.setEnabled(self.sequence_list.count() < 12)
        self.save_sequence_button.setEnabled(self.sequence_list.count() > 0)
        self.lock_strip.configure(
            [self.sequence_list.item(i).text() for i in range(self.sequence_list.count())]
        )

    def save_sequence(self):
        steps = [
            self.sequence_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.sequence_list.count())
        ]
        try:
            self.store.save_sequence(steps)
            self.sequence = steps
            self.go_home()
            self.refresh()
            self.status.setText(
                f"Saved {len(steps)} gesture locks. Perform them in this order to unlock."
            )
        except Exception as error:
            self.error(str(error))

    def enrolled(self, vector):
        try:
            self.store.save(vector)
            self.profile = vector
            self.status.setText("Profile enrolled. Create or select a vault.")
            self.stop_camera()
            self.refresh()
        except Exception as error:
            self.error(str(error))

    def choose_vault(self):
        filename = QFileDialog.getExistingDirectory(
            self, "Choose a folder previously encrypted by Face Lock"
        )
        if not filename:
            return
        try:
            folder_vault.folder_state(filename)
            if self.folder_is_readable:
                self.error("Lock the current folder before switching to another one.")
                return
            self.lock()
            self.folder = Path(filename)
            self.vault = folder_vault.archive_path(self.folder)
            self.folder_is_readable = folder_vault.folder_state(self.folder) == "unlocked"
            self.originals_removed = False
            self.save_settings()
            self.refresh()
        except Exception as error:
            self.error(str(error))

    def create(self):
        if self.busy or self.folder_is_readable:
            return
        source = QFileDialog.getExistingDirectory(self, "Choose the original folder to encrypt")
        if not source:
            return
        root = Path(source).resolve()
        project = Path(__file__).resolve().parents[1]
        if project.is_relative_to(root) or self.root.resolve().is_relative_to(root):
            self.error("Choose a data folder that does not contain the app or its settings.")
            return
        self.lock(clear_status=False)
        self.stop_camera()

        def prepared(result):
            key_error = None
            try:
                self.keychain.put("vault:" + result["id"], result["key"])
            except Exception as error:
                key_error = str(error)
            self.show_recovery(result["key"])
            if not self.confirm_removal(source, result["count"]):
                folder_vault.cancel(result)
                self.status.setText("Cancelled. The original folder is unchanged.")
                return

            def apply():
                if self.task is not None:
                    QTimer.singleShot(50, apply)
                    return

                def committed(count):
                    self.folder = root
                    self.folder_is_readable = False
                    self.vault = folder_vault.archive_path(root)
                    self.originals_removed = True
                    self.save_settings()
                    self.refresh()
                    self.status.setText(f"Folder encrypted in place: {count} files protected.")
                    if getattr(count, "warning", ""):
                        self.error(count.warning)
                    if key_error:
                        self.error(
                            "Folder encrypted. Keychain storage failed, so use the recovery key. "
                            + key_error
                        )

                self.run_task(lambda progress: folder_vault.commit(result, progress), committed)

            QTimer.singleShot(0, apply)

        self.run_task(lambda progress: folder_vault.prepare(root, progress), prepared)

    def confirm_removal(self, source, count):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Encrypt this folder in place?")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            f"All {count} files were encrypted and verified. Replace this folder's readable contents with the encrypted data?\n\n{source}"
        )
        dialog.setInformativeText(
            "The folder keeps its original path. Unlock restores the files there. Your saved recovery key can restore them if face unlock fails. Only file contents and folder structure are preserved; permissions, timestamps, extended attributes and ACLs are not preserved. Resource forks are rejected. Existing SSD remnants and sync history cannot be securely erased."
        )
        remove = dialog.addButton("Encrypt original folder", QMessageBox.ButtonRole.DestructiveRole)
        keep = dialog.addButton("Cancel — keep originals", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(keep)
        dialog.exec()
        return dialog.clickedButton() == remove

    def finish_removal(self, source, key):
        if self.task is not None:
            QTimer.singleShot(50, lambda: self.finish_removal(source, key))
            return
        destination = self.vault
        self.lock(clear_status=False)

        def removed(count):
            self.originals_removed = True
            self.save_settings()
            self.status.setText(f"Protected: {count} files encrypted. Original folder removed.")
            self.refresh()

        self.run_task(lambda progress: replace_source(source, destination, key, progress), removed)

    def remove_existing_originals(self):
        if self.session is None or self.busy:
            return
        source = QFileDialog.getExistingDirectory(
            self, "Choose the original folder that matches this vault"
        )
        if not source or self.session is None:
            return
        session, key = self.session, self.session.key

        def verified(count):
            self.status.setText(f"All {count} original files match the encrypted vault.")
            if self.confirm_removal(source, count):
                self.show_recovery(key)
                QTimer.singleShot(0, lambda: self.finish_removal(source, key))

        self.run_task(lambda progress: verify_source(source, session, progress), verified)

    def show_recovery(self, key):
        # Do not copy secrets to clipboard automatically or write beside the vault automatically.
        text = recovery_text(key)
        from PySide6.QtWidgets import QDialog, QTextEdit

        class RecoveryDialog(QDialog):
            saved = False

            def reject(dialog):
                if dialog.saved:
                    dialog.accept()
                else:
                    QMessageBox.information(
                        dialog,
                        "Save the key first",
                        "Save a recovery key before closing this dialog.",
                    )

        form = RecoveryDialog(self)
        form.setWindowTitle("Save your recovery key")
        form.setMinimumWidth(560)
        content = QVBoxLayout(form)
        content.addWidget(
            label(
                "This key opens the vault without your face or this Mac. Store it separately from the vault."
            )
        )
        field = QTextEdit(text)
        field.setReadOnly(True)
        field.setMaximumHeight(100)
        content.addWidget(field)
        save_button = QPushButton("Save key to file…")
        finish = QPushButton("I have saved the key")
        finish.setEnabled(False)

        def write():
            filename, _ = QFileDialog.getSaveFileName(
                form, "Save recovery key separately", "Face Lock recovery.txt", "Text file (*.txt)"
            )
            if filename:
                try:
                    atomic_write(filename, (text + "\n").encode())
                    form.saved = True
                    finish.setEnabled(True)
                except Exception as error:
                    QMessageBox.warning(form, "Recovery key", str(error))

        save_button.clicked.connect(write)
        finish.clicked.connect(form.accept)
        content.addWidget(save_button)
        content.addWidget(finish)
        form.exec()

    def unlock(self):
        if self.profile is None:
            self.enroll()
        else:
            self.start_camera("unlock")

    def face_accepted(self):
        if not self.vault:
            return
        self.stop_camera()
        try:
            identifier = vault_id(self.vault)
            key = self.keychain.get("vault:" + identifier)
            if key is None:
                raise ValueError("No key for this vault on this Mac. Use your recovery key.")
            self.open_session(key)
        except Exception as error:
            self.error(str(error))

    def open_session(self, key):
        path = self.vault
        self.stop_camera()

        def opened(session):
            self.session = session
            self.folder_is_readable = self.folder is not None
            self.file_list.clear()
            for entry in session.files:
                self.file_list.addItem(QListWidgetItem(f"{entry['name']}\n{entry['size']:,} bytes"))
            self.last_activity = time.monotonic()
            self.status.setText(
                "Folder decrypted at its original path. Open it, then Lock when finished."
                if self.folder
                else "Vault unlocked. Choose a file to export."
            )
            self.pages.setCurrentIndex(0)
            self.refresh()

        def restore(progress):
            if self.folder:
                folder_vault.unlock(self.folder, key, progress)
            return VaultSession(path, key)

        self.run_task(restore, opened)

    def open_folder(self):
        if self.folder and self.folder_is_readable:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    def recover(self):
        text, ok = QInputDialog.getText(
            self, "Recovery key", "Enter the FL1- recovery key:", QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        try:
            key = parse_recovery(text)
            self.open_session(key)
        except Exception as error:
            self.error(str(error))

    def export(self):
        if self.session is None or self.busy:
            return
        index = self.file_list.currentRow()
        if index < 0:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export readable copy — it remains after locking",
            Path(self.session.files[index]["name"]).name,
        )
        if filename:
            session = self.session
            self.run_task(
                lambda progress: session.export(index, filename),
                lambda result: self.status.setText(
                    "File exported. This readable copy remains after locking."
                ),
            )

    def lock(self, checked=False, clear_status=True):
        if self.busy:
            return
        if self.folder and self.folder_is_readable:
            try:
                key = (
                    self.session.key
                    if self.session
                    else self.keychain.get("vault:" + vault_id(self.vault))
                )
                if key is None:
                    raise ValueError(
                        "Use your recovery key to unlock this readable folder before re-encrypting it."
                    )
            except Exception as error:
                self.error(str(error))
                return
            if self.session:
                self.session.close()
                self.session = None
            self.stop_camera()

            def encrypted(count):
                self.folder_is_readable = False
                self.file_list.clear()
                self.refresh()
                self.status.setText(f"Folder locked: {count} files encrypted in place.")
                if getattr(count, "warning", ""):
                    self.quit_after_lock = False
                    self.error(count.warning)

            self.run_task(lambda progress: folder_vault.lock(self.folder, key, progress), encrypted)
            return
        self.epoch += 1
        self.pending_camera = None
        if self.worker is not None:
            self.worker.requestInterruption()
        if self.session is not None:
            self.session.close()
            self.session = None
        self.file_list.clear()
        if clear_status:
            self.status.setText("Vault locked")
            self.pages.setCurrentIndex(0)
        self.refresh()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.Wheel):
            self.last_activity = time.monotonic()
        if event.type() == QEvent.Type.ApplicationDeactivate and not self.busy and not self.folder:
            self.lock()
            self.stop_camera()
        return super().eventFilter(watched, event)

    def check_idle(self):
        if (
            self.session is not None
            and not self.folder
            and not self.busy
            and time.monotonic() - self.last_activity > 120
        ):
            self.lock()

    def closeEvent(self, event):
        if self.busy or self.task is not None:
            event.ignore()
            self.status.setText("Wait for the current file operation to finish before closing.")
            return
        if self.folder_is_readable:
            event.ignore()
            self.quit_after_lock = True
            self.lock()
            return
        self.closing = True
        self.stop_camera()
        self.lock()
        if self.worker is not None and not self.worker.wait(1500):
            event.ignore()
            QTimer.singleShot(250, self.close)
            return
        try:
            self.save_settings()
        except Exception:
            pass
        event.accept()
