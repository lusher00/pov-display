// hall_check.ino - bench check for A3144 hall sensors (open collector, unipolar south-pole switch).
//
// Wiring per sensor (A3144 pins, branded face toward you: 1 VCC, 2 GND, 3 OUT):
//   VCC -> 5V, GND -> GND, OUT -> one of SENSOR_PINS. 100 nF across VCC-GND at the sensor.
//   The internal pull-up is used; add an external 4.7k to the board's logic rail for long leads.
//
// Serial 115200. Prints every output change, then a once-per-second summary per sensor.
//
// Hand test: a south pole at the branded face pulls OUT low ("ON"); a north pole must do nothing.
// That is how to tell the index magnet (north out) from the four south-out magnets.
//
// Spinning test: with OPR_POSITIONS = 5 and OPR_MISSING = 1 (four south-out magnets + one north-out),
// each revolution gives 4 pulses and one double-length gap. The summary shows rpm from the pulse
// intervals, the index count, and pattern errors (revolutions with the wrong pulse count).
// Set PRINT_EDGES to 0 when spinning so the serial output does not slow the loop.

const uint8_t SENSOR_PINS[] = {2, 3};          // add or remove pins as needed
const uint8_t N_SENSORS = sizeof(SENSOR_PINS);
const uint8_t OPR_POSITIONS = 5;               // magnet positions round the gear
const uint8_t OPR_MISSING = 1;                 // positions with a north-out (no pulse) magnet
const unsigned long GLITCH_US = 500;           // ignore edges closer than this
const bool PRINT_EDGES = true;

struct Sensor {
  uint8_t pin;
  uint8_t state;            // last read level
  unsigned long tChange;    // micros() of last accepted change
  unsigned long tPulse;     // micros() of last falling edge (magnet arrives)
  unsigned long normal[4];  // recent normal pulse intervals
  uint8_t nNormal;
  uint8_t sinceIndex;
  bool haveIndex;
  unsigned long pulses, indexes, patternErrors;
  unsigned long pulsesLastReport;
};

Sensor s[sizeof(SENSOR_PINS)];
unsigned long tReport;

unsigned long medianNormal(const Sensor &x) {
  unsigned long v[4];
  for (uint8_t i = 0; i < x.nNormal; i++) v[i] = x.normal[i];
  for (uint8_t i = 1; i < x.nNormal; i++)          // insertion sort, n <= 4
    for (uint8_t j = i; j > 0 && v[j - 1] > v[j]; j--) { unsigned long t = v[j]; v[j] = v[j - 1]; v[j - 1] = t; }
  return v[x.nNormal / 2];
}

void pushNormal(Sensor &x, unsigned long dt) {
  if (x.nNormal < 4) x.normal[x.nNormal++] = dt;
  else { for (uint8_t i = 0; i < 3; i++) x.normal[i] = x.normal[i + 1]; x.normal[3] = dt; }
}

void onPulse(uint8_t k, unsigned long now) {
  Sensor &x = s[k];
  x.pulses++;
  unsigned long dt = now - x.tPulse;
  bool first = (x.tPulse == 0);
  x.tPulse = now;
  if (first || dt > 1000000UL) {                   // first pulse or rotor was stopped: restart pattern
    x.nNormal = 0; x.sinceIndex = 0; x.haveIndex = false;
    return;
  }
  if (OPR_MISSING && x.nNormal >= 2 && dt > medianNormal(x) * 3 / 2) {
    if (x.haveIndex && x.sinceIndex != OPR_POSITIONS - OPR_MISSING) x.patternErrors++;
    x.indexes++; x.haveIndex = true; x.sinceIndex = 1;
    if (PRINT_EDGES) { Serial.print(F("S")); Serial.print(k); Serial.println(F(" INDEX (end of gap)")); }
    return;
  }
  pushNormal(x, dt);
  x.sinceIndex++;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  for (uint8_t k = 0; k < N_SENSORS; k++) {
    s[k] = Sensor();
    s[k].pin = SENSOR_PINS[k];
    pinMode(s[k].pin, INPUT_PULLUP);
    s[k].state = digitalRead(s[k].pin);
  }
  Serial.println(F("hall_check: OUT low = south pole present (ON). North pole should not switch."));
  for (uint8_t k = 0; k < N_SENSORS; k++) {
    Serial.print(F("S")); Serial.print(k); Serial.print(F(" pin ")); Serial.print(s[k].pin);
    Serial.println(s[k].state ? F(" idle HIGH (ok)") : F(" reads LOW at start: magnet present, or OUT shorted / sensor wired wrong"));
  }
  tReport = millis();
}

void loop() {
  unsigned long now = micros();
  bool anyOn = false;
  for (uint8_t k = 0; k < N_SENSORS; k++) {
    Sensor &x = s[k];
    uint8_t v = digitalRead(x.pin);
    if (v == LOW) anyOn = true;
    if (v != x.state && now - x.tChange >= GLITCH_US) {
      x.state = v; x.tChange = now;
      if (PRINT_EDGES) {
        Serial.print(F("S")); Serial.print(k); Serial.print(v ? F(" OFF") : F(" ON ")); Serial.print(F("  t_ms="));
        Serial.println(now / 1000);
      }
      if (v == LOW) onPulse(k, now);
    }
  }
  digitalWrite(LED_BUILTIN, anyOn ? HIGH : LOW);

  if (millis() - tReport >= 1000) {
    tReport += 1000;
    for (uint8_t k = 0; k < N_SENSORS; k++) {
      Sensor &x = s[k];
      Serial.print(F("[S")); Serial.print(k);
      Serial.print(F("] pulses/s=")); Serial.print(x.pulses - x.pulsesLastReport);
      x.pulsesLastReport = x.pulses;
      Serial.print(F(" rpm="));
      if (x.nNormal >= 2 && micros() - x.tPulse < 1000000UL)
        Serial.print(60.0e6 / ((float)medianNormal(x) * OPR_POSITIONS), 1);
      else Serial.print(F("-"));
      Serial.print(F(" index=")); Serial.print(x.indexes);
      Serial.print(F(" pattern_errors=")); Serial.print(x.patternErrors);
      Serial.print(F(" now=")); Serial.println(x.state ? F("OFF") : F("ON"));
    }
  }
}
