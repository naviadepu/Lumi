"""Braille lookup table and text -> reading steps.

A braille cell has 6 dots:

    1 o o 4
    2 o o 5
    3 o o 6

Patterns are 6-character strings for dots 1..6, "1" = raised, "0" = flat.
Example: "a" is dot 1 only -> "100000".
"""

# Dots that are raised for each letter (standard English braille, grade 1).
LETTER_DOTS = {
    "a": [1], "b": [1, 2], "c": [1, 4], "d": [1, 4, 5], "e": [1, 5],
    "f": [1, 2, 4], "g": [1, 2, 4, 5], "h": [1, 2, 5], "i": [2, 4], "j": [2, 4, 5],
    "k": [1, 3], "l": [1, 2, 3], "m": [1, 3, 4], "n": [1, 3, 4, 5], "o": [1, 3, 5],
    "p": [1, 2, 3, 4], "q": [1, 2, 3, 4, 5], "r": [1, 2, 3, 5], "s": [2, 3, 4],
    "t": [2, 3, 4, 5], "u": [1, 3, 6], "v": [1, 2, 3, 6], "w": [2, 4, 5, 6],
    "x": [1, 3, 4, 6], "y": [1, 3, 4, 5, 6], "z": [1, 3, 5, 6],
}

# Digits reuse letters a-j: 1=a, 2=b, ... 9=i, 0=j.
DIGIT_TO_LETTER = {
    "1": "a", "2": "b", "3": "c", "4": "d", "5": "e",
    "6": "f", "7": "g", "8": "h", "9": "i", "0": "j",
}

NUMBER_SIGN_DOTS = [3, 4, 5, 6]
NUMBER_SIGN_CHAR = "#"
EMPTY_PATTERN = "000000"

# How punctuation and symbols are spoken. Anything not listed is spoken as-is.
SYMBOL_NAMES = {
    ".": "period", ",": "comma", "?": "question mark", "!": "exclamation mark",
    "'": "apostrophe", '"': "quote", ":": "colon", ";": "semicolon",
    "-": "dash", "(": "open parenthesis", ")": "close parenthesis",
    "/": "slash", "&": "ampersand", "@": "at sign", "#": "hash",
    "$": "dollar sign", "%": "percent", "+": "plus", "=": "equals",
    "*": "asterisk", "_": "underscore",
}


def dots_to_pattern(dots):
    """[1, 4] -> "100100"."""
    return "".join("1" if n in dots else "0" for n in range(1, 7))


LETTER_PATTERNS = {letter: dots_to_pattern(d) for letter, d in LETTER_DOTS.items()}
DIGIT_PATTERNS = {digit: LETTER_PATTERNS[letter] for digit, letter in DIGIT_TO_LETTER.items()}
NUMBER_SIGN_PATTERN = dots_to_pattern(NUMBER_SIGN_DOTS)


def pattern_for(char):
    """Braille pattern for a single character (no number sign). Unknown -> empty."""
    lower = char.lower()
    if lower in LETTER_PATTERNS:
        return LETTER_PATTERNS[lower]
    if char in DIGIT_PATTERNS:
        return DIGIT_PATTERNS[char]
    return EMPTY_PATTERN


def spoken_form(char, letter_prefix="Letter", number_prefix="Number"):
    """What we send to text-to-speech, e.g. "Letter A" or "Number 5".

    A bare "A" is often read as the word "a", so letters and digits get a prefix.
    An empty prefix means "just say the character".
    """
    if char.lower() in LETTER_PATTERNS:
        return f"{letter_prefix} {char.upper()}".strip()
    if char in DIGIT_PATTERNS:
        return f"{number_prefix} {char}".strip()
    return SYMBOL_NAMES.get(char, char)


def text_to_steps(text, letter_prefix="Letter", number_prefix="Number"):
    """Turn text into the list of cells shown one at a time.

    - Whitespace is skipped; the next step gets space_before=True so the
      page can announce "space" between words.
    - A run of digits starts with the number sign (dots 3-4-5-6), as in real
      braille: "12" -> [number sign, 1, 2]. The sign is repeated after any
      non-digit, e.g. "a1 2" -> [a, number sign, 1, number sign, 2].
    """
    steps = []
    pending_space = False
    in_number = False

    for char in text:
        if char.isspace():
            pending_space = bool(steps)  # ignore leading whitespace
            in_number = False
            continue

        is_digit = char in DIGIT_PATTERNS
        if is_digit and not in_number:
            steps.append({
                "char": NUMBER_SIGN_CHAR,
                "spoken": "Number sign",
                "pattern": NUMBER_SIGN_PATTERN,
                "is_number_sign": True,
                "space_before": pending_space,
            })
            pending_space = False
        in_number = is_digit

        steps.append({
            "char": char,
            "spoken": spoken_form(char, letter_prefix, number_prefix),
            "pattern": pattern_for(char),
            "is_number_sign": False,
            "space_before": pending_space,
        })
        pending_space = False

    return steps
