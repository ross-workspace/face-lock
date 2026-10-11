"""Platform routing and persistence tests; fixture protection is not Windows DPAPI."""

import ctypes
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from facelock import storage
from facelock.vault import VaultError
from facelock.windows_secrets import DataBlob, DPAPIProtector, ProtectedKeyStore


class FixtureProtector:
    """Authenticated test fixture only, never used by production platform routing."""

    def __init__(self):
        self.cipher = AESGCM(b"\x19" * 32)
        self.counter = 0

    def protect(self, data, entropy):
        self.counter += 1
        nonce = self.counter.to_bytes(12, "big")
        return nonce + self.cipher.encrypt(nonce, data, entropy)

    def unprotect(self, data, entropy):
        try:
            return self.cipher.decrypt(data[:12], data[12:], entropy)
        except (InvalidTag, ValueError) as error:
            raise VaultError("Fixture rejected damaged or swapped protected data") from error


def platform(monkeypatch, name):
    monkeypatch.setattr(storage, "sys", SimpleNamespace(platform=name))


def test_platform_data_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    platform(monkeypatch, "darwin")
    assert storage.data_dir() == tmp_path / "Library/Application Support/Face Lock"
    platform(monkeypatch, "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local user data"))
    assert storage.data_dir() == tmp_path / "Local user data/Face Lock"
    monkeypatch.delenv("LOCALAPPDATA")
    assert storage.data_dir() == tmp_path / "AppData/Local/Face Lock"


def test_unsupported_platform_has_no_plaintext_fallback(monkeypatch):
    platform(monkeypatch, "linux")
    with pytest.raises(VaultError, match="macOS and Windows"):
        storage.data_dir()
    with pytest.raises(VaultError, match="unavailable"):
        storage.Keychain()


def test_mac_facade_routes_without_accessing_native_keychain(monkeypatch):
    calls = []

    class FixtureMacKeychain:
        def get(self, account):
            calls.append(("get", account))
            return b"fixture"

        def put(self, account, value):
            calls.append(("put", account, value))

        def delete(self, account):
            calls.append(("delete", account))

    platform(monkeypatch, "darwin")
    monkeypatch.setattr(storage, "MacKeychain", FixtureMacKeychain)
    store = storage.Keychain()
    assert store.get("account") == b"fixture"
    store.put("account", b"value")
    store.delete("account")
    assert calls == [("get", "account"), ("put", "account", b"value"), ("delete", "account")]


def test_windows_facade_persists_only_protected_blobs(tmp_path, monkeypatch):
    platform(monkeypatch, "win32")
    protector = FixtureProtector()
    root = tmp_path / "keys"
    store = storage.Keychain(directory=root, protector=protector)
    secret = b"synthetic vault key fixture only"
    assert store.get("vault:example") is None
    store.put("vault:example", secret)
    files = list(root.iterdir())
    assert len(files) == 1 and files[0].suffix == ".dpapi"
    assert secret not in files[0].read_bytes()
    assert "vault:example" not in files[0].name
    restarted = storage.Keychain(directory=root, protector=protector)
    assert restarted.get("vault:example") == secret
    restarted.put("vault:example", b"replacement fixture")
    assert store.get("vault:example") == b"replacement fixture"
    restarted.delete("vault:example")
    assert store.get("vault:example") is None
    restarted.delete("vault:example")


def test_protected_key_tamper_and_account_swap_fail(tmp_path):
    store = ProtectedKeyStore(tmp_path, protector=FixtureProtector())
    store.put("first", b"first fixture secret")
    store.put("second", b"second fixture secret")
    first, _ = store._location("first")
    second, _ = store._location("second")
    second.write_bytes(first.read_bytes())
    with pytest.raises(VaultError, match="swapped"):
        store.get("second")
    altered = bytearray(first.read_bytes())
    altered[-1] ^= 1
    first.write_bytes(altered)
    with pytest.raises(VaultError, match="damaged"):
        store.get("first")


def test_protection_failure_never_overwrites_existing_key(tmp_path):
    store = ProtectedKeyStore(tmp_path, protector=FixtureProtector())
    store.put("existing", b"original fixture")
    path, _ = store._location("existing")
    protected = path.read_bytes()

    class FailingProtector:
        def protect(self, data, entropy):
            raise VaultError("synthetic platform failure")

    store.protector = FailingProtector()
    with pytest.raises(VaultError, match="platform failure"):
        store.put("existing", b"new fixture")
    assert path.read_bytes() == protected


def test_oversized_or_malformed_protected_key_rejected(tmp_path):
    store = ProtectedKeyStore(tmp_path, protector=FixtureProtector())
    store.put("key", b"fixture")
    path, _ = store._location("key")
    for malformed in (b"plaintext fixture", b"FLDP1", b"FLDP1" + b"x" * 65537):
        path.write_bytes(malformed)
        with pytest.raises(VaultError, match="Invalid Windows protected key"):
            store.get("key")


def test_dpapi_adapter_flags_output_free_and_plaintext_buffer_clear():
    # Exercise pointer plumbing with a fake native function, not the Windows API.
    adapter = DPAPIProtector.__new__(DPAPIProtector)
    allocation = ctypes.create_string_buffer(b"synthetic decrypted key")
    observed = []

    def fake_unprotect(source, description, entropy, reserved, prompt, flags, output):
        observed.append((description, reserved, prompt, flags))
        output_blob = ctypes.cast(output, ctypes.POINTER(DataBlob)).contents
        output_blob.cbData = len(b"synthetic decrypted key")
        output_blob.pbData = ctypes.cast(allocation, ctypes.POINTER(ctypes.c_ubyte))
        return 1

    adapter.unprotect_data = fake_unprotect
    adapter.protect_data = None
    freed = []
    adapter.local_free = lambda pointer: freed.append(pointer.value)
    assert adapter.unprotect(b"protected fixture", b"context") == b"synthetic decrypted key"
    assert observed == [(None, None, None, 1)]
    assert freed == [ctypes.addressof(allocation)]
    assert allocation.raw[: len(b"synthetic decrypted key")] == b"\0" * len(
        b"synthetic decrypted key"
    )


def test_dpapi_native_error_reports_code_and_releases_output(monkeypatch):
    adapter = DPAPIProtector.__new__(DPAPIProtector)
    allocation = ctypes.create_string_buffer(b"partial protected fixture")

    def fail_protection(source, description, entropy, reserved, prompt, flags, output):
        output_blob = ctypes.cast(output, ctypes.POINTER(DataBlob)).contents
        output_blob.cbData = len(allocation)
        output_blob.pbData = ctypes.cast(allocation, ctypes.POINTER(ctypes.c_ubyte))
        return 0

    adapter.protect_data = fail_protection
    adapter.unprotect_data = None
    freed = []
    adapter.local_free = lambda pointer: freed.append(pointer.value)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    with pytest.raises(VaultError, match=r"protection failed \(5\)"):
        adapter.protect(b"synthetic input key", b"context")
    assert freed == [ctypes.addressof(allocation)]
