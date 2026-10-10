from app.arduino import parse_line


def test_buttons():
    assert parse_line("BTN NEXT") == {"type": "button", "action": "next"}
    assert parse_line("BTN PREV") == {"type": "button", "action": "prev"}
    assert parse_line("BTN REPEAT") == {"type": "button", "action": "repeat"}
    assert parse_line("BTN ENTER") == {"type": "button", "action": "enter"}


def test_dots():
    assert parse_line("DOT 1") == {"type": "dot", "dot": 1}
    assert parse_line("DOT 6") == {"type": "dot", "dot": 6}


def test_forgiving_about_case_and_spaces():
    assert parse_line("  btn   enter \r\n") == {"type": "button", "action": "enter"}
    assert parse_line("dot 3") == {"type": "dot", "dot": 3}


def test_rejects_garbage():
    for line in ["", "HELLO", "DOT 0", "DOT 7", "DOT 12", "DOT", "BTN", "SHOW A 100000"]:
        assert parse_line(line) is None


# ---- braille_remote.ino protocol ----
# These are the exact line sequences the sketch prints.

from app.arduino import RemoteParser


def feed(parser, *lines):
    out = []
    for line in lines:
        out += parser.parse(line)
    return out


def test_boot_is_not_a_commit():
    p = RemoteParser()
    assert feed(p, "READY", "CELL 0", "MODE 0 0") == [
        {"type": "cell", "mask": 0, "quiet": True},
        {"type": "mode", "capital": False, "number": False},
    ]


def test_type_letter_a():
    p = RemoteParser()
    feed(p, "READY", "CELL 0", "MODE 0 0")
    assert feed(p, "CELL 1") == [{"type": "cell", "mask": 1, "quiet": False}]
    assert feed(p, "CHAR 1 a", "CELL 0", "MODE 0 0") == [
        {"type": "commit", "mask": 1, "char": "a"},
        {"type": "cell", "mask": 0, "quiet": True},  # cleared by Enter, not by the user
        {"type": "mode", "capital": False, "number": False},
    ]


def test_removing_last_dot_is_not_quiet():
    p = RemoteParser()
    feed(p, "READY", "CELL 0", "MODE 0 0")
    assert feed(p, "CELL 1", "CELL 0")[-1] == {"type": "cell", "mask": 0, "quiet": False}


def test_number_sign_reported_as_commit():
    p = RemoteParser()
    feed(p, "READY", "CELL 0", "MODE 0 0", "CELL 4", "CELL 12", "CELL 28", "CELL 60")
    out = feed(p, "CELL 0", "MODE 0 1")
    assert {"type": "commit", "mask": 60, "char": None} in out
    assert out[-1] == {"type": "mode", "capital": False, "number": True}
    # then "1" in number mode
    assert feed(p, "CELL 1", "CHAR 1 1")[-1] == {"type": "commit", "mask": 1, "char": "1"}


def test_capital_sign_reported_as_commit():
    p = RemoteParser()
    feed(p, "READY", "CELL 0", "MODE 0 0", "CELL 32")
    assert {"type": "commit", "mask": 32, "char": None} in feed(p, "CELL 0", "MODE 1 0")


def test_unknown_and_space():
    p = RemoteParser()
    feed(p, "READY", "CELL 0", "MODE 0 0")
    assert feed(p, "UNKNOWN 63")[0] == {"type": "commit", "mask": 63, "char": None}
    assert feed(p, "CELL 0", "MODE 0 0", "CHAR 0")[-1] == {"type": "commit", "mask": 0, "char": " "}


def test_new_long_message_names():
    p = RemoteParser()
    feed(p, "READY", "BRAILLE_CELL_BITMASK 0", "INPUT_MODE_FLAGS 0 0", "BRAILLE_CELL_BITMASK 3")
    assert feed(p, "COMMITTED_CHARACTER 3 b")[0] == {"type": "commit", "mask": 3, "char": "b"}
    assert feed(p, "NO_MATCHING_CHARACTER_FOR_BITMASK 5")[0]["char"] is None


def test_garbage_ignored():
    p = RemoteParser()
    for line in ["", "hello", "CELL x", "MODE 1", "CHAR"]:
        assert p.parse(line) == []
