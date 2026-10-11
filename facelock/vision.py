from __future__ import annotations

import hashlib
import json
import math
import queue
import sys
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from .gate import ChallengeGate
from .gestures import BODY_LINES, HAND_LINES, SequenceGate, distance, features, select_features
from .storage import model_dir

CONTOURS = [
    [
        10,
        338,
        297,
        332,
        284,
        251,
        389,
        356,
        454,
        323,
        361,
        288,
        397,
        365,
        379,
        378,
        400,
        377,
        152,
        148,
        176,
        149,
        150,
        136,
        172,
        58,
        132,
        93,
        234,
        127,
        162,
        21,
        54,
        103,
        67,
        109,
        10,
    ],
    [33, 160, 158, 133, 153, 144, 33],
    [362, 385, 387, 263, 373, 380, 362],
    [61, 40, 37, 0, 267, 270, 291, 321, 314, 17, 84, 91, 61],
    [70, 63, 105, 66, 107],
    [336, 296, 334, 293, 300],
    [168, 6, 197, 195, 5, 4, 1, 2],
    [98, 97, 2, 326, 327],
]


def verify_models():
    root = model_dir()
    entries = json.loads((root / "models.json").read_text())
    for entry in entries:
        if hashlib.sha256((root / entry["name"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Model verification failed. Run scripts/download_models.py again.")


def open_camera(index, platform=None, factory=None):
    platform = platform or sys.platform
    factory = factory or cv2.VideoCapture
    backends = (
        [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        if platform == "win32"
        else [cv2.CAP_AVFOUNDATION]
        if platform == "darwin"
        else [cv2.CAP_ANY]
    )
    for backend in backends:
        try:
            capture = factory(index, backend)
        except cv2.error:
            continue
        if capture.isOpened():
            return capture
        capture.release()
    raise RuntimeError("Cannot open this camera. Check camera permission or select another camera.")


class FaceEngine:
    def __init__(self):
        verify_models()
        import mediapipe as mp

        self.mp = mp
        root = model_dir()
        self.detector = cv2.FaceDetectorYN.create(
            str(root / "face_detection_yunet_2023mar.onnx"), "", (640, 480), 0.85
        )
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(root / "face_recognition_sface_2021dec.onnx"), ""
        )
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(root / "face_landmarker.task")),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_faces=2,
            output_face_blendshapes=True,
        )
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self.timestamp = 0

    def process(self, frame):
        height, width = frame.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(frame)
        count = 0 if faces is None else len(faces)
        self.timestamp = max(self.timestamp + 1, int(time.monotonic() * 1000))
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect_for_video(
            self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), self.timestamp
        )
        output = {
            "valid": False,
            "embedding": None,
            "blink": 0.0,
            "yaw": 0.0,
            "message": "No face — look toward the camera",
        }
        canvas = frame.copy()
        if result.face_landmarks:
            for landmarks in result.face_landmarks:
                for contour in CONTOURS:
                    points = np.array(
                        [
                            (int(landmarks[i].x * width), int(landmarks[i].y * height))
                            for i in contour
                        ],
                        np.int32,
                    )
                    cv2.polylines(canvas, [points], False, (210, 235, 75), 1, cv2.LINE_AA)
                for index in (1, 4, 33, 133, 263, 362, 61, 291, 152, 10, 234, 454):
                    point = landmarks[index]
                    cv2.circle(
                        canvas,
                        (int(point.x * width), int(point.y * height)),
                        3,
                        (240, 255, 185),
                        -1,
                        cv2.LINE_AA,
                    )
        if count != 1 or len(result.face_landmarks) != 1:
            if count > 1 or len(result.face_landmarks) > 1:
                output["message"] = "Only one person may be in frame"
            return canvas, output
        x, y, face_width, face_height = faces[0, :4]
        if face_width < 100 or face_height < 100:
            output["message"] = "Move closer to the camera"
            return canvas, output
        if x < 0 or y < 0 or x + face_width > width or y + face_height > height:
            output["message"] = "Keep your whole face in frame"
            return canvas, output
        crop = frame[int(y) : int(y + face_height), int(x) : int(x + face_width)]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if gray.mean() < 35 or gray.mean() > 230 or cv2.Laplacian(gray, cv2.CV_64F).var() < 20:
            output["message"] = "Use steady, even lighting"
            return canvas, output
        aligned = self.recognizer.alignCrop(frame, faces[0])
        embedding = self.recognizer.feature(aligned).flatten()
        norm = np.linalg.norm(embedding)
        if not np.all(np.isfinite(embedding)) or norm < 0.001:
            return canvas, output
        landmarks = result.face_landmarks[0]
        left, right, nose = landmarks[234].x, landmarks[454].x, landmarks[1].x
        yaw = (nose - (left + right) / 2) / max(abs(right - left), 0.01)
        scores = {item.category_name: item.score for item in result.face_blendshapes[0]}
        blink = min(scores.get("eyeBlinkLeft", 0), scores.get("eyeBlinkRight", 0))
        output.update(
            valid=True, embedding=embedding / norm, blink=blink, yaw=yaw, message="Face detected"
        )
        return canvas, output

    def close(self):
        self.landmarker.close()


class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    status = Signal(str)
    score = Signal(float)
    enrolled = Signal(object)
    accepted = Signal()
    failed = Signal(str)
    gesture_recorded = Signal(object)
    capture_finished = Signal()
    lock_progress = Signal(int, int)

    def __init__(self, camera=0, mode="preview", profile=None, steps=None):
        super().__init__()
        self.camera, self.mode, self.profile = camera, mode, profile
        self.steps = steps or []
        self.commands = queue.SimpleQueue()

    def run(self):
        capture, engine, motion = None, None, None
        try:
            self.status.emit("Loading local face models…")
            engine = FaceEngine()
            if self.mode == "record" or self.steps:
                motion = MotionEngine()
            if self.isInterruptionRequested():
                return
            capture = open_camera(self.camera)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if not capture.isOpened():
                raise RuntimeError(
                    "Camera unavailable. Allow camera access in System Settings → Privacy & Security → Camera, or choose another camera."
                )
            gate = SequenceGate(self.steps) if self.steps else ChallengeGate()
            pending_capture, capture_samples = None, []
            samples, sample_time = [], 0
            started = time.monotonic()
            last_message, last_status = "", 0
            while not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("Camera disconnected or stopped delivering frames.")
                frame = cv2.resize(frame, (640, 480))
                canvas, info = engine.process(frame)
                live = (
                    motion.process(frame, canvas, engine.timestamp)
                    if motion
                    else {"hands": {}, "body": {}}
                )
                now = time.monotonic()
                similarity = (
                    float(np.dot(info["embedding"], self.profile))
                    if info["valid"] and self.profile is not None
                    else 0.0
                )
                message = info["message"]
                accepted, complete = False, False
                if self.mode == "enroll":
                    if now - started > 60:
                        raise RuntimeError("Enrollment timed out. Try again with even lighting.")
                    if info["valid"] and info["blink"] < 0.4 and now - sample_time > 0.4:
                        if samples and float(np.dot(info["embedding"], samples[0])) < 0.45:
                            raise RuntimeError(
                                "Face changed during enrollment. Enroll one person at a time."
                            )
                        samples.append(info["embedding"])
                        sample_time = now
                    if info["valid"]:
                        message = f"Enrolling {len(samples)}/20 · slowly vary your angle"
                    complete = len(samples) >= 20
                elif self.mode == "record":
                    message = "Compose your next pose, then click Capture pose"
                    while not self.commands.empty():
                        command = self.commands.get()
                        pending_capture = {**command, "at": now + 3}
                        capture_samples = []
                    if pending_capture is not None:
                        remaining = pending_capture["at"] - now
                        if remaining > 0:
                            message = f"Get into your pose · capturing in {math.ceil(remaining)}…"
                        elif now - pending_capture["at"] > 8:
                            message = "Capture failed. Keep your face and selected landmarks visible, then retry."
                            pending_capture = None
                            self.capture_finished.emit()
                        elif not info["valid"] or similarity < 0.55:
                            capture_samples = []
                            message = "Keep your enrolled face visible during recording"
                        else:
                            try:
                                template = select_features(
                                    live, pending_capture["hands"], pending_capture["body"]
                                )
                                if capture_samples and distance(capture_samples[0], template) > 1:
                                    capture_samples = []
                                capture_samples.append(template)
                                message = "Hold the pose steady…"
                                if len(capture_samples) >= 5:
                                    self.gesture_recorded.emit(
                                        {
                                            "name": pending_capture["name"],
                                            "template": capture_samples[-1],
                                        }
                                    )
                                    pending_capture = None
                                    capture_samples = []
                                    self.capture_finished.emit()
                                    message = (
                                        "Pose captured. Record another lock or save the sequence."
                                    )
                            except ValueError as error:
                                capture_samples = []
                                message = str(error)
                elif self.mode == "unlock":
                    if self.steps:
                        message, accepted = gate.update(now, info["valid"], similarity, live)
                        self.lock_progress.emit(gate.index, len(self.steps))
                    else:
                        message, accepted = gate.update(
                            now, info["valid"], similarity, info["blink"], info["yaw"]
                        )
                        self.lock_progress.emit(gate.index, 2)
                    if not info["valid"]:
                        message = info["message"]
                    self.score.emit(similarity)
                elif self.profile is not None and info["valid"]:
                    self.score.emit(similarity)
                    message = (
                        "Ready — click Unlock vault"
                        if similarity >= 0.55
                        else "Face detected — profile does not match"
                    )
                if message != last_message or now - last_status > 0.5:
                    self.status.emit(message)
                    last_message, last_status = message, now
                display = cv2.cvtColor(cv2.flip(canvas, 1), cv2.COLOR_BGR2RGB)
                image = QImage(
                    display.data, 640, 480, display.strides[0], QImage.Format.Format_RGB888
                ).copy()
                self.frame_ready.emit(image)
                if complete:
                    centroid = np.mean(samples, axis=0)
                    norm = np.linalg.norm(centroid)
                    if norm < 0.1:
                        raise RuntimeError("Enrollment samples were inconsistent. Try again.")
                    self.enrolled.emit(centroid / norm)
                    break
                if accepted:
                    self.accepted.emit()
                    break
                self.msleep(35)
        except Exception as error:
            self.failed.emit(str(error))
        finally:
            if capture is not None:
                capture.release()
            if engine is not None:
                engine.close()
            if motion is not None:
                motion.close()


class MotionEngine:
    def __init__(self):
        import mediapipe as mp

        self.mp = mp
        root = model_dir()
        self.hands = mp.tasks.vision.HandLandmarker.create_from_options(
            mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(root / "hand_landmarker.task")
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_hands=2,
            )
        )
        self.pose = mp.tasks.vision.PoseLandmarker.create_from_options(
            mp.tasks.vision.PoseLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(root / "pose_landmarker_lite.task")
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_poses=1,
            )
        )

    def process(self, frame, canvas, timestamp):
        image = self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        )
        hands = self.hands.detect_for_video(image, timestamp)
        pose = self.pose.detect_for_video(image, timestamp)
        height, width = canvas.shape[:2]
        for points in hands.hand_landmarks:
            for line in HAND_LINES:
                pixels = np.array(
                    [(int(points[i].x * width), int(points[i].y * height)) for i in line], np.int32
                )
                cv2.polylines(canvas, [pixels], False, (80, 195, 255), 2, cv2.LINE_AA)
            for point in points:
                cv2.circle(
                    canvas,
                    (int(point.x * width), int(point.y * height)),
                    3,
                    (135, 220, 255),
                    -1,
                    cv2.LINE_AA,
                )
        if pose.pose_landmarks:
            points = pose.pose_landmarks[0]
            for a, b in BODY_LINES:
                if points[a].visibility > 0.5 and points[b].visibility > 0.5:
                    cv2.line(
                        canvas,
                        (int(points[a].x * width), int(points[a].y * height)),
                        (int(points[b].x * width), int(points[b].y * height)),
                        (235, 165, 115),
                        2,
                        cv2.LINE_AA,
                    )
        return features(hands, pose)

    def close(self):
        self.hands.close()
        self.pose.close()
