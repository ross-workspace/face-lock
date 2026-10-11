"""Local geometric held-pose templates, not video recordings or trusted liveness."""

from __future__ import annotations

import copy
import math
import numpy as np


HAND_LINES = [
    [0, 1, 2, 3, 4],
    [0, 5, 6, 7, 8],
    [5, 9, 10, 11, 12],
    [9, 13, 14, 15, 16],
    [13, 17, 18, 19, 20],
    [0, 17],
]
BODY_LINES = [
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (25, 27),
    (24, 26),
    (26, 28),
]


def features(hands, pose):
    result = {"hands": {}, "body": {}}
    for points, categories in zip(hands.hand_landmarks, hands.handedness):
        xyz = np.array([[p.x * 4 / 3, p.y, p.z * 0.5] for p in points])
        scale = np.linalg.norm(xyz[9] - xyz[0])
        if scale < 0.025 or not np.isfinite(xyz).all():
            continue
        # Reject partial/offscreen hands; posture should be fully visible.
        if any(p.x < 0 or p.x > 1 or p.y < 0 or p.y > 1 for p in points):
            continue
        result["hands"][categories[0].category_name] = {
            "shape": ((xyz - xyz[0]) / scale).flatten().tolist(),
            "center": [points[0].x, points[0].y],
        }
    if pose.pose_landmarks:
        points = pose.pose_landmarks[0]
        if points[11].visibility > 0.5 and points[12].visibility > 0.5:
            center = np.array(
                [(points[11].x + points[12].x) * 2 / 3, (points[11].y + points[12].y) / 2]
            )
            scale = np.linalg.norm(
                np.array([points[11].x * 4 / 3, points[11].y])
                - np.array([points[12].x * 4 / 3, points[12].y])
            )
            if scale > 0.06:
                for i in (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28):
                    p = points[i]
                    if p.visibility > 0.55 and 0 < p.x < 1 and 0 < p.y < 1:
                        result["body"][str(i)] = (
                            (np.array([p.x * 4 / 3, p.y]) - center) / scale
                        ).tolist()
    return result


def select_features(live, hands=True, body=False):
    selected = {
        "hands": copy.deepcopy(live["hands"]) if hands else {},
        "body": copy.deepcopy(live["body"]) if body else {},
    }
    if not hands and not body:
        raise ValueError("Select hands, body, or both.")
    if hands and not selected["hands"]:
        raise ValueError("Keep at least one whole hand visible.")
    if body and len(selected["body"]) < 4:
        raise ValueError("Step back so your shoulders and arms are visible.")
    return selected


def validate_step(step):
    if (
        not isinstance(step, dict)
        or not isinstance(step.get("name"), str)
        or len(step["name"]) > 80
    ):
        raise ValueError("Invalid gesture step.")
    template = step["template"]
    hands, body = template["hands"], template["body"]
    if not isinstance(hands, dict) or not isinstance(body, dict) or (not hands and not body):
        raise ValueError("Empty gesture template.")
    if not set(hands).issubset({"Left", "Right"}) or not set(body).issubset(
        {str(i) for i in (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)}
    ):
        raise ValueError("Invalid gesture landmarks.")
    for hand in hands.values():
        for key, length in (("shape", 63), ("center", 2)):
            values = np.asarray(hand[key], dtype=float)
            if (
                values.shape != (length,)
                or not np.isfinite(values).all()
                or np.abs(values).max() > 20
            ):
                raise ValueError("Invalid hand template.")
    for point in body.values():
        values = np.asarray(point, dtype=float)
        if values.shape != (2,) or not np.isfinite(values).all() or np.abs(values).max() > 20:
            raise ValueError("Invalid body template.")


def distance(template, live):
    """A value <= 1 matches. Missing recorded components always reject."""
    ratios = []
    if template["hands"]:
        if set(template["hands"]) != set(live["hands"]):
            return math.inf
        for side, expected in template["hands"].items():
            current = live["hands"][side]
            a = np.asarray(expected["shape"]).reshape(21, 3)
            b = np.asarray(current["shape"]).reshape(21, 3)
            error = a - b
            ratios.extend(
                [
                    float(np.sqrt(np.mean(error**2))) / 0.22,
                    float(np.max(np.linalg.norm(error[[4, 8, 12, 16, 20]], axis=1))) / 0.65,
                    float(np.linalg.norm(np.asarray(expected["center"]) - current["center"]))
                    / 0.18,
                ]
            )
    if template["body"]:
        if not set(template["body"]).issubset(live["body"]):
            return math.inf
        errors = np.array(
            [np.asarray(point) - live["body"][name] for name, point in template["body"].items()]
        )
        ratios.extend(
            [
                float(np.sqrt(np.mean(errors**2))) / 0.28,
                float(np.max(np.linalg.norm(errors, axis=1))) / 0.65,
            ]
        )
    return max(ratios, default=math.inf)


class SequenceGate:
    def __init__(self, steps, threshold=0.55):
        self.steps, self.threshold = steps, threshold
        self.index = 0
        self.face_since = self.pose_since = self.release_since = self.started = None
        self.await_release = False
        self.timed_out = False

    def update(self, now, valid, similarity, live):
        if self.timed_out:
            return "Sequence timed out. Cancel and try again.", False
        if self.started is not None and now - self.started > max(30, 20 * len(self.steps)):
            self.timed_out = True
            return "Sequence timed out. Cancel and try again.", False
        if not valid or similarity < self.threshold:
            self.index = 0
            self.face_since = self.pose_since = self.release_since = self.started = None
            self.await_release = False
            return "Keep your enrolled face visible. Sequence resets if it is lost.", False
        if self.face_since is None:
            self.face_since = now
        if now - self.face_since < 0.8:
            return "Face matches — hold still…", False
        if self.started is None:
            self.started = now
        if self.index == len(self.steps):
            return "All gesture locks opened", True
        if self.await_release:
            if distance(self.steps[self.index - 1]["template"], live) > 1:
                if self.release_since is None:
                    self.release_since = now
                if now - self.release_since > 0.25:
                    self.await_release = False
            else:
                self.release_since = None
            return "Release the previous pose, then perform the next one", False
        step = self.steps[self.index]
        if distance(step["template"], live) <= 1:
            if self.pose_since is None:
                self.pose_since = now
            if now - self.pose_since >= 0.7:
                self.index += 1
                self.pose_since = None
                self.await_release = self.index < len(self.steps)
                if self.index == len(self.steps):
                    return "All gesture locks opened", True
                return "Lock opened — release this pose", False
            return f"Hold {step['name']}…", False
        self.pose_since = None
        return f"Lock {self.index + 1}/{len(self.steps)} · {step['name']}", False
