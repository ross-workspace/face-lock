import pytest
from facelock.vault import VaultError, VaultSession, create_vault, replace_source


def make(tmp_path):
    source = tmp_path / "original"
    source.mkdir()
    (source / "a.txt").write_text("never lose this")
    destination = tmp_path / "vault.facevault"
    _, key = create_vault(source, destination)
    return source, destination, key


def test_verified_replacement_retains_complete_vault(tmp_path):
    source, vault, key = make(tmp_path)
    assert replace_source(source, vault, key) == 1
    assert not source.exists()
    session = VaultSession(vault, key)
    session.export(0, tmp_path / "recovered.txt")
    assert (tmp_path / "recovered.txt").read_text() == "never lose this"
    session.close()


@pytest.mark.parametrize("change", ["modify", "add", "delete"])
def test_changed_originals_never_removed(tmp_path, change):
    source, vault, key = make(tmp_path)
    if change == "modify":
        (source / "a.txt").write_text("changed since import")
    elif change == "add":
        (source / "extra").write_text("new")
    else:
        (source / "a.txt").unlink()
        (source / "new.txt").write_text("another file")
    with pytest.raises(VaultError):
        replace_source(source, vault, key)
    assert source.exists() and vault.exists()


def test_second_verification_failure_restores_original_path(tmp_path, monkeypatch):
    import facelock.vault as module

    source, vault, key = make(tmp_path)
    original = module.verify_source
    calls = []

    def verify(path, session, progress):
        calls.append(path)
        if len(calls) == 2:
            raise VaultError("simulated late source change")
        return original(path, session, progress)

    monkeypatch.setattr(module, "verify_source", verify)
    with pytest.raises(VaultError):
        replace_source(source, vault, key)
    assert source.exists()
    assert (source / "a.txt").read_text() == "never lose this"
    assert not list(tmp_path.glob(".face-lock-removing-*"))


def test_tampered_vault_never_deletes_originals(tmp_path):
    import zipfile

    source, vault, key = make(tmp_path)
    with zipfile.ZipFile(vault) as z:
        data = {name: z.read(name) for name in z.namelist()}
    data["files/000000"] = data["files/000000"][:-1] + bytes([data["files/000000"][-1] ^ 1])
    with zipfile.ZipFile(vault, "w") as z:
        for name, content in data.items():
            z.writestr(name, content)
    with pytest.raises(VaultError):
        replace_source(source, vault, key)
    assert (source / "a.txt").read_text() == "never lose this"
