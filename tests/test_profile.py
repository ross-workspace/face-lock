import numpy as np
import pytest
from facelock.storage import ProfileStore
from facelock.vault import VaultError


class MemoryKeychain:
    def __init__(self):
        self.secrets = {}

    def get(self, name):
        return self.secrets.get(name)

    def put(self, name, value):
        self.secrets[name] = value


def test_encrypted_profile_restart_and_tamper(tmp_path):
    keychain = MemoryKeychain()
    store = ProfileStore(tmp_path, keychain)
    vector = np.random.default_rng(7).normal(size=128).astype(np.float32)
    vector /= np.linalg.norm(vector)
    store.save(vector)
    restarted = ProfileStore(tmp_path, keychain)
    np.testing.assert_allclose(restarted.load(), vector, atol=1e-6)
    assert b"embedding" not in store.path.read_bytes()
    contents = bytearray(store.path.read_bytes())
    contents[-1] ^= 1
    store.path.write_bytes(contents)
    with pytest.raises(VaultError):
        restarted.load()
