from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

from asv_eval.runtime import EvaluatorRuntimeConfig, render_state_for_evaluator
from plugins.biomed_evidence.workflow.asv import trajectory_from_workflow_steps
from plugins.biomed_evidence.workflow.stateless.classify import classify_step
from plugins.biomed_evidence.workflow.stateless.compare import compare_projections
from plugins.biomed_evidence.workflow.stateless.retrieve import retrieve_step
from plugins.biomed_evidence.workflow.stateless.types import (
    MockRetrievalArtifact,
    StepInput,
    StepOutput,
    step_output_to_workflow_step,
)


def test_stateless_step_output_projects_to_biomed_workflow_step() -> None:
    step_input = StepInput(
        run_id="stateless-run-1",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )
    step_output = StepOutput(
        step_id="retrieve",
        step_name="retrieve",
        status="completed",
        input_state=step_input.to_state(),
        action={"type": "retrieve", "source_mode": "mock"},
        observation={"summary": "retrieved one mocked paper"},
        output_state={
            **step_input.to_state(),
            "completed_steps": ["classify", "retrieve"],
            "available_artifacts": [
                "classification:research",
                "retrieval_id:retrieval-1",
            ],
        },
        cost={"source_call_count": 1, "tool_calls": 1},
        warnings=["mock source"],
        artifact_ids={"retrieval_id": "retrieval-1"},
    )

    workflow_step = step_output_to_workflow_step("stateless-run-1", step_output)

    assert workflow_step.step_name == "retrieve"
    assert workflow_step.run_id == "stateless-run-1"
    assert workflow_step.action["source_mode"] == "mock"
    assert workflow_step.output_state["completed_steps"] == ["classify", "retrieve"]
    assert workflow_step.cost["source_call_count"] == 1
    assert workflow_step.warnings == ["mock source"]
    assert workflow_step.artifact_ids == {"retrieval_id": "retrieval-1"}


def test_stateless_classify_step_marks_research_question() -> None:
    step_input = StepInput(
        run_id="stateless-run-2",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.step_id == "classify"
    assert output.step_name == "classify"
    assert output.status == "completed"
    assert output.input_state == step_input.to_state()
    assert output.action == {
        "type": "classify",
        "policy": "deterministic_guardrail",
        "source_policy": "mock_only",
    }
    assert output.observation["classification"] == "research"
    assert output.observation["allowed_next_step"] == "retrieve"
    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == ["classification:research"]
    assert output.cost == {"llm_call_count": 0, "tool_calls": 0}
    assert output.warnings == []
    assert output.errors == []
    assert output.artifact_ids == {"classification": "research"}


def test_stateless_classify_step_refuses_clinical_request() -> None:
    step_input = StepInput(
        run_id="stateless-run-3",
        question="My father has symptoms, what dose of medication should he take?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.step_id == "classify"
    assert output.step_name == "classify"
    assert output.status == "skipped"
    assert output.input_state == step_input.to_state()
    assert output.action == {
        "type": "classify",
        "policy": "deterministic_guardrail",
        "source_policy": "mock_only",
    }
    assert output.observation["classification"] == "clinical_advice_refusal"
    assert output.observation["allowed_next_step"] == "stop"
    assert "research support only" in output.observation["refusal_reason"]
    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == [
        "classification:clinical_advice_refusal"
    ]
    assert output.output_state["clinical_boundary"] is True
    assert output.cost == {"llm_call_count": 0, "tool_calls": 0}
    assert output.warnings == ["clinical_boundary"]
    assert output.errors == []
    assert output.artifact_ids == {"classification": "clinical_advice_refusal"}


def test_stateless_classify_step_skips_unsupported_request() -> None:
    step_input = StepInput(
        run_id="stateless-run-unsupported",
        question="What evidence supports that my laptop battery drains quickly?",
        source_policy="mock_only",
        source="mock",
    )

    output = classify_step(step_input)

    assert output.status == "skipped"
    assert output.observation["classification"] == "unsupported_request"
    assert output.observation["allowed_next_step"] == "stop"
    assert output.output_state["available_artifacts"] == [
        "classification:unsupported_request"
    ]
    assert output.warnings == ["unsupported_request"]
    assert output.artifact_ids == {"classification": "unsupported_request"}


def test_stateless_classify_step_skips_biomedical_homonyms_out_of_domain() -> None:
    for question in [
        "What evidence supports that my cellular data drains quickly?",
        "What evidence supports that Cancer will be lucky this week?",
    ]:
        output = classify_step(
            StepInput(
                run_id="stateless-run-homonym",
                question=question,
                source_policy="mock_only",
                source="mock",
            )
        )

        assert output.status == "skipped"
        assert output.observation["classification"] == "unsupported_request"
        assert output.observation["allowed_next_step"] == "stop"


def test_stateless_classify_step_deduplicates_existing_state_markers() -> None:
    step_input = StepInput(
        run_id="stateless-run-idempotent",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )

    output = classify_step(step_input)

    assert output.output_state["completed_steps"] == ["classify"]
    assert output.output_state["available_artifacts"] == ["classification:research"]


def test_stateless_package_exports_retrieve_step() -> None:
    from plugins.biomed_evidence.workflow import stateless

    assert stateless.retrieve_step is retrieve_step


def test_retrieve_step_returns_mock_artifacts_from_explicit_input() -> None:
    artifact = MockRetrievalArtifact(
        paper_id="MOCK-PMID-1001",
        title="Microglial activation signatures track disease progression",
        abstract="Activated microglia correlated with Braak stage.",
    )
    step_input = StepInput(
        run_id="stateless-run-4",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
        artifact_payloads=[artifact],
    )

    output = retrieve_step(step_input)

    assert output.step_id == "retrieve"
    assert output.step_name == "retrieve"
    assert output.status == "completed"
    assert output.input_state == step_input.to_state()
    assert output.action == {
        "type": "retrieve",
        "source_mode": "mock",
        "query": "Does microglial activation track Alzheimer's progression?",
    }
    assert output.observation == {
        "retrieval_id": "stateless-run-4-retrieval-mock",
        "summary": "retrieved 1 mocked paper(s)",
        "paper_count": 1,
        "papers": [artifact.summary()],
    }
    assert output.output_state["completed_steps"] == ["classify", "retrieve"]
    assert output.output_state["available_artifacts"] == [
        "classification:research",
        "retrieval_id:stateless-run-4-retrieval-mock",
    ]
    assert output.output_state["retrieval_id"] == "stateless-run-4-retrieval-mock"
    assert output.output_state["retrieved_paper_ids"] == ["MOCK-PMID-1001"]
    assert output.output_state["retrieved_papers"] == [artifact.summary()]
    assert output.output_state["last_step"] == "retrieve"
    assert output.output_state["last_status"] == "completed"
    assert output.cost == {
        "source_call_count": 1,
        "artifact_cache_hit_count": 0,
        "tool_calls": 1,
    }
    assert output.warnings == []
    assert output.errors == []
    assert output.artifact_ids == {
        "retrieval_id": "stateless-run-4-retrieval-mock",
    }


def test_retrieve_step_deduplicates_existing_retrieve_markers() -> None:
    retrieval_id = "stateless-run-dedupe-retrieval-mock"
    step_input = StepInput(
        run_id="stateless-run-dedupe",
        question="What evidence links microglial activation to Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify", "retrieve"],
        available_artifacts=[
            "classification:research",
            f"retrieval_id:{retrieval_id}",
        ],
        artifact_payloads=[
            MockRetrievalArtifact(
                paper_id="MOCK-PMID-1002",
                title="Microglia and pathology progression",
                abstract="Mock abstract.",
            )
        ],
    )

    output = retrieve_step(step_input)

    assert output.output_state["completed_steps"] == ["classify", "retrieve"]
    assert output.output_state["available_artifacts"] == [
        "classification:research",
        f"retrieval_id:{retrieval_id}",
    ]


def test_retrieve_step_skips_after_clinical_boundary() -> None:
    step_input = StepInput(
        run_id="stateless-run-5",
        question="What dose should my father take?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:clinical_advice_refusal"],
    )

    output = retrieve_step(step_input)

    assert output.step_id == "retrieve"
    assert output.step_name == "retrieve"
    assert output.status == "skipped"
    assert output.input_state == step_input.to_state()
    assert output.output_state == {
        **step_input.to_state(),
        "last_step": "retrieve",
        "last_status": "skipped",
    }
    assert output.observation == {
        "summary": "clinical boundary stopped retrieval",
        "paper_count": 0,
    }
    assert output.cost == {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }
    assert output.warnings == ["clinical_boundary"]
    assert output.errors == []
    assert output.artifact_ids == {}


def test_retrieve_step_skips_after_unsupported_request_marker() -> None:
    step_input = StepInput(
        run_id="stateless-run-unsupported-retrieve",
        question="What evidence supports that my laptop battery drains quickly?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:unsupported_request"],
    )

    output = retrieve_step(step_input)

    assert output.status == "skipped"
    assert output.output_state == {
        **step_input.to_state(),
        "last_step": "retrieve",
        "last_status": "skipped",
    }
    assert output.observation == {
        "summary": "unsupported request stopped retrieval",
        "paper_count": 0,
    }
    assert output.cost == {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }
    assert output.warnings == ["unsupported_request"]
    assert output.errors == []
    assert output.artifact_ids == {}


def test_retrieve_step_rejects_non_mock_source_policy_or_source() -> None:
    for source_policy, source in [
        ("live_opt_in", "mock"),
        ("mock_only", "pubmed"),
    ]:
        step_input = StepInput(
            run_id=f"stateless-run-source-{source_policy}-{source}",
            question="What evidence links microglial activation to Alzheimer's progression?",
            source_policy=source_policy,
            source=source,
            completed_steps=["classify"],
            available_artifacts=["classification:research"],
        )

        output = retrieve_step(step_input)

        assert output.status == "failed"
        assert output.output_state == {
            **step_input.to_state(),
            "last_step": "retrieve",
            "last_status": "failed",
        }
        assert output.cost == {
            "source_call_count": 0,
            "artifact_cache_hit_count": 0,
            "tool_calls": 0,
        }
        assert output.warnings == []
        assert output.errors == ["unsupported_source_policy"]
        assert output.artifact_ids == {}


def test_retrieve_step_completes_empty_mock_retrieval_without_source_calls() -> None:
    step_input = StepInput(
        run_id="stateless-run-empty-retrieve",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        completed_steps=["classify"],
        available_artifacts=["classification:research"],
    )

    output = retrieve_step(step_input)

    assert output.status == "completed"
    assert output.observation == {
        "retrieval_id": "stateless-run-empty-retrieve-retrieval-mock",
        "summary": "retrieved 0 mocked paper(s)",
        "paper_count": 0,
        "papers": [],
    }
    assert output.output_state["completed_steps"] == ["classify", "retrieve"]
    assert output.output_state["available_artifacts"] == [
        "classification:research",
        "retrieval_id:stateless-run-empty-retrieve-retrieval-mock",
    ]
    assert output.output_state["retrieval_id"] == (
        "stateless-run-empty-retrieve-retrieval-mock"
    )
    assert output.output_state["retrieved_paper_ids"] == []
    assert output.output_state["retrieved_papers"] == []
    assert output.cost == {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }
    assert output.warnings == ["empty_mock_retrieval"]
    assert output.errors == []
    assert output.artifact_ids == {
        "retrieval_id": "stateless-run-empty-retrieve-retrieval-mock",
    }


def test_retrieve_step_state_after_renders_evidence_text_for_llm_evaluator() -> None:
    artifact = MockRetrievalArtifact(
        paper_id="MOCK-PMID-1001",
        title="Microglial activation signatures track disease progression",
        abstract="Activated microglia correlated with Braak stage.",
    )
    retrieve_output = retrieve_step(
        StepInput(
            run_id="stateless-run-render",
            question="Does microglial activation track Alzheimer's progression?",
            source_policy="mock_only",
            source="mock",
            completed_steps=["classify"],
            available_artifacts=["classification:research"],
            artifact_payloads=[artifact],
        )
    )
    workflow_step = step_output_to_workflow_step(
        "stateless-run-render", retrieve_output
    )
    trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-render",
        question="Does microglial activation track Alzheimer's progression?",
        steps=[workflow_step],
    )

    rendered = render_state_for_evaluator(
        trajectory.task,
        trajectory.steps[0],
        position="after",
        config=EvaluatorRuntimeConfig(state_text_max_chars=4000),
    )

    assert "Activated microglia correlated with Braak stage." in rendered.prompt
    assert "Microglial activation signatures track disease progression" in rendered.prompt


def test_retrieve_step_fails_without_research_classification_marker() -> None:
    step_input = StepInput(
        run_id="stateless-run-unclassified-retrieve",
        question="Does microglial activation track Alzheimer's progression?",
        source_policy="mock_only",
        source="mock",
        artifact_payloads=[
            MockRetrievalArtifact(
                paper_id="MOCK-PMID-1001",
                title="Microglial activation signatures track disease progression",
                abstract="Activated microglia correlated with Braak stage.",
            )
        ],
    )

    output = retrieve_step(step_input)

    assert output.status == "failed"
    assert output.observation["summary"] == "research classification is required"
    assert output.errors == ["missing_research_classification"]
    assert output.cost == {
        "source_call_count": 0,
        "artifact_cache_hit_count": 0,
        "tool_calls": 0,
    }


def test_stateless_classify_retrieve_slice_evaluates_with_provided_beliefs(
    tmp_path: Path,
) -> None:
    question = "Does microglial activation track Alzheimer's progression?"
    classify_output = classify_step(
        StepInput(
            run_id="stateless-run-6",
            question=question,
            source_policy="mock_only",
            source="mock",
        )
    )
    retrieve_output = retrieve_step(
        StepInput(
            run_id="stateless-run-6",
            question=question,
            source_policy="mock_only",
            source="mock",
            completed_steps=classify_output.output_state["completed_steps"],
            available_artifacts=classify_output.output_state["available_artifacts"],
            artifact_payloads=[
                MockRetrievalArtifact(
                    paper_id="MOCK-PMID-1001",
                    title="Microglial activation signatures track disease progression",
                    abstract="Activated microglia correlated with Braak stage.",
                )
            ],
        )
    )
    workflow_steps = [
        step_output_to_workflow_step("stateless-run-6", classify_output),
        step_output_to_workflow_step("stateless-run-6", retrieve_output),
    ]
    trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-6",
        question=question,
        steps=workflow_steps,
    )

    input_path = tmp_path / "stateless-asv.jsonl"
    fixture_path = tmp_path / "beliefs.jsonl"
    output_dir = tmp_path / "asv-report"
    input_path.write_text(
        json.dumps(asdict(trajectory), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fixture_rows = [
        {
            "trajectory_id": trajectory.trajectory_id,
            "step_id": "classify",
            "belief_before": {
                "supported": 0.34,
                "refuted": 0.33,
                "not_enough_information": 0.33,
            },
            "belief_after": {
                "supported": 0.36,
                "refuted": 0.31,
                "not_enough_information": 0.33,
            },
        },
        {
            "trajectory_id": trajectory.trajectory_id,
            "step_id": "retrieve",
            "belief_before": {
                "supported": 0.36,
                "refuted": 0.31,
                "not_enough_information": 0.33,
            },
            "belief_after": {
                "supported": 0.78,
                "refuted": 0.08,
                "not_enough_information": 0.14,
            },
        },
    ]
    fixture_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in fixture_rows),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "asv_eval",
            "evaluate",
            "--input",
            str(input_path),
            "--belief-fixture",
            str(fixture_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trajectory_count"] == 1
    assert summary["step_count"] == 2
    assert summary["positive_net_asv_steps"] == 2
    assert summary["evaluator"]["mode"] == "provided-belief"


def test_compare_projections_accepts_matching_stateless_slice() -> None:
    question = "Does microglial activation track Alzheimer's progression?"
    classify_workflow_step = step_output_to_workflow_step(
        "stateless-run-7",
        classify_step(
            StepInput(
                run_id="stateless-run-7",
                question=question,
            )
        ),
    )
    retrieve_workflow_step = step_output_to_workflow_step(
        "stateless-run-7",
        retrieve_step(
            StepInput(
                run_id="stateless-run-7",
                question=question,
                completed_steps=["classify"],
                available_artifacts=["classification:research"],
                artifact_payloads=[
                    MockRetrievalArtifact(
                        paper_id="MOCK-PMID-1001",
                        title="Microglial activation signatures track disease progression",
                        abstract="Activated microglia correlated with Braak stage.",
                    )
                ],
            )
        ),
    )
    old_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-7",
        question=question,
        steps=[classify_workflow_step, retrieve_workflow_step],
    )
    stateless_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-7",
        question=question,
        steps=[classify_workflow_step, retrieve_workflow_step],
    )

    summary = compare_projections(old_trajectory, stateless_trajectory)

    assert summary.ok is True
    assert summary.old_step_count == 2
    assert summary.stateless_step_count == 2
    assert summary.issues == []


def test_compare_projections_reports_missing_core_step() -> None:
    question = "Does microglial activation track Alzheimer's progression?"
    classify_workflow_step = step_output_to_workflow_step(
        "stateless-run-8",
        classify_step(
            StepInput(
                run_id="stateless-run-8",
                question=question,
            )
        ),
    )
    old_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-8",
        question=question,
        steps=[classify_workflow_step],
    )
    stateless_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-8",
        question=question,
        steps=[classify_workflow_step],
    )

    summary = compare_projections(old_trajectory, stateless_trajectory)

    assert summary.ok is False
    assert [issue.code for issue in summary.issues] == ["missing_core_step"]


def test_compare_projections_allows_safe_credential_env_quality_flag() -> None:
    question = "Does microglial activation track Alzheimer's progression?"
    workflow_steps = [
        step_output_to_workflow_step(
            "stateless-run-9",
            classify_step(StepInput(run_id="stateless-run-9", question=question)),
        ),
        step_output_to_workflow_step(
            "stateless-run-9",
            retrieve_step(
                StepInput(
                    run_id="stateless-run-9",
                    question=question,
                    completed_steps=["classify"],
                    available_artifacts=["classification:research"],
                    artifact_payloads=[
                        MockRetrievalArtifact(
                            paper_id="MOCK-PMID-1001",
                            title="Microglial activation signatures track disease progression",
                            abstract="Activated microglia correlated with Braak stage.",
                        )
                    ],
                )
            ),
        ),
    ]
    trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-9",
        question=question,
        steps=workflow_steps,
    )
    stateless_trajectory = replace(
        trajectory,
        steps=[
            replace(
                trajectory.steps[0],
                quality_flags={"credential_env": "DEEPSEEK_API_KEY"},
            ),
            trajectory.steps[1],
        ],
    )

    summary = compare_projections(trajectory, stateless_trajectory)

    assert summary.ok is True
    assert summary.issues == []


def test_compare_projections_reports_candidate_space_metadata_mismatch() -> None:
    question = "Does microglial activation track Alzheimer's progression?"
    workflow_steps = [
        step_output_to_workflow_step(
            "stateless-run-10",
            classify_step(StepInput(run_id="stateless-run-10", question=question)),
        ),
        step_output_to_workflow_step(
            "stateless-run-10",
            retrieve_step(
                StepInput(
                    run_id="stateless-run-10",
                    question=question,
                    completed_steps=["classify"],
                    available_artifacts=["classification:research"],
                    artifact_payloads=[
                        MockRetrievalArtifact(
                            paper_id="MOCK-PMID-1001",
                            title="Microglial activation signatures track disease progression",
                            abstract="Activated microglia correlated with Braak stage.",
                        )
                    ],
                )
            ),
        ),
    ]
    old_trajectory = trajectory_from_workflow_steps(
        run_id="stateless-run-10",
        question=question,
        steps=workflow_steps,
    )
    first_candidate = old_trajectory.task.candidate_space.candidates[0]
    changed_candidate_space = replace(
        old_trajectory.task.candidate_space,
        candidates=[
            replace(first_candidate, label="Z", text="changed prompt option"),
            *old_trajectory.task.candidate_space.candidates[1:],
        ],
        gold_candidate_id=first_candidate.id,
    )
    stateless_trajectory = replace(
        old_trajectory,
        task=replace(old_trajectory.task, candidate_space=changed_candidate_space),
    )

    summary = compare_projections(old_trajectory, stateless_trajectory)

    assert summary.ok is False
    assert [issue.code for issue in summary.issues] == [
        "candidate_space_mismatch"
    ]
