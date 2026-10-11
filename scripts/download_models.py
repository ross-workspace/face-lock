"""Fetch official model assets; record source revision and SHA-256 digests."""

import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / "models"
ROOT.mkdir(exist_ok=True)


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "FaceLockPrototype/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def main():
    lock_path = ROOT / "models.json"
    if lock_path.exists():
        entries = json.loads(lock_path.read_text())
    else:
        revision = json.loads(fetch("https://api.github.com/repos/opencv/opencv_zoo/commits/main"))[
            "sha"
        ]
        entries = []
        for folder, name in [
            ("face_detection_yunet", "face_detection_yunet_2023mar.onnx"),
            ("face_recognition_sface", "face_recognition_sface_2021dec.onnx"),
        ]:
            pointer = fetch(
                f"https://raw.githubusercontent.com/opencv/opencv_zoo/{revision}/models/{folder}/{name}"
            ).decode()
            digest = next(
                line.split("sha256:")[1] for line in pointer.splitlines() if line.startswith("oid ")
            )
            entries.append(
                {
                    "name": name,
                    "url": f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{revision}/models/{folder}/{name}",
                    "sha256": digest,
                }
            )
            (ROOT / f"{folder}-LICENSE.txt").write_bytes(
                fetch(
                    f"https://raw.githubusercontent.com/opencv/opencv_zoo/{revision}/models/{folder}/LICENSE"
                )
            )
        entries.append(
            {
                "name": "face_landmarker.task",
                "url": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            }
        )
    extra = [
        {
            "name": "hand_landmarker.task",
            "url": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task",
        },
        {
            "name": "pose_landmarker_lite.task",
            "url": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
        },
    ]
    for entry in extra:
        if entry["name"] not in {item["name"] for item in entries}:
            entries.append(entry)
    for entry in entries:
        target = ROOT / entry["name"]
        data = target.read_bytes() if target.exists() else fetch(entry["url"])
        digest = hashlib.sha256(data).hexdigest()
        if entry.get("sha256") and digest != entry["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {entry['name']}")
        if len(data) < 10000:
            raise RuntimeError("Downloaded asset is too small to be a model")
        target.write_bytes(data)
        entry["sha256"] = digest
        print(f"Ready: {entry['name']} ({len(data):,} bytes)")
    lock_path.write_text(json.dumps(entries, indent=2) + "\n")


if __name__ == "__main__":
    main()
