// =====================================================================
//  Robot Arm ITB Insight - Firmware ESP32
//  3 servo: base (GPIO 13), lengan (GPIO 14), gripper (GPIO 27)
//  Protokol serial 115200, ASCII, satu perintah per baris '\n':
//    A <base> <lengan> <grip>   target sudut servo; grip 0 = buka, 1 = tutup
//    H                          pulang pelan ke home            -> OK
//    S <deg_per_tick>           batas kecepatan (1..30)         -> OK
//    G <open> <close>           sudut gripper buka/tutup (0..180) -> OK   (tambahan)
//    P                          ping                            -> OK
//  Balasan: READY (sekali setelah boot), OK, ERR <pesan>
//
//  PENTING: logika ini ditiru oleh app/link.py (VirtualESP32) untuk mode simulasi.
//  Kalau mengubah perilaku di sini, ubah juga di sana.
// =====================================================================
#include <Arduino.h>
#include <ESP32Servo.h>

// ---------------- Konstanta (sesuaikan setelah kalibrasi mekanik) ----------------
static const int PIN_BASE   = 13;
static const int PIN_LENGAN = 14;
static const int PIN_GRIP   = 27;

// Batas keselamatan per servo {base, lengan, gripper}
static const int MIN_DEG[3] = {20, 30, 0};
static const int MAX_DEG[3] = {160, 160, 180};

static const int HOME_BASE   = 90;
static const int HOME_LENGAN = 90;

static int gripOpenDeg  = 20;   // default, bisa diubah dengan perintah G
static int gripCloseDeg = 80;

static const uint32_t TICK_MS          = 20;     // loop servo 50 Hz
static const int      DEFAULT_MAX_STEP = 3;      // derajat per tick (~150 deg/s)
static const int      HOME_STEP        = 1;      // derajat per tick saat pulang ke home
static const uint32_t HOLD_TIMEOUT_MS  = 1000;   // tanpa perintah A -> tahan posisi
static const uint32_t HOME_TIMEOUT_MS  = 10000;  // tanpa perintah A -> pulang ke home

static const int SERVO_MIN_US = 500;             // lebar pulsa MG90S / SG90
static const int SERVO_MAX_US = 2400;
// ----------------------------------------------------------------------------------

enum WatchdogState { WD_ACTIVE, WD_HOLD, WD_HOME };

Servo servos[3];
static const int PINS[3] = {PIN_BASE, PIN_LENGAN, PIN_GRIP};

int currentDeg[3];
int targetDeg[3];
int maxStep = DEFAULT_MAX_STEP;
int stepNow = DEFAULT_MAX_STEP;
uint32_t lastACommandMs = 0;
uint32_t lastTickMs = 0;
WatchdogState wdState = WD_HOME;

char lineBuf[64];
size_t lineLen = 0;
bool lineOverflow = false;

static int clampDeg(int i, int v) { return constrain(v, MIN_DEG[i], MAX_DEG[i]); }

static void goHome() {
  targetDeg[0] = clampDeg(0, HOME_BASE);
  targetDeg[1] = clampDeg(1, HOME_LENGAN);
  targetDeg[2] = clampDeg(2, gripOpenDeg);
  stepNow = HOME_STEP;
}

// Parse bilangan bulat ketat (boleh tanda minus). true kalau valid.
static bool parseInt(const char* s, int& out) {
  if (s == nullptr || *s == '\0') return false;
  char* end = nullptr;
  long v = strtol(s, &end, 10);
  if (end == s || *end != '\0') return false;
  if (v < -10000 || v > 10000) return false;
  out = (int)v;
  return true;
}

static void handleLine(char* line) {
  char* tok[5];
  int n = 0;
  for (char* t = strtok(line, " \t\r"); t && n < 5; t = strtok(nullptr, " \t\r")) tok[n++] = t;
  if (n == 0) return;
  char cmd = toupper(tok[0][0]);
  bool single = tok[0][1] == '\0';

  if (single && cmd == 'A' && n == 4) {
    int b, l, g;
    if (!parseInt(tok[1], b) || !parseInt(tok[2], l) || !parseInt(tok[3], g)) {
      Serial.println("ERR angka tidak valid"); return;
    }
    if (g != 0 && g != 1) { Serial.println("ERR grip harus 0 atau 1"); return; }
    targetDeg[0] = clampDeg(0, b);
    targetDeg[1] = clampDeg(1, l);
    targetDeg[2] = clampDeg(2, g ? gripCloseDeg : gripOpenDeg);
    stepNow = maxStep;
    lastACommandMs = millis();
    wdState = WD_ACTIVE;
    return;  // A tidak dibalas (supaya serial tidak penuh)
  }
  if (single && cmd == 'H' && n == 1) {
    goHome();
    wdState = WD_HOME;
    Serial.println("OK"); return;
  }
  if (single && cmd == 'S' && n == 2) {
    int v;
    if (!parseInt(tok[1], v)) { Serial.println("ERR angka tidak valid"); return; }
    if (v < 1 || v > 30) { Serial.println("ERR S harus 1..30"); return; }
    maxStep = v;
    if (wdState == WD_ACTIVE) stepNow = v;
    Serial.println("OK"); return;
  }
  if (single && cmd == 'G' && n == 3) {
    int o, c;
    if (!parseInt(tok[1], o) || !parseInt(tok[2], c)) { Serial.println("ERR angka tidak valid"); return; }
    if (o < 0 || o > 180 || c < 0 || c > 180) { Serial.println("ERR G harus 0..180"); return; }
    bool wasClosed = abs(targetDeg[2] - gripCloseDeg) < abs(targetDeg[2] - gripOpenDeg);
    gripOpenDeg = o;
    gripCloseDeg = c;
    targetDeg[2] = clampDeg(2, wasClosed ? c : o);
    Serial.println("OK"); return;
  }
  if (single && cmd == 'P' && n == 1) {
    Serial.println("OK"); return;
  }
  Serial.println("ERR perintah tidak dikenal");
}

// Baca serial tanpa blocking; baris terlalu panjang dibuang dan dibalas ERR.
static void pollSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (lineOverflow) {
        Serial.println("ERR baris terlalu panjang");
      } else {
        lineBuf[lineLen] = '\0';
        handleLine(lineBuf);
      }
      lineLen = 0;
      lineOverflow = false;
    } else if (!lineOverflow) {
      if (lineLen < sizeof(lineBuf) - 1) lineBuf[lineLen++] = c;
      else lineOverflow = true;
    }
  }
}

static void servoTick(uint32_t now) {
  uint32_t idle = now - lastACommandMs;
  if (wdState == WD_ACTIVE && idle > HOLD_TIMEOUT_MS) {
    wdState = WD_HOLD;                                   // tahan posisi terakhir
    for (int i = 0; i < 3; i++) targetDeg[i] = currentDeg[i];
  }
  if (wdState == WD_HOLD && idle > HOME_TIMEOUT_MS) {
    wdState = WD_HOME;                                   // pulang pelan ke home
    goHome();
  }
  for (int i = 0; i < 3; i++) {
    int d = targetDeg[i] - currentDeg[i];
    if (abs(d) <= stepNow) currentDeg[i] = targetDeg[i];
    else currentDeg[i] += (d > 0) ? stepNow : -stepNow;
    servos[i].write(currentDeg[i]);
  }
}

void setup() {
  Serial.begin(115200);
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);

  currentDeg[0] = clampDeg(0, HOME_BASE);
  currentDeg[1] = clampDeg(1, HOME_LENGAN);
  currentDeg[2] = clampDeg(2, gripOpenDeg);
  for (int i = 0; i < 3; i++) {
    targetDeg[i] = currentDeg[i];
    servos[i].setPeriodHertz(50);
    servos[i].attach(PINS[i], SERVO_MIN_US, SERVO_MAX_US);
    servos[i].write(currentDeg[i]);
  }
  lastACommandMs = millis();
  lastTickMs = millis();
  delay(200);
  Serial.println("READY");
}

void loop() {
  pollSerial();
  uint32_t now = millis();
  if (now - lastTickMs >= TICK_MS) {
    lastTickMs += TICK_MS;
    if (now - lastTickMs > 10 * TICK_MS) lastTickMs = now;  // jangan mengejar kalau tertinggal jauh
    servoTick(now);
  }
}
