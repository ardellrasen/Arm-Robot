// =========================================================================
//  Robot Arm ITB Insight — UI digital twin. Menerima telemetri (SSE) dari Python,
//  mengirim perintah (E-STOP, kalibrasi, dll.) lewat POST /api/cmd.
// =========================================================================
import { DigitalTwin } from "./twin.js";
import { CameraOverlay, JointRow, GripRow, HistoryChart, EventLog, fmt } from "./hud.js";

const $ = (id) => document.getElementById(id);
const body = document.body;

const STATE_LABEL = { IDLE: "Siaga", LIVE: "Aktif", ESTOP: "Dihentikan" };
const STATE_MSG = {
  IDLE: "Angkat tanganmu di depan kamera untuk mulai",
  LIVE: "Robot mengikuti tanganmu. Cubit untuk menjepit.",
  ESTOP: "Operator menghentikan robot. Robot diam di posisinya.",
};

async function post(cmd, extra = {}) {
  try {
    await fetch("api/cmd", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd, ...extra }) });
  } catch { /* server mati: layar "menghubungkan" sudah tampil */ }
}

async function boot() {
  let cfg;
  for (;;) {                       // tunggu server Python siap
    try { cfg = await (await fetch("api/config")).json(); break; }
    catch { body.classList.add("no-server"); await new Promise((r) => setTimeout(r, 1000)); }
  }
  body.classList.remove("no-server");
  body.dataset.mode = cfg.mode;
  $("modeChip").textContent = cfg.mode === "ASLI" ? "Robot asli" : "Simulasi";

  const twin = new DigitalTwin($("twinCanvas"), cfg);
  const cam = new CameraOverlay(cfg, (m) => post("mouse", m));
  const rBase = new JointRow($("jBase"), cfg.mapping.yaw_range, true);
  const rArm = new JointRow($("jArm"), cfg.mapping.pitch_range, false);
  const rGrip = new GripRow($("jGrip"));
  const chart = new HistoryChart(cfg);
  const log = new EventLog();
  log.add(`Aplikasi siap (${cfg.mode.toLowerCase()}), L ${cfg.geometry.L} cm, H0 ${cfg.geometry.H0} cm`);

  // ---- label sendi mengikuti model 3D ----
  const tags = { base: $("tagBase"), arm: $("tagArm"), grip: $("tagGrip") };
  const offs = { base: [18, -6], arm: [18, -34], grip: [16, -30] };
  twin.onFrame = () => {
    const a = twin.anchors();
    for (const k of Object.keys(tags)) {
      const p = a[k], [ox, oy] = offs[k];
      tags[k].style.transform = p.visible ? `translate(${p.x + ox}px, ${p.y + oy}px)` : "translate(-9999px,0)";
    }
    const tip = twin.tipWorld();          // three (x, z-atas, -y) -> robot (x, y, z)
    $("tipX").textContent = tip.x.toFixed(1);
    $("tipY").textContent = (-tip.z).toFixed(1);
    $("tipZ").textContent = tip.y.toFixed(1);
    cam.draw();
    chart.draw();
  };

  // ---- sudut pandang ----
  const viewBtns = [...document.querySelectorAll("#views button")];
  const setView = (v) => { twin.setView(v); viewBtns.forEach((b) => b.classList.toggle("active", b.dataset.view === v)); };
  viewBtns.forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  const order = viewBtns.map((b) => b.dataset.view);

  // ---- tombol & keyboard ----
  $("estopBtn").addEventListener("click", () => post("estop"));
  window.addEventListener("keydown", (e) => {
    if (e.repeat) return;
    const k = e.key.toLowerCase();
    if (e.code === "Space") { e.preventDefault(); post("estop"); }
    else if (k === "c") post("calib");
    else if (k === "v") setView(order[(order.indexOf(twin.view) + 1) % order.length]);
    else if (k === "f") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
    else if (k === "u" && cfg.mode === "SIMULASI") post("unplug");
    else if (k === "q" && confirm("Tutup aplikasi robot? Robot akan kembali ke posisi awal.")) post("quit");
  });

  setInterval(() => {
    $("clock").textContent = new Date().toLocaleTimeString("id-ID", { hour12: false, hour: "2-digit", minute: "2-digit" });
  }, 1000);

  // ---- telemetri ----
  let rx = 0, rxT = performance.now(), lastMsg = 0, last = null;
  const es = new EventSource("events");
  es.onopen = () => body.classList.remove("no-server");
  es.onerror = () => { body.classList.add("no-server"); $("disconnectText").textContent = "Koneksi ke aplikasi terputus. Mencoba lagi…"; };
  es.onmessage = (ev) => {
    const t = JSON.parse(ev.data);
    if (!t.state) return;
    lastMsg = performance.now();
    body.classList.remove("no-server");
    rx++;

    if (!last || last.state !== t.state) {
      body.dataset.state = t.state;
      $("stateBig").textContent = STATE_LABEL[t.state];
      const stopped = t.state === "ESTOP";
      $("estopLbl").textContent = stopped ? "Lanjutkan" : "Hentikan robot";
      $("estopHint").textContent = stopped ? "Jalankan lagi, tombol Space" : "E-STOP, tombol Space";
      log.add(`Status: ${STATE_LABEL[t.state].toLowerCase()}`, stopped ? "err" : t.state === "LIVE" ? "ok" : "");
    }
    $("stateMsg").textContent = !t.link.ok
      ? (t.mode === "ASLI" ? "Robot belum tersambung. Periksa kabel USB ke ESP32." : "Kabel virtual dicabut. Tekan U untuk menyambung lagi.")
      : STATE_MSG[t.state];

    body.classList.toggle("offline", !t.link.ok);
    body.dataset.grip = t.jt.grip;
    $("linkChip").classList.toggle("bad", !t.link.ok);
    $("linkText").textContent = t.link.ok ? (t.mode === "ASLI" ? "Tersambung" : "Virtual") : "Terputus";
    $("linkChip").title = t.link.text;
    if (last && last.link.ok !== t.link.ok) log.add(t.link.ok ? `Tersambung: ${t.link.text}` : `Terputus: ${t.link.text}`, t.link.ok ? "ok" : "warn");
    $("twinSub").textContent = t.link.ok
      ? (t.mode === "ASLI" ? "Model mengikuti robot fisik" : "Model mengikuti robot virtual")
      : "Menunggu robot tersambung";
    $("fpsVal").textContent = t.fps.toFixed(0);
    $("srcName").textContent = t.source;
    body.dataset.source = t.source.includes("mouse") ? "virtual" : "camera";
    if (last && last.hand.visible !== t.hand.visible && t.state !== "ESTOP") {
      log.add(t.hand.visible ? "Tangan terdeteksi" : "Tangan hilang dari kamera", t.hand.visible ? "ok" : "");
    }
    if (last && last.jt.grip !== t.jt.grip && t.state === "LIVE") log.add(t.jt.grip ? "Capit menutup" : "Capit membuka");
    if (last && last.calib !== t.calib) log.add(t.calib ? "Kalibrasi ditampilkan" : "Kalibrasi disembunyikan", "warn");
    log.syncLink(t.log);

    twin.update(t);
    cam.update(t);
    rBase.update(t.ja.yaw, t.jt.yaw, t.actual.base);
    rArm.update(t.ja.pitch, t.jt.pitch, t.actual.lengan);
    rGrip.update(t.ja.grip, t.jt.grip, t.actual.grip);
    $("tagBase").querySelector("span").textContent = `${fmt(t.ja.yaw)}°`;
    $("tagArm").querySelector("span").textContent = `${fmt(t.ja.pitch)}°`;
    $("tagGrip").querySelector("span").textContent = t.ja.grip > 0.5 ? "tertutup" : "terbuka";
    $("fwState").textContent = `servo ${Math.round(t.actual.base)}, ${Math.round(t.actual.lengan)}, ${Math.round(t.actual.grip)}`;
    chart.push(t);
    last = t;
  };

  setInterval(() => {
    const now = performance.now();
    $("syncVal").textContent = Math.round(rx / ((now - rxT) / 1000));
    rx = 0; rxT = now;
    if (lastMsg && now - lastMsg > 2500) { body.classList.add("no-server"); $("disconnectText").textContent = "Tidak ada data dari aplikasi."; }
  }, 1000);

  const img = $("camImg");
  img.addEventListener("error", () => setTimeout(() => { img.src = `stream.mjpg?t=${Date.now()}`; }, 1000));
}

boot();
