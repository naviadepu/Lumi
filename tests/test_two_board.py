"""Two-board setup: Uno remote (ARDUINO_PORT) + Mega wheel (ARDUINO_WHEEL_PORT)."""

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.arduino as arduino_module
from app.arduino import ArduinoLink, find_arduino_port


class FakeSerial:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data.decode("ascii"))


def fake_ports(*devices):
    return lambda: [SimpleNamespace(device=d, description="Arduino Mega 2560", manufacturer="Arduino") for d in devices]


# ---- auto-detect skips the wheel board's port ----

def test_auto_detect_skips_excluded_port(monkeypatch):
    monkeypatch.setattr(arduino_module.list_ports, "comports", fake_ports("COM6", "COM3"))
    assert find_arduino_port() == "COM6"
    assert find_arduino_port(exclude=("COM6",)) == "COM3"
    assert find_arduino_port(exclude=("com6",)) == "COM3"  # Windows port names ignore case
    assert find_arduino_port(exclude=("",)) == "COM6"      # empty setting = nothing excluded


def test_auto_detect_finds_nothing_when_only_the_wheel_is_plugged_in(monkeypatch):
    monkeypatch.setattr(arduino_module.list_ports, "comports", fake_ports("COM6"))
    assert find_arduino_port(exclude=("COM6",)) is None


def test_link_uses_its_exclusions_when_auto_detecting(monkeypatch):
    monkeypatch.setattr(arduino_module.list_ports, "comports", fake_ports("COM6", "COM3"))
    opened = []

    def fake_open(port, baud, timeout):
        opened.append(port)
        raise arduino_module.serial.SerialException("test: don't really open")

    monkeypatch.setattr(arduino_module.serial, "Serial", fake_open)
    link = ArduinoLink(port="", baud=9600, on_line=print, on_status=print, exclude_ports=("COM6",))
    assert link._connect() is False
    assert opened == ["COM3"]


def test_named_link_sends_show(caplog):
    caplog.set_level("INFO", logger="arduino")
    link = ArduinoLink(port="COM6", baud=9600, on_line=print, on_status=print, name="Wheel board")
    link.send_show("p", "111100")  # not connected: mock mode, just logged
    assert "Wheel board would get: SHOW p 111100" in caplog.text
    link.serial = FakeSerial()
    link.send_show("p", "111100")
    assert link.serial.written == ["SHOW p 111100\n"]


# ---- app.main with and without the wheel board ----

@pytest.fixture
def reload_main(monkeypatch):
    """Re-import app.main with the given env, then put it back the way the other tests expect."""
    import app.main as m

    def load(**env):
        monkeypatch.setenv("ARDUINO_PORT", "mock")
        monkeypatch.delenv("ARDUINO_WHEEL_PORT", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(m)

    yield load
    monkeypatch.undo()
    importlib.reload(m)


def test_one_board_setup_has_no_wheel_link(reload_main):
    m = reload_main()
    assert m.wheel_board is None
    with TestClient(m.app) as client:
        assert client.get("/api/status").json()["wheel_board"] is None
        m.arduino.serial = remote = FakeSerial()
        assert client.post("/api/show", json={"char": "p", "pattern": "111100"}).json() == {"ok": True}
        m.arduino.serial = None
    assert remote.written == ["SHOW p 111100\n"]


def test_two_board_setup_sends_show_to_both_boards(reload_main):
    m = reload_main(ARDUINO_WHEEL_PORT="mock")
    assert m.wheel_board is not None
    assert m.arduino.exclude_ports == ("mock",)
    with TestClient(m.app) as client:
        assert client.get("/api/status").json()["wheel_board"] is False
        m.arduino.serial = remote = FakeSerial()
        m.wheel_board.serial = wheel = FakeSerial()
        assert client.get("/api/status").json()["wheel_board"] is True
        client.post("/api/show", json={"char": "p", "pattern": "111100"})
        client.post("/api/show", json={"char": "5", "pattern": "100010"})  # digit 5 = the E slot
        m.arduino.serial = m.wheel_board.serial = None
    assert remote.written == wheel.written == ["SHOW p 111100\n", "SHOW 5 100010\n"]


def test_wheel_board_lines_are_not_treated_as_remote_input(reload_main, monkeypatch):
    m = reload_main(ARDUINO_WHEEL_PORT="mock")
    sent = []
    monkeypatch.setattr(m, "broadcast_from_thread", sent.append)
    m.wheel_board.on_line("AT p")
    m.wheel_board.on_line("CELL 15")  # even a remote-looking line from the wheel is only logged
    assert sent == []
    m.arduino.on_line("CELL 15")
    assert sent == [{"type": "cell", "mask": 15, "quiet": False}]


# ---- tools/remote_to_wheel.py practice logic ----

def load_tool():
    path = Path(__file__).resolve().parent.parent / "tools" / "remote_to_wheel.py"
    spec = importlib.util.spec_from_file_location("remote_to_wheel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wheel_letters_match_everywhere():
    """The disc order lives in three places; they must agree."""
    root = Path(__file__).resolve().parent.parent
    for sketch in ("wheel_mega/wheel_mega.ino", "braille_wheel/braille_wheel.ino"):
        assert 'WHEEL_LETTERS[] = "abceilnp"' in (root / sketch).read_text()
    assert load_tool().WHEEL_LETTERS == "abceilnp"


def test_tool_practice_lesson():
    tool = load_tool()
    lesson = tool.Lesson("pen")
    assert lesson.start()[0] == ("wheel", "p")
    assert lesson.on_remote_line("CELL 15") == [("say", "  dots pressed: 1-2-3-4")]
    wrong = lesson.on_remote_line("CHAR 7 l")
    assert wrong[0][1].startswith("You typed L. Good try. P is: 1 top left")
    assert lesson.on_remote_line("COMMITTED_CHARACTER 15 p")[0] == ("wheel", "e")
    assert lesson.on_remote_line("UNKNOWN 63") == [("say", "That pattern isn't a letter. Try again.")]


def test_tool_follow_mode():
    tool = load_tool()
    lesson = tool.Lesson(follow=True)
    assert lesson.on_remote_line("CHAR 13 n")[0] == ("wheel", "n")
    assert lesson.on_remote_line("CHAR 25 d") == [("say", "You typed D. It isn't on the wheel (A B C E I L N P).")]
