# Robot Arm ITB Insight — Hand-Tracking Robot Arm

Gerakkan tangan di depan webcam dan robot 3 servo (base, lengan, gripper) mengikutinya.
Spesifikasi lengkap ada di [CLAUDE.md](CLAUDE.md), salinan dari `PANDUAN_ARM_ROBOT.md`.

## Dua mode

| Mode | Perintah | Butuh ESP32? |
| --- | --- | --- |
| **SIMULASI** | `python -m app.main --mode sim` | Tidak. ESP32 ditiru oleh `VirtualESP32` (rate limiter 50 Hz, watchdog, clamp — persis firmware) |
| **ASLI** | `python -m app.main --mode real --port COM5` | Ya, lewat USB |

Kalau `--mode` tidak diberikan, mode dipilih dari `serial.mock` di `config/config.yaml`
(`true` = simulasi). Tampilan, mapping, dan state machine **sama persis** di kedua mode. Yang
berbeda hanya objek link (`MockLink` atau `SerialLink`), jadi kalau robot sudah jadi kamu cukup
ganti mode.

Sumber input (bisa dipakai di kedua mode):

- *(default)* webcam + MediaPipe Hands
- `--mouse`: tangan virtual. Posisi mouse = tangan, tahan klik kiri = cubit. Tidak perlu kamera.
- `--demo`: tangan virtual bergerak sendiri (untuk mengecek tampilan)
- `--video file.mp4`: input dari file video

Shortcut Windows: `jalankan_simulasi.bat` dan `jalankan_asli.bat` (argumen tambahan diteruskan,
mis. `jalankan_simulasi.bat --mouse`).

## Setup laptop (sekali saja)

MediaPipe butuh Python 3.10–3.12. Di laptop ini sudah ada Python 3.11:

```bash
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

## Tampilan: digital twin 3D (default)

Saat aplikasi dijalankan, Python membuka server lokal di `http://localhost:8765` dan jendela
aplikasi Edge/Chrome (tanpa address bar). Semua file UI (Three.js r160, font IBM Plex Sans/Mono)
ada di `app/web/`, jadi UI **tetap jalan tanpa internet** di lokasi pameran. Konsep visual, token
warna/tipe, dan alasan desainnya dicatat di [app/web/DESIGN.md](app/web/DESIGN.md).

- **Digital twin 3D.** Model robot dibuat prosedural dari `geometry.L` / `H0`: pedestal, servo
  base & lengan MG90S, lengan, dan gripper SG90 dengan 2 rahang. Pose model mengikuti posisi servo
  (hasil simulasi, atau perkiraan dari model firmware di mode asli). Selain itu ada kubah ruang kerja,
  sektor jangkauan di lantai, ghost target (garis putus-putus), jejak ujung gripper, dan label sudut
  tiap sendi. Sudut pandang: ISO, OPERATOR, ATAS, SAMPING (klik, atau tekan `V`). Kamera 3D bisa
  diputar/zoom dengan mouse.
- **Vision.** Video kamera dengan kerangka tangan, area interaksi, reticle, dan meter cubit.
  Pada `--mouse`, panel ini menjadi area tangan virtual: gerakkan pointer, tahan klik = cubit.
- **Telemetri.** Tabel sendi dengan bar rentang (posisi nyata + penanda target + sudut servo), grafik
  riwayat 10 detik (hover untuk melihat nilai), dan log sistem (state, TX/RX serial).
- **State visual.** Siaga (netral, robot berputar pelan + ajakan "Angkat tanganmu"), Aktif (hijau),
  Dihentikan (merah), dan robot terputus (kuning). Warnanya juga tampil di cincin LED status pada base
  model 3D.
- UI dirancang untuk layar 1920×1080 dan 1366×768. Untuk pameran, set `ui.fullscreen: true` atau
  tekan `F`.

UI jendela OpenCV lama masih ada sebagai cadangan: `--ui opencv` (atau `ui.backend: opencv`).

## Kontrol di aplikasi

| Tombol | Fungsi |
| --- | --- |
| `Space` / klik tombol merah | E-STOP (robot menahan posisi). Tekan lagi untuk **LANJUT** |
| `V` | Ganti sudut pandang 3D |
| `C` | Overlay kalibrasi: nilai x/y/pinch mentah, ambang cubit, perintah yang dikirim |
| `F` | Layar penuh on/off |
| `U` | (hanya simulasi) pura-pura cabut/colok kabel USB |
| `Q` | Keluar (dengan konfirmasi; robot dikirim ke home). Bisa juga `Ctrl+C` di terminal |

State: **SIAGA/IDLE** (robot di home, menunggu tangan) → **AKTIF/LIVE** (mengikuti tangan; kalau
tangan hilang sebentar, posisi ditahan) → kembali SIAGA setelah `ui.idle_timeout_s` detik tanpa tangan.

## Firmware ESP32 (saat hardware siap)

1. Rangkai sesuai CLAUDE.md §2: base GPIO 13, lengan GPIO 14, gripper GPIO 27. Servo diberi daya
   dari PSU 5 V ≥ 2 A terpisah, pasang kapasitor 1000 µF, dan **satukan GND dengan ESP32**.
2. Install PlatformIO (ekstensi VS Code, atau `pip install platformio`), lalu:
   ```bash
   cd firmware
   pio run -t upload
   ```
3. Cek dengan console:
   ```bash
   .venv\Scripts\python tools\serial_console.py --port COM5
   ```
   Coba `P` → `OK`, `A 90 90 0`, `A 120 60 1`, lalu `H`. Port COM bisa dilihat di Device Manager.
   Console ini juga bisa dijalankan tanpa hardware dengan `--mock`.
4. Kalibrasi (mode asli, bisa dilatih dulu dengan `--mock`):
   ```bash
   .venv\Scripts\python tools\calibrate_servo.py --port COM5
   ```
   Cari `center`, `min`, `max`, dan `sign` untuk base dan lengan, lalu `open` dan `close` untuk
   gripper. Setelah itu ketik `save`, dan hasilnya ditulis ke `config/config.yaml`.
5. Ubah `serial.port` di config (atau pakai `--port`), lalu jalankan `jalankan_asli.bat`.

### Protokol serial

Sesuai CLAUDE.md §5, ditambah satu perintah: `G <open> <close>` untuk mengatur sudut buka/tutup
gripper. Aplikasi mengirim perintah ini otomatis saat terhubung, sehingga `config.yaml` tetap jadi
satu-satunya sumber nilai kalibrasi. Setelah menerima `READY` (atau `OK` dari ping), aplikasi
mengirim `S` dan `G`. Kalau kabel dicabut, aplikasi otomatis mencoba menyambung lagi tiap 1 detik.

### Keselamatan

- Sudut di-clamp dua kali: di Python (`servos.*.min/max`) **dan** di firmware (`MIN_DEG`/`MAX_DEG`).
- Kecepatan dibatasi firmware: 3°/tick (≈150°/s), pulang ke home 1°/tick.
- Watchdog firmware: kalau tidak ada perintah `A` selama 1 detik, robot menahan posisi. Setelah
  10 detik, robot pulang pelan ke home.
- Kalau batas di firmware diubah, ubah juga `FirmwareParams` di `app/link.py`.
  `tests/test_link.py` akan gagal kalau keduanya tidak sama.

## Yang perlu dicek manual di hardware

- [ ] `A 90 90 0` / `A 120 60 1` / `H` / `P` dari console; servo bergerak halus, tanpa jitter
- [ ] Tidak ada brown-out (ESP32 reboot) saat 3 servo bergerak bersamaan
- [ ] Arah base dan lengan benar (tangan ke kiri → base ke kiri, tangan naik → lengan naik). Kalau
      terbalik, ubah `sign`
- [ ] Batas min/max aman secara mekanik (tidak menabrak)
- [ ] Gripper menutup saat dicubit, dan tidak berkedip di ambang
- [ ] Cabut USB saat LIVE → robot menahan posisi, lalu pulang ke home setelah 10 detik. Colok lagi →
      aplikasi tersambung otomatis

## Struktur

```
app/        main.py, controller.py, config.py, tracker.py, sources.py, filters.py, mapping.py,
            kinematics.py, servo_map.py, link.py, state.py, web_server.py, ui.py (OpenCV lama)
app/web/    index.html, css/, js/twin.js (model 3D), js/hud.js, js/main.js, vendor/three, fonts/
firmware/   platformio.ini, src/main.cpp
tools/      serial_console.py, calibrate_servo.py
tests/      48 unit test (pytest): logika, firmware sim, SerialLink port palsu, server web
config/     config.yaml
```

Status milestone: M1–M6 sudah diimplementasikan dan dites di simulasi, tetapi belum diuji di
hardware. M7 (record & playback) opsional dan belum dikerjakan.
