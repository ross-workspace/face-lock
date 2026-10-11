"""Build and check a portable application on its target operating system."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def build_target(system, machine):
    if system == "Windows" and machine.lower() in {"amd64", "x86_64"}:
        return "windows-x64", Path("Face Lock") / "FaceLock.exe"
    if system == "Darwin" and machine.lower() == "arm64":
        return "macos-arm64", Path("Face Lock.app") / "Contents" / "MacOS" / "Face Lock"
    raise RuntimeError(
        "Build on Windows x64 or macOS Apple silicon with Python 3.12. Cross-compilation is not supported."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    target, executable = build_target(platform.system(), platform.machine())
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use Python 3.12 for the supported build environment.")
    destination = args.dist_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "work" / "pyinstaller"))
    env.setdefault("MPLCONFIGDIR", str(ROOT / "work" / "mpl"))

    def run(command, extra_env=None):
        subprocess.run(command, cwd=ROOT, env=env | (extra_env or {}), check=True)

    run([sys.executable, str(ROOT / "scripts" / "download_models.py")])
    run([sys.executable, str(ROOT / "main.py"), "--check-models"])
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--distpath",
            str(destination),
            str(ROOT / "FaceLock.spec"),
        ]
    )
    run([str(destination / executable), "--check-models"])
    screenshot = ROOT / "work" / f"packaged-{target}.png"
    screenshot.unlink(missing_ok=True)
    run(
        [str(destination / executable), "--smoke-test", "--screenshot", str(screenshot)],
        {"QT_QPA_PLATFORM": "offscreen"},
    )
    if not screenshot.is_file():
        raise RuntimeError("Packaged UI smoke test did not produce a screenshot.")
    archive = destination / f"FaceLock-{target}.zip"
    if target.startswith("macos"):
        run(
            [
                "ditto",
                "-c",
                "-k",
                "--keepParent",
                "--norsrc",
                "--noextattr",
                str(destination / "Face Lock.app"),
                str(archive),
            ]
        )
    else:
        shutil.make_archive(
            str(archive.with_suffix("")), "zip", root_dir=destination, base_dir="Face Lock"
        )
    if archive.stat().st_size > 10 * 1024**3:
        archive.unlink()
        raise RuntimeError("Build archive exceeded the 10 GiB artifact limit.")
    print(f"Portable application: {archive}")


if __name__ == "__main__":
    main()
