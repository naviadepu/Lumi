# Braille Reader

A low-cost tool for adults learning grade 1 braille. A voice prompts "Type the letter A."
and the learner presses the matching dots on a 6-button remote. If it's wrong, the voice
says which buttons to press ("Incorrect. Top, left. Bottom, left. Middle, right."). If it's
right: "Good job! Next is: the letter B."

The buttons are named by position on the remote instead of by dot number:

```
TOP LEFT     (1)   TOP RIGHT    (4)
MIDDLE LEFT  (2)   MIDDLE RIGHT (5)
BOTTOM LEFT  (3)   BOTTOM RIGHT (6)
            [ ENTER ]
```

Speech uses ElevenLabs, with the browser's built-in voice as a fallback. Everything
works without the remote: the keyboard and on-screen buttons do the same things.

The remote is an Arduino Uno running `braille_remote/braille_remote.ino`. Pressing a dot
toggles it; Enter commits the cell. See "The remote" below.

## Setup (once)

Needs Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your ElevenLabs key into .env
```

No ElevenLabs key? Leave it empty. The page uses the browser's built-in voice.

## Run

```bash
source .venv/bin/activate
python -m app.main
```

Open http://127.0.0.1:8000

## Modes

Type the letters to practise (default `abc`), then pick a mode.

**Learn**: type each letter in braille.

| Remote | Keyboard | Action |
| --- | --- | --- |
| Dot buttons | `1`-`6`, or `F D S` / `J K L` | Toggle a dot (press again to remove it) |
| Enter | Enter or Space | Check the answer |
| | R | Hear the prompt again |
| | Right / Left arrow | Skip to the next / previous letter |
| | Escape | Back to the text input |

On the start screen, the remote's Enter starts Learn mode. Digits are two steps: the
number sign (dots 3-4-5-6), then the digit.

**Type**: write freely with the remote (no text needed). Shows the live cell, a preview of
what Enter will type, Capital and Number badges, and the typed text. Each character is spoken.

| Remote | Keyboard | Action |
| --- | --- | --- |
| Dot buttons | `1`-`6`, or `F D S` / `J K L` | Toggle a dot |
| Enter | Enter or Space | Type the cell (empty cell = space) |
| | Backspace | Delete the last character |
| | R | Read back what you typed |
| | Escape | Back to the text input |

Dot 6 alone = capital sign (next letter is a capital). Dots 3-4-5-6 = number sign
(a-j type 1-0 until a space).

**Read**: show and speak each character, one at a time.

| Key | Action |
| --- | --- |
| Right arrow, Space, or the remote's Enter | Next character |
| Left arrow | Previous character |
| R | Repeat current character |
| Escape | Back to the text input |

Braille details:
- Digits use the **number sign** (dots 3-4-5-6, shown as `#`) at the start of a run, then
  letters a-j (1 = a ... 0 = j). So "42" becomes `#`, `4`, `2`. In Learn mode the number sign
  is its own step.
- Spaces are skipped; in Read mode "Space" is announced between words.
- Punctuation is spoken in Read mode (empty braille cell) and skipped in Learn mode.

## Test without the remote

While the server is running, type the remote's messages into **the same terminal**.
For example, the letter "a" (dot 1, then Enter):

```
CELL 1
CHAR 1 a
CELL 0
MODE 0 0
```

The page reacts exactly as if the remote sent them. Shortcuts that also work here:
`DOT 1` ... `DOT 6` (toggle a dot), `BTN ENTER`, `BTN NEXT`, `BTN PREV`, `BTN REPEAT`.

Unit tests:

```bash
pytest
```

## Demo day checklist

- **Click anywhere on the page once** before handing over the remote. Browsers block audio
  until someone has interacted with the page. (Or start Chrome with
  `--autoplay-policy=no-user-gesture-required`.)
- Check the corner says "Arduino: connected" (and that the IDE / test page is closed).
- Run it once beforehand with the ElevenLabs key set. Every phrase is cached in `audio_cache/`,
  so the demo plays instantly and still works if the Wi-Fi drops.

## The remote

Hardware (under $30): Arduino Uno, half-size breadboard, 7 tactile buttons, jumper wires.
No resistors: the pins use the Uno's internal pull-ups.

```
Dot 1 (top left)    -> D2      Dot 4 (top right)    -> D5
Dot 2 (middle left) -> D3      Dot 5 (middle right) -> D6
Dot 3 (bottom left) -> D4      Dot 6 (bottom right) -> D7
Enter               -> D8      other leg of every button -> GND
```

1. Open `braille_remote/braille_remote.ino` in the Arduino IDE (it must stay in the
   `braille_remote` folder), pick Arduino Uno and its port, and Upload.
2. **Close the Serial Monitor and quit the IDE.** Only one program can use the port at a time.
   The same goes for `braille_interface.html` (the standalone Web Serial test page):
   disconnect it before starting this app.
3. Start `python -m app.main`. It finds the board within a few seconds and the corner of the
   page says "Arduino: connected". If it picks the wrong port, set `ARDUINO_PORT` in `.env`
   (Windows: `COM3`; Mac: `ls /dev/cu.*`, e.g. `/dev/cu.usbmodem1101`).

Serial protocol (9600 baud, one line each). Both the short names and the long names work:

| Line | Meaning |
| --- | --- |
| `READY` | sketch booted |
| `CELL <mask>` / `BRAILLE_CELL_BITMASK <mask>` | current dots changed (bit 0 = dot 1 ... bit 5 = dot 6) |
| `MODE <cap> <num>` / `INPUT_MODE_FLAGS <cap> <num>` | capital / number mode, 0 or 1 |
| `CHAR <mask> <c>` / `COMMITTED_CHARACTER <mask> <c>` | Enter typed character c (may be a space) |
| `UNKNOWN <mask>` / `NO_MATCHING_CHARACTER_FOR_BITMASK <mask>` | Enter on a pattern with no meaning |

Enter on the capital or number sign prints no character, only `CELL 0` and `MODE`; the
server reports that to the page as a commit of the sign. The app also sends
`SHOW A 100000` lines (the current character) which the remote ignores.

## How it fits together

```
browser (app/static)  --HTTP-->  FastAPI (app/main.py)  --HTTPS-->  ElevenLabs
        ^                              |
        +------- WebSocket ------------+  <--serial-->  braille remote (Arduino)
          (button presses, status)
```

| File | What it does |
| --- | --- |
| `app/braille.py` | Braille table and text -> list of cells (number sign, spaces) |
| `app/tts.py` | ElevenLabs Python SDK call + audio cache (memory and `audio_cache/` on disk) |
| `app/arduino.py` | Serial connection, auto-detect, reconnect, mock mode, remote protocol parser |
| `app/main.py` | Web server: `/api/steps`, `/api/show`, `/speak`, `/ws`, console test mode |
| `app/static/` | The page: `index.html`, `style.css`, `app.js` (Learn, Read, Type) |
| `braille_remote/` | Arduino sketch for the remote |
| `braille_interface.html` | Standalone Web Serial test page for the remote (no server needed) |
| `tests/` | Braille lookup and serial protocol tests |

Settings in `.env`: `SPEAK_LETTER_PREFIX` / `SPEAK_NUMBER_PREFIX` change what Read mode speaks
("Letter A", "Number 5"); `ELEVENLABS_MODEL_ID` defaults to `eleven_multilingual_v2`
(switch to `eleven_flash_v2_5` for lower latency). Each phrase is fetched once and cached, so repeats play
instantly and don't use extra credits.
