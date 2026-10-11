from pathlib import Path
from types import SimpleNamespace

import cv2
import pytest

from facelock import folder_vault as fv, vault, windows_files
from facelock.vision import open_camera


@pytest.mark.parametrize(
    "name",
    [
        "CON",
        "nul.txt",
        "folder/AUX.csv",
        "COM1",
        "LPT9.txt",
        "COM¹.txt",
        "trailing.",
        "trailing ",
        "a?b",
        "a|b",
        "a\x01b",
    ],
)
def test_windows_incompatible_names_are_rejected(name):
    with pytest.raises(vault.VaultError, match="portable"):
        vault.safe_name(name)


def test_windows_camera_falls_back_and_releases_failed_handle():
    attempts = []
    captures = []

    class Capture:
        def __init__(self, opened):
            self.opened = opened
            self.released = False

        def isOpened(self):
            return self.opened

        def release(self):
            self.released = True

    def factory(index, backend):
        attempts.append((index, backend))
        capture = Capture(backend == cv2.CAP_MSMF)
        captures.append(capture)
        return capture

    result = open_camera(2, platform="win32", factory=factory)
    assert attempts == [(2, cv2.CAP_DSHOW), (2, cv2.CAP_MSMF)]
    assert captures[0].released and not captures[1].released
    assert result is captures[1]


def test_closed_cameras_report_failure():
    class Capture:
        released = False

        def isOpened(self):
            return False

        def release(self):
            self.released = True

    captures = []

    def factory(index, backend):
        capture = Capture()
        captures.append(capture)
        return capture

    with pytest.raises(RuntimeError, match="Cannot open"):
        open_camera(0, platform="win32", factory=factory)
    assert len(captures) == 3 and all(item.released for item in captures)


@pytest.mark.parametrize("where", ["root", "directory", "file"])
def test_ntfs_named_streams_rejected_before_folder_replacement(tmp_path, monkeypatch, where):
    root = tmp_path / "original"
    directory = root / "nested"
    directory.mkdir(parents=True)
    path = directory / "example.txt"
    path.write_text("ordinary sample")
    target = {"root": root, "directory": directory, "file": path}[where]
    monkeypatch.setattr(vault, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(windows_files, "has_alternate_streams", lambda p: Path(p) == target)
    with pytest.raises(vault.VaultError, match="alternate data streams"):
        fv.prepare(root)
    assert path.read_text() == "ordinary sample"
    assert not (root / fv.BACKING).exists()
    assert not list(tmp_path.glob(".face-lock-*"))


def test_folder_swaps_never_hold_open_archive_handles(tmp_path, monkeypatch):
    root = tmp_path / "original"
    root.mkdir()
    (root / "example.txt").write_text("ordinary sample")
    sessions = []
    original_session = fv.VaultSession

    class TrackedSession(original_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

    monkeypatch.setattr(fv, "VaultSession", TrackedSession)
    rename = fv.os.rename

    def windows_style_rename(source, destination):
        for session in sessions:
            if session.path.is_relative_to(Path(source)):
                assert session.archive.fp is None, "Windows directory swap has an open archive"
        rename(source, destination)

    monkeypatch.setattr(fv.os, "rename", windows_style_rename)
    prepared = fv.prepare(root)
    fv.commit(prepared)
    assert fv.unlock(root, prepared["key"]) == 1
    (root / "example.txt").write_text("edited sample")
    assert fv.lock(root, prepared["key"]) == 1
    fv.unlock(root, prepared["key"])
    assert (root / "example.txt").read_text() == "edited sample"


def test_regular_file_read_when_no_posix_nofollow_flag(tmp_path, monkeypatch):
    path = tmp_path / "example.txt"
    path.write_bytes(b"example")
    monkeypatch.delattr(vault.os, "O_NOFOLLOW", raising=False)
    descriptor = vault.open_regular_file(path)
    try:
        assert vault.os.read(descriptor, 7) == b"example"
    finally:
        vault.os.close(descriptor)
