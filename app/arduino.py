"""Serial link to the braille boards.

One board (braille_wheel/braille_wheel.ino) is both the remote and the wheel. In the
two-board setup the remote is braille_remote/braille_remote.ino on an Uno, and the wheel
is wheel_mega/wheel_mega.ino on a Mega with its own ArduinoLink (ARDUINO_WHEEL_PORT).

Arduino -> laptop:  see RemoteParser below (CELL / MODE / CHAR / UNKNOWN lines).
                    Also accepted, for testing: "DOT 1".."DOT 6", "BTN ENTER/NEXT/PREV/REPEAT".
Laptop -> Arduino:  "SHOW A 100000\n" (current character; a remote-only board ignores it).

If no Arduino is plugged in we run in mock mode: SHOW lines are only logged.
A background thread keeps retrying, so you can plug the board in while the
app is running.
"""

import logging
import threading
import time

import serial
from serial.tools import list_ports

log = logging.getLogger("arduino")

BUTTON_ACTIONS = {"BTN NEXT": "next", "BTN PREV": "prev", "BTN REPEAT": "repeat", "BTN ENTER": "enter"}


def parse_line(line):
    """Turn a line from the remote into a message for the page, or None.

    "BTN NEXT" -> {"type": "button", "action": "next"}
    "DOT 3"    -> {"type": "dot", "dot": 3}
    """
    words = line.upper().split()
    action = BUTTON_ACTIONS.get(" ".join(words))
    if action:
        return {"type": "button", "action": action}
    if len(words) == 2 and words[0] == "DOT" and words[1] in ("1", "2", "3", "4", "5", "6"):
        return {"type": "dot", "dot": int(words[1])}
    return None


CAPITAL_SIGN_MASK = 32  # dot 6
NUMBER_SIGN_MASK = 60   # dots 3-4-5-6

# The first version of braille_remote.ino used short names. Accept both.
LEGACY_NAMES = {
    "CELL": "BRAILLE_CELL_BITMASK",
    "MODE": "INPUT_MODE_FLAGS",
    "CHAR": "COMMITTED_CHARACTER",
    "UNKNOWN": "NO_MATCHING_CHARACTER_FOR_BITMASK",
}


class RemoteParser:
    """Turns lines from the remote (braille_remote.ino or braille_wheel.ino) into messages for the page.

    The remote keeps the dot state itself (bit 0 = dot 1 ... bit 5 = dot 6):
        READY                                    sketch booted
        BRAILLE_CELL_BITMASK <mask>              -> {"type": "cell", "mask", "quiet"}
        INPUT_MODE_FLAGS <capital> <number>      -> {"type": "mode", "capital", "number"}
        COMMITTED_CHARACTER <mask> <char>        -> {"type": "commit", "mask", "char"}
        NO_MATCHING_CHARACTER_FOR_BITMASK <mask> -> {"type": "commit", "mask", "char": None}

    Enter on the capital or number sign prints no character, only the cleared
    cell and new mode flags, so we report that as a commit of the cleared cell.
    "quiet" marks the cell clearing after a commit (not the user removing a dot).
    DOT n / BTN ... lines (keyboard-style test input) are passed through too.
    """

    def __init__(self):
        self.cell = 0
        self.cleared_cell = 0
        self.commit_reported = True  # nothing pending at startup

    def parse(self, line):
        simple = parse_line(line)
        if simple:
            return [simple]
        words = line.split()
        if not words:
            return []
        name = words[0].upper()
        name = LEGACY_NAMES.get(name, name)
        try:
            numbers = [int(w) for w in words[1:]] if name != "COMMITTED_CHARACTER" else [int(words[1])]
        except (ValueError, IndexError):
            return []

        if name == "READY":
            self.cell = 0
            self.commit_reported = True  # the boot-time CELL 0 / MODE are not a commit
            return []

        if name == "BRAILLE_CELL_BITMASK" and len(numbers) == 1:
            mask = numbers[0]
            quiet = mask == 0 and self.commit_reported
            if mask == 0:
                self.cleared_cell = self.cell
            self.cell = mask
            return [{"type": "cell", "mask": mask, "quiet": quiet}]

        if name == "COMMITTED_CHARACTER":
            # A committed space arrives as "COMMITTED_CHARACTER 0 " and the trailing space is stripped.
            char = words[2] if len(words) > 2 else " "
            self.commit_reported = True
            return [{"type": "commit", "mask": numbers[0], "char": char}]

        if name == "NO_MATCHING_CHARACTER_FOR_BITMASK" and len(numbers) == 1:
            self.commit_reported = True
            return [{"type": "commit", "mask": numbers[0], "char": None}]

        if name == "INPUT_MODE_FLAGS" and len(numbers) == 2:
            messages = []
            if not self.commit_reported and self.cleared_cell in (CAPITAL_SIGN_MASK, NUMBER_SIGN_MASK):
                messages.append({"type": "commit", "mask": self.cleared_cell, "char": None})
            self.commit_reported = False  # MODE ends every commit; the next one starts now
            messages.append({"type": "mode", "capital": numbers[0] == 1, "number": numbers[1] == 1})
            return messages

        return []


RETRY_SECONDS = 3
# Words that show up in the port name/description of common Arduino boards.
ARDUINO_HINTS = ("arduino", "usbmodem", "usbserial", "ttyacm", "ttyusb", "ch340", "cp210", "wchusbserial")


def find_arduino_port(exclude=()):
    """First port that looks like an Arduino, skipping the ports in exclude (e.g. the wheel board's)."""
    skip = {p.lower() for p in exclude if p}
    for port in list_ports.comports():
        if port.device.lower() in skip:
            continue
        text = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
        if any(hint in text for hint in ARDUINO_HINTS):
            return port.device
    return None


class ArduinoLink:
    def __init__(self, port, baud, on_line, on_status, exclude_ports=(), name="Arduino"):
        """
        port:          serial port like /dev/cu.usbmodem1101 or COM3; "" = auto-detect; "mock" = never connect
        on_line:       called with each line the Arduino sends (from a background thread)
        on_status:     called with True/False when the connection changes
        exclude_ports: ports auto-detect must skip (another link's port)
        name:          used in log messages
        """
        self.port_setting = port
        self.exclude_ports = tuple(exclude_ports)
        self.name = name
        self.baud = baud
        self.on_line = on_line
        self.on_status = on_status
        self.serial = None
        self.write_lock = threading.Lock()
        self.stopped = threading.Event()

    @property
    def connected(self):
        return self.serial is not None

    def start(self):
        threading.Thread(target=self._run, daemon=True, name=self.name.lower().replace(" ", "-")).start()

    def stop(self):
        self.stopped.set()

    def send_show(self, char, pattern):
        # The Arduino splits on spaces, so the character must be one visible ASCII symbol.
        if not (len(char) == 1 and char.isascii() and char.isprintable() and char != " "):
            char = "?"
        line = f"SHOW {char} {pattern}"
        port = self.serial  # local copy: the reader thread may set self.serial to None
        if port is None:
            log.info("[mock] %s would get: %s", self.name, line)
            return
        try:
            with self.write_lock:
                port.write((line + "\n").encode("ascii"))
            log.info("sent to %s: %s", self.name, line)
        except (serial.SerialException, OSError) as e:
            log.warning("%s write failed: %s", self.name, e)
            self._disconnect()

    def _connect(self):
        port = self.port_setting or find_arduino_port(self.exclude_ports)
        if not port or port.lower() == "mock":
            return False
        try:
            conn = serial.Serial(port, self.baud, timeout=0.2)
            # Opening the port resets most Arduinos; give the sketch time to boot.
            time.sleep(2)
            conn.reset_input_buffer()
        except (serial.SerialException, OSError):
            return False
        self.serial = conn
        log.info("%s connected on %s at %d baud", self.name, port, self.baud)
        self.on_status(True)
        return True

    def _disconnect(self):
        if self.serial is None:
            return
        try:
            self.serial.close()
        except Exception:
            pass
        self.serial = None
        log.info("%s disconnected, back to mock mode", self.name)
        self.on_status(False)

    def _run(self):
        if self.port_setting.lower() == "mock":
            log.info("%s: port is 'mock', running in mock mode", self.name)
        elif self.port_setting:
            log.info("%s: waiting for %s (mock mode until it opens)", self.name, self.port_setting)
        else:
            log.info("%s: looking for a board (mock mode until one is found)", self.name)
        while not self.stopped.is_set():
            if not self.connected:
                if not self._connect():
                    self.stopped.wait(RETRY_SECONDS)
                continue
            try:
                raw = self.serial.readline()
            except (serial.SerialException, OSError) as e:
                log.warning("%s read failed: %s", self.name, e)
                self._disconnect()
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if line:
                self.on_line(line)
