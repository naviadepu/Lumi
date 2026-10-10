from app.braille import pattern_for, NUMBER_SIGN_PATTERN
from app.coach import check, hint, mirror


def test_correct():
    assert check("D", pattern_for("d"), pattern_for("d"))["correct"] is True


def test_mirror_pairs_are_real_letters():
    assert mirror(pattern_for("d")) == pattern_for("f")
    assert mirror(pattern_for("e")) == pattern_for("i")
    assert mirror(pattern_for("h")) == pattern_for("j")


def test_mirror_error_names_the_letter_typed():
    r = check("D", pattern_for("d"), pattern_for("f"))
    assert r["kind"] == "mirror"
    assert r["spoken"].startswith("Close! You typed F, the mirror image. Swap left and right.")
    assert "D is: 1, top left. 4, top right. 5, middle right." in r["spoken"]


def test_one_row_too_low():
    r = check("A", "100000", "010000")
    assert r["kind"] == "shifted" and "too low" in r["spoken"]


def test_one_row_too_high():
    r = check("the comma", "010000", "100000")  # comma is dot 2; typed dot 1
    assert r["kind"] == "shifted" and "too high" in r["spoken"]


def test_nothing_pressed():
    assert check("A", "100000", "000000")["kind"] == "empty"


def test_missing_dot():
    r = check("B", pattern_for("b"), pattern_for("a"))
    assert r["kind"] == "missing"
    assert r["spoken"] == "Almost! Also press: 2, middle left."


def test_extra_dot():
    r = check("A", pattern_for("a"), pattern_for("b"))
    assert r["kind"] == "extra"
    assert r["text"] == "Almost! Leave out: 2 middle left"


def test_wrong_names_what_was_typed():
    r = check("C", pattern_for("c"), pattern_for("e"))  # c=1,4  e=1,5: mixed missing/extra
    assert r["kind"] == "wrong"
    assert r["spoken"] == "Incorrect. You typed E. C is: 1, top left. 4, top right."


def test_digits_named_as_digits():
    r = check("4", pattern_for("4"), pattern_for("6"))  # d vs f: mirror
    assert "You typed 6" in r["spoken"]


def test_number_sign_target():
    r = check("the number sign", NUMBER_SIGN_PATTERN, "000000")
    assert "The number sign is:" in r["spoken"]


def test_spoken_feedback_fits_speak_limit():
    letters = "abcdefghijklmnopqrstuvwxyz"
    for t in letters:
        for g in letters:
            assert len(check(t.upper(), pattern_for(t), pattern_for(g))["spoken"]) <= 200


def test_hints_follow_braille_decades():
    assert hint("k") == "K is A plus bottom left."
    assert hint("t") == "T is J plus bottom left."
    assert hint("u") == "U is A plus both bottom dots."
    assert hint("w") == "W is J plus bottom right."
    assert hint("4") == "4 uses the same dots as D."
    assert hint("a") is None
    assert "right column" in hint("#", is_number_sign=True)


def test_hints_are_true():
    # "plus bottom left" really adds dot 3, "both bottom dots" adds 3 and 6
    for c, base in zip("klmnopqrst", "abcdefghij"):
        assert int(pattern_for(c), 2) == int(pattern_for(base), 2) | int("001000", 2)
    for c, base in zip("uvxyz", "abcde"):
        assert int(pattern_for(c), 2) == int(pattern_for(base), 2) | int("001001", 2)
