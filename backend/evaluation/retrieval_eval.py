"""Measure whether expected source pages appear in retrieval results."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from backend.services.retrieval_service import RetrievalService
from backend.services.safety_policy import assess_question

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "data" / "eval" / "questions.json"
DEFAULT_OUTPUT = ROOT / "data" / "eval" / "retrieval_results.json"
DEFAULT_TOP_K_VALUES = (3, 5, 10)
DEFAULT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
ANSWER_POINT_STOP_WORDS = {
    "את",
    "או",
    "אם",
    "אל",
    "אילו",
    "אלא",
    "אחרי",
    "ב",
    "בין",
    "בו",
    "בה",
    "וה",
    "ול",
    "ומ",
    "וכן",
    "וגם",
    "וכל",
    "של",
    "שלו",
    "שלה",
    "שלהם",
    "שלהן",
    "לה",
    "לו",
    "להם",
    "להן",
    "מ",
    "מה",
    "על",
    "עם",
    "ל",
    "כ",
}
HEBREW_PREFIXES = "בהוכולמש"


def _normalize_url(url: str) -> str:
    """Normalize trailing slashes so redirected page URLs match sitemap URLs."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def _answer_point_terms(point: str) -> list[str]:
    """Extract meaningful terms while keeping negations, numbers, and identifiers."""
    return [
        term
        for term in re.findall(r"[\w@.+*-]+", point.casefold(), flags=re.UNICODE)
        if term not in ANSWER_POINT_STOP_WORDS
    ]


def _term_matches(term: str, retrieved_terms: set[str]) -> bool:
    """Match a term with or without one common Hebrew prefix."""
    if term in retrieved_terms:
        return True
    return len(term) > 4 and term[0] in HEBREW_PREFIXES and term[1:] in retrieved_terms


def _answer_point_report(
    expected_points: list[str],
    evidence_text: str,
) -> tuple[float, int, int, list[dict[str, Any]]]:
    """Measure expected-answer term coverage in excerpts from the expected source."""
    retrieved_terms = set(re.findall(r"[\w@.+*-]+", evidence_text.casefold(), flags=re.UNICODE))
    point_details: list[dict[str, Any]] = []
    matched_total = 0
    expected_total = 0
    for point in expected_points:
        terms = _answer_point_terms(point)
        matched = [term for term in terms if _term_matches(term, retrieved_terms)]
        missing = [term for term in terms if not _term_matches(term, retrieved_terms)]
        matched_total += len(matched)
        expected_total += len(terms)
        point_details.append(
            {
                "point": point,
                "coverage": len(matched) / len(terms) if terms else 0.0,
                "matched_terms": matched,
                "missing_terms": missing,
            }
        )
    return (
        matched_total / expected_total if expected_total else 0.0,
        matched_total,
        expected_total,
        point_details,
    )


def _case_answer_point_report(
    case: dict[str, Any],
    retrieved: list[dict[str, Any]],
) -> tuple[float, int, int, list[dict[str, Any]]]:
    expected_urls = {_normalize_url(url) for url in case.get("expected_sources", [])}
    evidence = [
        item
        for item in retrieved
        if isinstance(item, dict)
        and isinstance(item.get("url"), str)
        and _normalize_url(item["url"]) in expected_urls
    ]
    evidence_text = "\n".join(
        item["text"] for item in evidence if isinstance(item.get("text"), str)
    )
    return _answer_point_report(case.get("expected_answer_points", []), evidence_text)


def evaluate_retrieval(
    cases: list[dict[str, Any]],
    retrieval_service: Any,
) -> dict[str, Any]:
    """Run retrieval cases and report expected-source recall and unanswerable abstention."""
    results: list[dict[str, Any]] = []
    answerable_total = 0
    answerable_hits = 0
    answer_point_matched = 0
    answer_point_total = 0
    unanswerable_total = 0
    unanswerable_empty = 0
    safety_abstained_total = 0

    for case in cases:
        question = case["question"]
        expected_urls = {_normalize_url(url) for url in case.get("expected_sources", [])}
        safety_decision = assess_question(question)
        retrieved = [] if safety_decision else retrieval_service.retrieve(question)
        safety_abstained_total += int(safety_decision is not None)
        retrieved_urls = {
            _normalize_url(item["url"])
            for item in retrieved
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        }
        is_answerable = bool(expected_urls)
        point_coverage, matched_terms, expected_terms, point_details = _case_answer_point_report(
            case, retrieved
        )
        answer_point_matched += matched_terms
        answer_point_total += expected_terms
        if is_answerable:
            answerable_total += 1
            hit = bool(expected_urls & retrieved_urls)
            answerable_hits += int(hit)
        else:
            unanswerable_total += 1
            hit = not retrieved
            unanswerable_empty += int(hit)

        results.append(
            {
                "id": case["id"],
                "question": question,
                "answerable": is_answerable,
                "expected_sources": sorted(expected_urls),
                "retrieved_sources": sorted(url for url in retrieved_urls if isinstance(url, str)),
                "expected_source_found": hit if is_answerable else None,
                "retrieval_abstained": hit if not is_answerable else None,
                "safety_abstained": safety_decision is not None,
                "safety_category": safety_decision.category if safety_decision else None,
                "expected_answer_points": case.get("expected_answer_points", []),
                "answer_point_coverage": point_coverage if is_answerable else None,
                "answer_point_details": point_details if is_answerable else [],
                "retrieved_evidence": [
                    {
                        "url": item["url"],
                        "similarity": item.get("similarity"),
                        "text": item["text"][:600],
                    }
                    for item in retrieved
                    if isinstance(item, dict)
                    and isinstance(item.get("url"), str)
                    and isinstance(item.get("text"), str)
                ],
            }
        )

    return {
        "answerable_cases": answerable_total,
        "answerable_source_recall": answerable_hits / answerable_total if answerable_total else 0.0,
        "answer_point_terms_matched": answer_point_matched,
        "answer_point_terms_total": answer_point_total,
        "answer_point_recall": (
            answer_point_matched / answer_point_total if answer_point_total else 0.0
        ),
        "unanswerable_cases": unanswerable_total,
        "safety_abstained_cases": safety_abstained_total,
        "unanswerable_retrieval_abstention_rate": (
            unanswerable_empty / unanswerable_total if unanswerable_total else 0.0
        ),
        "cases": results,
    }


def evaluate_sweep(
    cases: list[dict[str, Any]],
    retrieval_service: Any,
    *,
    top_k_values: tuple[int, ...] = DEFAULT_TOP_K_VALUES,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Compare threshold/top-k settings using one candidate search per question."""
    if not top_k_values or any(value < 1 for value in top_k_values):
        raise ValueError("Top-k values must be positive integers.")
    if not thresholds or any(not 0 <= value <= 1 for value in thresholds):
        raise ValueError("Thresholds must be between 0 and 1.")

    max_top_k = max(top_k_values)
    cached = []
    candidate_searches = 0
    safety_abstained_total = 0
    for case in cases:
        safety_decision = assess_question(case["question"])
        if safety_decision:
            safety_abstained_total += 1
            cached.append((case, [], safety_decision))
        else:
            cached.append(
                (
                    case,
                    retrieval_service.retrieve_candidates(case["question"], top_k=max_top_k),
                    None,
                )
            )
            candidate_searches += 1
    configurations: list[dict[str, Any]] = []
    for threshold in thresholds:
        for top_k in top_k_values:
            answerable_total = 0
            answerable_hits = 0
            reciprocal_ranks: list[float] = []
            answer_point_matched = 0
            answer_point_total = 0
            unanswerable_total = 0
            unanswerable_false_positives = 0
            for case, candidates, _safety_decision in cached:
                expected_urls = {
                    _normalize_url(url) for url in case.get("expected_sources", [])
                }
                selected = [
                    candidate
                    for candidate in candidates
                    if candidate["similarity"] >= threshold
                ][:top_k]
                selected_urls = [_normalize_url(candidate["url"]) for candidate in selected]
                if expected_urls:
                    answerable_total += 1
                    ranks = [
                        index
                        for index, url in enumerate(selected_urls, start=1)
                        if url in expected_urls
                    ]
                    answerable_hits += int(bool(ranks))
                    reciprocal_ranks.append(1 / min(ranks) if ranks else 0.0)
                    _, matched_terms, expected_terms, _ = _case_answer_point_report(
                        case,
                        [
                            candidate
                            for candidate in selected
                            if isinstance(candidate.get("url"), str)
                            and _normalize_url(candidate["url"]) in expected_urls
                        ],
                    )
                    answer_point_matched += matched_terms
                    answer_point_total += expected_terms
                else:
                    unanswerable_total += 1
                    unanswerable_false_positives += int(bool(selected))

            recall = answerable_hits / answerable_total if answerable_total else 0.0
            answer_point_recall = (
                answer_point_matched / answer_point_total if answer_point_total else 0.0
            )
            false_positive_rate = (
                unanswerable_false_positives / unanswerable_total if unanswerable_total else 0.0
            )
            abstention_rate = 1 - false_positive_rate
            configurations.append(
                {
                    "top_k": top_k,
                    "threshold": threshold,
                    "answerable_source_recall": recall,
                    "answer_point_recall": answer_point_recall,
                    "answer_point_terms_matched": answer_point_matched,
                    "answer_point_terms_total": answer_point_total,
                    "answerable_mrr": (
                        sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
                    ),
                    "unanswerable_false_positive_rate": false_positive_rate,
                    "unanswerable_abstention_rate": abstention_rate,
                    "balanced_score": (recall + answer_point_recall + abstention_rate) / 3,
                }
            )

    configurations.sort(
        key=lambda item: (
            item["balanced_score"],
            item["answerable_source_recall"],
            item["unanswerable_abstention_rate"],
            item["threshold"],
            -item["top_k"],
        ),
        reverse=True,
    )
    return {
        "questions": len(cases),
        "candidate_searches": candidate_searches,
        "safety_abstained_cases": safety_abstained_total,
        "recommended": configurations[0],
        "configurations": configurations,
    }


def main() -> int:
    """Run retrieval evaluation against the configured index and save reviewable results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Evaluation cases JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Detailed result JSON path")
    parser.add_argument("--sweep", action="store_true", help="Compare threshold and top-k settings")
    parser.add_argument(
        "--top-k-values",
        default=",".join(map(str, DEFAULT_TOP_K_VALUES)),
        help="Comma-separated retrieval counts for --sweep",
    )
    parser.add_argument(
        "--thresholds",
        default=",".join(map(str, DEFAULT_THRESHOLDS)),
        help="Comma-separated similarity thresholds for --sweep",
    )
    args = parser.parse_args()

    try:
        cases = json.loads(args.dataset.read_text(encoding="utf-8"))
        if isinstance(cases, dict):
            cases = cases.get("cases")
        if not isinstance(cases, list) or not all(isinstance(case, dict) for case in cases):
            raise ValueError("Evaluation dataset must be a JSON array of objects.")
        service = RetrievalService()
        if args.sweep:
            top_k_values = tuple(int(value) for value in args.top_k_values.split(","))
            thresholds = tuple(float(value) for value in args.thresholds.split(","))
            report = evaluate_sweep(
                cases,
                service,
                top_k_values=top_k_values,
                thresholds=thresholds,
            )
        else:
            report = evaluate_retrieval(cases, service)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Retrieval evaluation failed: {exc}", file=sys.stderr)
        return 1

    if args.sweep:
        best = report["recommended"]
        print(
            f"Best candidate: TOP_K={best['top_k']}, threshold={best['threshold']:.2f}; "
            f"source recall={best['answerable_source_recall']:.1%}, "
            f"unanswerable false positives={best['unanswerable_false_positive_rate']:.1%}"
        )
    else:
        print(
            f"Source recall: {report['answerable_source_recall']:.1%} "
            f"({report['answerable_cases']} answerable); "
            f"abstention retrieval rate: {report['unanswerable_retrieval_abstention_rate']:.1%} "
            f"({report['unanswerable_cases']} unanswerable)"
        )
    print(f"Detailed results: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
