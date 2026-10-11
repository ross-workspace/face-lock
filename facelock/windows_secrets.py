"""Windows user-scoped DPAPI and persistent protected key blobs."""

import ctypes
import hashlib
from pathlib import Path
import sys

from .vault import VaultError, atomic_write, is_linked

MAX_KEY = 4096
MAX_BLOB = 65536
MAGIC = b"FLDP1"
CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DataBlob(ctypes.Structure):
    # DWORD remains 32 bits on both 32-bit and 64-bit Windows.
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class DPAPIProtector:
    def __init__(self):
        if sys.platform != "win32":
            raise VaultError("Windows DPAPI is unavailable on this platform.")
        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        blob_pointer = ctypes.POINTER(DataBlob)
        self.protect_data = crypt32.CryptProtectData
        self.protect_data.argtypes = [
            blob_pointer,
            ctypes.c_wchar_p,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self.protect_data.restype = ctypes.c_int
        self.unprotect_data = crypt32.CryptUnprotectData
        self.unprotect_data.argtypes = [
            blob_pointer,
            ctypes.POINTER(ctypes.c_wchar_p),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self.unprotect_data.restype = ctypes.c_int
        self.local_free = kernel32.LocalFree
        self.local_free.argtypes = [ctypes.c_void_p]
        self.local_free.restype = ctypes.c_void_p

    def _transform(self, data, entropy, decrypting):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BLOB:
            raise VaultError("Invalid Windows protected data size.")
        source_buffer = ctypes.create_string_buffer(data)
        entropy_buffer = ctypes.create_string_buffer(entropy)
        source = DataBlob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        context = DataBlob(
            len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte))
        )
        destination = DataBlob()
        function = self.unprotect_data if decrypting else self.protect_data
        try:
            # No machine-wide flag: only the current Windows user can normally unprotect.
            success = function(
                ctypes.byref(source),
                None,
                ctypes.byref(context),
                None,
                None,
                CRYPTPROTECT_UI_FORBIDDEN,
                ctypes.byref(destination),
            )
            if not success:
                code = ctypes.get_last_error()
                raise VaultError(
                    f"Windows secret protection failed ({code}). Use recovery if needed."
                )
            if not destination.pbData or not 0 < destination.cbData <= MAX_BLOB:
                raise VaultError("Windows secret protection returned invalid data.")
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            ctypes.memset(source_buffer, 0, ctypes.sizeof(source_buffer))
            if destination.pbData:
                if decrypting and destination.cbData <= MAX_BLOB:
                    ctypes.memset(destination.pbData, 0, destination.cbData)
                self.local_free(ctypes.cast(destination.pbData, ctypes.c_void_p))

    def protect(self, value, entropy):
        return self._transform(value, entropy, False)

    def unprotect(self, value, entropy):
        return self._transform(value, entropy, True)


class ProtectedKeyStore:
    """Only DPAPI-protected bytes are persisted; injected protectors are for tests."""

    def __init__(self, directory, protector=None):
        self.root = Path(directory)
        if is_linked(self.root):
            raise VaultError("Windows key storage must not be symlinked.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.protector = protector if protector is not None else DPAPIProtector()

    def _location(self, account):
        if not isinstance(account, str) or not 0 < len(account) <= 512:
            raise VaultError("Invalid secret account.")
        context = hashlib.sha256(("local.face-lock.prototype:" + account).encode()).digest()
        path = self.root / (context.hex() + ".dpapi")
        if is_linked(path):
            raise VaultError("Windows protected key must not be symlinked.")
        return path, context

    def get(self, account):
        path, context = self._location(account)
        if not path.exists():
            return None
        with path.open("rb") as stream:
            blob = stream.read(MAX_BLOB + len(MAGIC) + 1)
        if not blob.startswith(MAGIC) or not len(MAGIC) < len(blob) <= MAX_BLOB + len(MAGIC):
            raise VaultError("Invalid Windows protected key. Use recovery if needed.")
        value = self.protector.unprotect(blob[len(MAGIC) :], context)
        if not isinstance(value, bytes) or not 0 < len(value) <= MAX_KEY:
            raise VaultError("Invalid recovered Windows key.")
        return value

    def put(self, account, value):
        path, context = self._location(account)
        if not isinstance(value, bytes) or not 0 < len(value) <= MAX_KEY:
            raise VaultError("Invalid secret value.")
        protected = self.protector.protect(value, context)
        if not isinstance(protected, bytes) or not 0 < len(protected) <= MAX_BLOB:
            raise VaultError("Invalid Windows protected key.")
        atomic_write(path, MAGIC + protected, replace=True)

    def delete(self, account):
        path, _ = self._location(account)
        path.unlink(missing_ok=True)
