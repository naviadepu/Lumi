# Lumi

A low-cost tool for adults learning grade 1 braille. A voice prompts "Type the letter A."
and the learner presses the matching dots on a 6-button remote. If it's wrong, the voice
says which buttons to press ("Good try. C is: 1, top left. 4, top right."). If it's
right: "Good job! Next is: the letter B."

The buttons are called by number and position ("1, top left"):

```
TOP LEFT     (1)   TOP RIGHT    (4)
MIDDLE LEFT  (2)   MIDDLE RIGHT (5)
BOTTOM LEFT  (3)   BOTTOM RIGHT (6)
            [ ENTER ]
```

**Snap it, learn it:** hold anything up to the webcam (a medicine bottle, a name badge,
a spice jar) and press Enter on the remote. Gemini reads it, the device says "I see a
pen. Write pen.", turns each letter under your finger on the braille wheel, and coaches
you through the word.
Labeling your own things is one of the first everyday uses of braille after vision loss.

Speech uses ElevenLabs, with the browser's built-in voice as a fallback. Everything
works without the remote: the keyboard and on-screen buttons do the same things.

The hardware comes in two setups. **One board:** an Arduino Uno running
`braille_wheel/braille_wheel.ino` is both the remote and the wheel. **Two boards:** an Uno
running `braille_remote/braille_remote.ino` is the remote, and an Arduino Mega running
`wheel_mega/wheel_mega.ino` turns the wheel; see "Two-board setup" below. Either way, pressing
a dot toggles it and Enter commits the cell. See "The remote" below.

## Setup (once)

Needs Python 3.10+.

```bash
python3 -m venv .venv              # Windows: py -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate (Git Bash: source .venv/Scripts/activate)
pip install -r requirements.txt
cp .env.example .env               # then paste your ElevenLabs key into .env
```

No ElevenLabs key? Leave it empty. The page uses the browser's built-in voice.

For Snap, get a free Gemini key at https://aistudio.google.com/apikey and set
`GEMINI_API_KEY` in `.env`. Without it, Snap is off and everything else works.

## Run

**Hands-free (for the learner and the demo), macOS, Windows or Linux:**

```bash
./start.sh
```

On Windows, run it from Git Bash in the Lumi folder (`sh start.sh` also works). It needs the
`.venv` from Setup, made on that computer; it opens Chrome, or Edge if Chrome isn't installed.
If the window shows `$'\r': command not found`, the file got Windows line endings: run
`sed -i 's/\r$//' start.sh` once in Git Bash (this repo's `.gitattributes` prevents it for new clones).

It starts the server and opens Chrome as a full-screen app that may use the camera and
microphone and play sound without anyone clicking first. The camera turns on by itself and the voice says
"Welcome to Lumi. Hold up any object to the camera and keep it still."
Nothing on screen needs to be found or clicked. Quit with Cmd+Q (Windows: Alt+F4), and stop
the server with Ctrl+C in the terminal.

**For development:**

```bash
source .venv/bin/activate          # Windows Git Bash: source .venv/Scripts/activate
python -m app.main
```

Open http://127.0.0.1:8000 in Chrome. In a normal browser tab, click once anywhere if
there's no sound (browsers block audio until the page is touched).

## Modes

The app opens on a home screen with two hands-free options, and says so:
*"Hold up any object to the camera, and I'll teach you its name in braille. Or press Enter
and tell me what you'd like to learn."*

**Ask** (press Enter on the remote, then talk): have a conversation with Lumi. A high beep
means it's listening; it stops by itself when you stop talking (low beep). ElevenLabs
speech-to-text (`scribe_v2`) hears you and Gemini replies to the whole conversation so far,
then Lumi listens again. Ask it anything, chat, or ask for a lesson:

> "Hi Lumi, how are you?" -> "I'm doing great, thanks for asking! How are you today?" ->
> "What is braille?" -> "A system of raised dots you read with your fingertips. ..." ->
> "How do I write my name?" -> "I'd love to help. What's your name?" -> "Navi" ->
> "Let's write your name, Navi. N, A, V, I. Type the letter N. Feel it on the wheel."

The conversation ends when you go quiet or say goodbye. Press Enter while Lumi is talking
to cut in.

**Snap** (automatic): learn a word from the real world. Hold an object up to the
camera and keep it still for about a second; no button needed. The page watches for
something new to move into view and settle, then asks Gemini what it is (if it's just a
person or the room, it keeps watching). Gemini names
it, preferring a word that fits the wheel (a pill bottle -> "pill"); when you finish, the
camera opens for the next thing.

| Remote | Keyboard | Action |
| --- | --- | --- |
| (nothing) | (nothing) | Hold the object still: it looks automatically |
| Enter | Enter or Space | Talk (Ask). Press again to stop early, or to cut in while Lumi talks |
| | "Look now" button | Take the photo right away |
| | Escape | Text screen (for sighted helpers: Learn, Read, Type) |

For the other modes, type the letters to practise (default `abc`), then pick a mode.

**Learn**: type each letter in braille.

| Remote | Keyboard | Action |
| --- | --- | --- |
| Dot buttons | `1`-`6`, or `F D S` / `J K L` | Toggle a dot (press again to remove it) |
| Enter | Enter or Space | Check the answer |
| | R | Hear the prompt again |
| | Right / Left arrow | Skip to the next / previous letter |
| | Escape | Back to the text input |

On the start screen, the remote's Enter starts Snap (or Learn if there's no Gemini key). Digits are two steps: the
number sign (dots 3-4-5-6), then the digit.

**The coach.** Learn mode doesn't just say "wrong", it explains the mistake (`app/coach.py`):

| You did | It says |
| --- | --- |
| Typed the mirror image (F for D, I for E, J for H) | "Close! You typed F, the mirror image. Swap left and right." |
| Right shape, wrong row | "Close! Right shape, but one row too low." |
| Left out a dot | "Almost! Also press: 3, bottom left." |
| Added a dot | "Almost! Leave out: 5, middle right." |
| Anything else | "Good try. You typed E. C is: 1, top left. 4, top right." |

New letters come with a hint from braille's structure ("K is A plus bottom left",
"U is A plus both bottom dots", "4 uses the same dots as D"). Letters you miss come back
for review a few letters later, and the lesson ends with a summary
("Lesson complete! 3 characters, 2 mistakes. Trickiest: the letter D.").

Why: adult braille learners say existing tools "only flag errors without clarifying
rules" ([arXiv 2512.03398](https://arxiv.org/abs/2512.03398)), and adults learning braille
make mirror-image errors, as children do with b and d.

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
- Allow camera access once in Chrome, and have props whose names fit the wheel:
  pen, pencil, pill bottle, clip, apple, banana, ball, can.
- Run it once beforehand with the ElevenLabs key set. Every phrase is cached in `audio_cache/`,
  so the demo plays instantly and still works if the Wi-Fi drops.

## The remote and the braille wheel

Hardware (about $25-30 with an Uno clone): Arduino Uno, 7 tactile buttons, 6 LEDs + 220 ohm
resistors, a 28BYJ-48 stepper with ULN2003 driver, a hall sensor + magnet (or microswitch),
and a disc with raised braille letters (hot-glue dots, puff paint or 3D print; bigger
"jumbo" dots are easier for beginners).

How a lesson uses it ("I see a pen. Write pen."):
1. **Feel**: the wheel turns the target letter under the finger. "Type the letter P. Feel it on the wheel."
2. **Type**: press the dot buttons (the LEDs light up live), then Enter.
3. **Coach**: right -> next letter; wrong -> "Almost! Also press: 6, bottom right." The wheel stays put.

Letters that aren't on the wheel flash on the LEDs instead, and the voice reads the dots:
"It's not on the wheel. Press 1, top left. 3, bottom left. 6, bottom right."

**Wheel-only mode (`WHEEL_ONLY=true`, the default).** The wheel only has 8 letters, so every
lesson is kept to them:
- Scan: Gemini is given the words the wheel can spell (`app/wheel.py`) and picks one that fits
  the object (a pill bottle -> "pill", a charger -> "cable").
- Ask: "Navi" -> "V isn't on your wheel, so we'll skip it", then N, A, I. Ideas ("what can I
  learn?", "a fruit") only suggest words the wheel can spell; the server checks them.
- Nothing fits ("mug"): "None of those letters are on your wheel. Your wheel has A, B, C, E, I,
  L, N and P. Try a pen, an apple, or a ball."
- Numbers are skipped (the number sign isn't on the wheel), and memory hints only mention
  letters the learner can feel ("L is B plus bottom left").

Set `WHEEL_ONLY=false` to teach any letter, with the LEDs standing in for letters off the wheel.

**The 8 wheel letters: A B C E I L N P.** Out of about 100 everyday object names, these
spell the most (pen, pencil, pill, pin, cap, can, cane, clip, apple, banana, ball, bell...).
Gemini is told to pick a word spelled with them when one fits the object. Digits use the
same slots (1 = a, 2 = b, 3 = c, 5 = e, 9 = i). To change the disc, change `WHEEL_LETTERS`
in both `.env` and the sketch.

```
Dot 1 (top left)    -> D2      Dot 4 (top right)    -> D5      Enter -> D8
Dot 2 (middle left) -> D3      Dot 5 (middle right) -> D6      other leg of every button -> GND
Dot 3 (bottom left) -> D4      Dot 6 (bottom right) -> D7

LEDs dots 1-6       -> D9, D10, D11, D12, D13, A0  (each via 220 ohm to GND)
ULN2003 IN1-IN4     -> A1, A2, A3, A4              (driver powered from 5V)
Home sensor         -> A5 (LOW at home; set HOME_SENSOR_PIN = -1 if you have none)
```

1. Open `braille_wheel/braille_wheel.ino` in the Arduino IDE (it must stay in the
   `braille_wheel` folder), pick Arduino Uno and its port, and Upload. No extra libraries.
2. Calibrate: at power-on the wheel finds home, then goes to slot 0 (A). Adjust
   `HOME_OFFSET_STEPS` until A sits exactly under the finger, and `WHEEL_DIRECTION` if it
   turns the wrong way. Letters go round the disc in `WHEEL_LETTERS` order, evenly spaced.
3. **Close the Serial Monitor and quit the IDE.** Only one program can use the port at a time.
   The same goes for `braille_interface.html` (the standalone Web Serial test page).
4. Start `python -m app.main`. The corner of the page says "Arduino: connected" within a
   few seconds. If it picks the wrong port, set `ARDUINO_PORT` in `.env`
   (Windows: `COM3`; Mac: `ls /dev/cu.*`).

Serial protocol (9600 baud, one line each). Both short and long names work:

| Direction | Line | Meaning |
| --- | --- | --- |
| remote -> laptop | `READY` | sketch booted |
| remote -> laptop | `CELL <mask>` / `BRAILLE_CELL_BITMASK <mask>` | current dots changed (bit 0 = dot 1 ... bit 5 = dot 6) |
| remote -> laptop | `MODE <cap> <num>` / `INPUT_MODE_FLAGS <cap> <num>` | capital / number mode, 0 or 1 |
| remote -> laptop | `CHAR <mask> <c>` / `COMMITTED_CHARACTER <mask> <c>` | Enter typed character c (may be a space) |
| remote -> laptop | `UNKNOWN <mask>` / `NO_MATCHING_CHARACTER_FOR_BITMASK <mask>` | Enter on a pattern with no meaning |
| laptop -> remote | `SHOW <c> <dots>` | new target, e.g. `SHOW p 111100`: wheel turns to the slot with that pattern, or the LEDs flash it |

Enter on the capital or number sign prints no character, only `CELL 0` and `MODE`; the
server reports that to the page as a commit of the sign.

### Two-board setup: Uno remote + Mega wheel

The remote and the wheel are separate boards, each on its own USB cable. They are not wired
to each other; Lumi talks to both.

```
Uno  (braille_remote/braille_remote.ino) --USB--> laptop: Lumi --USB--> Mega (wheel_mega/wheel_mega.ino)
```

Uno remote: dots 1-6 -> D2-D7, Enter -> D8, the other leg of every button -> GND (no LEDs).

Mega wheel: 28BYJ-48 stepper on a ULN2003 driver. IN1-IN4 -> D9, D10, D11, D12; driver + -> 5V,
- -> GND. If the Mega resets when the motor starts, power the driver from a separate 5 V supply
and join its GND to the Mega's GND. The disc has the 8 letters A B C E I L N P, 45 degrees apart,
in `WHEEL_LETTERS` order.

1. Upload `braille_remote/braille_remote.ino` to the Uno and `wheel_mega/wheel_mega.ino` to the
   Mega (Board: Arduino Mega or Mega 2560). Each sketch must stay in its own folder.
2. Calibrate the wheel once (Serial Monitor on the Mega, 9600 baud, "New Line"). It's saved
   on the Mega, so it survives power-off and the reset that happens when Lumi opens the port.
   - Line up A: nudge with `+` / `-` (small steps; `++` / `--` are 10 times bigger) until A
     is under the finger, then type `zero`.
   - Measure one turn: type `calstart`, then `turn`, then nudge until A is back under the
     finger, then `calend`. (If you already know the number, `rev 8152` sets it.)
   - Fine-tune a letter: type it (e.g. `l`), nudge it into place, type `fix`. `evenly` undoes
     all fixes, `info` prints the calibration, `help` lists every command.
3. Close the Serial Monitor and quit the IDE.
4. In `.env`, set `ARDUINO_WHEEL_PORT` to the Mega's port (e.g. `COM6`) and `ARDUINO_PORT` to
   the Uno's (or leave it empty: auto-detect skips the wheel's port). To see which is which:
   `python tools/remote_to_wheel.py --list`.
5. Start `python -m app.main`. Every new target is sent to both boards: the Uno ignores it and
   the Mega turns to that letter and prints `AT <letter>`. A pattern that isn't on the wheel
   prints `NOT ON WHEEL <dots>` and the wheel stays put. `/api/status` shows
   `"wheel_board": true` once the Mega is connected.

Test without Lumi (stop Lumi first; only one program can use a port):
- `tools/wheel_test.html`: open it in Chrome or Edge, connect each board, and drive the wheel
  and its calibration with buttons. "Practice" runs a lesson using the remote.
- `python tools/remote_to_wheel.py --remote COM3 --wheel COM6`: the same practice lesson in a
  terminal. Add `--follow` to make the wheel turn to whatever wheel letter you type.

| Problem | Fix |
| --- | --- |
| `Access is denied` / `could not open port` | Close the Serial Monitor, the test page and any other program using the port; replug |
| `A device attached to the system is not functioning` | Unplug the board and plug it back in |
| Wheel stops halfway to each letter | Measure one turn again (`calstart` ... `calend`) |
| Motor hums but doesn't turn, or one direction is slow | An IN1-IN4 wire is loose or in the wrong order |
| Wheel turns the wrong way | Set `DIRECTION = -1` in `wheel_mega.ino` |
| Wrong letter under the finger after moving the disc | Line up A again and type `zero` |

## How it fits together

```
browser (app/static)  --HTTP-->  FastAPI (app/main.py)  --HTTPS-->  ElevenLabs (voice)
  + webcam                                               --HTTPS-->  Gemini (reads photos)
        ^                              |
        +------- WebSocket ------------+  <--serial-->  braille remote (Arduino)
          (button presses, status)
```

| File | What it does |
| --- | --- |
| `app/braille.py` | Braille table and text -> list of cells (number sign, spaces) |
| `app/assistant.py` | Ask: ElevenLabs speech-to-text + a Gemini conversation that can start lessons |
| `app/vision.py` | Snap: Gemini reads a webcam photo and picks a word to learn |
| `app/coach.py` | Mistake diagnosis (mirror, shifted, missing/extra dots) and memory hints |
| `app/tts.py` | ElevenLabs Python SDK call + audio cache (memory and `audio_cache/` on disk) |
| `app/arduino.py` | Serial connection, auto-detect, reconnect, mock mode, remote protocol parser |
| `app/main.py` | Web server: `/api/steps`, `/api/show`, `/speak`, `/ws`, console test mode |
| `app/static/` | The page: `index.html`, `style.css`, `app.js` (Learn, Read, Type) |
| `braille_wheel/` | One-board sketch: remote, LEDs and wheel on one Uno |
| `braille_remote/` | Two-board setup: remote-only sketch for the Uno |
| `wheel_mega/` | Two-board setup: stepper wheel sketch for the Mega (calibration saved in EEPROM) |
| `tools/` | Two-board test tools: `wheel_test.html` (Web Serial panel) and `remote_to_wheel.py` |
| `braille_interface.html` | Standalone Web Serial test page for the remote (no server needed) |
| `tests/` | Braille lookup, coach, vision, assistant, wheel and serial protocol tests |

Settings in `.env`: `SPEAK_LETTER_PREFIX` / `SPEAK_NUMBER_PREFIX` change what Read mode speaks
("Letter A", "Number 5"); `ELEVENLABS_MODEL_ID` defaults to `eleven_multilingual_v2`
(switch to `eleven_flash_v2_5` for lower latency). Each phrase is fetched once and cached, so repeats play
instantly and don't use extra credits.
