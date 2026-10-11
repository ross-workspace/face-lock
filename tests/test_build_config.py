from pathlib import Path
import runpy

import pytest

build_target = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "build.py"))[
    "build_target"
]


def test_native_windows_executable_layout():
    target, executable = build_target("Windows", "AMD64")
    assert target == "windows-x64"
    assert executable.parts == ("Face Lock", "FaceLock.exe")


def test_native_macos_bundle_layout():
    target, executable = build_target("Darwin", "arm64")
    assert target == "macos-arm64"
    assert executable.parts == ("Face Lock.app", "Contents", "MacOS", "Face Lock")


@pytest.mark.parametrize(
    "system,machine", [("Darwin", "x86_64"), ("Windows", "ARM64"), ("Linux", "x86_64")]
)
def test_build_rejects_unsupported_host(system, machine):
    with pytest.raises(RuntimeError, match="Cross-compilation"):
        build_target(system, machine)
