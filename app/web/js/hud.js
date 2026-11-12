// =========================================================================
//  HUD: overlay kamera, tabel sendi, grafik riwayat sudut, log.
// =========================================================================
const HAND_CONNECTIONS = [[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],
  [9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];

const css = (name) => getComputedStyle(document.body).getPropertyValue(name).trim();
export const fmt = (v, d = 1) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d);
const FONT = "'IBM Plex Sans', 'Segoe UI', sans-serif";

function fitCanvas(canvas) {
  const r = canvas.getBoundingClientRect();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.round(r.width * dpr)), h = Math.max(1, Math.round(r.height * dpr));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { g, w: r.width, h: r.height };
}

// ------------------------------------------------------------------ kamera
export class CameraOverlay {
  constructor(cfg, onMouse) {
    this.cfg = cfg;
    this.canvas = document.getElementById("camCanvas");
    this.flag = document.getElementById("handFlag");
    this.calib = document.getElementById("calibBox");
    this.pinchFill = document.getElementById("pinchFill");
    this.pinchVal = document.getElementById("pinchVal");
    this.t = null;
    this.pmax = 1.0;   // skala bar cubit 0..1
    document.getElementById("thClose").style.left = `${(cfg.mapping.pinch_close / this.pmax) * 100}%`;
    document.getElementById("thOpen").style.left = `${(cfg.mapping.pinch_open / this.pmax) * 100}%`;

    // tangan virtual (mode --mouse): kirim posisi pointer, dibatasi ~30 Hz
    let pressed = false, last = 0;
    const send = (e, inside, force = false) => {
      const r = this.canvas.getBoundingClientRect();
      const msg = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height, inside, pressed: pressed && inside };
      const now = performance.now();
      if (force || now - last > 30) { last = now; onMouse(msg); }
    };
    this.canvas.addEventListener("pointermove", (e) => send(e, true));
    this.canvas.addEventListener("pointerdown", (e) => { pressed = true; this.canvas.setPointerCapture(e.pointerId); send(e, true, true); });
    this.canvas.addEventListener("pointerup", (e) => { pressed = false; send(e, true, true); });
    this.canvas.addEventListener("pointerleave", () => { pressed = false; onMouse({ x: 0.5, y: 0.5, inside: false, pressed: false }); });
  }

  update(t) {
    this.t = t;
    const h = t.hand;
    this.flag.textContent = h.visible ? "Tangan terdeteksi" : "Mencari tangan";
    this.flag.classList.toggle("on", h.visible);
    this.pinchFill.style.width = h.visible ? `${Math.min(1, h.pinch / this.pmax) * 100}%` : "0%";
    this.pinchVal.textContent = h.visible ? h.pinch.toFixed(2) : "—";

    this.calib.classList.toggle("on", t.calib);
    if (t.calib) {
      const m = this.cfg.mapping;
      this.calib.innerHTML = `<h4>Kalibrasi</h4>` + (h.visible
        ? `x ${h.x.toFixed(3)}, y ${h.y.toFixed(3)}<br>` +
          `cubit ${h.pinch.toFixed(3)} (tutup &lt; ${m.pinch_close}, buka &gt; ${m.pinch_open})<br>` +
          `base ${fmt(t.jt.yaw)}°, lengan ${fmt(t.jt.pitch)}°<br>` +
          `dikirim: A ${t.target.base} ${t.target.lengan} ${t.target.grip}`
        : "Tangan belum terdeteksi");
    }
  }

  draw() {
    const t = this.t;
    if (!t) return;
    const { g, w, h } = fitCanvas(this.canvas);
    g.clearRect(0, 0, w, h);
    const m = this.cfg.mapping;
    const ink = css("--ink"), ink2 = css("--ink-2"), good = css("--good-ink");

    // area gerak (batas mapping): di luar kotak, robot sudah di batas sudutnya
    const [x0, x1] = [...m.x_range].sort((a, b) => a - b);
    const [y0, y1] = [...m.y_range].sort((a, b) => a - b);
    g.setLineDash([6, 5]); g.lineWidth = 1.5; g.strokeStyle = ink2;
    g.strokeRect(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h);
    g.setLineDash([]);
    g.font = `500 12px ${FONT}`; g.fillStyle = ink2;
    g.fillText("Area gerak", x0 * w + 6, y0 * h + 16);

    const hand = t.hand;
    if (!hand.visible) return;
    const closed = t.jt.grip === 1;

    if (hand.lm.length === 21) {
      const P = hand.lm.map(([x, y]) => [x * w, y * h]);
      g.strokeStyle = "rgba(255,255,255,0.85)"; g.lineWidth = 2; g.lineCap = "round";
      g.beginPath();
      for (const [a, b] of HAND_CONNECTIONS) { g.moveTo(...P[a]); g.lineTo(...P[b]); }
      g.stroke();
      for (let i = 0; i < 21; i++) {
        const tip = i === 4 || i === 8;
        g.beginPath(); g.arc(P[i][0], P[i][1], tip ? 5 : 2.5, 0, Math.PI * 2);
        g.fillStyle = tip ? (closed ? good : ink) : "rgba(255,255,255,0.85)"; g.fill();
      }
      g.lineWidth = 2; g.strokeStyle = closed ? good : "rgba(255,255,255,0.5)";
      g.beginPath(); g.moveTo(...P[4]); g.lineTo(...P[8]); g.stroke();
    }

    // titik yang dipakai robot (setelah filter)
    const f = hand.f || [hand.x, hand.y];
    const rx = f[0] * w, ry = f[1] * h;
    g.strokeStyle = closed ? good : ink; g.lineWidth = 2;
    g.beginPath(); g.arc(rx, ry, 14, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.moveTo(rx - 22, ry); g.lineTo(rx - 8, ry); g.moveTo(rx + 8, ry); g.lineTo(rx + 22, ry);
    g.moveTo(rx, ry - 22); g.lineTo(rx, ry - 8); g.moveTo(rx, ry + 8); g.lineTo(rx, ry + 22); g.stroke();
    if (closed) { g.beginPath(); g.arc(rx, ry, 5, 0, Math.PI * 2); g.fillStyle = good; g.fill(); }
  }
}

// ------------------------------------------------------------------ tabel sendi
export class JointRow {
  /** range: [min,max] derajat sendi. invert: nilai positif digambar di kiri (yaw + = putar kiri). */
  constructor(el, range, invert = false) {
    this.lo = Math.min(...range); this.hi = Math.max(...range);
    this.invert = invert;
    this.big = el.querySelector(".big");
    this.fill = el.querySelector(".fill");
    this.tgt = el.querySelector(".tgt");
    this.tgtv = el.querySelector(".tgtv");
    this.srv = el.querySelector(".srv");
    const [l, r] = el.querySelectorAll(".lims span");
    const left = invert ? this.hi : this.lo, right = invert ? this.lo : this.hi;
    l.textContent = `${fmt(left, 0)}°`; r.textContent = `${fmt(right, 0)}°`;
    el.querySelector(".zero").style.left = `${this._pct(0)}%`;
  }
  _pct(v) {
    let t = (v - this.lo) / (this.hi - this.lo);
    t = Math.max(0, Math.min(1, t));
    return (this.invert ? 1 - t : t) * 100;
  }
  update(actual, target, servo) {
    const a = this._pct(0), b = this._pct(actual);
    this.fill.style.left = `${Math.min(a, b)}%`;
    this.fill.style.width = `${Math.abs(b - a)}%`;
    this.tgt.style.left = `${this._pct(target)}%`;
    this.big.textContent = `${fmt(actual)}°`;
    this.tgtv.textContent = `${fmt(target)}°`;
    this.srv.textContent = `servo ${Math.round(servo)}°`;
  }
}

export class GripRow {
  constructor(el) {
    this.el = el;
    this.big = el.querySelector(".big");
    this.fill = el.querySelector(".fill");
    this.tgtv = el.querySelector(".tgtv");
    this.srv = el.querySelector(".srv");
  }
  update(grip01, targetGrip, servoDeg) {
    this.fill.style.width = `${grip01 * 100}%`;
    this.el.classList.toggle("closed", grip01 > 0.5);
    this.big.textContent = grip01 > 0.5 ? "Tertutup" : "Terbuka";
    this.tgtv.textContent = targetGrip ? "tutup" : "buka";
    this.srv.textContent = `servo ${Math.round(servoDeg)}°`;
  }
}

// ------------------------------------------------------------------ grafik
export class HistoryChart {
  constructor(cfg, windowS = 10) {
    this.canvas = document.getElementById("chart");
    this.tip = document.getElementById("chartTip");
    this.windowS = windowS;
    this.data = [];        // {t, yaw, pitch, grip}
    const all = [...cfg.mapping.yaw_range, ...cfg.mapping.pitch_range];
    this.lo = Math.min(-30, ...all); this.hi = Math.max(30, ...all);
    this.hover = null;
    const wrap = document.getElementById("chartWrap");
    wrap.addEventListener("pointermove", (e) => { const r = wrap.getBoundingClientRect(); this.hover = e.clientX - r.left; });
    wrap.addEventListener("pointerleave", () => { this.hover = null; this.tip.style.display = "none"; });
  }
  push(t) {
    const now = performance.now() / 1000;
    this.data.push({ t: now, yaw: t.ja.yaw, pitch: t.ja.pitch, grip: t.ja.grip > 0.5 });
    while (this.data.length && this.data[0].t < now - this.windowS - 0.5) this.data.shift();
  }
  draw() {
    const { g, w, h } = fitCanvas(this.canvas);
    g.clearRect(0, 0, w, h);
    const padL = 34, padR = 56, padT = 6, padB = 18;
    const pw = w - padL - padR, ph = h - padT - padB;
    if (pw < 20 || ph < 20) return;
    const now = performance.now() / 1000;
    const X = (t) => padL + (1 - (now - t) / this.windowS) * pw;
    const Y = (v) => padT + (1 - (v - this.lo) / (this.hi - this.lo)) * ph;
    const ink = css("--ink"), ink3 = css("--ink-3"), surface = css("--surface");

    // grid & sumbu (resesif)
    g.font = `11px ${FONT}`;
    g.textAlign = "right"; g.textBaseline = "middle";
    for (let v = Math.ceil(this.lo / 30) * 30; v <= this.hi; v += 30) {
      g.strokeStyle = v === 0 ? "rgba(255,255,255,0.22)" : "rgba(255,255,255,0.07)";
      g.lineWidth = 1;
      g.beginPath(); g.moveTo(padL, Y(v)); g.lineTo(padL + pw, Y(v)); g.stroke();
      g.fillStyle = ink3;
      g.fillText(`${v}°`, padL - 6, Y(v));
    }
    g.textAlign = "center"; g.textBaseline = "alphabetic";
    for (let s = 0; s <= this.windowS; s += 5) g.fillText(s === 0 ? "sekarang" : `${s} s lalu`, padL + (1 - s / this.windowS) * pw, h - 3);

    if (this.data.length < 2) return;
    g.save();
    g.beginPath(); g.rect(padL, 0, pw, h); g.clip();

    // pita "capit tertutup" bertekstur di dasar plot (identitas bukan hanya warna)
    const gripY = padT + ph - 6;
    let start = null;
    for (let i = 0; i < this.data.length; i++) {
      const d = this.data[i];
      if (d.grip && start === null) start = d.t;
      if ((!d.grip || i === this.data.length - 1) && start !== null) {
        const x0 = X(start), x1 = X(d.t);
        g.fillStyle = "rgba(12,163,12,0.3)";
        g.fillRect(x0, gripY, Math.max(1, x1 - x0), 6);
        g.strokeStyle = "rgba(12,163,12,0.85)"; g.lineWidth = 1;
        g.save(); g.beginPath(); g.rect(x0, gripY, Math.max(1, x1 - x0), 6); g.clip();
        for (let x = x0 - 6; x < x1; x += 4) { g.beginPath(); g.moveTo(x, gripY + 6); g.lineTo(x + 6, gripY); g.stroke(); }
        g.restore();
        start = null;
      }
    }

    const series = [["yaw", css("--yaw"), "Base"], ["pitch", css("--pitch"), "Lengan"]];
    for (const [key, color] of series) {
      g.strokeStyle = color; g.lineWidth = 2; g.lineJoin = "round"; g.lineCap = "round";
      g.beginPath();
      this.data.forEach((d, i) => (i ? g.lineTo(X(d.t), Y(d[key])) : g.moveTo(X(d.t), Y(d[key]))));
      g.stroke();
    }
    g.restore();

    // label langsung di ujung kanan (nilai terkini), dijaga agar tidak bertumpuk
    const last = this.data[this.data.length - 1];
    const labels = series.map(([key, color]) => ({ key, color, y: Y(last[key]), v: last[key] }));
    labels.sort((a, b) => a.y - b.y);
    if (labels[1].y - labels[0].y < 14) { const mid = (labels[0].y + labels[1].y) / 2; labels[0].y = mid - 7; labels[1].y = mid + 7; }
    g.textAlign = "left"; g.textBaseline = "middle"; g.font = `500 12px ${FONT}`;
    for (const l of labels) {
      g.fillStyle = l.color; g.beginPath(); g.arc(padL + pw, Y(last[l.key]), 3.5, 0, Math.PI * 2); g.fill();
      g.fillStyle = ink; g.fillText(`${fmt(l.v)}°`, padL + pw + 8, l.y);
    }

    // crosshair + tooltip
    if (this.hover !== null && this.hover >= padL && this.hover <= padL + pw) {
      const tAt = now - (1 - (this.hover - padL) / pw) * this.windowS;
      let best = this.data[0];
      for (const d of this.data) if (Math.abs(d.t - tAt) < Math.abs(best.t - tAt)) best = d;
      const x = X(best.t);
      g.strokeStyle = "rgba(255,255,255,0.4)"; g.lineWidth = 1;
      g.beginPath(); g.moveTo(x, padT); g.lineTo(x, padT + ph); g.stroke();
      for (const [key, color] of series) {
        g.beginPath(); g.arc(x, Y(best[key]), 4.5, 0, Math.PI * 2);
        g.fillStyle = color; g.fill(); g.lineWidth = 2; g.strokeStyle = surface; g.stroke();
      }
      this.tip.style.display = "block";
      this.tip.innerHTML = `<div style="color:${ink3}">${(now - best.t).toFixed(1)} detik lalu</div>` +
        series.map(([key, color, name]) => `<div><i style="background:${color}"></i>${name} <b>${fmt(best[key])}°</b></div>`).join("") +
        `<div>Capit <b>${best.grip ? "tertutup" : "terbuka"}</b></div>`;
      const tw = this.tip.offsetWidth;
      this.tip.style.left = `${x + 12 + tw > w ? x - tw - 12 : x + 12}px`;
      this.tip.style.top = "4px";
    }
  }
}

// ------------------------------------------------------------------ log
export class EventLog {
  constructor(max = 40) {
    this.el = document.getElementById("log");
    this.max = max;
    this.seen = [];
  }
  add(text, kind = "") {
    const li = document.createElement("li");
    li.className = kind;
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString("id-ID", { hour12: false });
    li.append(time, document.createTextNode(text));
    this.el.appendChild(li);
    while (this.el.children.length > this.max) this.el.firstChild.remove();
  }
  /** Tambahkan baris baru dari log link (perintah/balasan serial). */
  syncLink(lines) {
    let k = 0;
    for (let n = Math.min(this.seen.length, lines.length); n > 0; n--) {
      if (this.seen.slice(-n).join("\n") === lines.slice(0, n).join("\n")) { k = n; break; }
    }
    for (const l of lines.slice(k)) {
      const kind = l.startsWith("< ERR") ? "err" : l.startsWith("< ") ? "ok" : "";
      this.add(l.startsWith(">") ? `kirim ${l.slice(2)}` : `terima ${l.slice(2)}`, kind);
    }
    this.seen = lines.slice();
  }
}
