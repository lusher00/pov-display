// povd-hub bring-up sketch (Arduino, ESP32 core 2.x/3.x, board "ESP32S3 Dev Module",
// USB CDC On Boot: Enabled). Type commands in the serial monitor at 115200, newline ending.
//
//   en 1 / en 0   BUCK_EN (IO4): turn the 5 V / 15 A buck on / off. Starts OFF.
//   i             read I_IN (IO1, INA240 output) in mV, 16-sample average
//   walk          pulse PCLK, then D0..D7 one at a time, 1 s each (scope J2/J3 pins 9-16)
//   dot [n] [b]   moving dot on all 8 channels, n LEDs (default 62), brightness b 1..31 (default 4)
//   off [n]       send all-off to n LEDs
//   enc           toggle printing ENC_A / ENC_B edges
//
// Pin map from povd-hub.kicad_pcb (U5 Waveshare ESP32-S3-Zero):
//   IO1 I_IN, IO2 ENC_B, IO3 ENC_A, IO4 BUCK_EN, IO5 LCD_PCLK (strip clock),
//   IO6..IO12 LCD_D0..D6, IO13 LCD_D7 (strip data)

const int PIN_I_IN = 1, PIN_ENC_B = 2, PIN_ENC_A = 3, PIN_BUCK_EN = 4, PIN_CLK = 5;
const int PIN_D[8] = {6, 7, 8, 9, 10, 11, 12, 13};

bool encPrint = false;
volatile uint32_t encA = 0, encB = 0;
void IRAM_ATTR isrA() { encA++; }
void IRAM_ATTR isrB() { encB++; }

void dataAll(int v) { for (int i = 0; i < 8; i++) digitalWrite(PIN_D[i], v); }

void sendByte(uint8_t b) {          // same byte on all 8 channels, MSB first, shared clock
  for (int i = 7; i >= 0; i--) {
    dataAll((b >> i) & 1);
    delayMicroseconds(1);
    digitalWrite(PIN_CLK, HIGH); delayMicroseconds(1);
    digitalWrite(PIN_CLK, LOW);
  }
}

void sendFrame(int n, int lit, uint8_t bright, uint8_t r, uint8_t g, uint8_t b) {
  for (int i = 0; i < 4; i++) sendByte(0x00);                  // start frame
  for (int k = 0; k < n; k++) {
    bool on = (k == lit);
    sendByte(0xE0 | (on ? bright : 0));
    sendByte(on ? b : 0); sendByte(on ? g : 0); sendByte(on ? r : 0);
  }
  for (int i = 0; i < 4 + n / 16; i++) sendByte(0x00);          // end frame (SK9822 wants n/2 extra clocks)
}

void setup() {
  pinMode(PIN_BUCK_EN, OUTPUT); digitalWrite(PIN_BUCK_EN, LOW);
  pinMode(PIN_CLK, OUTPUT); digitalWrite(PIN_CLK, LOW);
  for (int i = 0; i < 8; i++) { pinMode(PIN_D[i], OUTPUT); digitalWrite(PIN_D[i], LOW); }
  pinMode(PIN_ENC_A, INPUT); pinMode(PIN_ENC_B, INPUT);
  attachInterrupt(PIN_ENC_A, isrA, CHANGE); attachInterrupt(PIN_ENC_B, isrB, CHANGE);
  analogReadResolution(12);
  Serial.begin(115200);
  delay(1500);
  Serial.println("povd-hub bringup. BUCK_EN=0. commands: en 1|0, i, walk, dot [n] [b], off [n], enc");
}

void loop() {
  static uint32_t lastA = 0, lastB = 0;
  if (encPrint && (encA != lastA || encB != lastB)) {
    lastA = encA; lastB = encB;
    Serial.printf("ENC_A edges %lu (now %d)  ENC_B edges %lu (now %d)\n",
                  (unsigned long)lastA, digitalRead(PIN_ENC_A), (unsigned long)lastB, digitalRead(PIN_ENC_B));
  }
  if (!Serial.available()) { delay(5); return; }
  String line = Serial.readStringUntil('\n'); line.trim();
  int a1 = -1, a2 = -1;
  char cmd[8] = {0};
  sscanf(line.c_str(), "%7s %d %d", cmd, &a1, &a2);
  String c(cmd);

  if (c == "en") {
    digitalWrite(PIN_BUCK_EN, a1 == 1 ? HIGH : LOW);
    Serial.printf("BUCK_EN=%d\n", a1 == 1);
  } else if (c == "i") {
    uint32_t s = 0; for (int k = 0; k < 16; k++) s += analogReadMilliVolts(PIN_I_IN);
    Serial.printf("I_IN = %lu mV\n", (unsigned long)(s / 16));
  } else if (c == "walk") {
    Serial.println("PCLK"); for (int k = 0; k < 1000; k++) { digitalWrite(PIN_CLK, k & 1); delay(1); }
    digitalWrite(PIN_CLK, LOW);
    for (int i = 0; i < 8; i++) {
      Serial.printf("D%d (IO%d) high\n", i, PIN_D[i]);
      digitalWrite(PIN_D[i], HIGH); delay(1000); digitalWrite(PIN_D[i], LOW);
    }
    Serial.println("walk done");
  } else if (c == "dot") {
    int n = a1 > 0 ? a1 : 62, br = (a2 >= 1 && a2 <= 31) ? a2 : 4;
    Serial.printf("dot over %d LEDs, brightness %d; send any key to stop\n", n, br);
    for (int lit = 0; !Serial.available(); lit = (lit + 1) % n) {
      uint8_t r = (lit % 3 == 0) * 255, g = (lit % 3 == 1) * 255, b = (lit % 3 == 2) * 255;
      sendFrame(n, lit, br, r, g, b);
      delay(30);
    }
    while (Serial.available()) Serial.read();
    sendFrame(n, -1, 0, 0, 0, 0);
    Serial.println("dot stopped, strips off");
  } else if (c == "off") {
    sendFrame(a1 > 0 ? a1 : 62, -1, 0, 0, 0, 0); Serial.println("off");
  } else if (c == "enc") {
    encPrint = !encPrint; Serial.printf("enc print %s\n", encPrint ? "on" : "off");
  } else if (line.length()) {
    Serial.println("? en 1|0, i, walk, dot [n] [b], off [n], enc");
  }
}
