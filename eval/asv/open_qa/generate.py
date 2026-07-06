from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent.provider import LLMProvider
from asv_eval.adapters import open_qa_candidate_spec_to_trajectory

OPEN_QA_CATEGORIES = {
    "intervention",
    "risk",
    "mechanism",
    "diagnostic",
    "insufficient_evidence",
}
NONE_OF_THE_ABOVE_ID = "none-of-the-above"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


@dataclass(frozen=True)
class OpenQAQuestion:
    question_id: str
    category: str
    question: str
    source: str = "pubmed"
    max_papers: int = 5

    @classmethod
    def from_json(
        cls,
        payload: dict[str, Any],
        *,
        path: Path,
        line_no: int,
    ) -> "OpenQAQuestion":
        question_id = str(payload.get("question_id") or "").strip()
        if not question_id:
            raise ValueError(f"{path}:{line_no}: question_id is required")
        category = str(payload.get("category") or "").strip()
        if category not in OPEN_QA_CATEGORIES:
            raise ValueError(f"{path}:{line_no}: invalid category: {category}")
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValueError(f"{path}:{line_no}: question is required")
        source = str(payload.get("source") or "pubmed").strip()
        if source != "pubmed":
            raise ValueError(f"{path}:{line_no}: source must be pubmed")
        max_papers = int(payload.get("max_papers", 5))
        if max_papers < 1:
            raise ValueError(f"{path}:{line_no}: max_papers must be positive")
        return cls(
            question_id=question_id,
            category=category,
            question=question,
            source="pubmed",
            max_papers=max_papers,
        )


def load_open_qa_questions(path: Path) -> list[OpenQAQuestion]:
    questions: list[OpenQAQuestion] = []
    seen_ids: set[str] = set()
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: question row must be an object")
        question = OpenQAQuestion.from_json(payload, path=path, line_no=line_no)
        if question.question_id in seen_ids:
            raise ValueError(f"{path}:{line_no}: duplicate question_id")
        seen_ids.add(question.question_id)
        questions.append(question)
    return questions


def build_generation_prompt(question: OpenQAQuestion) -> str:
    payload = {
        "trajectory_id": question.question_id,
        "question": question.question,
        "category": question.category,
        "candidate_answers": [
            {"id": "answer-a", "text": "<candidate answer>"},
            {"id": "answer-b", "text": "<candidate answer>"},
            {"id": "answer-c", "text": "<candidate answer>"},
            {
                "id": NONE_OF_THE_ABOVE_ID,
                "text": "Evidence is insufficient to support any candidate.",
            },
        ],
        "gold_candidate_id": "<best candidate id after reviewing PubMed evidence>",
    }
    return (
        "You are preparing reviewed candidate answers for an Agent Step Value "
        "open QA evaluation. Generate four candidate answers for the biomedical "
        "question below. Exactly one candidate must have id "
        f"{NONE_OF_THE_ABOVE_ID}. The other three candidates should be plausible, "
        "mutually distinct biomedical answers. Include a recommended "
        "gold_candidate_id only when the retrieved PubMed evidence would support "
        "that candidate; use none-of-the-above when evidence is insufficient. "
        "Do not include hidden answer keys in state fields. Return only JSON using "
        "this schema:\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n\n"
        f"Question category: {question.category}\n"
        f"Question: {question.question}\n"
    )


async def generate_candidate_specs(
    questions: list[OpenQAQuestion],
    *,
    provider: LLMProvider,
    model: str,
    max_concurrency: int = 1,
) -> list[dict[str, Any]]:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    if max_concurrency == 1:
        rows: list[dict[str, Any]] = []
        for question in questions:
            rows.append(
                await _generate_candidate_spec(
                    question,
                    provider=provider,
                    model=model,
                )
            )
        return rows
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_one(question: OpenQAQuestion) -> dict[str, Any]:
        async with semaphore:
            return await _generate_candidate_spec(
                question,
                provider=provider,
                model=model,
            )

    return list(await asyncio.gather(*(run_one(question) for question in questions)))


async def append_generated_candidate_specs(
    questions: list[OpenQAQuestion],
    *,
    provider: LLMProvider,
    model: str,
    output: Path,
    max_concurrency: int = 1,
) -> int:
    written = 0
    batch_size = max(1, max_concurrency)
    for offset in range(0, len(questions), batch_size):
        batch = questions[offset : offset + batch_size]
        rows = await generate_candidate_specs(
            batch,
            provider=provider,
            model=model,
            max_concurrency=max_concurrency,
        )
        append_candidate_specs(output, rows)
        written += len(rows)
        print(
            f"candidate_spec_progress={written}/{len(questions)} output={output}",
            flush=True,
        )
    return written


async def _generate_candidate_spec(
    question: OpenQAQuestion,
    *,
    provider: LLMProvider,
    model: str,
) -> dict[str, Any]:
    response = await provider.chat(
        [{"role": "user", "content": build_generation_prompt(question)}],
        [],
        model=model,
        max_tokens=1200,
        tool_choice="none",
        disable_thinking=True,
    )
    payload = _parse_json_object(response.content or "")
    return _validated_spec(payload, question)


def build_template_specs(questions: list[OpenQAQuestion]) -> list[dict[str, Any]]:
    return [
        _validated_spec(_template_spec(question), question) for question in questions
    ]


def write_candidate_specs(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def append_candidate_specs(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def load_existing_candidate_spec_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: candidate row must be an object")
        trajectory_id = str(payload.get("trajectory_id") or "").strip()
        if trajectory_id:
            seen.add(trajectory_id)
    return seen


def _template_spec(question: OpenQAQuestion) -> dict[str, Any]:
    return {
        "trajectory_id": question.question_id,
        "task_id": question.question_id,
        "question": question.question,
        "task_type": "open_qa_candidate_set",
        "domain": "biomedicine",
        "metadata": {
            "category": question.category,
            "source": question.source,
            "max_papers": question.max_papers,
            "requires_human_review": True,
        },
        "candidate_answers": [
            {"id": "answer-a", "text": "Candidate answer A pending review."},
            {"id": "answer-b", "text": "Candidate answer B pending review."},
            {"id": "answer-c", "text": "Candidate answer C pending review."},
            {
                "id": NONE_OF_THE_ABOVE_ID,
                "text": "Evidence is insufficient to support any candidate.",
            },
        ],
        "gold_candidate_id": NONE_OF_THE_ABOVE_ID,
    }


def _validated_spec(
    payload: dict[str, Any],
    question: OpenQAQuestion,
) -> dict[str, Any]:
    row = {
        **payload,
        "trajectory_id": str(payload.get("trajectory_id") or question.question_id),
        "task_id": str(payload.get("task_id") or question.question_id),
        "question": str(payload.get("question") or question.question),
        "task_type": "open_qa_candidate_set",
        "domain": str(payload.get("domain") or "biomedicine"),
        "metadata": {
            **dict(payload.get("metadata") or {}),
            "category": question.category,
            "source": question.source,
            "max_papers": question.max_papers,
        },
    }
    open_qa_candidate_spec_to_trajectory(row)
    return row


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("candidate generation response must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate open QA candidate answer specs."
    )
    parser.add_argument("--questions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", choices=["deepseek"])
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--base-url")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    questions = load_open_qa_questions(Path(args.questions))
    output = Path(args.output)
    append = bool(args.append or args.resume)
    existing_ids = load_existing_candidate_spec_ids(output) if args.resume else set()
    pending_questions = [
        question for question in questions if question.question_id not in existing_ids
    ]
    if args.provider:
        api_key = os.getenv(str(args.api_key_env or ""))
        if not api_key:
            parser.error(f"{args.api_key_env} is required for --provider")
        provider = LLMProvider(
            api_key=api_key,
            base_url=args.base_url or DEEPSEEK_BASE_URL,
            provider_name=args.provider,
            force_disable_thinking=True,
        )
        if append:
            written_count = asyncio.run(
                append_generated_candidate_specs(
                    pending_questions,
                    provider=provider,
                    model=str(args.model),
                    output=output,
                    max_concurrency=int(args.max_concurrency),
                )
            )
            print(
                "candidate_spec_count="
                f"{written_count} skipped={len(existing_ids)} output={args.output}"
            )
            return 0
        rows = asyncio.run(
            generate_candidate_specs(
                pending_questions,
                provider=provider,
                model=str(args.model),
                max_concurrency=int(args.max_concurrency),
            )
        )
    else:
        rows = build_template_specs(pending_questions)
    if append:
        append_candidate_specs(output, rows)
    else:
        write_candidate_specs(output, rows)
    print(
        f"candidate_spec_count={len(rows)} skipped={len(existing_ids)} output={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
