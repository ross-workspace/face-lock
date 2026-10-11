"""Mock native enumeration behavior; these tests do not run the Windows API."""

import ctypes
from types import SimpleNamespace

import pytest

from facelock import windows_files as wf
from facelock.vault import VaultError


class FixtureStreamAPI:
    def __init__(self, streams=(), first_error=38, next_error=38, close_success=True):
        self.streams = list(streams)
        self.error = first_error
        self.next_error = next_error
        self.close_success = close_success
        self.closed = []
        self.calls = []

    def fill(self, output):
        entry = ctypes.cast(output, ctypes.POINTER(wf.StreamData)).contents
        entry.cStreamName = self.streams.pop(0)
        entry.StreamSize = 0

    def first(self, path, level, output, flags):
        self.calls.append((level, flags))
        if not self.streams:
            return wf.INVALID_HANDLE_VALUE
        self.fill(output)
        return 123

    def next(self, handle, output):
        if not self.streams:
            self.error = self.next_error
            return False
        self.fill(output)
        return True

    def last_error(self):
        return self.error

    def close(self, handle):
        self.closed.append(handle)
        return self.close_success


@pytest.mark.parametrize(
    "streams, expected",
    [
        (["::$DATA"], False),
        (["::$DATA", ":private:$DATA"], True),
        ([":directory-extra:$DATA"], True),
    ],
)
def test_only_default_data_stream_is_supported(tmp_path, streams, expected):
    api = FixtureStreamAPI(streams)
    assert wf.has_alternate_streams(tmp_path / "fixture.txt", api) is expected
    assert api.calls == [(0, 0)]
    assert api.closed == [123]


@pytest.mark.parametrize("error", [38, 87])
def test_no_streams_or_unsupported_filesystem_is_ordinary(tmp_path, error):
    api = FixtureStreamAPI(first_error=error)
    assert not wf.has_alternate_streams(tmp_path / "fixture.txt", api)
    assert api.closed == []


def test_access_denied_fails_closed(tmp_path):
    api = FixtureStreamAPI(first_error=5)
    with pytest.raises(VaultError, match="Cannot check Windows file streams"):
        wf.has_alternate_streams(tmp_path / "fixture.txt", api)
    assert api.closed == []


def test_next_error_still_closes_handle(tmp_path):
    api = FixtureStreamAPI(["::$DATA"], next_error=5)
    with pytest.raises(VaultError, match="Cannot finish checking"):
        wf.has_alternate_streams(tmp_path / "fixture.txt", api)
    assert api.closed == [123]


def test_close_error_fails_closed(tmp_path):
    api = FixtureStreamAPI(["::$DATA"], close_success=False)
    with pytest.raises(VaultError, match="Cannot close"):
        wf.has_alternate_streams(tmp_path / "fixture.txt", api)


def test_other_platform_never_loads_windows_library(tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(wf, "StreamAPI", lambda: pytest.fail("unexpected native library load"))
    assert not wf.has_alternate_streams(tmp_path / "fixture.txt")
