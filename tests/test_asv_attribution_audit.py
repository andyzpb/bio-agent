from __future__ import annotations

from eval.asv.open_qa.attribution_audit import _swap_rationales


def test_swap_rationales_is_deterministic_and_cross_trajectory() -> None:
    samples = [
        {"trajectory_id": "t1", "step_id": "s1"},
        {"trajectory_id": "t2", "step_id": "s1"},
        {"trajectory_id": "t3", "step_id": "s1"},
    ]
    generated = {
        ("t1", "s1", "before"): "before from t1",
        ("t1", "s1", "after"): "after from t1",
        ("t2", "s1", "before"): "before from t2",
        ("t2", "s1", "after"): "after from t2",
        ("t3", "s1", "before"): "before from t3",
        ("t3", "s1", "after"): "after from t3",
    }

    first = _swap_rationales(samples, generated, seed=7)
    second = _swap_rationales(samples, generated, seed=7)

    assert first == second
    for key, rationale in first.items():
        trajectory_id, _, position = key
        assert rationale != generated[(trajectory_id, "s1", position)]
