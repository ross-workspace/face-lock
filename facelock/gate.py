"""Gesture challenge is a playful replay deterrent, not trusted liveness."""

import secrets


class ChallengeGate:
    def __init__(self, threshold=0.55):
        self.threshold = threshold
        self.match_start = None
        self.started = None
        self.actions = []
        self.index = 0
        self.armed = False
        self.closed = False
        self.timed_out = False

    def reset(self):
        self.match_start, self.started = None, None
        self.actions, self.index = [], 0
        self.armed, self.closed = False, False

    def update(self, now, valid, similarity=0, blink=0, yaw=0):
        if self.timed_out:
            return "Challenge timed out. Click Unlock to try again.", False
        if self.started is not None and now - self.started > 15:
            self.timed_out = True
            return "Challenge timed out. Click Unlock to try again.", False
        if not valid or similarity < self.threshold:
            self.reset()
            return "Looking for your enrolled face…", False
        if self.match_start is None:
            self.match_start = now
        if now - self.match_start < 0.8:
            return "Face matches — hold still…", False
        if self.started is None:
            self.started = now
            turn = secrets.choice(["left", "right"])
            self.actions = secrets.choice([["blink", turn], [turn, "blink"]])
        if self.index >= len(self.actions):
            return "Face accepted", True
        action = self.actions[self.index]
        neutral = blink < 0.25 and abs(yaw) < 0.10
        if not self.armed:
            if neutral:
                self.armed = True
            else:
                return "Look straight ahead with eyes open…", False
        complete = False
        if action == "blink":
            if blink > 0.60:
                self.closed = True
            complete = self.closed and blink < 0.25
            message = "Blink once, then open your eyes"
        else:
            # Preview is mirrored. 'Left' means moving nose left on the preview.
            complete = yaw > 0.18 if action == "left" else yaw < -0.18
            message = f"Turn toward the {action} side of the preview"
        if complete:
            self.index += 1
            self.armed, self.closed = False, False
            if self.index == len(self.actions):
                return "Face accepted", True
            return "Look straight ahead for the next step…", False
        return f"Step {self.index + 1}/2 · {message}", False
