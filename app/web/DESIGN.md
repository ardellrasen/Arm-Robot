# Catatan desain UI — Robot Arm ITB Insight

Acuan: skill `frontend-design` (anthropics/skills) dan `impeccable` (pbakaus/impeccable:
craft-floor + operate mode), ditemukan lewat registry skills.sh.

## Brief
- **Subjek:** lengan robot meja 3 servo yang dikendalikan gestur, dipamerkan di ITB Insight.
- **Pengguna:** (1) pengunjung yang berdiri 1–2 m dari layar dan hanya punya beberapa detik untuk
  paham; (2) operator yang memantau koneksi, sudut servo, dan E-STOP.
- **Tugas utama:** pengunjung tahu robot mengikuti tangannya; operator bisa menghentikan robot
  kapan saja.

## Konsep
Lantai bengkel abu-abu netral. Satu-satunya benda berwarna jenuh adalah lengan robot oranye di
tengah. Instrumen di sekitarnya tenang (gaya HMI ISA-101: kondisi normal berwarna netral) dan
hanya berwarna saat ada status yang perlu diperhatikan. Elemen yang paling menonjol: model 3D.
Elemen fisik yang dikenal dari dunia industri: tombol E-STOP merah di pelat kuning.

## Token
| Peran | Nilai |
| --- | --- |
| ground (latar app / scene 3D) | `#1f2225` |
| surface (panel) | `#26292d` |
| bar (top/bottom bar, netral kedua) | `#17191b` |
| line (pemisah 1px) | `#3a3f45` |
| ink / ink-2 | `#eceff1` / `#a3abb3` |
| robot (hanya di model 3D) | `#e2702a` |
| status: aktif / peringatan / kritis | `#0ca30c` / `#fab219` / `#d03b3b` (dataviz status palette) |
| seri grafik: base / lengan | `#3987e5` / `#d95926` (divalidasi CVD di `#26292d`) |

- Status SIAGA = netral (bukan warna), sesuai ISA-101.
- **Tipografi:** IBM Plex Sans (400/500/600) untuk semuanya, angka `tabular-nums`. IBM Plex Mono
  hanya untuk log serial (data mentah). Skala rem tetap, rasio ~1.2: 12 / 14 / 16 / 19 / 23 / 28 / 40.
- **Teks:** sentence case, tanpa eyebrow huruf kapital berjarak, tanpa string meta bertitik tengah.

## Wireframe
```
┌ Lengan Robot ITB Insight ...................... Simulasi │ Terhubung │ 30 fps  14:02 ┐
│ ┌─ model 3D (hero) ──────────────────────────┐ ┌ Kamera ───────────────────┐ │
│ │                                            │ │ video + kerangka tangan    │ │
│ │        lengan oranye di lantai abu         │ │ Cubit ▕████░░░▏ 0.42       │ │
│ │                                            │ ├ Sendi ────────────────────┤ │
│ │ [ISO|Operator|Atas|Samping]   x y z (cm)   │ │ Base    +23.4° ▕─▲──●───▏  │ │
│ └────────────────────────────────────────────┘ │ Lengan  +12.0° ▕───●▲───▏  │ │
│                                                │ Capit   Tertutup  80°      │ │
│                                                ├ Riwayat 10 detik ─────────┤ │
│                                                ├ Log ──────────────────────┤ │
├────────────────────────────────────────────────────────────────────────────┤
│ ● Aktif  Robot mengikuti tanganmu    ⇆ ⇅ ✊ petunjuk          [ E-STOP ] │
└────────────────────────────────────────────────────────────────────────────┘
```

## Prinsip
1. Warna = informasi. Aksen hanya untuk status, pilihan aktif, dan aksi utama.
2. Tidak ada glow, neon, glass/blur, garis pinggir berwarna (side stripe), scanline, atau
   animasi dekoratif. Satu-satunya gerak ambient adalah robot yang berputar pelan saat SIAGA.
3. Instrumen memakai bar linear (rentang + posisi + penanda target), bukan cincin progres.
4. Kolom kanan adalah satu permukaan yang dibagi garis 1px, bukan kumpulan kartu.
5. Status selalu berupa bentuk + label, tidak hanya warna.

## Yang diubah dari versi pertama (dan alasannya)
- Cyan neon di atas hampir-hitam + bloom: termasuk "near-black + satu aksen terang", default AI.
  Diganti abu netral, dengan warna hanya di robot dan status.
- Rajdhani + Share Tech Mono: font display "sci-fi" di label dan data, monospace sebagai kostum.
  Diganti satu keluarga, IBM Plex Sans (vernakular engineering/industri).
- Label huruf kapital berjarak, titik tengah, sudut bracket, scanline, pulse di semua titik,
  border-left berwarna: semuanya dekorasi, jadi dihapus.
- Gauge busur ×3 dalam kartu kembar diganti tabel sendi dengan bar linear.
