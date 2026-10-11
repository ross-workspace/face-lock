# Face Lock

A local desktop experiment for macOS and Windows: unlock an encrypted folder with your face and a sequence of hand or body poses you record yourself.

The folder stays at its original path. Locking replaces its readable contents with an encrypted archive inside that folder; unlocking restores the files there. There is no mounted volume, and the result is more than a folder fingerprint: file contents and filenames are encrypted.

**This is a playful prototype, not a trusted biometric security boundary.** The camera checks run in software and the app can retrieve its key from macOS Keychain or Windows user-scoped DPAPI storage. Someone controlling the logged-in computer or modifying the app may bypass those checks. See [Security](SECURITY.md) before using it with valuable data.

![Face Lock folder workspace](docs/images/vault.png)

*The actual folder workspace, shown with dummy data.*

## What it does

- Enrolls a face locally using OpenCV SFace, with MediaPipe landmarks drawn over the camera preview.
- Records 1–12 named hand/body poses and checks them in your chosen order.
- Shows a lock opening for each completed step while requiring the enrolled face to remain visible.
- Encrypts file contents and the filename/directory manifest with AES-256-GCM.
- Verifies the encrypted result before replacing readable originals.
- Restores normal files for Finder/File Explorer and editors, then includes changes when you lock again.
- Provides a recovery key when the camera or face recognition is unavailable.

Camera frames are processed in memory. Application code does not save camera video or upload frames. Face and gesture templates are encrypted locally; setup downloads dependencies and model assets. MediaPipe's upstream [privacy notice](https://pypi.org/project/mediapipe/1.1.0/) states that input processing stays on device while its Tasks APIs send performance and utilization metrics to Google. Do not interpret local image processing as a guarantee of zero dependency telemetry.

## Setup

The build targets are **macOS on Apple silicon** and **Windows 10/11 x64**, using Python 3.12 for development. A webcam and camera permission are needed for enrollment and normal unlocking. Windows packaging is configured but still requires a successful native Windows build and live-camera testing; no Windows binary is supplied in this source checkout. Other architectures and Python versions are not supported.

### Packaged applications

When a successful Windows build artifact is available, download `FaceLock-windows-x64.zip`, extract the **whole ZIP**, and run `Face Lock/FaceLock.exe`. Keep the executable beside its `_internal` directory; it contains required libraries and models. A packaged build does not need Python installed. This is a portable application folder rather than a single self-contained executable.

For macOS, extract `FaceLock-macos-arm64.zip` and open `Face Lock.app`. Builds are not notarized or Developer ID signed. Windows builds are not Authenticode signed; downloaded unsigned applications may trigger operating-system trust prompts.

### Run from source

On macOS, from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/download_models.py
python main.py --check-models
python main.py
```

On Windows, use PowerShell from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/download_models.py
.\.venv\Scripts\python.exe main.py --check-models
.\.venv\Scripts\python.exe main.py
```

The downloader retrieves five model assets from their recorded upstream URLs and checks the SHA-256 digests in `models/models.json`. Keep that manifest in the checkout; it pins the assets used by the application. Models are downloaded locally rather than committed as binaries.

On macOS, you can also run `Launch.command` after creating `.venv` and downloading the models. Allow camera access when macOS prompts. If access was previously denied, check **System Settings → Privacy & Security → Camera** for the app or launcher you use. On Windows, check **Settings → Privacy & security → Camera** and allow desktop apps to access your camera.

## Protect and open a folder

Try this with a small folder of disposable files first, and keep an independent backup.

1. Open **Set up my face**. Keep your face visible and follow the enrollment prompts.
2. Select **Encrypt a folder** and choose a specific data folder. Avoid application bundles, system folders, or a whole home directory.
3. Save the displayed `FL1-…` recovery key privately, outside the folder. It grants full access to the encrypted data.
4. Confirm **Encrypt original folder**. The app verifies the encrypted files before replacing the folder contents at the same path.
5. Select **Unlock folder** and follow the camera prompts. Without a custom sequence, the app asks for a blink and a head turn.
6. Select **Open in Finder** on macOS or **Open in Explorer** on Windows to work with the restored files.
7. Close editors using those files, then select **Lock folder**. Edits, additions, deletions, and empty directories are included in the new encrypted result.

Closing the app also attempts to lock an open folder. Switching to the file manager does not lock it, so you can work with the files. Forced termination, a crash, or a power failure while unlocked can leave them readable. Check the folder state rather than assuming that quitting always finished encryption.

The managed folder contains an internal `.face-lock-vault` directory (visible in Windows Explorer). **Do not delete it, even while the folder is unlocked.** It holds the encrypted archive and folder state. A legacy standalone `.facevault` archive is an encrypted copy; it does not protect readable originals beside it. Use **Encrypt a folder** on the original folder for the current workflow.

## Make your own gesture locks

![Gesture sequence editor and lock progress](docs/images/gesture-locks.png)

*The actual gesture workspace with a demonstration sequence and an illustrative synthetic camera frame. No live camera or successful authentication is shown.*

Open **Gesture locks** while the folder is locked:

1. Give the next pose a name and choose **Hands**, **Body**, or both.
2. Select **Capture pose · 3s**, then hold the pose after the countdown. Keep your face and the selected landmarks visible.
3. Repeat for each lock, drag steps to reorder them, and select **Save sequence**.

For example:

| Step | Pose to record | Useful capture option |
| --- | --- | --- |
| 1 | Both hands raised | Body, optionally Hands |
| 2 | A triangle formed with both hands | Hands |
| 3 | A raised middle finger | Hands |

During unlocking, hold the first pose until its lock opens, release it, then perform the next. Face loss resets progress. Each capture stores a landmark pose template, not a video clip or a named gesture classifier. The labels are yours: naming a step “Triangle” does not teach the app that gesture independently of your recording.

These are **held poses**, not arbitrary moving choreography. Camera angle, framing, lighting, handedness, and finger visibility affect matching. Record and test the sequence in the position where you expect to use it; live recognition needs calibration with your own poses.

![Illustrative face and body landmark overlay](docs/images/face-landmarks.png)

*Illustrative synthetic example featuring a fictional adult. This is not a live application screenshot or an authentication result; it shows the idea of a landmark overlay.*

## Recovery and practical limits

Choose **Choose encrypted folder**, then **Use recovery key** and enter the saved key locally. Do not paste recovery keys into issues, screenshots, commits, or chat. The recovery key is equivalent to the vault encryption key; losing both it and the stored vault key can make the files unrecoverable.

The current limits are 64 MiB per file, 2 GiB total file data, 2,000 files, and 2,000 directories. Nested folders, Unicode names, and empty directories are supported. Symlinks, Windows junctions, and special files are rejected. macOS resource forks and Windows alternate data streams are rejected before replacing originals. Filenames must also be valid on Windows, even when encrypting on macOS. Extended attributes, ACLs, original timestamps, and original permissions are not preserved.

Folder swaps use temporary sibling directories and need additional free disk space. Do not edit the folder during encryption or decryption. Successful cleanup removes readable originals, but it cannot guarantee erasure from SSD storage, backups, sync history, open file handles, or copies you exported elsewhere. A crash or failed cleanup may leave staging or original directories behind. [SECURITY.md](SECURITY.md) explains the protection boundary.

## How it is built

| Component | Responsibility |
| --- | --- |
| `facelock/ui.py`, `layout.py`, `visuals.py`, `lock_strip.py` | PySide6 interface, camera workspace, and progress display |
| `facelock/vision.py` | OpenCV face recognition and MediaPipe face, hand, and body landmarks |
| `facelock/gestures.py`, `gate.py` | Pose matching, ordered steps, and default movement challenge |
| `facelock/vault.py` | Authenticated file encryption, encrypted manifest, validation, and recovery keys |
| `facelock/folder_vault.py` | Verified staging, same-path folder swaps, and rollback on handled failures |
| `facelock/storage.py` | macOS Keychain / Windows DPAPI access and encrypted local profile storage |
| `models/models.json` | Upstream asset URLs and pinned hashes |

Runtime profile and settings data are stored under `~/Library/Application Support/Face Lock/` on macOS and `%LOCALAPPDATA%/Face Lock/` on Windows. macOS secrets use native Keychain APIs; Windows secrets use user-scoped DPAPI-encrypted files. They are not plaintext project configuration. Settings include the selected folder path; keep runtime data out of source control.

## Development and checks

With the virtual environment activated:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
QT_QPA_PLATFORM=offscreen python main.py --smoke-test --screenshot work/ui.png
python main.py --check-models
```

For the Windows UI smoke test in PowerShell:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe main.py --smoke-test --screenshot work/ui.png
Remove-Item Env:QT_QPA_PLATFORM
```

Use `.\.venv\Scripts\python.exe` in place of `python` for the other checks on Windows.

The smoke test renders the interface without opening the camera or reading Keychain. The model check loads the assets and runs blank-frame inference. Automated tests cover encryption and tamper rejection, recovery, encrypted templates, gesture ordering and face loss, folder swaps, and failure rollback. These checks do not establish live-camera recognition accuracy or resistance to spoofing.

## Build portable applications

Install `requirements-dev.txt`, then build on the target operating system:

```sh
python scripts/build.py
```

On Windows, use `.\.venv\Scripts\python.exe scripts/build.py`. The helper downloads and validates models, builds with PyInstaller, runs packaged blank-frame inference and a camera-free UI smoke test, then creates `dist/FaceLock-windows-x64.zip` or `dist/FaceLock-macos-arm64.zip`. Pass `--dist-dir PATH` to choose another output directory. On macOS, a local temporary path can avoid cloud-synced folder metadata interfering with bundles.

[PyInstaller builds are native to their host operating system](https://pyinstaller.org/en/stable/operating-mode.html); a Mac cannot directly produce the Windows executable. The [manual build workflow](.github/workflows/build.yml) uses separate Windows x64 and macOS arm64 runners, runs tests and packaged checks, and uploads ZIP artifacts. It has read-only repository permissions and does not publish a release automatically. A successful workflow run is required before treating its Windows artifact as available. Private-repository runs consume the account's Actions allowance.

Model assets must be downloaded before packaging; upstream model license notices are included in `models/`. See [THIRD_PARTY.md](THIRD_PARTY.md) for dependency and model terms.
