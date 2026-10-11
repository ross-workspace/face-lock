from pathlib import Path
import pytest
from facelock import folder_vault as fv
from facelock.vault import VaultError, vault_id


def source(tmp_path):
    root = tmp_path / "Original"
    (root / "nested").mkdir(parents=True)
    (root / "nested" / "private.txt").write_bytes(b"secret content example")
    (root / "empty").mkdir()
    (root / "other.bin").write_bytes(b"\x00\xffdata")
    return root


def test_original_path_roundtrip_and_edits(tmp_path):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    key, identifier = prepared["key"], prepared["id"]
    assert (root / "nested/private.txt").exists()
    assert fv.commit(prepared) == 2
    assert root.is_dir() and list(root.iterdir()) == [root / fv.BACKING]
    assert fv.folder_state(root) == "locked"
    ciphertext = fv.archive_path(root).read_bytes()
    assert b"secret content example" not in ciphertext
    assert b"private.txt" not in ciphertext
    assert not list(tmp_path.glob(".face-lock-*"))
    # Finder metadata must not prevent unlocking.
    (root / ".DS_Store").write_bytes(b"finder metadata")
    assert fv.unlock(root, key) == 2
    assert (root / "nested/private.txt").read_bytes() == b"secret content example"
    assert (root / "empty").is_dir()
    (root / "nested/private.txt").write_text("edited")
    (root / "other.bin").unlink()
    (root / "new.txt").write_text("new")
    assert fv.lock(root, key) == 2
    assert vault_id(fv.archive_path(root)) == identifier
    assert fv.archive_path(root).read_bytes() != ciphertext
    fv.unlock(root, key)
    assert (root / "nested/private.txt").read_text() == "edited"
    assert (root / "new.txt").read_text() == "new"
    assert not (root / "other.bin").exists()
    # Re-locking an emptied folder is supported.
    (root / "nested/private.txt").unlink()
    (root / "new.txt").unlink()
    assert fv.lock(root, key) == 0
    assert fv.unlock(root, key) == 0


def test_cancel_preserves_originals(tmp_path):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    fv.cancel(prepared)
    assert (root / "nested/private.txt").read_bytes() == b"secret content example"
    assert not (root / fv.BACKING).exists()
    assert not list(tmp_path.glob(".face-lock-*"))


def test_changed_originals_abort_commit(tmp_path):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    (root / "other.bin").write_bytes(b"changed")
    with pytest.raises(VaultError):
        fv.commit(prepared)
    assert (root / "other.bin").read_bytes() == b"changed"
    assert not list(tmp_path.glob(".face-lock-*"))


def test_failed_swap_restores_originals(tmp_path, monkeypatch):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    rename = fv.os.rename

    def fail_stage(src, dest):
        if Path(src) == prepared["stage"]:
            raise OSError("simulated failed commit")
        rename(src, dest)

    monkeypatch.setattr(fv.os, "rename", fail_stage)
    with pytest.raises(OSError):
        fv.commit(prepared)
    assert (root / "other.bin").read_bytes() == b"\x00\xffdata"
    assert not list(tmp_path.glob(".face-lock-*"))


def test_wrong_key_leaves_folder_locked(tmp_path):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    fv.commit(prepared)
    with pytest.raises(VaultError):
        fv.unlock(root, b"x" * 32)
    assert fv.folder_state(root) == "locked"
    assert not (root / "nested/private.txt").exists()
    assert not list(tmp_path.glob(".face-lock-*"))


def test_cleanup_failure_reports_committed_state(tmp_path, monkeypatch):
    root = source(tmp_path)
    prepared = fv.prepare(root)
    remove = fv.shutil.rmtree

    def fail_originals(path, *args, **kwargs):
        if Path(path).name.startswith(".face-lock-originals-"):
            raise OSError("simulated cleanup failure")
        return remove(path, *args, **kwargs)

    monkeypatch.setattr(fv.shutil, "rmtree", fail_originals)
    result = fv.commit(prepared)
    assert result == 2
    assert "readable originals remain" in result.warning
    assert fv.folder_state(root) == "locked"
    assert not (root / "other.bin").exists()
    backups = list(tmp_path.glob(".face-lock-originals-*"))
    assert len(backups) == 1
    assert (backups[0] / "other.bin").read_bytes() == b"\x00\xffdata"
    fv.unlock(root, prepared["key"])
    assert (root / "other.bin").read_bytes() == b"\x00\xffdata"


def test_resource_fork_rejected_before_replacing_originals(tmp_path, monkeypatch):
    from facelock import vault

    root = source(tmp_path)
    monkeypatch.setattr(vault, "has_resource_fork", lambda path: path.name == "other.bin")
    with pytest.raises(VaultError, match="resource forks"):
        fv.prepare(root)
    assert (root / "other.bin").read_bytes() == b"\x00\xffdata"
    assert not (root / fv.BACKING).exists()
    assert not list(tmp_path.glob(".face-lock-*"))
