"""The rotating braille wheel only has a few letters (default A B C E I L N P).

In wheel-only mode every lesson is kept to those letters: Gemini is given this list of
everyday words the wheel can spell, and anything else is filtered out with an explanation.
"""

# Everyday things (and a few names) spelled only with a, b, c, e, i, l, n, p.
# words_for() filters this for whatever letters the wheel really has.
EVERYDAY_WORDS = """
pen pencil pin pill pipe clip cap can cane cable label panel plane pan pail pie pea bean
apple banana pecan pineapple ice lace bell ball bib bin cab cabin pebble bible lilac
nail lip cell
alice caleb elena ian ana nina bella neil abe ben lia ali
""".split()


def spellable(text, letters):
    """True if every letter in text is on the wheel (spaces ignored)."""
    return all(c in letters for c in text.lower() if not c.isspace())


def words_for(letters):
    return [w for w in EVERYDAY_WORDS if spellable(w, letters)]
