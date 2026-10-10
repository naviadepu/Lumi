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
| ENTER | Enter or Space | Check the answer |
| REPEAT | R | Hear the prompt again |
| NEXT / PREV | Right / Left arrow | Skip to the next / previous letter |
| | Escape | Back to the text input |

On the start screen, the remote's ENTER starts Learn mode.

**Read**: show and speak each character, one at a time.

| Key | Action |
| --- | --- |
| Right arrow, Space, or remote ENTER / NEXT | Next character |
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

While the server is running, type into **the same terminal** and press Enter:

```
DOT 1
DOT 4
BTN ENTER
BTN NEXT
BTN PREV
BTN REPEAT
```

The page reacts exactly as if a physical button was pressed.

Unit tests:

```bash
pytest
```

## Demo day checklist

- **Click anywhere on the page once** before handing over the remote. Browsers block audio
  until someone has interacted with the page. (Or start Chrome with
  `--autoplay-policy=no-user-gesture-required`.)
- Check the corner says "Arduino: connected".
- Run it once beforehand with the ElevenLabs key set. Every phrase is cached in `audio_cache/`,
  so the demo plays instantly and still works if the Wi-Fi drops.

## Building the remote

1. Wire each button between a pin and GND (no resistors needed). Default pins are at the top of
   `arduino/braille_board/braille_board.ino`:
   TOP LEFT 2, MIDDLE LEFT 3, BOTTOM LEFT 4, TOP RIGHT 5, MIDDLE RIGHT 6, BOTTOM RIGHT 7, ENTER 8.
   Optional: NEXT 9, PREV 10, REPEAT 11 (set to `-1` if you skip them), and 6 LEDs on A0-A5 that
   show the target pattern (set `USE_LEDS = false` if you skip them).
2. Open the sketch in the Arduino IDE, pick your board and port, and click Upload.
3. **Close the Arduino IDE Serial Monitor.** Only one program can use the port at a time.
4. Start (or keep running) `python -m app.main`. It finds the board within a few seconds and the
   corner of the page changes to "Arduino: connected". If it picks the wrong port, set
   `ARDUINO_PORT` in `.env` (Mac: `ls /dev/cu.*`, e.g. `/dev/cu.usbmodem1101`; Windows: `COM3`).

Serial protocol (9600 baud, one line each, `\n` ending):

| Direction | Line | Meaning |
| --- | --- | --- |
| remote -> laptop | `DOT 1` ... `DOT 6` | dot button pressed (laptop toggles it) |
| remote -> laptop | `BTN ENTER` / `BTN NEXT` / `BTN PREV` / `BTN REPEAT` | button pressed |
| laptop -> remote | `SHOW A 100000` | current character, dots 1-6 (1 = raised), for the optional LEDs |

## How it fits together

```
browser (app/static)  --HTTP-->  FastAPI (app/main.py)  --HTTPS-->  ElevenLabs
        ^                              |
        +------- WebSocket ------------+  <--serial-->  Arduino remote
          (button presses, status)
```

| File | What it does |
| --- | --- |
| `app/braille.py` | Braille table and text -> list of cells (number sign, spaces) |
| `app/tts.py` | ElevenLabs Python SDK call + audio cache (memory and `audio_cache/` on disk) |
| `app/arduino.py` | Serial connection, auto-detect, reconnect, mock mode, line parsing |
| `app/main.py` | Web server: `/api/steps`, `/api/show`, `/speak`, `/ws`, console test mode |
| `app/static/` | The page: `index.html`, `style.css`, `app.js` (Learn + Read logic) |
| `arduino/braille_board/` | Arduino sketch for the remote |
| `tests/` | Braille lookup and serial protocol tests |

Settings in `.env`: `SPEAK_LETTER_PREFIX` / `SPEAK_NUMBER_PREFIX` change what Read mode speaks
("Letter A", "Number 5"); `ELEVENLABS_MODEL_ID` defaults to `eleven_multilingual_v2`
(switch to `eleven_flash_v2_5` for lower latency). Each phrase is fetched once and cached, so repeats play
instantly and don't use extra credits.
