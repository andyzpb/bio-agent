from asv_eval.core import Candidate, CandidateSpace, StepRecord, TaskRecord, TrajectoryRecord
from asv_eval.runtime import EvaluatorRuntimeConfig, fill_missing_beliefs, quote_buffer_from_state_text


def test_quote_buffer_uses_verbatim_state_lines() -> None:
    state_text = "\n".join(
        [
            '{"question": "Should not be selected",',
            '"supported_claims": ["Alpha reduced risk in trial X.",',
            '"audit": {"recommended_action": "pass"},',
            '"metadata": "ignore me"}',
        ]
    )

    buffer = quote_buffer_from_state_text(state_text, max_lines=2)

    lines = buffer.splitlines()
    assert lines == [
        '"supported_claims": ["Alpha reduced risk in trial X.",',
        '"audit": {"recommended_action": "pass"},',
    ]
    assert all(line in state_text for line in lines)


def test_quote_buffer_skips_audit_inside_evidence_facts() -> None:
    state_text = (
        '{"evidence_facts": {"audit": {"recommended_action": "revise"}, '
        '"supported_claims": ["Alpha is supported."]}}'
    )

    buffer = quote_buffer_from_state_text(state_text)

    assert "supported_claims" in buffer
    assert "audit" not in buffer
    assert "recommended_action" not in buffer


def test_quote_buffer_skips_bibliographic_metadata() -> None:
    state_text = (
        '{"paper_ids": ["123"], "papers_found": 1, '
        '"supported_claims": ["Alpha is supported."]}'
    )

    buffer = quote_buffer_from_state_text(state_text)

    assert "supported_claims" in buffer
    assert "paper_ids" not in buffer
    assert "papers_found" not in buffer


def test_quote_mode_scores_only_quote_buffer() -> None:
    task = TaskRecord(
        task_id="task-quote",
        question="Which answer is supported?",
        candidate_space=CandidateSpace(
            candidates=[
                Candidate(id="answer-a", label="A", text="Alpha is supported."),
                Candidate(id="answer-b", label="B", text="Beta is supported."),
            ],
        ),
    )
    trajectory = TrajectoryRecord(
        trajectory_id="traj-quote",
        task=task,
        steps=[
            StepRecord(
                step_id="s1",
                index=0,
                action={"type": "final"},
                state_before={"metadata": "ignore", "supported_claims": ["Alpha is supported."]},
                state_after={"metadata": "ignore", "supported_claims": ["Alpha is supported."]},
            )
        ],
    )
    evaluator = _CapturingEvaluator()

    fill_missing_beliefs(
        [trajectory],
        config=EvaluatorRuntimeConfig(mode="deepseek-chat-logprob", rationale_mode="quote"),
        evaluator=evaluator,
    )

    assert evaluator.evidence_texts
    assert all("metadata" not in text for text in evaluator.evidence_texts)
    assert all("supported_claims" in text for text in evaluator.evidence_texts)
    assert all(text is None for text in evaluator.rationale_texts)


class _CapturingEvaluator:
    def __init__(self) -> None:
        self.evidence_texts: list[str] = []
        self.rationale_texts: list[str | None] = []

    def score_state(self, **kwargs):
        self.evidence_texts.append(kwargs["evidence_text"])
        self.rationale_texts.append(kwargs.get("rationale_text"))
        return {"answer-a": 0.0, "answer-b": -1.0}, []
