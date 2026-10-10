/*
  Braille Reader remote

  The remote has 6 dot buttons laid out like a braille cell, plus ENTER:

      TOP LEFT     (1)   TOP RIGHT    (4)
      MIDDLE LEFT  (2)   MIDDLE RIGHT (5)
      BOTTOM LEFT  (3)   BOTTOM RIGHT (6)
                  [ ENTER ]

  Arduino -> laptop (one line per press):
      "DOT 1" ... "DOT 6"   a dot button (the laptop toggles it on/off)
      "BTN ENTER"           check the answer / start the lesson
      "BTN NEXT", "BTN PREV", "BTN REPEAT"   optional extra buttons

  Laptop -> Arduino:
      "SHOW A 100000"  (6 digits = dots 1..6). Lights the optional LEDs.

  Wiring:
    - Each button: one leg -> Arduino pin, other leg -> GND (internal pull-up, no resistor needed)
    - Each LED (optional): pin -> 220 ohm resistor -> LED long leg (+), short leg (-) -> GND
*/

// ======================= CHANGE THESE TO MATCH YOUR WIRING =======================
const int BAUD_RATE = 9600;              // must match ARDUINO_BAUD in .env

const int TOP_LEFT_PIN     = 2;          // dot 1
const int MIDDLE_LEFT_PIN  = 3;          // dot 2
const int BOTTOM_LEFT_PIN  = 4;          // dot 3
const int TOP_RIGHT_PIN    = 5;          // dot 4
const int MIDDLE_RIGHT_PIN = 6;          // dot 5
const int BOTTOM_RIGHT_PIN = 7;          // dot 6
const int ENTER_PIN        = 8;

// Optional buttons. Set to -1 if you don't build them.
const int NEXT_PIN   = 9;
const int PREV_PIN   = 10;
const int REPEAT_PIN = 11;

// Optional LEDs showing the target pattern. Set USE_LEDS to false if you don't build them.
const bool USE_LEDS = true;
const int LED_PINS[6] = { A0, A1, A2, A3, A4, A5 };  // dots 1..6

const unsigned long DEBOUNCE_MS = 30;
// ================================================================================

struct Button {
  int pin;
  const char* message;
  int stableState;            // last debounced state
  int lastReading;            // last raw reading
  unsigned long lastChangeMs; // when the raw reading last changed
};

Button buttons[] = {
  { TOP_LEFT_PIN,     "DOT 1",      HIGH, HIGH, 0 },
  { MIDDLE_LEFT_PIN,  "DOT 2",      HIGH, HIGH, 0 },
  { BOTTOM_LEFT_PIN,  "DOT 3",      HIGH, HIGH, 0 },
  { TOP_RIGHT_PIN,    "DOT 4",      HIGH, HIGH, 0 },
  { MIDDLE_RIGHT_PIN, "DOT 5",      HIGH, HIGH, 0 },
  { BOTTOM_RIGHT_PIN, "DOT 6",      HIGH, HIGH, 0 },
  { ENTER_PIN,        "BTN ENTER",  HIGH, HIGH, 0 },
  { NEXT_PIN,         "BTN NEXT",   HIGH, HIGH, 0 },
  { PREV_PIN,         "BTN PREV",   HIGH, HIGH, 0 },
  { REPEAT_PIN,       "BTN REPEAT", HIGH, HIGH, 0 },
};
const int BUTTON_COUNT = sizeof(buttons) / sizeof(buttons[0]);

char lineBuffer[32];
int lineLength = 0;

void setup() {
  Serial.begin(BAUD_RATE);
  for (int i = 0; i < BUTTON_COUNT; i++) {
    if (buttons[i].pin >= 0) pinMode(buttons[i].pin, INPUT_PULLUP);  // pressed = LOW
  }
  if (USE_LEDS) {
    // Light each LED briefly as a self-test.
    for (int i = 0; i < 6; i++) {
      pinMode(LED_PINS[i], OUTPUT);
      digitalWrite(LED_PINS[i], HIGH);
      delay(80);
      digitalWrite(LED_PINS[i], LOW);
    }
  }
}

void loop() {
  readSerial();
  readButtons();
}

// Collect characters until newline, then handle the full line.
void readSerial() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLength > 0) {
        lineBuffer[lineLength] = '\0';
        handleLine(lineBuffer);
        lineLength = 0;
      }
    } else if (lineLength < (int)sizeof(lineBuffer) - 1) {
      lineBuffer[lineLength++] = c;
    }
  }
}

// Expects "SHOW <char> <6 digits>", e.g. "SHOW A 100000".
void handleLine(const char* line) {
  if (!USE_LEDS || strncmp(line, "SHOW ", 5) != 0) return;
  const char* pattern = strrchr(line, ' ');  // last space, right before the digits
  if (pattern == NULL || strlen(pattern + 1) != 6) return;
  pattern++;
  for (int i = 0; i < 6; i++) {
    digitalWrite(LED_PINS[i], pattern[i] == '1' ? HIGH : LOW);
  }
}

// Send a line once per press (on the debounced HIGH -> LOW change).
void readButtons() {
  unsigned long now = millis();
  for (int i = 0; i < BUTTON_COUNT; i++) {
    Button& b = buttons[i];
    if (b.pin < 0) continue;
    int reading = digitalRead(b.pin);
    if (reading != b.lastReading) {
      b.lastReading = reading;
      b.lastChangeMs = now;
    }
    if (now - b.lastChangeMs > DEBOUNCE_MS && reading != b.stableState) {
      b.stableState = reading;
      if (b.stableState == LOW) {
        Serial.println(b.message);
      }
    }
  }
}
