"""Secrets use native Keychain APIs, never command arguments or plaintext config."""

import json
from pathlib import Path
import secrets
import sys

import numpy as np
from .vault import VaultError, atomic_write, encrypt, decrypt

SERVICE = "local.face-lock.prototype"


def data_dir():
    path = Path.home() / "Library" / "Application Support" / "Face Lock"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


class Keychain:
    def __init__(self):
        import Security

        self.api = Security

    def query(self, account):
        s = self.api
        return {
            s.kSecClass: s.kSecClassGenericPassword,
            s.kSecAttrService: SERVICE,
            s.kSecAttrAccount: account,
        }

    def get(self, account):
        s = self.api
        query = self.query(account)
        query.update({s.kSecReturnData: True, s.kSecMatchLimit: s.kSecMatchLimitOne})
        status, result = s.SecItemCopyMatching(query, None)
        if status == s.errSecItemNotFound:
            return None
        if status != 0:
            raise VaultError(f"Keychain access failed ({status}). Use recovery if needed.")
        return bytes(result)

    def put(self, account, value):
        s = self.api
        query = self.query(account)
        status = s.SecItemUpdate(query, {s.kSecValueData: value})
        if status == s.errSecItemNotFound:
            query[s.kSecValueData] = value
            status, _ = s.SecItemAdd(query, None)
        if status != 0:
            raise VaultError(f"Could not save secret in Keychain ({status}).")

    def delete(self, account):
        status = self.api.SecItemDelete(self.query(account))
        if status not in (0, self.api.errSecItemNotFound):
            raise VaultError(f"Could not remove Keychain item ({status}).")


class ProfileStore:
    def __init__(self, directory=None, keychain=None):
        self.root = Path(directory) if directory else data_dir()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "profile.enc"
        self.keychain = keychain or Keychain()

    def load(self):
        if not self.path.exists():
            return None
        key = self.keychain.get("face-profile")
        if key is None:
            raise VaultError("Profile key is missing. Re-enroll your face.")
        if self.path.stat().st_size > 128000:
            raise VaultError("Invalid profile size.")
        try:
            data = json.loads(decrypt(key, self.path.read_bytes(), b"face-lock:profile:v1"))
            vector = np.asarray(data["embedding"], dtype=np.float32)
            if vector.shape != (128,) or not np.all(np.isfinite(vector)):
                raise VaultError("Invalid face profile.")
            norm = np.linalg.norm(vector)
            if norm < 0.1:
                raise VaultError("Invalid face profile.")
            return vector / norm
        except (ValueError, KeyError, TypeError) as error:
            raise VaultError("Cannot read face profile. Re-enroll your face.") from error

    def save(self, embedding):
        key = self.keychain.get("face-profile")
        if key is None:
            key = secrets.token_bytes(32)
            self.keychain.put("face-profile", key)
        payload = json.dumps(
            {"version": 1, "model": "sface-2021dec", "embedding": embedding.tolist()}
        ).encode()
        atomic_write(self.path, encrypt(key, payload, b"face-lock:profile:v1"), replace=True)

    def load_sequence(self):
        path = self.root / "gestures.enc"
        if not path.exists():
            return []
        key = self.keychain.get("face-profile")
        if key is None or path.stat().st_size > 500000:
            raise VaultError("Gesture profile is missing its key or invalid.")
        data = json.loads(decrypt(key, path.read_bytes(), b"face-lock:gestures:v1"))
        from .gestures import validate_step

        if not isinstance(data, list) or not 1 <= len(data) <= 12:
            raise VaultError("Invalid gesture sequence.")
        for step in data:
            validate_step(step)
        return data

    def save_sequence(self, steps):
        from .gestures import validate_step

        if not 1 <= len(steps) <= 12:
            raise VaultError("Record between 1 and 12 locks.")
        for step in steps:
            validate_step(step)
        key = self.keychain.get("face-profile")
        if key is None:
            key = secrets.token_bytes(32)
            self.keychain.put("face-profile", key)
        atomic_write(
            self.root / "gestures.enc",
            encrypt(key, json.dumps(steps).encode(), b"face-lock:gestures:v1"),
            replace=True,
        )


def model_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "models"
