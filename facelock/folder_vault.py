"""Replace folder contents at the original path, with verified staged swaps."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .vault import (
    VaultError,
    VaultSession,
    atomic_write,
    create_vault,
    verify_source,
    vault_id,
    is_linked,
)

BACKING = ".face-lock-vault"


class CommitResult(int):
    """A completed folder swap may still need manual plaintext cleanup."""

    def __new__(cls, count, warning=""):
        result = super().__new__(cls, count)
        result.warning = warning
        return result


def archive_path(folder):
    return Path(folder) / BACKING / "contents.facevault"


def folder_state(folder):
    folder = Path(folder)
    backing = folder / BACKING
    if is_linked(folder) or is_linked(backing) or is_linked(archive_path(folder)):
        raise VaultError("Encrypted folder metadata must not be symlinked.")
    state_file = backing / "state.json"
    if state_file.stat().st_size > 4096:
        raise VaultError("Invalid folder state.")
    state = json.loads(state_file.read_text())
    if state not in ({"version": 1, "state": "locked"}, {"version": 1, "state": "unlocked"}):
        raise VaultError("Invalid folder state.")
    vault_id(archive_path(folder))
    return state["state"]


def write_state(folder, state):
    atomic_write(
        Path(folder) / BACKING / "state.json",
        json.dumps({"version": 1, "state": state}).encode(),
        replace=True,
    )


def prepare(folder, progress=lambda message: None, key=None):
    folder = Path(folder)
    if is_linked(folder):
        raise VaultError("Choose an ordinary folder.")
    folder = folder.resolve(strict=True)
    if folder == Path.home() or folder == Path(folder.anchor):
        raise VaultError("Choose a specific data folder, not your home or filesystem root.")
    managed = (folder / BACKING).exists()
    if managed and folder_state(folder) != "unlocked":
        raise VaultError("This folder is already encrypted.")
    if managed and key is None:
        raise VaultError("The vault key is needed to re-encrypt this folder.")
    identifier = vault_id(archive_path(folder)) if managed else None
    excluded = (BACKING,) if managed else ()
    staged = Path(tempfile.mkdtemp(prefix=".face-lock-encrypt-", dir=folder.parent))
    (staged / BACKING).mkdir(mode=0o700)
    try:
        identifier, key = create_vault(
            folder,
            archive_path(staged),
            progress,
            key=key,
            existing_id=identifier,
            excluded=excluded,
            allow_empty=managed,
        )
        session = VaultSession(archive_path(staged), key)
        try:
            count = verify_source(folder, session, progress, excluded=excluded)
        finally:
            session.close()
        write_state(staged, "locked")
        return {
            "folder": folder,
            "stage": staged,
            "key": key,
            "id": identifier,
            "count": count,
            "excluded": excluded,
        }
    except Exception:
        shutil.rmtree(staged)
        raise


def commit(prepared, progress=lambda message: None):
    """Destructive only after UI approval. Reverify after moving originals."""
    folder, staged = prepared["folder"], prepared["stage"]
    backup = folder.parent / (".face-lock-originals-" + uuid.uuid4().hex)
    session = None
    committed = False
    try:
        session = VaultSession(archive_path(staged), prepared["key"])
        verify_source(folder, session, progress, excluded=prepared["excluded"])
        os.rename(folder, backup)
        try:
            verify_source(backup, session, progress, excluded=prepared["excluded"])
            # Windows cannot rename directories holding open archive handles.
            session.close()
            os.rename(staged, folder)
            committed = True
        except Exception:
            if not folder.exists():
                os.rename(backup, folder)
            raise
        progress("Removing verified readable originals…")
        warning = ""
        try:
            shutil.rmtree(backup)
        except OSError:
            warning = f"Folder is encrypted, but some readable originals remain at {backup}. Remove them after checking the vault."
        return CommitResult(prepared["count"], warning)
    finally:
        if session:
            session.close()
        if not committed and staged.exists():
            shutil.rmtree(staged)


def cancel(prepared):
    if prepared["stage"].exists():
        shutil.rmtree(prepared["stage"])


def unlock(folder, key, progress=lambda message: None):
    folder = Path(folder).resolve(strict=True)
    if folder_state(folder) == "unlocked":
        session = VaultSession(archive_path(folder), key)
        try:
            return len(session.files)
        finally:
            session.close()
    if set(item.name for item in folder.iterdir()) - {BACKING, ".DS_Store"}:
        raise VaultError(
            "Unexpected files in locked folder. Move those extra files elsewhere before unlocking."
        )
    session = VaultSession(archive_path(folder), key)
    count = len(session.files)
    staged = Path(tempfile.mkdtemp(prefix=".face-lock-decrypt-", dir=folder.parent))
    backup = folder.parent / (".face-lock-ciphertext-" + uuid.uuid4().hex)
    moved = False
    try:
        for name in session.directories:
            (staged / name).mkdir(parents=True, exist_ok=True, mode=0o700)
        for index, entry in enumerate(session.files):
            progress(f"Restoring file {index + 1} of {len(session.files)}")
            target = staged / entry["name"]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            session.export(index, target)
        verify_source(staged, session, progress)
        (staged / BACKING).mkdir(mode=0o700)
        # Copy bytes, not external metadata or symlinks.
        with (
            open(archive_path(folder), "rb") as source,
            open(archive_path(staged), "xb") as destination,
        ):
            shutil.copyfileobj(source, destination)
        os.chmod(archive_path(staged), 0o600)
        write_state(staged, "unlocked")
        session.close()
        os.rename(folder, backup)
        try:
            os.rename(staged, folder)
            moved = True
        except Exception:
            os.rename(backup, folder)
            raise
        try:
            shutil.rmtree(backup)
        except OSError:
            progress(f"Files restored. An encrypted backup remains at {backup}.")
        return count
    finally:
        session.close()
        if not moved and staged.exists():
            shutil.rmtree(staged)


def lock(folder, key, progress=lambda message: None):
    prepared = prepare(folder, progress, key)
    return commit(prepared, progress)
