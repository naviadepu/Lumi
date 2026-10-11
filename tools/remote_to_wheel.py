"""Lumi two-board test tool: connect the braille remote (Uno) to the braille wheel (Mega) without Lumi.

Both boards stay on their own USB cables. This program reads the letters you type on the
remote and tells the wheel what to show.

    python tools/remote_to_wheel.py --list                              # which COM port is which
    python tools/remote_to_wheel.py --remote COM3 --wheel COM6          # practice all 8 wheel letters
    python tools/remote_to_wheel.py --remote COM3 --wheel COM6 --letters pen
    python tools/remote_to_wheel.py --remote COM3 --wheel COM6 --follow # the wheel turns to whatever you type

Practice: the wheel turns a letter under your finger and asks you to type it. Right -> the
wheel moves on to the next letter. Wrong -> it tells you which buttons make that letter.

Needs: pip install pyserial. Close the Arduino Serial Monitor (and Lumi) first: only one
program can use a port at a time. Stop with Ctrl+C.
"""

import argparse
import queue
import sys
import threading
import time

WHEEL_LETTERS = "abceilnp"  # must match WHEEL_LETTERS in wheel_mega/wheel_mega.ino

# Braille dot patterns: bit 0 = dot 1 ... bit 5 = dot 6.
LETTER_MASKS = dict(zip(
    "abcdefghijklmnopqrstuvwxyz",
    [1, 3, 9, 25, 17, 11, 27, 19, 10, 26, 5, 7, 13, 29, 21, 15, 31, 23, 14, 30, 37, 39, 58, 45, 61, 53],
))
DOT_NAMES = {1: "1 top left", 2: "2 middle left", 3: "3 bottom left",
             4: "4 top right", 5: "5 middle right", 6: "6 bottom right"}

# The remote sketches use short or long message names; accept both.
CHAR_NAMES = ("CHAR", "COMMITTED_CHARACTER")
UNKNOWN_NAMES = ("UNKNOWN", "NO_MATCHING_CHARACTER_FOR_BITMASK")
CELL_NAMES = ("CELL", "BRAILLE_CELL_BITMASK")


def dots_in(mask):
    return [d for d in range(1, 7) if mask >> (d - 1) & 1]


def describe(letter):
    """'P is: 1 top left, 2 middle left, 3 bottom left, 4 top right'"""
    return f"{letter.upper()} is: " + ", ".join(DOT_NAMES[d] for d in dots_in(LETTER_MASKS[letter]))


class Lesson:
    """The decisions, kept apart from the serial ports so they're easy to test.

    Every method returns a list of actions: ("wheel", letter) or ("say", text).
    """

    def __init__(self, letters=WHEEL_LETTERS, follow=False):
        self.letters = letters
        self.follow = follow
        self.index = 0

    @property
    def target(self):
        return self.letters[self.index]

    def start(self):
        if self.follow:
            return [("say", "Follow mode: type a wheel letter (A B C E I L N P) on the remote, then Enter.")]
        return self.show_target("Let's start.")

    def show_target(self, lead_in):
        return [("wheel", self.target),
                ("say", f"{lead_in} Feel the wheel. Type the letter {self.target.upper()} on the remote, then Enter.")]

    def on_remote_line(self, line):
        words = line.split()
        if not words:
            return []
        name = words[0].upper()

        if name in CELL_NAMES and len(words) == 2 and words[1].isdigit():
            mask = int(words[1])
            return [("say", "  dots pressed: " + "-".join(map(str, dots_in(mask))))] if mask else []

        if name in UNKNOWN_NAMES:
            return [("say", "That pattern isn't a letter. Try again.")]

        if name in CHAR_NAMES and len(words) >= 2:
            typed = words[2].lower() if len(words) > 2 else " "  # "CHAR 0 " (a space) loses its last word
            return self.on_typed(typed)

        return []  # READY, MODE, ...

    def on_typed(self, typed):
        if typed == " ":
            return [("say", "That was a space (no dots). Press some dots first, then Enter.")]
        if self.follow:
            if typed in WHEEL_LETTERS:
                return [("wheel", typed), ("say", f"You typed {typed.upper()}. Turning the wheel to {typed.upper()}.")]
            return [("say", f"You typed {typed.upper()}. It isn't on the wheel (A B C E I L N P).")]

        if typed == self.target:
            self.index = (self.index + 1) % len(self.letters)
            lead_in = "Correct! Starting again from the top." if self.index == 0 else "Correct! Next letter."
            return self.show_target(lead_in)
        hint = describe(self.target)
        if typed in LETTER_MASKS:
            return [("say", f"You typed {typed.upper()}. Good try. {hint}")]
        return [("say", f"You typed {typed!r}. {hint}")]


# ---------------------------------------------------------------- serial ports

def list_ports():
    from serial.tools import list_ports as lp
    ports = list(lp.comports())
    if not ports:
        print("No serial ports found. Are the boards plugged in?")
    for p in ports:
        print(f"  {p.device:<14} {p.description}")
    print("The Uno is usually the one that changes when you unplug the remote.")


def open_port(device, label):
    import serial
    try:
        conn = serial.Serial(device, 9600, timeout=0.2)
    except serial.SerialException as e:
        sys.exit(f"Can't open the {label} on {device}: {e}\n"
                 "Check the port name (python remote_to_wheel.py --list) and close the Serial Monitor / Lumi.")
    time.sleep(2)  # opening the port restarts the board; give it time to boot
    return conn


def read_lines(conn, source, inbox):
    """Background thread: put every line from a board into the inbox as (source, text)."""
    while True:
        try:
            raw = conn.readline()
        except Exception as e:  # unplugged
            inbox.put((source, f"!disconnected: {e}"))
            return
        text = raw.decode("ascii", errors="ignore").strip()
        if text:
            inbox.put((source, text))


def apply(actions, wheel):
    for kind, value in actions:
        if kind == "wheel":
            wheel.write(f"{value}\n".encode("ascii"))
        else:
            print(value, flush=True)


def run(remote, wheel, lesson, inbox, show_wheel_output=False, stop=None):
    apply(lesson.start(), wheel)
    while stop is None or not stop.is_set():
        try:
            source, text = inbox.get(timeout=0.2)
        except queue.Empty:
            continue
        if text.startswith("!disconnected"):
            print(f"The {source} was unplugged. Stopping.")
            return
        if source == "remote":
            apply(lesson.on_remote_line(text), wheel)
        elif show_wheel_output or text.startswith("AT "):
            print(f"  [wheel] {text}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Connect the braille remote (Uno) to the braille wheel (Mega).")
    parser.add_argument("--list", action="store_true", help="show the serial ports and exit")
    parser.add_argument("--remote", help="the Uno remote's port, e.g. COM3")
    parser.add_argument("--wheel", help="the Mega wheel's port, e.g. COM5")
    parser.add_argument("--letters", default=WHEEL_LETTERS, help="letters to practise (only A B C E I L N P)")
    parser.add_argument("--follow", action="store_true", help="the wheel turns to whatever you type")
    parser.add_argument("--verbose", action="store_true", help="also print everything the wheel says")
    args = parser.parse_args(argv)

    if args.list:
        list_ports()
        return
    if not args.remote or not args.wheel:
        parser.error("give both ports, e.g. --remote COM3 --wheel COM5 (find them with --list)")
    letters = args.letters.lower().replace(" ", "")
    bad = sorted({c for c in letters if c not in WHEEL_LETTERS})
    if not letters or bad:
        parser.error(f"--letters can only use the wheel letters A B C E I L N P (not: {' '.join(bad).upper()})")

    print("Connecting...")
    remote = open_port(args.remote, "remote")
    wheel = open_port(args.wheel, "wheel")
    remote.reset_input_buffer()
    inbox = queue.Queue()
    threading.Thread(target=read_lines, args=(remote, "remote", inbox), daemon=True).start()
    threading.Thread(target=read_lines, args=(wheel, "wheel", inbox), daemon=True).start()
    print("Connected. Press Ctrl+C to stop.\n")
    try:
        run(remote, wheel, Lesson(letters, args.follow), inbox, args.verbose)
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
