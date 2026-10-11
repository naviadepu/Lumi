// Braille remote — 6 dot buttons + Enter, Arduino Uno. Remote only.
// Used in the two-board setup, with the wheel on a Mega (wheel_mega/wheel_mega.ino).
// For one board that is both the remote and the wheel, use braille_wheel/braille_wheel.ino.
// Wiring: dots 1-6 -> D2-D7, Enter -> D8, other leg of each button -> GND
// Uses INPUT_PULLUP, so pressed = LOW. No resistors needed.
//
// Serial protocol (9600 baud, one message per line):
//   READY              sketch started
//   CELL <mask>        current dot pattern changed (bit 0 = dot 1 ... bit 5 = dot 6)
//   MODE <cap> <num>   capital / number indicators (0 or 1)
//   CHAR <mask> <c>    Enter produced character c (may be a space)
//   UNKNOWN <mask>     Enter pressed on a pattern with no meaning

const uint8_t NUM_BTNS = 7;
const uint8_t PINS[NUM_BTNS] = { 2, 3, 4, 5, 6, 7, 8 };  // dots 1-6, then Enter
const uint8_t ENTER_INDEX = 6;
const unsigned long DEBOUNCE_MS = 20;

const uint8_t CAP_SIGN = 32;  // dot 6
const uint8_t NUM_SIGN = 60;  // dots 3-4-5-6

bool stableState[NUM_BTNS];
bool lastReading[NUM_BTNS];
unsigned long lastChange[NUM_BTNS];

uint8_t cell = 0;
bool capNext = false;
bool numMode = false;
char table[64];

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
  sendCell();
  sendMode();
}

void onPress(uint8_t i) {
  if (i == ENTER_INDEX) {
    commit();
  } else {
    cell ^= (1 << i);  // press once to set, again to cancel
    sendCell();
  }
}

void setup() {
  Serial.begin(9600);
  buildTable();
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
}
