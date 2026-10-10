// Braille remote — 6 dot buttons + Enter, 6 LEDs, rotating braille wheel. Arduino Uno.
//
// Buttons: dots 1-6 -> D2-D7, Enter -> D8, other leg of each button -> GND
//          (INPUT_PULLUP, so pressed = LOW. No resistors needed.)
// LEDs:    one per dot, each through a 220 ohm resistor to GND. They light up live
//          as dots are pressed, and flash the target letter when it isn't on the wheel.
// Wheel:   28BYJ-48 stepper + ULN2003 driver, with a disc of raised braille letters
//          (WHEEL_LETTERS, evenly spaced). It turns the target letter under the finger.
//          Optional home sensor (hall sensor + magnet, or a microswitch) finds slot 0 at power-on.
//
// Serial protocol (9600 baud, one message per line):
//   Arduino -> laptop
//     READY              sketch started
//     CELL <mask>        current dot pattern changed (bit 0 = dot 1 ... bit 5 = dot 6)
//     MODE <cap> <num>   capital / number indicators (0 or 1)
//     CHAR <mask> <c>    Enter produced character c (may be a space)
//     UNKNOWN <mask>     Enter pressed on a pattern with no meaning
//   Laptop -> Arduino
//     SHOW <c> <dots>    new target, e.g. "SHOW p 111100" (dots 1-6, 1 = raised).
//                        If a wheel slot has that pattern, the wheel turns to it;
//                        otherwise the LEDs show the pattern for a few seconds.

// ======================= CHANGE THESE TO MATCH YOUR BUILD =======================
const uint8_t NUM_BTNS = 7;
const uint8_t PINS[NUM_BTNS] = { 2, 3, 4, 5, 6, 7, 8 };  // dots 1-6, then Enter
const uint8_t ENTER_INDEX = 6;

const uint8_t LED_PINS[6] = { 9, 10, 11, 12, 13, A0 };  // dots 1-6

// Letters on the wheel, in order around the disc. Must match WHEEL_LETTERS in the app's .env.
const char WHEEL_LETTERS[] = "abceilnp";

const uint8_t STEPPER_PINS[4] = { A1, A2, A3, A4 };  // ULN2003 IN1, IN2, IN3, IN4
const long STEPS_PER_REV = 4096;          // 28BYJ-48 in half-step mode
const unsigned int STEP_INTERVAL_US = 1200;  // lower = faster; too low and the motor stalls
const int WHEEL_DIRECTION = 1;            // set to -1 if the wheel turns the wrong way

const int HOME_SENSOR_PIN = A5;           // LOW when slot 0 is home; set to -1 if you have no sensor
const long HOME_OFFSET_STEPS = 0;         // nudge until slot 0 sits exactly under the finger

const unsigned long DEBOUNCE_MS = 20;
const unsigned long LED_FLASH_MS = 3000;  // how long an off-wheel target shows on the LEDs
const unsigned long LED_HOLD_MS = 1200;   // how long a typed cell stays lit after Enter
// ================================================================================

const uint8_t CAP_SIGN = 32;  // dot 6
const uint8_t NUM_SIGN = 60;  // dots 3-4-5-6

bool stableState[NUM_BTNS];
bool lastReading[NUM_BTNS];
unsigned long lastChange[NUM_BTNS];

uint8_t cell = 0;
bool capNext = false;
bool numMode = false;
char table[64];

// ---------------------------------------------------------------- letters

void buildTable() {
  for (uint8_t i = 0; i < 64; i++) table[i] = 0;  // 0 = unknown pattern

  const char letters[] = "abcdefghijklmnopqrstuvwxyz";
  const uint8_t masks[26] = {
    1, 3, 9, 25, 17, 11, 27, 19, 10, 26,   // a-j
    5, 7, 13, 29, 21, 15, 31, 23, 14, 30,  // k-t
    37, 39, 58, 45, 61, 53                 // u v w x y z
  };
  for (uint8_t i = 0; i < 26; i++) table[masks[i]] = letters[i];

  table[0] = ' ';   // Enter on an empty cell = space
  table[2] = ',';   // dot 2
  table[6] = ';';   // dots 2-3
  table[18] = ':';  // dots 2-5
  table[50] = '.';  // dots 2-5-6
  table[22] = '!';  // dots 2-3-5
  table[38] = '?';  // dots 2-3-6
  table[4] = '\'';  // dot 3
  table[36] = '-';  // dots 3-6
}

uint8_t maskForLetter(char letter) {
  for (uint8_t m = 1; m < 64; m++) {
    if (table[m] == letter) return m;
  }
  return 0;
}

// ---------------------------------------------------------------- LEDs

uint8_t ledOverride = 0;          // pattern shown instead of the live cell
unsigned long ledOverrideUntil = 0;

void showOnLeds(uint8_t mask) {
  for (uint8_t i = 0; i < 6; i++) digitalWrite(LED_PINS[i], (mask >> i) & 1 ? HIGH : LOW);
}

void flashOnLeds(uint8_t mask, unsigned long ms) {
  ledOverride = mask;
  ledOverrideUntil = millis() + ms;
  showOnLeds(mask);
}

void updateLeds() {
  if (ledOverrideUntil && millis() >= ledOverrideUntil) {
    ledOverrideUntil = 0;
    showOnLeds(cell);
  }
}

// ---------------------------------------------------------------- wheel

const uint8_t WHEEL_SLOTS = sizeof(WHEEL_LETTERS) - 1;
uint8_t wheelMasks[WHEEL_SLOTS];

const uint8_t HALF_STEP[8][4] = {
  {1, 0, 0, 0}, {1, 1, 0, 0}, {0, 1, 0, 0}, {0, 1, 1, 0},
  {0, 0, 1, 0}, {0, 0, 1, 1}, {0, 0, 0, 1}, {1, 0, 0, 1}
};

long wheelPosition = 0;  // in steps, 0 = slot 0 under the finger
long wheelTarget = 0;
unsigned long lastStepMicros = 0;

void energize(long position) {
  uint8_t phase = ((position * WHEEL_DIRECTION) % 8 + 8) % 8;
  for (uint8_t i = 0; i < 4; i++) digitalWrite(STEPPER_PINS[i], HALF_STEP[phase][i]);
}

void releaseCoils() {  // stops the motor heating up while it waits
  for (uint8_t i = 0; i < 4; i++) digitalWrite(STEPPER_PINS[i], LOW);
}

void stepOnce(int direction) {
  wheelPosition += direction;
  energize(wheelPosition);
}

// Non-blocking: one step at most per call, so the buttons keep working while it turns.
void updateWheel() {
  if (wheelPosition == wheelTarget) return;
  unsigned long now = micros();
  if (now - lastStepMicros < STEP_INTERVAL_US) return;
  lastStepMicros = now;
  stepOnce(wheelTarget > wheelPosition ? 1 : -1);
  if (wheelPosition == wheelTarget) releaseCoils();
}

// Turn the shortest way round to a slot.
void turnToSlot(uint8_t slot) {
  long slotSteps = (long)slot * STEPS_PER_REV / WHEEL_SLOTS;
  long current = ((wheelPosition % STEPS_PER_REV) + STEPS_PER_REV) % STEPS_PER_REV;
  long delta = slotSteps - current;
  if (delta > STEPS_PER_REV / 2) delta -= STEPS_PER_REV;
  if (delta < -STEPS_PER_REV / 2) delta += STEPS_PER_REV;
  wheelTarget = wheelPosition + delta;
}

// At power-on: turn until the home sensor triggers, then nudge to slot 0.
void homeWheel() {
  if (HOME_SENSOR_PIN < 0) return;  // no sensor: put slot 0 under the finger by hand before power-on
  pinMode(HOME_SENSOR_PIN, INPUT_PULLUP);
  for (long i = 0; i < STEPS_PER_REV + STEPS_PER_REV / 4 && digitalRead(HOME_SENSOR_PIN) == HIGH; i++) {
    stepOnce(1);
    delayMicroseconds(STEP_INTERVAL_US);
  }
  for (long i = 0; i < HOME_OFFSET_STEPS; i++) {
    stepOnce(1);
    delayMicroseconds(STEP_INTERVAL_US);
  }
  releaseCoils();
  wheelPosition = 0;
  wheelTarget = 0;
}

// ---------------------------------------------------------------- laptop -> Arduino

char lineBuffer[24];
uint8_t lineLength = 0;

// "SHOW p 111100": turn the wheel to the slot with that pattern, or flash it on the LEDs.
void handleLine(const char* line) {
  if (strncmp(line, "SHOW ", 5) != 0) return;
  const char* dots = strrchr(line, ' ');
  if (dots == NULL || strlen(dots + 1) != 6) return;
  dots++;
  uint8_t mask = 0;
  for (uint8_t i = 0; i < 6; i++) {
    if (dots[i] == '1') mask |= (1 << i);
  }
  for (uint8_t s = 0; s < WHEEL_SLOTS; s++) {
    if (wheelMasks[s] == mask && mask != 0) {
      turnToSlot(s);
      return;
    }
  }
  if (mask != 0) flashOnLeds(mask, LED_FLASH_MS);
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLength > 0) {
        lineBuffer[lineLength] = '\0';
        handleLine(lineBuffer);
        lineLength = 0;
      }
    } else if (lineLength < sizeof(lineBuffer) - 1) {
      lineBuffer[lineLength++] = c;
    }
  }
}

// ---------------------------------------------------------------- Arduino -> laptop

void sendCell() {
  Serial.print(F("CELL "));
  Serial.println(cell);
}

void sendMode() {
  Serial.print(F("MODE "));
  Serial.print(capNext ? 1 : 0);
  Serial.print(' ');
  Serial.println(numMode ? 1 : 0);
}

void commit() {
  uint8_t committed = cell;
  if (cell == CAP_SIGN) {
    capNext = true;
  } else if (cell == NUM_SIGN) {
    numMode = true;
  } else {
    char c = table[cell];
    if (c == 0) {
      Serial.print(F("UNKNOWN "));
      Serial.println(cell);
    } else {
      if (c == ' ') {
        numMode = false;
        capNext = false;
      } else {
        bool isDigit = false;
        if (numMode) {
          if (c >= 'a' && c <= 'j') {
            c = (c == 'j') ? '0' : char('1' + (c - 'a'));
            isDigit = true;
          } else {
            numMode = false;  // any non a-j symbol ends number mode
          }
        }
        if (!isDigit && capNext && c >= 'a' && c <= 'z') c = c - 'a' + 'A';
        capNext = false;
      }
      Serial.print(F("CHAR "));
      Serial.print(cell);
      Serial.print(' ');
      Serial.println(c);
    }
  }
  cell = 0;
  if (committed) flashOnLeds(committed, LED_HOLD_MS);  // keep what was typed lit for a moment
  sendCell();
  sendMode();
}

void onPress(uint8_t i) {
  if (i == ENTER_INDEX) {
    commit();
  } else {
    cell ^= (1 << i);  // press once to set, again to cancel
    ledOverrideUntil = 0;
    showOnLeds(cell);  // LEDs follow the buttons live
    sendCell();
  }
}

// ---------------------------------------------------------------- setup / loop

void setup() {
  Serial.begin(9600);
  buildTable();
  for (uint8_t s = 0; s < WHEEL_SLOTS; s++) wheelMasks[s] = maskForLetter(WHEEL_LETTERS[s]);

  for (uint8_t i = 0; i < 6; i++) pinMode(LED_PINS[i], OUTPUT);
  for (uint8_t i = 0; i < 4; i++) pinMode(STEPPER_PINS[i], OUTPUT);
  for (uint8_t i = 0; i < 6; i++) {  // LED self-test
    showOnLeds(1 << i);
    delay(80);
  }
  showOnLeds(0);
  homeWheel();

  for (uint8_t i = 0; i < NUM_BTNS; i++) {
    pinMode(PINS[i], INPUT_PULLUP);
    bool pressed = digitalRead(PINS[i]) == LOW;
    stableState[i] = pressed;
    lastReading[i] = pressed;
    lastChange[i] = 0;
  }
  Serial.println(F("READY"));
  sendCell();
  sendMode();
}

void loop() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < NUM_BTNS; i++) {
    bool reading = digitalRead(PINS[i]) == LOW;
    if (reading != lastReading[i]) {
      lastReading[i] = reading;
      lastChange[i] = now;
    }
    if (now - lastChange[i] > DEBOUNCE_MS && reading != stableState[i]) {
      stableState[i] = reading;
      if (reading) onPress(i);  // act on the press edge only
    }
  }
  readSerial();
  updateWheel();
  updateLeds();
}
