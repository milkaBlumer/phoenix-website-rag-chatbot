from __future__ import annotations

from types import SimpleNamespace

from backend.evaluation.retrieval_eval import evaluate_retrieval, evaluate_sweep


def test_evaluation_measures_source_recall_and_empty_retrieval() -> None:
    cases = [
        {
            "id": "answerable-hit",
            "question": "שאלה א",
            "expected_sources": ["https://www.fnx.co.il/a"],
            "expected_answer_points": ["נקודה"],
        },
        {
            "id": "answerable-miss",
            "question": "שאלה ב",
            "expected_sources": ["https://www.fnx.co.il/b/"],
        },
        {"id": "unanswerable-empty", "question": "שאלה ג", "expected_sources": []},
        {"id": "unanswerable-hit", "question": "שאלה ד", "expected_sources": []},
    ]
    results = {
        "שאלה א": [{"url": "https://www.fnx.co.il/a/"}],
        "שאלה ב": [{"url": "https://www.fnx.co.il/a"}],
        "שאלה ג": [],
        "שאלה ד": [{"url": "https://www.fnx.co.il/a"}],
    }
    service = SimpleNamespace(retrieve=lambda question: results[question])

    report = evaluate_retrieval(cases, service)

    assert report["answerable_source_recall"] == 0.5
    assert report["unanswerable_retrieval_abstention_rate"] == 0.5
    assert report["cases"][0]["expected_source_found"] is True
    assert report["cases"][1]["expected_source_found"] is False
    assert report["cases"][2]["retrieval_abstained"] is True
    assert report["cases"][3]["retrieval_abstained"] is False


def test_evaluation_checks_answer_evidence_not_only_source_url() -> None:
    cases = [
        {
            "id": "supported",
            "question": "שאלה נתמכת",
            "expected_sources": ["https://example.com/a"],
            "expected_answer_points": ["אישור משטרה"],
        },
        {
            "id": "wrong-chunk",
            "question": "שאלה עם מקטע לא מתאים",
            "expected_sources": ["https://example.com/a"],
            "expected_answer_points": ["אישור משטרה"],
        },
    ]
    results = {
        "שאלה נתמכת": [
            {
                "url": "https://example.com/a/",
                "text": "יש לצרף אישור משטרה על הגשת התלונה.",
                "similarity": 0.91,
            }
        ],
        "שאלה עם מקטע לא מתאים": [
            {
                "url": "https://example.com/a/",
                "text": "יש לצרף תמונות ממקום האירוע.",
                "similarity": 0.88,
            }
        ],
    }

    report = evaluate_retrieval(cases, SimpleNamespace(retrieve=lambda question: results[question]))

    assert report["answerable_source_recall"] == 1.0
    assert report["answer_point_recall"] == 0.5
    assert report["cases"][0]["answer_point_coverage"] == 1.0
    assert report["cases"][1]["answer_point_coverage"] == 0.0
    assert report["cases"][1]["answer_point_details"][0]["missing_terms"] == [
        "אישור",
        "משטרה",
    ]
    assert report["cases"][0]["retrieved_evidence"][0]["text"] == results["שאלה נתמכת"][0]["text"]


def test_evaluation_applies_chat_safety_before_retrieval() -> None:
    calls: list[str] = []

    def retrieve(question: str) -> list[dict]:
        calls.append(question)
        return [{"url": "https://example.com/personal", "text": "מידע לא אישי"}]

    report = evaluate_retrieval(
        [
            {
                "id": "personal",
                "question": "מה מספר הפוליסה שלי?",
                "expected_sources": [],
            }
        ],
        SimpleNamespace(retrieve=retrieve),
    )

    assert calls == []
    assert report["unanswerable_retrieval_abstention_rate"] == 1.0
    assert report["safety_abstained_cases"] == 1
    assert report["cases"][0]["safety_category"] == "personal_information"


def test_sweep_reuses_candidates_and_compares_thresholds_and_top_k() -> None:
    cases = [
        {
            "id": "answerable",
            "question": "שאלה",
            "expected_sources": ["https://example.com/a"],
            "expected_answer_points": ["אישור משטרה"],
        },
        {"id": "unanswerable", "question": "שאלה לא ידועה", "expected_sources": []},
    ]
    calls: list[tuple[str, int]] = []
    candidates = {
        "שאלה": [
            {"url": "https://example.com/a", "similarity": 0.82, "text": "אישור משטרה"},
            {"url": "https://example.com/b", "similarity": 0.61, "text": "תמונות"},
        ],
        "שאלה לא ידועה": [
            {"url": "https://example.com/b", "similarity": 0.58, "text": "תמונות"}
        ],
    }
    service = SimpleNamespace(
        retrieve_candidates=lambda question, top_k: (
            calls.append((question, top_k)) or candidates[question]
        )
    )

    report = evaluate_sweep(cases, service, top_k_values=(1, 2), thresholds=(0.6, 0.8))

    assert report["candidate_searches"] == 2
    assert calls == [("שאלה", 2), ("שאלה לא ידועה", 2)]
    assert len(report["configurations"]) == 4
    strict = next(
        item
        for item in report["configurations"]
        if item["threshold"] == 0.8 and item["top_k"] == 1
    )
    assert strict["answerable_source_recall"] == 1.0
    assert strict["answerable_mrr"] == 1.0
    assert strict["answer_point_recall"] == 1.0
    assert strict["unanswerable_abstention_rate"] == 1.0


def test_sweep_does_not_count_expected_source_with_irrelevant_text_as_evidence() -> None:
    cases = [
        {
            "id": "answerable",
            "question": "שאלה",
            "expected_sources": ["https://example.com/a"],
            "expected_answer_points": ["אישור משטרה"],
        }
    ]
    service = SimpleNamespace(
        retrieve_candidates=lambda _question, top_k: [
            {
                "url": "https://example.com/a",
                "similarity": 0.9,
                "text": "תמונות ממקום האירוע",
            }
        ]
    )

    report = evaluate_sweep(cases, service, top_k_values=(1,), thresholds=(0.8,))

    assert report["recommended"]["answerable_source_recall"] == 1.0
    assert report["recommended"]["answer_point_recall"] == 0.0


def test_sweep_skips_retrieval_for_safety_abstentions() -> None:
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Safety-abstained questions must not be embedded or retrieved")

    report = evaluate_sweep(
        [{"id": "personal", "question": "מה מספר הפוליסה שלי?", "expected_sources": []}],
        SimpleNamespace(retrieve_candidates=unexpected),
        top_k_values=(3,),
        thresholds=(0.7,),
    )

    assert report["candidate_searches"] == 0
    assert report["safety_abstained_cases"] == 1
    assert report["recommended"]["unanswerable_abstention_rate"] == 1.0


def test_sweep_ties_prefer_stricter_threshold_and_smaller_top_k() -> None:
    service = SimpleNamespace(
        retrieve_candidates=lambda _question, top_k: [
            {"url": "https://example.com/a", "similarity": 0.9, "text": "אישור"}
        ]
    )

    report = evaluate_sweep(
        [{"id": "answerable", "question": "שאלה", "expected_sources": ["https://example.com/a"]}],
        service,
        top_k_values=(1, 2),
        thresholds=(0.6, 0.8),
    )

    assert report["recommended"]["threshold"] == 0.8
    assert report["recommended"]["top_k"] == 1
