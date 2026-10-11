from facelock.gate import ChallengeGate


def start(gate):
    assert not gate.update(0, True, 0.8)[1]
    gate.update(1, True, 0.8)
    gate.actions = ["blink", "left"]
    gate.index = 0
    gate.armed = True


def test_matching_alone_never_unlocks():
    gate = ChallengeGate()
    for i in range(50):
        assert not gate.update(i / 10, True, 0.9)[1]


def test_full_sequence():
    gate = ChallengeGate()
    start(gate)
    assert not gate.update(2, True, 0.8, blink=0.8)[1]
    assert not gate.update(3, True, 0.8, blink=0)[1]
    assert not gate.update(4, True, 0.8)[1]
    assert gate.update(5, True, 0.8, yaw=0.25)[1]


def test_face_loss_resets_and_timeout_fails_closed():
    gate = ChallengeGate()
    start(gate)
    gate.update(2, False)
    assert gate.started is None and not gate.actions
    start(gate)
    assert not gate.update(17, True, 0.9)[1]
    assert gate.timed_out
    assert not gate.update(18, True, 0.9, blink=0.8, yaw=0.3)[1]


def test_impostor_never_starts_challenge():
    gate = ChallengeGate()
    for t in range(30):
        assert not gate.update(t, True, 0.2, blink=0.8, yaw=0.3)[1]
    assert gate.started is None
