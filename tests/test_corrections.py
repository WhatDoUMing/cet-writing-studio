from ai.corrections import apply_report_corrections


def test_apply_report_corrections_replaces_grammar_and_upgrade() -> None:
    original = (
        "I like this activty. It was very good. "
        "Another sentence stays unchanged."
    )
    report = {
        "grammar_errors": [
            {
                "sentence": "I like this activty.",
                "correct": "I like this activity.",
            }
        ],
        "sentence_upgrade": [
            {
                "original": "It was very good.",
                "rewrite": "It was truly remarkable.",
            }
        ],
    }

    result = apply_report_corrections(original, report)

    assert result.text == (
        "I like this activity. It was truly remarkable. "
        "Another sentence stays unchanged."
    )
    assert result.applied == 2
    assert result.skipped == []


def test_apply_report_corrections_skips_unmatched_source() -> None:
    result = apply_report_corrections(
        "The original essay.",
        {
            "grammar_errors": [
                {
                    "sentence": "This sentence is absent.",
                    "correct": "Replacement.",
                }
            ]
        },
    )

    assert result.text == "The original essay."
    assert result.applied == 0
    assert result.skipped == ["This sentence is absent."]
