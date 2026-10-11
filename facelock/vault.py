"""Immutable, bounded encrypted archives. No ZIP extraction of supplied paths."""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import shutil
import tempfile
import uuid
import sys
import ctypes
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_FILES = 2000
MAX_MANIFEST = 2 * 1024 * 1024


class VaultError(ValueError):
    pass


def safe_name(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise VaultError("Invalid filename in vault.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise VaultError("Unsafe filename in vault.")
    if "\\" in value or ":" in value or "\x00" in value:
        raise VaultError("Unsafe filename in vault.")
    return value


def aad(vault_id, part):
    return f"face-lock:v1:{vault_id}:{part}".encode()


def encrypt(key, data, context):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(key).encrypt(nonce, data, context)


def decrypt(key, data, context):
    if len(data) < 28:
        raise VaultError("Truncated encrypted data.")
    try:
        return AESGCM(key).decrypt(data[:12], data[12:], context)
    except (InvalidTag, ValueError) as error:
        raise VaultError("Wrong recovery key or damaged vault.") from error


def atomic_write(path, data, *, replace=False):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".face-lock-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)  # Atomic, never overwrites an existing file.
    finally:
        Path(name).unlink(missing_ok=True)


def has_resource_fork(path):
    """Inspect the fork size without reading its private contents."""
    if sys.platform != "darwin":
        return False
    native = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    getxattr = native.getxattr
    getxattr.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    getxattr.restype = ctypes.c_ssize_t
    size = getxattr(os.fsencode(path), b"com.apple.ResourceFork", None, 0, 0, 1)
    if size < 0:
        # ENOATTR: this ordinary file has no resource fork.
        import errno

        if ctypes.get_errno() != errno.ENOATTR:
            raise VaultError("Cannot check file resource forks. Originals were not changed.")
        return False
    return size > 0


def scan_source(root, excluded=(), allow_empty=False):
    supplied = Path(root)
    if supplied.is_symlink():
        raise VaultError("Choose an ordinary folder, not a symlink.")
    root = supplied.resolve(strict=True)
    if not root.is_dir():
        raise VaultError("Choose a folder.")
    files, total = [], 0

    def walk_error(error):
        raise VaultError(f"Cannot read source folder: {error}")

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        if Path(directory) == root:
            dirs[:] = [name for name in dirs if name not in excluded]
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise VaultError("Symlink directories are unsupported. Originals were not changed.")
        for name in sorted(names):
            path = Path(directory) / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise VaultError("Only ordinary files are supported; symlinks are rejected.")
            if has_resource_fork(path):
                raise VaultError(
                    "Files with macOS resource forks are unsupported. Originals were not changed."
                )
            relative = safe_name(path.relative_to(root).as_posix())
            total += info.st_size
            if info.st_size > MAX_FILE or total > MAX_TOTAL or len(files) >= MAX_FILES:
                raise VaultError("Limit: 64 MiB per file, 2 GiB total, 2,000 files.")
            files.append((path, relative, info.st_size))
    if not files and not allow_empty:
        raise VaultError("The folder contains no files.")
    return root, sorted(files, key=lambda item: item[1])


def source_directories(root, excluded=()):
    directories = []
    for directory, dirs, _ in os.walk(root, followlinks=False):
        if Path(directory) == Path(root):
            dirs[:] = [name for name in dirs if name not in excluded]
        for name in dirs:
            path = Path(directory) / name
            if path.is_symlink():
                raise VaultError("Symlink directories are unsupported.")
            directories.append(safe_name(path.relative_to(root).as_posix()))
            if len(directories) > MAX_FILES:
                raise VaultError("Limit: 2,000 directories.")
    return sorted(directories)


def create_vault(
    source,
    destination,
    progress=lambda message: None,
    *,
    key=None,
    existing_id=None,
    excluded=(),
    allow_empty=False,
):
    root, files = scan_source(source, excluded, allow_empty)
    directories = source_directories(root, excluded)
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to(root):
        raise VaultError("Save the vault outside the source folder.")
    if destination.exists():
        raise VaultError("Choose a new vault filename; existing files are never overwritten.")
    key = secrets.token_bytes(32) if key is None else key
    if len(key) != 32:
        raise VaultError("Invalid vault key.")
    vault_id = str(uuid.uuid4()) if existing_id is None else str(uuid.UUID(existing_id))
    fd, temporary = tempfile.mkstemp(prefix=".face-lock-", dir=destination.parent)
    os.close(fd)
    manifest, total = [], 0
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(
                "header.json", json.dumps({"format": "face-lock", "version": 1, "id": vault_id})
            )
            for index, (path, relative, size) in enumerate(files):
                progress(f"Encrypting file {index + 1} of {len(files)}")
                # Recheck ancestors; this is a local prototype, not a hostile-filesystem sandbox.
                if path.resolve().is_relative_to(root) is False or path.is_symlink():
                    raise VaultError("Source changed during import.")
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise VaultError("Source changed during import.")
                    contents = stream.read(MAX_FILE + 1)
                    after = os.fstat(stream.fileno())
                if (
                    len(contents) != size
                    or len(contents) > MAX_FILE
                    or before.st_mtime_ns != after.st_mtime_ns
                ):
                    raise VaultError("A file changed during import. Try again when files are idle.")
                total += len(contents)
                if total > MAX_TOTAL:
                    raise VaultError("Source exceeds the vault size limit.")
                part = f"files/{index:06d}"
                archive.writestr(part, encrypt(key, contents, aad(vault_id, part)))
                manifest.append({"part": part, "name": relative, "size": len(contents)})
            metadata = json.dumps(
                {"files": manifest, "directories": directories}, ensure_ascii=False
            ).encode()
            if len(metadata) > MAX_MANIFEST:
                raise VaultError("Too much filename metadata.")
            archive.writestr("manifest.enc", encrypt(key, metadata, aad(vault_id, "manifest")))
        with open(temporary, "rb") as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return vault_id, key


class VaultSession:
    def __init__(self, path, key):
        self.path, self.key, self.files = Path(path), key, []
        try:
            self.archive = zipfile.ZipFile(self.path)
            self._validate()
        except Exception:
            self.close()
            raise

    def _validate(self):
        infos = self.archive.infolist()
        names = [item.filename for item in infos]
        if len(infos) > MAX_FILES + 2 or len(set(names)) != len(names):
            raise VaultError("Invalid archive entries.")
        if sum(item.file_size for item in infos) > MAX_TOTAL + MAX_MANIFEST + MAX_FILES * 28 + 4096:
            raise VaultError("Vault exceeds the size limit.")
        for item in infos:
            if item.compress_type != zipfile.ZIP_STORED or item.file_size > MAX_FILE + 28:
                raise VaultError("Unsupported or oversized archive entry.")
        header = self._read("header.json", 4096)
        try:
            self.header = json.loads(header)
            if self.header["format"] != "face-lock" or self.header["version"] != 1:
                raise VaultError("Unsupported vault format.")
            self.id = str(uuid.UUID(self.header["id"]))
            payload = decrypt(
                self.key, self._read("manifest.enc", MAX_MANIFEST + 28), aad(self.id, "manifest")
            )
            manifest = json.loads(payload)
            entries = manifest["files"]
            if not isinstance(entries, list) or not 0 <= len(entries) <= MAX_FILES:
                raise VaultError("Invalid file list.")
            seen = set()
            for i, entry in enumerate(entries):
                name = safe_name(entry["name"])
                if name in seen or entry["part"] != f"files/{i:06d}":
                    raise VaultError("Duplicate or invalid file entry.")
                seen.add(name)
                size = entry["size"]
                if type(size) is not int or not 0 <= size <= MAX_FILE:
                    raise VaultError("Invalid file size.")
                if self.archive.getinfo(entry["part"]).file_size != size + 28:
                    raise VaultError("Encrypted file size mismatch.")
            expected = {"header.json", "manifest.enc"} | {entry["part"] for entry in entries}
            if set(names) != expected or sum(entry["size"] for entry in entries) > MAX_TOTAL:
                raise VaultError("Unexpected vault contents.")
            directories = manifest.get("directories", [])
            if not isinstance(directories, list) or len(directories) > MAX_FILES:
                raise VaultError("Invalid directory list.")
            directories = [safe_name(name) for name in directories]
            if len(set(directories)) != len(directories) or set(directories) & seen:
                raise VaultError("Invalid directory names.")
            self.directories = directories
            self.has_directories = "directories" in manifest
            self.files = entries
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
            if isinstance(error, VaultError):
                raise
            raise VaultError("Invalid vault metadata.") from error

    def _read(self, name, limit):
        if self.archive.getinfo(name).file_size > limit:
            raise VaultError("Oversized vault metadata.")
        return self.archive.read(name)

    def export(self, index, destination):
        if self.key is None:
            raise VaultError("Vault is locked.")
        if Path(destination).resolve() == self.path.resolve():
            raise VaultError("Cannot export over the vault.")
        atomic_write(destination, self.read_file(index))

    def read_file(self, index):
        if self.key is None:
            raise VaultError("Vault is locked.")
        entry = self.files[index]
        data = decrypt(
            self.key, self._read(entry["part"], MAX_FILE + 28), aad(self.id, entry["part"])
        )
        if len(data) != entry["size"]:
            raise VaultError("File size mismatch.")
        return data

    def close(self):
        self.key, self.files = None, []
        if hasattr(self, "archive"):
            self.archive.close()


def vault_id(path):
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("header.json")
            if info.file_size > 4096 or info.compress_type != zipfile.ZIP_STORED:
                raise VaultError("Invalid vault header.")
            data = json.loads(archive.read(info))
            if data.get("format") != "face-lock" or data.get("version") != 1:
                raise VaultError("Unsupported vault format.")
            return str(uuid.UUID(data["id"]))
    except (KeyError, ValueError, zipfile.BadZipFile) as error:
        raise VaultError("Invalid Face Lock vault.") from error


def recovery_text(key):
    return "FL1-" + key.hex()


def parse_recovery(text):
    text = text.strip()
    if not text.startswith("FL1-") or len(text) != 68:
        raise VaultError("Recovery key should start FL1- followed by 64 hex characters.")
    try:
        key = bytes.fromhex(text[4:])
    except ValueError as error:
        raise VaultError("Invalid recovery key.") from error
    if len(key) != 32:
        raise VaultError("Invalid recovery key.")
    return key


def verify_source(source, session, progress=lambda message: None, *, excluded=()):
    """Verify all bytes and the complete file set before allowing source removal."""
    root, files = scan_source(source, excluded, allow_empty=not session.files)
    if session.has_directories and source_directories(root, excluded) != session.directories:
        raise VaultError("Folder directories changed. Nothing was removed.")
    entries = {entry["name"]: index for index, entry in enumerate(session.files)}
    if {relative for _, relative, _ in files} != set(entries):
        raise VaultError("Original folder does not exactly match the vault. Nothing was removed.")
    snapshots = []
    for number, (path, relative, size) in enumerate(files):
        progress(f"Verifying encrypted file {number + 1} of {len(files)}")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            contents = stream.read(MAX_FILE + 1)
            after = os.fstat(stream.fileno())
        if before.st_mtime_ns != after.st_mtime_ns or len(contents) != size:
            raise VaultError("Original files changed during verification. Nothing was removed.")
        recovered = session.read_file(entries[relative])
        if hashlib.sha256(contents).digest() != hashlib.sha256(recovered).digest():
            raise VaultError("Original file contents differ from the vault. Nothing was removed.")
        snapshots.append((relative, after.st_ino, after.st_size, after.st_mtime_ns))
    _, current = scan_source(root, excluded, allow_empty=not session.files)
    if [relative for _, relative, _ in current] != [relative for _, relative, _ in files]:
        raise VaultError("Original folder changed during verification. Nothing was removed.")
    for relative, inode, size, modified in snapshots:
        info = (root / relative).lstat()
        if (info.st_ino, info.st_size, info.st_mtime_ns) != (inode, size, modified):
            raise VaultError("Original files changed during verification. Nothing was removed.")
    return len(files)


def replace_source(source, vault, key, progress=lambda message: None):
    """Called only after explicit user confirmation. Vault remains outside source."""
    source = Path(source)
    if source.is_symlink():
        raise VaultError("Cannot replace a symlink folder.")
    source = source.resolve(strict=True)
    if Path(vault).resolve().is_relative_to(source):
        raise VaultError("The vault must be outside the original folder.")
    session = VaultSession(vault, key)
    staged = source.parent / (".face-lock-removing-" + uuid.uuid4().hex)
    try:
        count = verify_source(source, session, progress)
        # Rename into the same parent before a second verification. Any changed
        # or additional file aborts; restore the original path when possible.
        os.rename(source, staged)
        try:
            verify_source(staged, session, progress)
            progress("Removing verified plaintext originals…")
            shutil.rmtree(staged)
        except Exception as error:
            if staged.exists() and not source.exists():
                os.rename(staged, source)
            raise VaultError(
                "Could not finish removing originals. The verified vault is intact; check the original folder for remaining files."
            ) from error
        return count
    finally:
        session.close()
