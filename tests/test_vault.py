import hashlib
import json
import os
import zipfile

import pytest

from facelock.vault import (
    VaultError,
    VaultSession,
    aad,
    create_vault,
    encrypt,
    parse_recovery,
    recovery_text,
    safe_name,
    vault_id,
)


@pytest.fixture
def example(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested" / "Příliš žluťoučký.txt").write_text(
        "Private sample text 🦊", encoding="utf-8"
    )
    (root / "binary.bin").write_bytes(os.urandom(8192))
    (root / "empty").write_bytes(b"")
    destination = tmp_path / "demo.facevault"
    identifier, key = create_vault(root, destination)
    return root, destination, identifier, key


def rewrite(path, transform):
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    transform(entries)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def test_round_trip_recovery_and_lock(example, tmp_path):
    root, path, identifier, key = example
    assert vault_id(path) == identifier
    assert parse_recovery(recovery_text(key)) == key
    session = VaultSession(path, parse_recovery(recovery_text(key)))
    for index, entry in enumerate(session.files):
        output = tmp_path / f"export-{index}"
        session.export(index, output)
        assert (
            hashlib.sha256(output.read_bytes()).digest()
            == hashlib.sha256((root / entry["name"]).read_bytes()).digest()
        )
        if os.name != "nt":
            assert output.stat().st_mode & 0o777 == 0o600
    session.close()
    with pytest.raises(VaultError, match="locked"):
        session.export(0, tmp_path / "after-lock")


def test_names_and_contents_not_plaintext(example):
    root, path, _, key = example
    data = path.read_bytes()
    assert "Příliš žluťoučký".encode() not in data
    assert b"Private sample text" not in data
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "header.json",
            "manifest.enc",
            "files/000000",
            "files/000001",
            "files/000002",
        }


def test_wrong_key_and_manifest_tamper(example):
    _, path, _, key = example
    with pytest.raises(VaultError):
        VaultSession(path, os.urandom(32))

    def corrupt(entries):
        payload = bytearray(entries["manifest.enc"])
        payload[-1] ^= 1
        entries["manifest.enc"] = bytes(payload)

    rewrite(path, corrupt)
    with pytest.raises(VaultError):
        VaultSession(path, key)


def test_file_tamper_exports_nothing(example, tmp_path):
    _, path, _, key = example

    def corrupt(entries):
        payload = bytearray(entries["files/000000"])
        payload[-1] ^= 1
        entries["files/000000"] = bytes(payload)

    rewrite(path, corrupt)
    session = VaultSession(path, key)
    output = tmp_path / "tampered-export"
    with pytest.raises(VaultError):
        session.export(0, output)
    assert not output.exists()
    session.close()


def test_does_not_overwrite_or_change_originals(example, tmp_path):
    root, path, _, key = example
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(VaultError):
        create_vault(root, path)
    session = VaultSession(path, key)
    output = tmp_path / "existing"
    output.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        session.export(0, output)
    assert output.read_bytes() == b"keep me"
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    session.close()


@pytest.mark.parametrize(
    "name", ["../bad", "/absolute", "a/../b", "a\\b", "a//b", "a/./b", "x:y", "a\x00b"]
)
def test_reject_unsafe_name(name):
    with pytest.raises(VaultError):
        safe_name(name)


def test_reject_authenticated_traversal_manifest(example):
    _, path, identifier, key = example

    def malicious(entries):
        manifest = {"files": [{"part": "files/000000", "name": "../escape", "size": 8192}]}
        entries["manifest.enc"] = encrypt(
            key, json.dumps(manifest).encode(), aad(identifier, "manifest")
        )

    rewrite(path, malicious)
    with pytest.raises(VaultError, match="Unsafe"):
        VaultSession(path, key)


def test_inside_source_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_bytes(b"a")
    with pytest.raises(VaultError, match="outside"):
        create_vault(source, source / "inside.facevault")
    assert not (source / "inside.facevault").exists()


def test_symlink_source_rejected(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_bytes(b"a")
    try:
        (source / "link").symlink_to(source / "a")
    except OSError as error:
        if os.name == "nt" and error.winerror == 1314:
            pytest.skip("Windows symlink privilege or Developer Mode is unavailable")
        raise
    with pytest.raises(VaultError, match="symlink"):
        create_vault(source, tmp_path / "bad.facevault")
    assert not (tmp_path / "bad.facevault").exists()


def test_failed_import_is_atomic(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a").write_bytes(b"a")
    import facelock.vault as module

    def fail(*args):
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(module, "encrypt", fail)
    with pytest.raises(RuntimeError):
        create_vault(source, tmp_path / "failed.facevault")
    assert not (tmp_path / "failed.facevault").exists()
    assert not list(tmp_path.glob(".face-lock-*"))
    assert (source / "a").read_bytes() == b"a"


def test_limit_and_compressed_entry_rejected(example, tmp_path, monkeypatch):
    import facelock.vault as module

    _, path, _, key = example
    monkeypatch.setattr(module, "MAX_FILES", 1)
    with pytest.raises(VaultError):
        VaultSession(path, key)
    compressed = tmp_path / "bomb.facevault"
    with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("header.json", "x" * 10000)
    with pytest.raises(VaultError):
        VaultSession(compressed, key)


def test_header_swap_is_authenticated(example):
    _, path, _, key = example

    def change(entries):
        import uuid

        header = json.loads(entries["header.json"])
        header["id"] = str(uuid.uuid4())
        entries["header.json"] = json.dumps(header).encode()

    rewrite(path, change)
    with pytest.raises(VaultError):
        VaultSession(path, key)


@pytest.mark.parametrize("text", ["", "FL1-x", "FL1-" + "z" * 64, "FL1-" + " " * 64])
def test_bad_recovery(text):
    with pytest.raises(VaultError):
        parse_recovery(text)
