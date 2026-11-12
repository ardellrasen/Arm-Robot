# Robot Arm ITB Insight — Hand-Tracking Robot Arm (Computer Vision)

> Dokumen ini adalah spesifikasi proyek untuk Claude Code. Simpan sebagai `CLAUDE.md` di root repo,
> lalu minta Claude Code: *"Baca CLAUDE.md dan kerjakan milestone M1."* Kerjakan per milestone,
> jangan semuanya sekaligus.

## 1. Ringkasan proyek

Lengan robot meja sederhana untuk pameran **ITB Insight**. Visitor menggerakkan tangan di depan
webcam dan robot mengikuti secara real-time ("efek telekinesis"):

- tangan ke **kiri–kanan** → **base** berputar
- tangan **naik–turun** → **lengan** terangkat/turun
- **cubit** jempol–telunjuk → **gripper** menutup

Fitur tambahan opsional (milestone terakhir): visitor merekam gerakannya, lalu tombol **Play**
membuat robot mengulang gerakan yang sama.

Alur data:

```
Webcam → Laptop (Python: MediaPipe Hands → filter → mapping → sudut servo → UI)
       → USB serial → ESP32 (rate limiter) → 3 servo total
```

## 2. Hardware (tetap, jangan diganti tanpa persetujuan)

Robot ini **hanya punya 3 servo total**: 2 sendi gerak + 1 gripper. Jangan menambah sendi.

| Komponen | Detail |
| --- | --- |
| Kontroler | ESP32 DevKit (Arduino core), terhubung ke laptop via USB |
| Servo base | 1× MG90S, putaran horizontal (yaw), GPIO 13 |
| Servo lengan | 1× MG90S, angkat/turun lengan (pitch) di atas base, GPIO 14 |
| Servo gripper | 1× SG90, buka/tutup capit di ujung lengan, GPIO 27 |
| Daya servo | PSU 5V ≥ 2A terpisah, kapasitor 1000 µF, GND disatukan dengan ESP32 |
| Kamera | Webcam USB 720p 30 fps, posisi tetap menghadap area interaksi |
| Komputer | Laptop Windows/Linux/macOS |

Geometri (PLACEHOLDER — akan diukur, harus lewat config, jangan di-hardcode):

- `L` panjang lengan dari sumbu servo lengan ke titik tengah gripper: 10.0 cm
- `H0` tinggi sumbu servo lengan dari meja: 6.0 cm

Konsekuensi desain 2 sendi: panjang lengan tetap, jadi ujung gripper bergerak di permukaan
"kubah" berjari-jari `L`. Tidak ada gerak maju–mundur terpisah, dan tidak perlu estimasi jarak
tangan ke kamera.

## 3. Stack software

- **Laptop:** Python 3.10+ (versi yang didukung MediaPipe saat ini), `opencv-python`,
  `mediapipe`, `pyserial`, `numpy`, `pyyaml`, `pytest`. Dependensi di `requirements.txt`
  (versi di-pin), pakai virtualenv.
- **ESP32:** Arduino framework via **PlatformIO** (`platformio.ini`), library `ESP32Servo`.
- Bahasa komentar dan teks UI: **Bahasa Indonesia**. Nama variabel/fungsi: English.

## 4. Struktur repo yang diharapkan

```
robot-arm-itb-insight/
├── CLAUDE.md
├── README.md                  # cara setup, kalibrasi, menjalankan
├── requirements.txt
├── config/
│   └── config.yaml            # SEMUA parameter yang bisa dikalibrasi
├── firmware/
│   ├── platformio.ini
│   └── src/main.cpp
├── app/
│   ├── main.py                # entry point: python -m app.main
│   ├── config.py              # load + validasi config.yaml
│   ├── tracker.py             # MediaPipe Hands → fitur tangan
│   ├── filters.py             # EMA dan One Euro filter
│   ├── mapping.py             # fitur tangan → (yaw, pitch, grip)
│   ├── kinematics.py          # FK untuk visualisasi + konversi tinggi ↔ pitch
│   ├── servo_map.py           # sudut sendi → sudut servo (offset, arah, batas)
│   ├── link.py                # serial ke ESP32 + MockLink (tanpa hardware)
│   ├── ui.py                  # tampilan, tombol, overlay, visual robot
│   ├── state.py               # state machine aplikasi
│   └── recorder.py            # OPSIONAL (M7): rekam / simpan / playback
├── tools/
│   ├── calibrate_servo.py     # tool interaktif kalibrasi offset & batas servo
│   └── serial_console.py      # kirim perintah manual ke ESP32
└── tests/
    ├── test_mapping.py
    ├── test_kinematics.py
    └── test_servo_map.py
```

## 5. Protokol serial (Laptop ↔ ESP32)

115200 baud, teks ASCII, satu perintah per baris diakhiri `\n`. Angka bulat derajat servo (0–180).

| Arah | Perintah | Arti |
| --- | --- | --- |
| → ESP32 | `A <base> <lengan> <grip>` | Target sudut servo; `grip` 0 = buka, 1 = tutup |
| → ESP32 | `H` | Kembali pelan ke pose home dari konstanta firmware |
| → ESP32 | `S <deg_per_tick>` | Ubah batas kecepatan (derajat per tick 20 ms) |
| → ESP32 | `P` | Ping |
| ← ESP32 | `READY` | Dikirim sekali setelah boot |
| ← ESP32 | `OK` | Balasan untuk `P`, `H`, `S` |
| ← ESP32 | `ERR <pesan>` | Perintah tidak valid |

## 6. Spesifikasi firmware ESP32 (`firmware/src/main.cpp`)

- 3 servo: base (GPIO 13), lengan (GPIO 14), gripper (GPIO 27).
- Loop servo tetap **50 Hz** (tick 20 ms). Tiap tick, sudut saat ini bergerak menuju target
  maksimal `MAX_STEP` derajat (default 3°/tick ≈ 150°/s). Ini rate limiter utama.
- Batas sudut min/max per servo dan pose home sebagai konstanta di atas file.
  Target selalu di-`constrain` ke batas itu.
- Sudut gripper buka/tutup berupa konstanta (default 20° / 80°).
- **Watchdog:** tidak ada perintah `A` selama 1 detik → tahan posisi terakhir.
  Selama 10 detik → bergerak pelan ke home.
- Parsing tanpa blocking; baris rusak dibalas `ERR` dan diabaikan.
- Saat boot: attach servo di pose home, lalu kirim `READY`.

## 7. Spesifikasi aplikasi Python

### 7.1 Tracker (`tracker.py`)
- MediaPipe Hands, `max_num_hands=1`, confidence dari config.
- Frame di-mirror (`cv2.flip(frame, 1)`) agar gerakan terasa natural.
- Output per frame: `HandFeatures(x, y, pinch, visible)`:
  - `x, y` = posisi landmark 9 (pangkal jari tengah), ternormalisasi 0–1
  - `pinch` = jarak landmark 4 → 8, dinormalisasi dengan ukuran tangan
    (jarak landmark 0 → 9) supaya tidak bergantung jarak tangan ke kamera
- Kalau ada beberapa tangan di frame, pakai yang terbesar (paling dekat).

### 7.2 Filter (`filters.py`)
- Implementasikan **One Euro filter** (default) dan EMA; pilihan dan parameter dari config.
- Diterapkan ke `x` dan `y` sebelum mapping.

### 7.3 Mapping (`mapping.py`)
- `x` → `yaw` derajat (default ±60°), linear dengan clamp.
- `y` → **tinggi ujung gripper** `z` (cm) dalam rentang config, lalu dikonversi ke `pitch`
  oleh `kinematics.py`. Opsi config `y_mode: "height" | "angle"`:
  - `height` (default): tangan naik X → ujung gripper naik secara linear (terasa lebih natural)
  - `angle`: `y` langsung linear ke `pitch`
- `pinch < pinch_close` → grip = 1; `pinch > pinch_open` → grip = 0 (**hysteresis**, supaya
  gripper tidak berkedip).

### 7.4 Kinematika (`kinematics.py`)
- Konversi tinggi ke pitch: `pitch = asin((z − H0) / L)`, dengan `z` di-clamp ke
  `[H0 − L·sin(pitch_max_down), H0 + L·sin(pitch_max_up)]` agar asin selalu valid.
- FK untuk visualisasi: ujung gripper = `(L·cos(pitch)·cos(yaw), L·cos(pitch)·sin(yaw), H0 + L·sin(pitch))`.
- Fungsi pure (tanpa I/O), punya unit test.

### 7.5 Servo map (`servo_map.py`)
- `servo_deg = offset + sign × joint_deg` untuk base dan lengan, lalu clamp ke `min/max`.
- Gripper: `open`/`close` dari config. Semua nilai dari config.

### 7.6 Link (`link.py`)
- `SerialLink` (pyserial, non-blocking, auto-reconnect kalau kabel dicabut) dan `MockLink`
  (log perintah, tanpa hardware). Dipilih lewat `--mock` atau config.
- Kirim `A ...` hanya kalau nilainya berubah, atau minimal tiap 200 ms (keep-alive watchdog).

### 7.7 State machine (`state.py`)

```
IDLE ──tangan terdeteksi──▶ LIVE ──tidak ada tangan > N detik──▶ IDLE
  ▲                                                               │
  └──────────────────────── E-STOP (kapan pun) ◀──────────────────┘
```

- IDLE: robot di home, layar menampilkan ajakan ("Angkat tanganmu di area kotak").
- LIVE: robot mengikuti tangan. Kalau tangan hilang sebentar, robot **menahan posisi terakhir**.
- E-STOP (keyboard `Space` dan tombol UI) selalu bisa: hold posisi, masuk IDLE.
- Kalau M7 dikerjakan, tambahkan state RECORDING dan PLAYING (lihat 7.9).

### 7.8 UI (`ui.py`)
- Jendela OpenCV, mode fullscreen (opsi windowed untuk development).
- Preview kamera dengan landmark tangan, kotak area interaksi, indikator state besar,
  status koneksi ESP32, dan FPS.
- **Visual robot** di pojok: tampak atas (yaw) dan tampak samping (pitch) dari FK, plus status
  gripper. Ini membuat sistem bisa dites tanpa robot.
- Tombol klik mouse besar: **E-STOP** (dan Start/Stop/Play kalau M7 dikerjakan).
  Shortcut: `Space` e-stop, `q` keluar, `c` mode kalibrasi.
- Teks UI Bahasa Indonesia, ramah visitor.

### 7.9 Recorder (`recorder.py`) — OPSIONAL, hanya di M7
- Rekam `(t_relatif_detik, base, lengan, grip)` sudut servo yang benar-benar dikirim.
- Durasi maksimal dari config (default 30 detik), lalu otomatis stop.
- Playback: gerak pelan ke frame pertama (lead-in 1 detik), lalu kirim tiap frame sesuai
  timestamp aslinya. Selama PLAYING, input kamera diabaikan.
- Simpan/muat CSV di `recordings/` (di-.gitignore).

## 8. `config/config.yaml` (contoh awal, semua nilai PLACEHOLDER)

```yaml
serial:
  port: "COM5"          # atau /dev/ttyUSB0
  baud: 115200
  mock: false
camera:
  index: 0
  width: 1280
  height: 720
  mirror: true
geometry:
  L: 10.0
  H0: 6.0
tracking:
  min_detection_confidence: 0.7
  min_tracking_confidence: 0.6
filter:
  type: one_euro        # one_euro | ema
  min_cutoff: 1.0
  beta: 0.02
  ema_alpha: 0.3
mapping:
  x_range: [0.15, 0.85]
  yaw_range: [60, -60]          # derajat
  y_mode: height                # height | angle
  y_range: [0.85, 0.15]         # bawah frame → atas frame
  pitch_range: [-30, 60]        # derajat, dipakai untuk clamp
  pinch_close: 0.35             # relatif terhadap ukuran tangan
  pinch_open: 0.50
servos:                         # servo_deg = offset + sign * joint_deg
  base:   {offset: 90, sign: 1, min: 20, max: 160}
  lengan: {offset: 90, sign: 1, min: 30, max: 160}
  grip:   {open: 20, close: 80}
ui:
  fullscreen: true
  idle_timeout_s: 3
recording:                      # hanya dipakai kalau M7 dikerjakan
  enabled: false
  max_seconds: 30
  lead_in_seconds: 1.0
```

## 9. Milestone (kerjakan berurutan, berhenti dan laporkan di akhir tiap milestone)

- **M1 — Firmware & serial:** firmware ESP32 lengkap (bagian 6) + `tools/serial_console.py`.
  Selesai jika: `A 90 90 0`, `A 120 60 1`, `H`, `P` bekerja dari console dan servo bergerak halus.
- **M2 — Mapping, kinematika, servo map + tes:** `config.py`, `mapping.py`, `kinematics.py`,
  `servo_map.py`, unit test. Selesai jika: `pytest` lulus, termasuk clamp di luar rentang,
  konsistensi tinggi → pitch → FK, hysteresis gripper, dan batas servo.
- **M3 — Tracker & UI tanpa hardware:** jalan dengan `--mock`, menampilkan landmark, area interaksi,
  dan visual robot. Selesai jika: tangan digerakkan dan visual robot mengikuti dengan halus.
- **M4 — Integrasi live:** `SerialLink` + rate limiting kirim + keep-alive watchdog.
  Selesai jika: robot fisik mengikuti tangan dan gripper menutup saat dicubit.
- **M5 — Mode pameran:** fullscreen, state machine IDLE/LIVE/E-STOP, auto-reconnect,
  teks ajakan, tahan posisi saat tangan hilang.
- **M6 — Tool kalibrasi:** `tools/calibrate_servo.py` untuk mencari offset/sign/batas tiap servo
  dan sudut buka/tutup gripper secara interaktif, lalu menulis ke `config.yaml`.
- **M7 — OPSIONAL: Record & playback:** hanya dikerjakan kalau diminta. Recorder + state
  RECORDING/PLAYING + tombol Start/Stop/Play. Selesai jika: rekaman 10 detik diputar ulang
  dengan selisih durasi < 2%.

## 10. Aturan kerja untuk Claude Code

- Robot hanya punya **3 servo** (base, lengan, gripper). Jangan menambah sendi, IK multi-link,
  atau estimasi jarak/depth.
- Jangan hardcode parameter fisik; semuanya lewat `config.yaml`.
- Logika inti (mapping, kinematika, servo map) harus pure dan punya unit test.
- Semua fitur harus bisa dijalankan dengan `--mock` (tanpa ESP32) dan `--video <file>`
  (input video, bukan webcam) untuk pengujian.
- Keselamatan: sudut servo selalu di-clamp di Python **dan** di firmware; kecepatan dibatasi
  di firmware.
- Jangan menambah dependensi berat (ROS, PyTorch, dsb.) tanpa bertanya.
- Setelah tiap milestone: jalankan tes, perbarui `README.md`, dan ringkas apa yang perlu dicek
  manual di hardware.
- Kalau ada keputusan desain yang ambigu, tanya dulu sebelum menulis banyak kode.

## 11. Hal yang belum diputuskan (tanyakan kalau relevan)

- Ukuran final `L`, `H0`, dan bentuk gripper.
- Rentang putar base dan rentang angkat lengan yang aman secara mekanik.
- Apakah record & playback (M7) jadi dipakai di pameran.
- UI tetap di jendela OpenCV atau pindah ke web/PyGame untuk tampilan yang lebih bagus.
