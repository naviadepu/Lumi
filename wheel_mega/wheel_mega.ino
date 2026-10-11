// Lumi braille wheel - second board (Arduino Mega). 28BYJ-48 stepper + ULN2003 driver.
//
// Two-board setup: the Uno runs the remote (braille_remote/braille_remote.ino) and this Mega
// turns the wheel. Both plug into the laptop by USB; Lumi talks to both (ARDUINO_PORT for the
// remote, ARDUINO_WHEEL_PORT for this board). For one board doing both jobs, use
// braille_wheel/braille_wheel.ino instead.
//
// Wiring:
//   Motor's white plug -> the white socket on the ULN2003 board
//   ULN2003 IN1 -> D9,  IN2 -> D10,  IN3 -> D11,  IN4 -> D12
//   ULN2003 +   -> 5V,  ULN2003 -   -> GND   (keep the ON/OFF jumper on the driver in place)
//
// The wheel REMEMBERS (in the Mega's EEPROM): where it is, how many steps one full turn takes,
// and the exact spot of each letter. So it stays calibrated when the board restarts - which
// happens every time the laptop connects.
//
// Keyboard (Serial Monitor, 9600 baud, "New Line") or the buttons on tools/wheel_test.html:
//   a b c e i l n p     turn to that letter (shortest way round)
//   0 - 7               the same by letter number (0 = a ... 7 = p)
//   turn | sweep        one full turn | visit all 8 letters
//   +  -                nudge a little (about 3 degrees)
//   ++  --              nudge 10x as much (about 30 degrees)
//   step 500            move 500 steps (step -500 goes back)
//   zero                "letter A is under the window right now"
//   where | info        print where the wheel is | print the calibration
//
// Calibration (do these once, in this order):
//   1. Measure one full turn:
//        line A up under the window with + / - / ++ / --, then type  calstart
//        turn the wheel ONE full turn with ++ / + / - until A is back under the window, then type  calend
//      (or, if you already know the number:  rev 8152)
//   2. Fine-tune each letter: type a letter (e.g. "c"), nudge with + / - until it sits exactly
//      under the window, then type  fix.  Repeat for each letter that's off.
//      "evenly" puts all letters back to even spacing.
//
// From Lumi:  SHOW <c> <dots>   e.g. "SHOW p 111100" (dots 1-6, 1 = raised). The wheel turns to the
//             letter with that dot pattern; patterns that aren't on the wheel are ignored
//             (it prints "NOT ON WHEEL <dots>"), because Lumi reads those letters out instead.
// From tools/remote_to_wheel.py and tools/wheel_test.html: a letter or WHEEL <0-7>.
// After every letter move the sketch prints "AT <letter>", so the laptop knows it has arrived.

#include <EEPROM.h>

// ======================= CHANGE THESE TO MATCH YOUR BUILD =======================
const uint8_t IN_PINS[4] = { 9, 10, 11, 12 };  // ULN2003 IN1, IN2, IN3, IN4
const long DEFAULT_STEPS_PER_REV = 4076;  // used until you calibrate (28BYJ-48 half-step, no gears)
const unsigned int STEP_DELAY_US = 1200;  // time per step: lower = faster; too low and it buzzes without turning
const int DIRECTION = 1;                  // set to -1 if the wheel turns the wrong way
const char WHEEL_LETTERS[] = "abceilnp";  // letters on the wheel, in order, evenly spaced
const long NUDGE_STEPS = 32;              // + and - ; ++ and -- move 10x this
// ================================================================================

const uint8_t NUM_LETTERS = sizeof(WHEEL_LETTERS) - 1;

// Braille dot patterns a-z (bit 0 = dot 1 ... bit 5 = dot 6), to match Lumi's SHOW command.
const uint8_t LETTER_MASKS[26] = {
  1, 3, 9, 25, 17, 11, 27, 19, 10, 26,   // a-j
  5, 7, 13, 29, 21, 15, 31, 23, 14, 30,  // k-t
  37, 39, 58, 45, 61, 53                 // u v w x y z
};

const uint8_t HALF_STEP[8][4] = {
  {1, 0, 0, 0}, {1, 1, 0, 0}, {0, 1, 0, 0}, {0, 1, 1, 0},
  {0, 0, 1, 0}, {0, 0, 1, 1}, {0, 0, 0, 1}, {1, 0, 0, 1}
};

long position = 0;                  // steps within one turn; 0 = letter A under the window
long stepsPerRev = DEFAULT_STEPS_PER_REV;
long letterSteps[NUM_LETTERS];      // where each letter sits, in steps from A
int8_t lastLetter = -1;             // the letter most recently asked for (for "fix")

void setStepsPerRev(long steps);  // defined below

bool calibrating = false;
long calSteps = 0;                  // net steps moved since "calstart"

// ---------------------------------------------------------------- saved settings

const uint16_t SAVE_MAGIC = 0x5355;  // changes whenever this layout changes
const int SAVE_ADDRESS = 0;

struct Saved {
  uint16_t magic;
  long position;
  long stepsPerRev;
  long letterSteps[NUM_LETTERS];
};

long withinTurn(long pos) {
  return ((pos % stepsPerRev) + stepsPerRev) % stepsPerRev;
}

void spaceLettersEvenly() {
  for (uint8_t i = 0; i < NUM_LETTERS; i++) letterSteps[i] = (long)i * stepsPerRev / NUM_LETTERS;
}

void save() {
  Saved s;
  s.magic = SAVE_MAGIC;
  s.position = withinTurn(position);
  s.stepsPerRev = stepsPerRev;
  for (uint8_t i = 0; i < NUM_LETTERS; i++) s.letterSteps[i] = letterSteps[i];
  EEPROM.put(SAVE_ADDRESS, s);  // put() only rewrites bytes that changed
}

bool load() {
  Saved s;
  EEPROM.get(SAVE_ADDRESS, s);
  if (s.magic != SAVE_MAGIC || s.stepsPerRev < 100 || s.stepsPerRev > 100000) return false;
  stepsPerRev = s.stepsPerRev;
  for (uint8_t i = 0; i < NUM_LETTERS; i++) letterSteps[i] = s.letterSteps[i];
  position = withinTurn(s.position);
  return true;
}

// ---------------------------------------------------------------- motor

void energize(long pos) {
  uint8_t phase = ((pos * DIRECTION) % 8 + 8) % 8;
  for (uint8_t i = 0; i < 4; i++) digitalWrite(IN_PINS[i], HALF_STEP[phase][i]);
}

void releaseCoils() {  // stops the motor heating up while it waits
  for (uint8_t i = 0; i < 4; i++) digitalWrite(IN_PINS[i], LOW);
}

void moveSteps(long steps) {
  int dir = steps > 0 ? 1 : -1;
  for (long i = 0; i < abs(steps); i++) {
    position += dir;
    energize(position);
    delayMicroseconds(STEP_DELAY_US);
  }
  releaseCoils();
  if (calibrating) calSteps += steps;
  position = withinTurn(position);
  save();
}

int letterAtPosition() {  // -1 if between letters
  for (uint8_t i = 0; i < NUM_LETTERS; i++) {
    if (withinTurn(letterSteps[i]) == position) return i;
  }
  return -1;
}

void printWhere() {
  Serial.print(F("at step "));
  Serial.print(position);
  Serial.print(F(" of "));
  Serial.print(stepsPerRev);
  int letter = calibrating ? -1 : letterAtPosition();
  if (letter >= 0) {
    Serial.print(F(" = letter "));
    Serial.print(WHEEL_LETTERS[letter]);
  }
  if (calibrating) {
    Serial.print(F("  (calibrating: "));
    Serial.print(calSteps);
    Serial.print(F(" steps so far)"));
  }
  Serial.println();
}

void printInfo() {
  Serial.print(F("steps per turn: "));
  Serial.println(stepsPerRev);
  for (uint8_t i = 0; i < NUM_LETTERS; i++) {
    Serial.print(F("  "));
    Serial.print(WHEEL_LETTERS[i]);
    Serial.print(F(" at step "));
    Serial.print(letterSteps[i]);
    long even = (long)i * stepsPerRev / NUM_LETTERS;
    if (letterSteps[i] != even) {
      Serial.print(F("  (fine-tuned by "));
      Serial.print(letterSteps[i] - even);
      Serial.print(F(")"));
    }
    Serial.println();
  }
}

// Turn the shortest way round to a letter, then report "AT <letter>".
void wheelTo(uint8_t index) {
  if (index >= NUM_LETTERS) {
    Serial.println(F("letter number must be 0-7"));
    return;
  }
  lastLetter = index;
  long delta = withinTurn(letterSteps[index]) - position;
  if (delta > stepsPerRev / 2) delta -= stepsPerRev;
  if (delta < -stepsPerRev / 2) delta += stepsPerRev;
  if (delta != 0) moveSteps(delta);
  Serial.print(F("AT "));
  Serial.println(WHEEL_LETTERS[index]);
}

// "SHOW p 111100": turn to the wheel letter with that dot pattern (digits 1-0 share a-j's patterns).
void showPattern(const char* line) {
  const char* dots = strrchr(line, ' ');
  if (dots == NULL || strlen(dots + 1) != 6) return;
  dots++;
  uint8_t mask = 0;
  for (uint8_t i = 0; i < 6; i++) {
    if (dots[i] == '1') mask |= (1 << i);
  }
  for (uint8_t i = 0; i < NUM_LETTERS; i++) {
    char c = WHEEL_LETTERS[i];
    if (c >= 'a' && c <= 'z' && LETTER_MASKS[c - 'a'] == mask && mask != 0) {
      wheelTo(i);
      return;
    }
  }
  Serial.print(F("NOT ON WHEEL "));
  Serial.println(dots);
}

void sweep() {
  Serial.println(F("sweeping all letters..."));
  for (uint8_t i = 0; i < NUM_LETTERS; i++) {
    wheelTo(i);
    delay(1000);
  }
  wheelTo(0);
  Serial.println(F("done"));
}

// ---------------------------------------------------------------- calibration

void calStart() {
  calibrating = true;
  calSteps = 0;
  Serial.println(F("CAL started. Now turn the wheel ONE full turn with ++ / + / - until A is back under the window, then type calend."));
}

void calEnd() {
  if (!calibrating) { Serial.println(F("type calstart first")); return; }
  calibrating = false;
  long measured = labs(calSteps);
  if (measured < 500) {
    Serial.print(F("CAL cancelled: only "));
    Serial.print(measured);
    Serial.println(F(" steps - that's not a full turn. Try again."));
    return;
  }
  setStepsPerRev(measured);
  Serial.print(F("CAL done: one full turn = "));
  Serial.print(measured);
  Serial.println(F(" steps (saved). A is letter 0 here."));
}

void setStepsPerRev(long steps) {
  stepsPerRev = steps;
  position = 0;           // A is under the window
  spaceLettersEvenly();
  save();
}

void fixLetter() {
  if (lastLetter < 0) { Serial.println(F("type a letter first, nudge it into place, then fix")); return; }
  if (lastLetter == 0) {
    // A defines zero: shift every letter so A sits here.
    long shift = position;
    for (uint8_t i = 0; i < NUM_LETTERS; i++) letterSteps[i] = withinTurn(letterSteps[i] - shift);
    letterSteps[0] = 0;
    position = 0;
  } else {
    letterSteps[lastLetter] = position;
  }
  save();
  Serial.print(F("OK: letter "));
  Serial.print(WHEEL_LETTERS[lastLetter]);
  Serial.println(F(" now stops here (saved)"));
}

// ---------------------------------------------------------------- commands

char rx[24];
uint8_t rxLen = 0;

void printHelp() {
  Serial.println(F("Type: a b c e i l n p | 0-7 | turn | sweep | + - ++ -- | step 500 | zero | where | info"));
  Serial.println(F("Calibrate: calstart ... calend | rev 8152 | fix | evenly"));
}

void handleLine() {
  while (rxLen > 0 && rx[rxLen - 1] == ' ') rx[--rxLen] = 0;  // trim trailing spaces
  if (rxLen == 0) return;

  if (strncmp(rx, "SHOW ", 5) == 0) { showPattern(rx); return; }
  if (strncmp(rx, "WHEEL ", 6) == 0) { wheelTo((uint8_t)atoi(rx + 6)); return; }
  if (strncmp(rx, "step ", 5) == 0) { moveSteps(atol(rx + 5)); printWhere(); return; }
  if (strncmp(rx, "rev ", 4) == 0) {
    long n = atol(rx + 4);
    if (n < 500 || n > 100000) { Serial.println(F("rev must be between 500 and 100000")); return; }
    calibrating = false;
    setStepsPerRev(n);
    Serial.print(F("OK: one full turn = "));
    Serial.print(n);
    Serial.println(F(" steps (saved). A is letter 0 here."));
    return;
  }
  if (strcmp(rx, "turn") == 0) { Serial.println(F("one full turn...")); moveSteps(stepsPerRev); printWhere(); return; }
  if (strcmp(rx, "sweep") == 0) { sweep(); return; }
  if (strcmp(rx, "zero") == 0) { position = withinTurn(letterSteps[0]); lastLetter = 0; save(); Serial.println(F("OK: this is letter a now (saved)")); return; }
  if (strcmp(rx, "where") == 0) { printWhere(); return; }
  if (strcmp(rx, "info") == 0) { printInfo(); return; }
  if (strcmp(rx, "help") == 0) { printHelp(); return; }
  if (strcmp(rx, "calstart") == 0) { calStart(); return; }
  if (strcmp(rx, "calend") == 0) { calEnd(); return; }
  if (strcmp(rx, "fix") == 0) { fixLetter(); return; }
  if (strcmp(rx, "evenly") == 0) { spaceLettersEvenly(); save(); Serial.println(F("OK: letters evenly spaced again (saved)")); return; }
  if (strcmp(rx, "++") == 0) { moveSteps(NUDGE_STEPS * 10); printWhere(); return; }
  if (strcmp(rx, "--") == 0) { moveSteps(-NUDGE_STEPS * 10); printWhere(); return; }

  if (rxLen == 1) {
    char c = rx[0];
    if (c == '+') { moveSteps(NUDGE_STEPS); printWhere(); return; }
    if (c == '-') { moveSteps(-NUDGE_STEPS); printWhere(); return; }
    if (c >= '0' && c <= '7') { wheelTo(c - '0'); return; }
    const char* found = strchr(WHEEL_LETTERS, tolower(c));
    if (found) { wheelTo(found - WHEEL_LETTERS); return; }
  }

  Serial.print(F("? "));
  Serial.println(rx);
  printHelp();
}

void readSerial() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (rxLen > 0) { rx[rxLen] = 0; handleLine(); rxLen = 0; }
    } else if (rxLen < sizeof(rx) - 1) {
      rx[rxLen++] = ch;
    }
  }
}

void setup() {
  Serial.begin(9600);
  for (uint8_t i = 0; i < 4; i++) pinMode(IN_PINS[i], OUTPUT);
  releaseCoils();
  if (load()) {
    Serial.print(F("READY - remembered position: "));
    printWhere();
  } else {
    spaceLettersEvenly();
    Serial.println(F("READY - not calibrated yet, assuming letter a is under the window"));
  }
  printHelp();
}

void loop() {
  readSerial();
}
