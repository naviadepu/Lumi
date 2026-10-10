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
