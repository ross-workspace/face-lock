"""Exercise real Windows APIs on the native CI runner using disposable data."""

from pathlib import Path
import secrets
import sys

import pytest

from facelock import folder_vault, vault
from facelock.windows_files import has_alternate_streams
from facelock.windows_secrets import ProtectedKeyStore

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows")


def test_native_dpapi_persistence_and_tamper(tmp_path):
    secret = secrets.token_bytes(32)
    store = ProtectedKeyStore(tmp_path / "keys")
    store.put("synthetic-test", secret)
    path, _ = store._location("synthetic-test")
    assert secret not in path.read_bytes()
    assert ProtectedKeyStore(store.root).get("synthetic-test") == secret
    blob = bytearray(path.read_bytes())
    blob[-1] ^= 1
    path.write_bytes(blob)
    with pytest.raises(vault.VaultError):
        store.get("synthetic-test")
    store.delete("synthetic-test")
    assert store.get("synthetic-test") is None


def test_native_alternate_stream_preserved_on_rejection(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    path = root / "example.bin"
    path.write_bytes(b"ordinary synthetic content")
    stream = Path(str(path) + ":test-stream")
    stream.write_bytes(b"synthetic extra stream")
    assert has_alternate_streams(path)
    with pytest.raises(vault.VaultError, match="alternate data streams"):
        folder_vault.prepare(root)
    assert path.read_bytes() == b"ordinary synthetic content"
    assert stream.read_bytes() == b"synthetic extra stream"


def test_native_binary_roundtrip_and_no_overwrite(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    content = bytes(range(256)) + b"\r\n\x1a\n"
    (root / "binary.bin").write_bytes(content)
    prepared = folder_vault.prepare(root)
    folder_vault.commit(prepared)
    folder_vault.unlock(root, prepared["key"])
    assert (root / "binary.bin").read_bytes() == content
    destination = tmp_path / "existing.bin"
    destination.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        vault.atomic_write(destination, b"replacement")
    assert destination.read_bytes() == b"original"
