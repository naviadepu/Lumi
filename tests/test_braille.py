from app.braille import (
    NUMBER_SIGN_PATTERN,
    dots_to_pattern,
    pattern_for,
    spoken_form,
    text_to_steps,
)


def chars(steps):
    return [s["char"] for s in steps]


def test_dots_to_pattern():
    assert dots_to_pattern([1]) == "100000"
    assert dots_to_pattern([1, 4]) == "100100"
    assert dots_to_pattern([]) == "000000"


def test_some_letters():
    assert pattern_for("a") == "100000"
    assert pattern_for("c") == "100100"
    assert pattern_for("k") == "101000"   # dots 1, 3
    assert pattern_for("w") == "010111"   # dots 2, 4, 5, 6
    assert pattern_for("z") == "101011"   # dots 1, 3, 5, 6


def test_uppercase_uses_same_pattern():
    assert pattern_for("Q") == pattern_for("q")


def test_all_letters_unique():
    patterns = [pattern_for(c) for c in "abcdefghijklmnopqrstuvwxyz"]
    assert len(set(patterns)) == 26


def test_number_sign_is_dots_3456():
    assert NUMBER_SIGN_PATTERN == "001111"


def test_digits_match_letters_a_to_j():
    for digit, letter in zip("1234567890", "abcdefghij"):
        assert pattern_for(digit) == pattern_for(letter)


def test_unknown_character_is_empty():
    assert pattern_for("!") == "000000"
    assert pattern_for("é") == "000000"


def test_digit_gets_number_sign_first():
    steps = text_to_steps("5")
    assert chars(steps) == ["#", "5"]
    assert steps[0]["pattern"] == "001111"
    assert steps[0]["is_number_sign"] is True
    assert steps[1]["pattern"] == "100010"  # same as "e"


def test_number_sign_once_per_run_of_digits():
    assert chars(text_to_steps("123")) == ["#", "1", "2", "3"]


def test_number_sign_repeats_after_letters_or_spaces():
    assert chars(text_to_steps("a1b2")) == ["a", "#", "1", "b", "#", "2"]
    assert chars(text_to_steps("1 2")) == ["#", "1", "#", "2"]


def test_spaces_are_skipped_and_flagged():
    steps = text_to_steps("hi  you")
    assert chars(steps) == ["h", "i", "y", "o", "u"]
    assert [s["space_before"] for s in steps] == [False, False, True, False, False]


def test_space_flag_goes_on_number_sign():
    steps = text_to_steps("go 7")
    assert chars(steps) == ["g", "o", "#", "7"]
    assert steps[2]["space_before"] is True
    assert steps[3]["space_before"] is False


def test_leading_and_trailing_whitespace_ignored():
    steps = text_to_steps("  ab \n")
    assert chars(steps) == ["a", "b"]
    assert steps[0]["space_before"] is False


def test_spoken_forms():
    assert spoken_form("a") == "Letter A"
    assert spoken_form("7") == "Number 7"
    assert spoken_form("?") == "question mark"
    assert spoken_form("a", letter_prefix="") == "A"
    assert spoken_form("a", letter_prefix="Capital") == "Capital A"
