import copy
from facelock.gestures import SequenceGate, distance
from facelock.storage import ProfileStore
from test_profile import MemoryKeychain


def pose(value):
    return {
        "hands": {},
        "body": {"11": [-0.5, 0], "12": [0.5, 0], "15": [value, -1], "16": [-value, -1]},
    }


def test_exact_pose_matches_missing_and_different_pose_rejected():
    template = pose(2)
    assert distance(template, copy.deepcopy(template)) == 0
    assert distance(template, pose(-2)) > 1
    assert distance(template, {"hands": {}, "body": {}}) > 1


def test_order_hold_release_and_face_loss():
    steps = [{"name": "Hands up", "template": pose(2)}, {"name": "Triangle", "template": pose(-2)}]
    gate = SequenceGate(steps)
    gate.update(0, True, 0.8, pose(2))
    gate.update(1, True, 0.8, pose(-2))
    assert gate.index == 0  # Wrong order.
    gate.update(2, True, 0.8, pose(2))
    gate.update(2.8, True, 0.8, pose(2))
    assert gate.index == 1
    assert not gate.update(3, True, 0.8, pose(2))[1]
    gate.update(4, True, 0.8, pose(-2))
    gate.update(4.4, True, 0.8, pose(-2))
    gate.update(5, True, 0.8, pose(-2))
    assert gate.update(5.8, True, 0.8, pose(-2))[1]
    gate.update(6, False, 0, pose(-2))
    assert gate.index == 0


def test_identical_consecutive_steps_require_release():
    step = {"name": "Pose", "template": pose(2)}
    gate = SequenceGate([step, step])
    gate.update(0, True, 0.8, pose(2))
    gate.update(1, True, 0.8, pose(2))
    gate.update(2, True, 0.8, pose(2))
    assert gate.index == 1
    for t in (3, 4, 5):
        assert not gate.update(t, True, 0.8, pose(2))[1]
    assert gate.index == 1


def test_hand_finger_difference_rejected():
    hand = {"shape": [0.0] * 63, "center": [0.5, 0.5]}
    template = {"hands": {"Left": hand}, "body": {}}
    live = copy.deepcopy(template)
    assert distance(template, live) == 0
    live["hands"]["Left"]["shape"][12 * 3 + 1] = 1.5
    assert distance(template, live) > 1


def test_sequence_storage_is_encrypted_and_survives_restart(tmp_path):
    chain = MemoryKeychain()
    store = ProfileStore(tmp_path, chain)
    steps = [{"name": "Custom pose", "template": pose(2)}]
    store.save_sequence(steps)
    assert b"Custom pose" not in (tmp_path / "gestures.enc").read_bytes()
    assert ProfileStore(tmp_path, chain).load_sequence() == steps
