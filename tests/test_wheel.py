from fastapi.testclient import TestClient

import app.main as m


def steps_for(text):
    with TestClient(m.app) as client:
        return client.post("/api/steps", json={"text": text}).json()["steps"]


def test_letters_on_the_wheel():
    m.WHEEL_PATTERNS = {m.pattern_for(c) for c in "abceilnp"}
    assert [s["on_wheel"] for s in steps_for("pen")] == [True, True, True]
    assert [s["on_wheel"] for s in steps_for("cup")] == [True, False, True]


def test_digits_use_their_letter_slot():
    m.WHEEL_PATTERNS = {m.pattern_for(c) for c in "abceilnp"}
    steps = steps_for("15")
    assert [s["char"] for s in steps] == ["#", "1", "5"]
    assert [s["on_wheel"] for s in steps] == [False, True, True]  # 1 = a, 5 = e; the number sign isn't on it


def test_prompt_lists_wheel_letters():
    from app.vision import build_prompt
    assert "a, b, c, e, i, l, n, p" in build_prompt("abceilnp")


def test_hints_only_use_letters_on_the_wheel():
    from app.coach import hint
    wheel = "abceilnp"
    assert hint("l", wheel_letters=wheel) == "L is B plus bottom left."  # B is on the wheel
    assert hint("p", wheel_letters=wheel) is None                       # F isn't
    assert hint("p") == "P is F plus bottom left."                      # no wheel: always


def test_word_list_is_spellable():
    from app.wheel import EVERYDAY_WORDS, spellable, words_for
    assert all(spellable(w, "abceilnp") for w in EVERYDAY_WORDS)
    assert "pen" in words_for("abceilnp") and "pen" not in words_for("abc")
