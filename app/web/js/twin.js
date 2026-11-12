// =========================================================================
//  Digital twin 3D: model robot prosedural (Three.js), dibangun dari geometri config.yaml.
//  Satuan scene = cm. Koordinat robot (x maju, y kiri, z atas) -> three (x, z, -y).
//  Konvensi sama dengan app/kinematics.py: yaw + = putar ke kiri, pitch + = lengan naik.
// =========================================================================
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const D2R = Math.PI / 180;
// Warna LED status di base (seperti lampu status robot industri). Siaga = putih netral.
const STATE_COLORS = {
  IDLE: new THREE.Color("#d9dde1"),
  LIVE: new THREE.Color("#0ca30c"),
  ESTOP: new THREE.Color("#d03b3b"),
  OFFLINE: new THREE.Color("#fab219"),
};
const GROUND = "#1f2225";

/** FK yang sama dengan kinematics.forward(), dalam koordinat three. */
function fk(yawDeg, pitchDeg, L, H0) {
  const y = yawDeg * D2R, p = pitchDeg * D2R, r = L * Math.cos(p);
  return new THREE.Vector3(r * Math.cos(y), H0 + L * Math.sin(p), -r * Math.sin(y));
}

function rbox(w, h, d, r, mat) {
  const m = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2, h / 2, d / 2)), mat);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}
function cyl(rTop, rBot, h, mat, seg = 48) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rTop, rBot, h, seg), mat);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}

/** Tekstur label kecil di bodi servo (mis. "MG90S"). */
function labelTexture(text, bg, fg) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 96;
  const g = c.getContext("2d");
  g.fillStyle = bg; g.fillRect(0, 0, 256, 96);
  g.fillStyle = fg; g.font = "600 44px 'IBM Plex Sans', sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text, 128, 50);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export class DigitalTwin {
  constructor(container, cfg) {
    this.container = container;
    this.L = cfg.geometry.L;
    this.H0 = cfg.geometry.H0;
    this.yawRange = [...cfg.mapping.yaw_range].sort((a, b) => a - b);
    this.pitchRange = [...cfg.mapping.pitch_range].sort((a, b) => a - b);
    this.pose = { yaw: 0, pitch: 0, grip: 0 };          // ditampilkan (dihaluskan)
    this.poseIn = { yaw: 0, pitch: 0, grip: 0 };        // dari telemetri
    this.target = { yaw: 0, pitch: 0, grip: 0 };
    this.state = "IDLE";
    this.offline = false;
    this.accent = STATE_COLORS.IDLE.clone();
    this.accentTarget = STATE_COLORS.IDLE.clone();
    this.view = "iso";
    this.tween = null;
    this.trail = [];
    this.clock = new THREE.Clock();

    this._initRenderer();
    this._initScene();
    this._buildEnvironment();
    this._buildRobot();
    this._buildOverlays();
    this.setView("iso", true);

    new ResizeObserver(() => this._resize()).observe(container);
    this._resize();
    this.renderer.setAnimationLoop(() => this._frame());
  }

  // ------------------------------------------------------------------ setup
  _initRenderer() {
    const r = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.0;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(r.domElement);
    this.renderer = r;
  }

  _initScene() {
    const s = new THREE.Scene();
    s.background = new THREE.Color(GROUND);
    s.fog = new THREE.Fog(GROUND, 70, 160);
    const pm = new THREE.PMREMGenerator(this.renderer);
    s.environment = pm.fromScene(new RoomEnvironment(), 0.04).texture;
    s.environmentIntensity = 0.5;
    this.scene = s;

    this.camera = new THREE.PerspectiveCamera(34, 1, 0.1, 500);
    const c = new OrbitControls(this.camera, this.renderer.domElement);
    c.enableDamping = true;
    c.dampingFactor = 0.08;
    c.minDistance = 12;
    c.maxDistance = 90;
    c.maxPolarAngle = Math.PI * 0.495;
    c.autoRotateSpeed = 0.55;
    c.addEventListener("start", () => { this.tween = null; this.userOrbit = performance.now(); });
    this.controls = c;

    s.add(new THREE.HemisphereLight("#f2f4f6", "#2a2d31", 0.9));
    const key = new THREE.DirectionalLight("#ffffff", 1.5);
    key.position.set(-14, 26, 18);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    const sc = key.shadow.camera;
    sc.left = -22; sc.right = 22; sc.top = 22; sc.bottom = -22; sc.near = 1; sc.far = 80;
    key.shadow.bias = -0.0004;
    key.shadow.radius = 4;
    s.add(key);
    const rim = new THREE.DirectionalLight("#ffffff", 0.7);
    rim.position.set(20, 10, -18);
    s.add(rim);
  }

  _buildEnvironment() {
    const s = this.scene, L = this.L;
    // lantai gelap yang menerima bayangan
    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(120, 96),
      new THREE.MeshStandardMaterial({ color: "#232629", roughness: 0.95, metalness: 0.0 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    s.add(floor);

    // grid holografik
    const grid = new THREE.GridHelper(160, 32, "#4a5057", "#33373c");
    grid.material.transparent = true;
    grid.material.opacity = 0.9;
    grid.material.depthWrite = false;
    grid.position.y = 0.01;
    s.add(grid);
    const fine = new THREE.GridHelper(40, 40, "#2c3034", "#2c3034");
    fine.material.transparent = true;
    fine.material.opacity = 0.8;
    fine.material.depthWrite = false;
    fine.position.y = 0.012;
    s.add(fine);

    // cincin skala jarak (tiap 5 cm)
    const ringMat = new THREE.LineBasicMaterial({ color: "#4a5057", transparent: true, opacity: 0.6 });
    for (let r = 10; r <= L * 2; r += 10) {
      const pts = [];
      for (let i = 0; i <= 128; i++) {
        const a = (i / 128) * Math.PI * 2;
        pts.push(new THREE.Vector3(Math.cos(a) * r, 0.03, Math.sin(a) * r));
      }
      s.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), ringMat));
    }

    // sektor jangkauan di lantai (rentang yaw x jangkauan horizontal)
    const [y0, y1] = this.yawRange;
    const [p0, p1] = this.pitchRange;
    const rMax = L * (p0 <= 0 && p1 >= 0 ? 1 : Math.max(Math.cos(p0 * D2R), Math.cos(p1 * D2R)));
    const rMin = L * Math.min(Math.cos(p0 * D2R), Math.cos(p1 * D2R));
    this.sectorMat = new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.05,
      side: THREE.DoubleSide, depthWrite: false });
    const sector = new THREE.Mesh(new THREE.RingGeometry(rMin, rMax, 96, 1, y0 * D2R, (y1 - y0) * D2R), this.sectorMat);
    sector.rotation.x = -Math.PI / 2;
    sector.position.y = 0.04;
    s.add(sector);
    const edgePts = [];
    for (let i = 0; i <= 64; i++) {
      const a = (y0 + (y1 - y0) * (i / 64)) * D2R;
      edgePts.push(new THREE.Vector3(Math.cos(a) * rMax, 0.05, -Math.sin(a) * rMax));
    }
    this.sectorEdgeMat = new THREE.LineBasicMaterial({ color: "#a3abb3", transparent: true, opacity: 0.5 });
    s.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(edgePts), this.sectorEdgeMat));
  }

  _buildRobot() {
    const L = this.L, H0 = this.H0;
    const mat = {
      shell: new THREE.MeshStandardMaterial({ color: "#e2702a", metalness: 0.1, roughness: 0.45 }),   // lengan oranye
      alu: new THREE.MeshStandardMaterial({ color: "#aeb5bc", metalness: 0.75, roughness: 0.35 }),    // aluminium
      dark: new THREE.MeshStandardMaterial({ color: "#2c3035", metalness: 0.4, roughness: 0.55 }),
      steel: new THREE.MeshStandardMaterial({ color: "#8a97a6", metalness: 1.0, roughness: 0.22 }),
      servo: new THREE.MeshStandardMaterial({ color: "#1d58b8", metalness: 0.05, roughness: 0.42 }),
      servoSmall: new THREE.MeshStandardMaterial({ color: "#2a72e0", metalness: 0.05, roughness: 0.42 }),
      horn: new THREE.MeshStandardMaterial({ color: "#f3f5f7", metalness: 0.0, roughness: 0.5 }),
      rubber: new THREE.MeshStandardMaterial({ color: "#0d1117", metalness: 0.0, roughness: 0.9 }),
    };
    // LED status (satu-satunya bagian yang menyala) dan bantalan capit
    this.accentMat = new THREE.MeshStandardMaterial({ color: "#000000", emissive: "#d9dde1", emissiveIntensity: 1.2 });
    this.padMat = new THREE.MeshStandardMaterial({ color: "#15171a", roughness: 0.9 });
    const trim = mat.dark;
    this.mat = mat;

    const root = new THREE.Group();
    this.scene.add(root);

    // ---- pedestal (diam) ----
    const plate = cyl(4.4, 4.7, 0.8, mat.dark, 72);
    plate.position.y = 0.4;
    root.add(plate);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(4.42, 0.12, 12, 120), this.accentMat);
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.82;
    root.add(ring);
    for (let i = 0; i < 6; i++) {                     // baut
      const a = (i / 6) * Math.PI * 2 + Math.PI / 6;
      const b = cyl(0.28, 0.28, 0.16, mat.steel, 16);
      b.position.set(Math.cos(a) * 3.75, 0.88, Math.sin(a) * 3.75);
      root.add(b);
    }
    const columnH = Math.max(1.6, Math.min(3.0, H0 - 3.2));
    const column = cyl(2.25, 2.6, columnH, mat.alu, 64);
    column.position.y = 0.8 + columnH / 2;
    root.add(column);
    const colBand = cyl(2.36, 2.36, 0.18, trim, 64);
    colBand.position.y = 0.8 + columnH * 0.62;
    root.add(colBand);
    // jendela servo base (MG90S terlihat dari depan)
    const win = new THREE.Mesh(new THREE.PlaneGeometry(1.4, columnH * 0.5),
      new THREE.MeshStandardMaterial({ map: labelTexture("MG90S", "#1d58b8", "#d8e6ff"), roughness: 0.5 }));
    win.position.set(-2.56, 0.8 + columnH * 0.36, 0);
    win.rotation.y = -Math.PI / 2;
    win.rotation.x = 0;
    root.add(win);
    const turretY = 0.8 + columnH;

    // ---- grup YAW (berputar) ----
    const yawG = new THREE.Group();
    root.add(yawG);
    this.yawG = yawG;
    const turret = cyl(2.5, 2.5, 0.6, mat.dark, 72);
    turret.position.y = turretY + 0.3;
    yawG.add(turret);
    const tRing = new THREE.Mesh(new THREE.TorusGeometry(2.52, 0.05, 10, 100), trim);
    tRing.rotation.x = Math.PI / 2;
    tRing.position.y = turretY + 0.6;
    yawG.add(tRing);
    const pointer = rbox(0.9, 0.12, 0.3, 0.05, mat.horn);   // penanda arah depan
    pointer.position.set(2.2, turretY + 0.64, 0);
    yawG.add(pointer);

    // bracket U di kiri-kanan sumbu bahu
    const brTop = H0 + 1.0, brBot = turretY + 0.6;
    const brH = brTop - brBot;
    for (const z of [-1.62, 1.62]) {
      const br = rbox(2.4, brH, 0.34, 0.12, mat.alu);
      br.position.set(0, brBot + brH / 2, z);
      yawG.add(br);
    }
    // servo lengan (MG90S) di antara bracket
    const sServo = rbox(2.3, 2.2, 1.24, 0.1, mat.servo);
    sServo.position.set(-0.9, H0 - 0.9, 0);
    yawG.add(sServo);
    const sLabel = new THREE.Mesh(new THREE.PlaneGeometry(1.8, 0.55),
      new THREE.MeshBasicMaterial({ map: labelTexture("MG90S", "#1d58b8", "#d8e6ff") }));
    sLabel.position.set(-0.9, H0 - 1.4, 0.63);
    yawG.add(sLabel);
    // poros bahu
    const axle = cyl(0.42, 0.42, 4.0, mat.steel, 32);
    axle.rotation.x = Math.PI / 2;
    axle.position.y = H0;
    yawG.add(axle);
    for (const z of [-1.95, 1.95]) {
      const cap = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.08, 12, 48), trim);
      cap.position.set(0, H0, z);
      yawG.add(cap);
    }

    // ---- grup PITCH (lengan) ----
    const pitchG = new THREE.Group();
    pitchG.position.y = H0;
    yawG.add(pitchG);
    this.pitchG = pitchG;

    const wristX = L - 2.7;                 // pangkal gripper
    const beamLen = wristX + 0.9;
    for (const z of [-1.25, 1.25]) {
      const plateA = rbox(beamLen, 1.5, 0.3, 0.14, mat.shell);
      plateA.position.set(beamLen / 2 - 0.9, 0, z);
      pitchG.add(plateA);
      // lubang pengurang berat (dekor)
      for (let i = 1; i <= 2; i++) {
        const h = cyl(0.34, 0.34, 0.32, mat.dark, 24);
        h.rotation.x = Math.PI / 2;
        h.position.set(wristX * (i / 3), -0.15, z);
        pitchG.add(h);
      }
    }
    const horn = cyl(0.95, 0.95, 0.16, mat.horn, 32);       // horn servo di bahu
    horn.rotation.x = Math.PI / 2;
    horn.position.set(0, 0, 0.95);
    pitchG.add(horn);
    const cross = cyl(0.22, 0.22, 2.8, mat.steel, 16);
    cross.rotation.x = Math.PI / 2;
    cross.position.set(wristX * 0.55, 0.45, 0);
    pitchG.add(cross);

    // ---- gripper (SG90 + 2 rahang) ----
    const gServo = rbox(2.0, 1.25, 2.0, 0.1, mat.servoSmall);
    gServo.position.set(wristX + 0.2, 0.05, 0);
    pitchG.add(gServo);
    const gLabel = new THREE.Mesh(new THREE.PlaneGeometry(1.1, 0.4),
      new THREE.MeshBasicMaterial({ map: labelTexture("SG90", "#2a72e0", "#e3eeff") }));
    gLabel.position.set(wristX + 0.6, 0.05, 1.01);
    pitchG.add(gLabel);
    const palm = rbox(0.35, 1.7, 2.9, 0.08, mat.dark);
    palm.position.set(wristX + 1.35, 0, 0);
    pitchG.add(palm);
    const rail = cyl(0.1, 0.1, 2.9, mat.steel, 12);
    rail.rotation.x = Math.PI / 2;
    rail.position.set(wristX + 1.62, 0.5, 0);
    pitchG.add(rail);

    this.jaws = [];
    const jawLen = L - (wristX + 1.5) + 0.5;
    for (const side of [-1, 1]) {
      const jg = new THREE.Group();
      const finger = rbox(jawLen, 1.05, 0.26, 0.08, mat.dark);
      finger.position.set(jawLen / 2, 0, 0);
      jg.add(finger);
      const pad = rbox(jawLen * 0.55, 0.8, 0.08, 0.03, this.padMat);
      pad.position.set(jawLen * 0.68, 0, -side * 0.17);
      jg.add(pad);
      jg.position.set(wristX + 1.52, 0, side * 1.0);
      jg.userData.side = side;
      pitchG.add(jg);
      this.jaws.push(jg);
    }
    this.jawOpen = 1.05;     // setengah jarak rahang saat buka
    this.jawClosed = 0.22;   // saat tutup

    // titik tengah gripper (= ujung FK, panjang L)
    this.tipMarker = new THREE.Mesh(new THREE.SphereGeometry(0.16, 16, 16), mat.horn);
    this.tipMarker.position.set(L, 0, 0);
    pitchG.add(this.tipMarker);

    root.traverse((o) => { if (o.isMesh && o.material === this.accentMat) o.castShadow = false; });
  }

  _buildOverlays() {
    const s = this.scene, L = this.L, H0 = this.H0;
    const [y0, y1] = this.yawRange, [p0, p1] = this.pitchRange;

    // kubah ruang kerja (meridian & paralel dari FK)
    const pts = [];
    const seg = 36;
    for (let yaw = y0; yaw <= y1 + 0.01; yaw += (y1 - y0) / 8) {
      for (let i = 0; i < seg; i++) {
        pts.push(fk(yaw, p0 + (p1 - p0) * (i / seg), L, H0), fk(yaw, p0 + (p1 - p0) * ((i + 1) / seg), L, H0));
      }
    }
    for (let p = p0; p <= p1 + 0.01; p += (p1 - p0) / 6) {
      for (let i = 0; i < seg; i++) {
        pts.push(fk(y0 + (y1 - y0) * (i / seg), p, L, H0), fk(y0 + (y1 - y0) * ((i + 1) / seg), p, L, H0));
      }
    }
    this.domeMat = new THREE.LineBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.07, depthWrite: false });
    s.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), this.domeMat));

    // ghost target: garis bahu -> target + cincin
    this.ghostMat = new THREE.LineDashedMaterial({ color: "#ffffff", transparent: true, opacity: 0.55,
      dashSize: 0.4, gapSize: 0.25, depthWrite: false });
    this.ghostLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(0, H0, 0), new THREE.Vector3(L, H0, 0)]), this.ghostMat);
    s.add(this.ghostLine);
    this.ghostRing = new THREE.Mesh(new THREE.TorusGeometry(0.55, 0.045, 8, 40),
      new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.75, depthWrite: false }));
    s.add(this.ghostRing);

    // proyeksi ujung ke lantai (garis vertikal + titik)
    this.dropMat = new THREE.LineDashedMaterial({ color: "#a3abb3", transparent: true, opacity: 0.6, dashSize: 0.3, gapSize: 0.3 });
    this.dropLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(), new THREE.Vector3()]), this.dropMat);
    s.add(this.dropLine);
    this.dropDot = new THREE.Mesh(new THREE.RingGeometry(0.25, 0.42, 32),
      new THREE.MeshBasicMaterial({ color: "#d9dde1", transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }));
    this.dropDot.rotation.x = -Math.PI / 2;
    s.add(this.dropDot);

    // jejak ujung gripper
    this.trailMax = 220;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(this.trailMax * 3), 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(this.trailMax * 3), 3));
    g.setDrawRange(0, 0);
    this.trailLine = new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    this.trailLine.frustumCulled = false;
    this.trailColor = new THREE.Color("#e2702a");   // jejak = warna lengan
    s.add(this.trailLine);
  }

  // ------------------------------------------------------------------ API
  update(t) {
    this.poseIn = { yaw: t.ja.yaw, pitch: t.ja.pitch, grip: t.ja.grip };
    this.target = { yaw: t.jt.yaw, pitch: t.jt.pitch, grip: t.jt.grip };
    this.setState(t.state, !t.link.ok);
  }

  setState(state, offline) {
    if (state === this.state && offline === this.offline) return;
    const prev = this.state;
    this.state = state;
    this.offline = offline;
    this.accentTarget.copy(offline ? STATE_COLORS.OFFLINE : STATE_COLORS[state] || STATE_COLORS.IDLE);
    this.controls.autoRotate = state === "IDLE";
    if (prev === "IDLE" && state !== "IDLE") this.setView(this.view);  // kembali ke sudut pandang pilihan
  }

  views() {
    const L = this.L, H0 = this.H0;
    const look = new THREE.Vector3(L * 0.4, H0 + L * 0.15, 0);
    return {
      iso: { pos: new THREE.Vector3(-L * 2.3, H0 + L * 1.7, L * 2.25), look },
      back: { pos: new THREE.Vector3(-L * 3.4, H0 + L * 1.3, 0.001), look },
      top: { pos: new THREE.Vector3(L * 0.35 - 0.6, L * 4.6, 0.001), look: new THREE.Vector3(L * 0.35, 0, 0) },
      side: { pos: new THREE.Vector3(L * 0.45, H0 + L * 0.25, L * 3.8), look: new THREE.Vector3(L * 0.45, H0 * 0.8, 0) },
    };
  }

  setView(name, instant = false) {
    const v = this.views()[name];
    if (!v) return;
    this.view = name;
    if (instant) {
      this.camera.position.copy(v.pos);
      this.controls.target.copy(v.look);
      this.controls.update();
      return;
    }
    this.tween = { t: 0, dur: 0.9, fromPos: this.camera.position.clone(), fromLook: this.controls.target.clone(),
      toPos: v.pos, toLook: v.look };
  }

  /** Posisi layar (px, relatif container) untuk label sendi. */
  anchors() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    const out = {};
    const pts = {
      base: this.yawG.localToWorld(new THREE.Vector3(0, this._turretTop(), 0)),
      arm: this.pitchG.localToWorld(new THREE.Vector3(0, 0, 0)),
      grip: this.pitchG.localToWorld(new THREE.Vector3(this.L, 0, 0)),
    };
    for (const [k, p] of Object.entries(pts)) {
      const v = p.project(this.camera);
      out[k] = { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h, visible: v.z < 1 };
    }
    return out;
  }

  _turretTop() { return 0.8 + Math.max(1.6, Math.min(3.0, this.H0 - 3.2)) + 0.6; }

  tipWorld() {
    return fk(this.pose.yaw, this.pose.pitch, this.L, this.H0);
  }

  // ------------------------------------------------------------------ loop
  _resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _frame() {
    const dt = Math.min(this.clock.getDelta(), 0.1);

    // haluskan pose (telemetri ~30 Hz -> render 60 Hz)
    const k = 1 - Math.exp(-dt * 18);
    for (const key of ["yaw", "pitch", "grip"]) this.pose[key] += (this.poseIn[key] - this.pose[key]) * k;
    this.yawG.rotation.y = this.pose.yaw * D2R;
    this.pitchG.rotation.z = this.pose.pitch * D2R;
    const half = this.jawOpen + (this.jawClosed - this.jawOpen) * this.pose.grip;
    for (const j of this.jaws) j.position.z = j.userData.side * half;

    // warna aksen
    this.accent.lerp(this.accentTarget, 1 - Math.exp(-dt * 6));
    this.accentMat.emissive.copy(this.accent);
    // bantalan capit hijau saat menjepit (status, bukan dekorasi)
    this.padMat.color.set(this.pose.grip > 0.5 ? "#0ca30c" : "#15171a");

    // ghost target
    const tgt = fk(this.target.yaw, this.target.pitch, this.L, this.H0);
    const gp = this.ghostLine.geometry.attributes.position;
    gp.setXYZ(1, tgt.x, tgt.y, tgt.z);
    gp.needsUpdate = true;
    this.ghostLine.computeLineDistances();
    this.ghostRing.position.copy(tgt);
    this.ghostRing.lookAt(this.camera.position);
    const err = Math.hypot(this.target.yaw - this.pose.yaw, this.target.pitch - this.pose.pitch);
    const ghostVis = this.state === "IDLE" ? 0 : Math.min(1, err / 4);
    this.ghostMat.opacity = 0.6 * ghostVis;
    this.ghostRing.material.opacity = 0.8 * ghostVis;

    // proyeksi ke lantai
    const tip = this.tipWorld();
    const dp = this.dropLine.geometry.attributes.position;
    dp.setXYZ(0, tip.x, tip.y, tip.z);
    dp.setXYZ(1, tip.x, 0.05, tip.z);
    dp.needsUpdate = true;
    this.dropLine.computeLineDistances();
    this.dropDot.position.set(tip.x, 0.06, tip.z);

    this._updateTrail(tip);

    // tween kamera
    if (this.tween) {
      const tw = this.tween;
      tw.t += dt / tw.dur;
      const e = tw.t >= 1 ? 1 : 1 - Math.pow(1 - tw.t, 3);
      this.camera.position.lerpVectors(tw.fromPos, tw.toPos, e);
      this.controls.target.lerpVectors(tw.fromLook, tw.toLook, e);
      if (tw.t >= 1) this.tween = null;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.onFrame?.();
  }

  _updateTrail(tip) {
    const last = this.trail[this.trail.length - 1];
    if (!last || last.distanceToSquared(tip) > 0.0025) {
      this.trail.push(tip.clone());
      if (this.trail.length > this.trailMax) this.trail.shift();
    }
    const n = this.trail.length;
    const pos = this.trailLine.geometry.attributes.position;
    const col = this.trailLine.geometry.attributes.color;
    for (let i = 0; i < n; i++) {
      const p = this.trail[i];
      pos.setXYZ(i, p.x, p.y, p.z);
      const a = Math.pow(i / Math.max(1, n - 1), 1.6);      // memudar ke belakang
      col.setXYZ(i, this.trailColor.r * a * 0.8, this.trailColor.g * a * 0.8, this.trailColor.b * a * 0.8);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    this.trailLine.geometry.setDrawRange(0, n);
  }
}
