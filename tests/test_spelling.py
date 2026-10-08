from gui.text_hints import SpellingHintService


def test_only_obvious_spelling_errors_are_auto_fixed() -> None:
    service = SpellingHintService()
    text = "This activty has great walue. onigi nal enablesenables."

    corrected, fixed = service.apply_safe_corrections(text)

    assert corrected == (
        "This activity has great value. onigi nal enables."
    )
    assert {hint.original for hint in fixed} == {
        "activty",
        "walue",
        "enablesenables",
    }
