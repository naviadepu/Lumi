"""Serial link to the Arduino braille board.

Laptop -> Arduino:  "SHOW A 100000\n"   (dots 1-6, 1 = raised)
Arduino -> laptop:  "DOT 1" ... "DOT 6"  (a dot button on the remote was pressed)
                    "BTN ENTER" / "BTN NEXT" / "BTN PREV" / "BTN REPEAT"

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


RETRY_SECONDS = 3
# Words that show up in the port name/description of common Arduino boards.
ARDUINO_HINTS = ("arduino", "usbmodem", "usbserial", "ttyacm", "ttyusb", "ch340", "cp210", "wchusbserial")


def find_arduino_port():
    for port in list_ports.comports():
        text = f"{port.device} {port.description} {port.manufacturer or ''}".lower()
        if any(hint in text for hint in ARDUINO_HINTS):
            return port.device
    return None


class ArduinoLink:
    def __init__(self, port, baud, on_line, on_status):
        """
        port:      serial port like /dev/cu.usbmodem1101 or COM3; "" = auto-detect; "mock" = never connect
        on_line:   called with each line the Arduino sends (from a background thread)
        on_status: called with True/False when the connection changes
        """
        self.port_setting = port
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
        threading.Thread(target=self._run, daemon=True, name="arduino").start()

    def stop(self):
        self.stopped.set()

    def send_show(self, char, pattern):
        # The Arduino splits on spaces, so the character must be one visible ASCII symbol.
        if not (len(char) == 1 and char.isascii() and char.isprintable() and char != " "):
            char = "?"
        line = f"SHOW {char} {pattern}"
        port = self.serial  # local copy: the reader thread may set self.serial to None
        if port is None:
            log.info("[mock] would send: %s", line)
            return
        try:
            with self.write_lock:
                port.write((line + "\n").encode("ascii"))
            log.info("sent: %s", line)
        except (serial.SerialException, OSError) as e:
            log.warning("write failed: %s", e)
            self._disconnect()

    def _connect(self):
        port = self.port_setting or find_arduino_port()
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
        log.info("Arduino connected on %s at %d baud", port, self.baud)
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
        log.info("Arduino disconnected, back to mock mode")
        self.on_status(False)

    def _run(self):
        if self.port_setting.lower() == "mock":
            log.info("ARDUINO_PORT=mock: running in mock mode")
        else:
            log.info("Looking for an Arduino (mock mode until one is found)")
        while not self.stopped.is_set():
            if not self.connected:
                if not self._connect():
                    self.stopped.wait(RETRY_SECONDS)
                continue
            try:
                raw = self.serial.readline()
            except (serial.SerialException, OSError) as e:
                log.warning("read failed: %s", e)
                self._disconnect()
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if line:
                self.on_line(line)
