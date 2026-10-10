"""The braille coach: explains *why* an answer was wrong, like a teacher would.

Research on adult braille learners (arXiv 2512.03398) found existing tools
"only flag errors without clarifying rules". Adults also make mirror-image
errors when learning braille (d/f, e/i, h/j are mirror pairs). So instead
of "Incorrect", we gently diagnose the mistake:

    mirror   "Close! You typed F, the mirror image. Swap left and right."
    shifted  "Right shape, but one row too low."
    missing  "Almost! Also press bottom left."
    extra    "Almost! Leave out middle right."

Patterns are "101010" strings for dots 1-6 (see braille.py).
"""

from app.braille import DIGIT_PATTERNS, LETTER_PATTERNS, NUMBER_SIGN_PATTERN

ROW = {1: "top", 2: "middle", 3: "bottom", 4: "top", 5: "middle", 6: "bottom"}
COLUMN = {1: "left", 2: "left", 3: "left", 4: "right", 5: "right", 6: "right"}

LETTER_FOR_PATTERN = {p: letter for letter, p in LETTER_PATTERNS.items()}
DIGIT_FOR_PATTERN = {p: digit for digit, p in DIGIT_PATTERNS.items()}


def raised(pattern):
    """"101010" -> [1, 3, 5]"""
    return [i + 1 for i, bit in enumerate(pattern) if bit == "1"]


def from_dots(dots):
    return "".join("1" if n in dots else "0" for n in range(1, 7))


def mirror(pattern):
    """Swap left and right columns: dots 1<->4, 2<->5, 3<->6."""
    return pattern[3:] + pattern[:3]


def shift_down(pattern):
    """Move every dot one row down, or None if a dot would fall off the bottom."""
    dots = raised(pattern)
    if any(n in (3, 6) for n in dots):
        return None
    return from_dots([n + 1 for n in dots])


def spoken_dots(dots):
    """[1, 3] -> "1, top left. 3, bottom left." (button number, then where it is)"""
    return " ".join(f"{n}, {ROW[n]} {COLUMN[n]}." for n in dots)


def text_dots(dots):
    """[1, 3] -> "1 top left, 3 bottom left" """
    return ", ".join(f"{n} {ROW[n]} {COLUMN[n]}" for n in dots)


def name_pattern(pattern, digits=False):
    """What the learner actually typed, if it means something."""
    if pattern == NUMBER_SIGN_PATTERN:
        return "the number sign"
    if digits and pattern in DIGIT_FOR_PATTERN:
        return DIGIT_FOR_PATTERN[pattern]
    if pattern in LETTER_FOR_PATTERN:
        return LETTER_FOR_PATTERN[pattern].upper()
    return None


def check(target, expected, got):
    """Compare the learner's dots to the target.

    target:   how to say the target, e.g. "D", "4" or "the number sign"
    expected: target pattern, got: what was entered (both "101010" strings)
    Returns {"correct", "kind", "spoken", "text"}.
    """
    if got == expected:
        return {"correct": True, "kind": "correct", "spoken": "Good job!", "text": "Good job!"}

    digits = target.isdigit()
    typed = name_pattern(got, digits)
    want = raised(expected)
    have = raised(got)
    how = f"{target[0].upper() + target[1:]} is: {spoken_dots(want)}"

    def result(kind, spoken, text):
        return {"correct": False, "kind": kind, "spoken": spoken, "text": text}

    if not have:
        return result("empty", f"No buttons yet. Take your time. {how}",
                      f"No buttons yet. Press: {text_dots(want)}")

    if mirror(expected) == got:
        you_typed = f"You typed {typed}, the mirror image." if typed else "That's the mirror image."
        return result("mirror", f"Close! {you_typed} Swap left and right. {how}",
                      f"Mirror image{f' ({typed})' if typed else ''}: swap left and right")

    if shift_down(expected) == got or shift_down(got) == expected:
        where = "low" if shift_down(expected) == got else "high"
        return result("shifted", f"Close! Right shape, but one row too {where}. {how}",
                      f"Right shape, one row too {where}")

    missing = [n for n in want if n not in have]
    extra = [n for n in have if n not in want]
    if missing and not extra:
        return result("missing", f"Almost! Also press: {spoken_dots(missing)}",
                      f"Almost! Also press: {text_dots(missing)}")
    if extra and not missing:
        return result("extra", f"Almost! Leave out: {spoken_dots(extra)}",
                      f"Almost! Leave out: {text_dots(extra)}")

    you_typed = f" You typed {typed}." if typed else ""
    return result("wrong", f"Good try.{you_typed} {how}",
                  f"Good try{f' (that was {typed})' if typed else ''}. Press: {text_dots(want)}")


# ---- hints from braille's structure -------------------------------------------
# Braille is built in "decades": k-t are a-j plus bottom left (dot 3);
# u, v, x, y, z are a-e plus both bottom dots (3 and 6); w is j plus bottom right.

FIRST_DECADE = "abcdefghij"


def hint(char, is_number_sign=False, wheel_letters=None):
    """A short memory hook for a character, or None.
    With wheel_letters, only hooks whose base letter is on the wheel (so the learner can feel it)."""
    text = _hint(char, is_number_sign)
    if text and wheel_letters is not None and not is_number_sign:
        base = text.split()[2].lower()  # "K is A plus ..." -> "a"
        if base not in wheel_letters:
            return None
    return text


def _hint(char, is_number_sign):
    if is_number_sign:
        return "The number sign is the whole right column, plus bottom left."
    c = char.lower()
    if c in "klmnopqrst":
        base = FIRST_DECADE["klmnopqrst".index(c)]
        return f"{c.upper()} is {base.upper()} plus bottom left."
    if c in "uvxyz":
        base = "abcde"["uvxyz".index(c)]
        return f"{c.upper()} is {base.upper()} plus both bottom dots."
    if c == "w":
        return "W is J plus bottom right."
    if c in DIGIT_PATTERNS:
        letter = LETTER_FOR_PATTERN[DIGIT_PATTERNS[c]]
        return f"{c} uses the same dots as {letter.upper()}."
    return None
