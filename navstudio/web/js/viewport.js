// 2D world viewport: map, costmaps, paths, scan, range-sensor hits, perception marks, robot, scene objects, editing tools.
// Scene objects are 2.5D: obstacles have z0..z1 (default 0..1 m: low obstacles, overhangs), 'cliff' rects are drops.
import { cssVar } from './ui.js';

const TAU = Math.PI * 2;
let gid = 1;
export const newGroupId = () => `g${Date.now().toString(36)}${(gid++).toString(36)}`;

export const OBS_TOP = 1.0;           // obstacles without a height reach 1 m (same as the simulator)
export const obsZ = (o) => [o.z0 ?? 0, o.z1 ?? OBS_TOP];
// short height label for an obstacle: '' for ordinary floor-standing ones
export function heightLabel(o) {
  if (o.type === 'cliff') return `단차 ${Math.round((o.depth ?? 0.3) * 100)} cm`;
  const [z0, z1] = obsZ(o);
  const cm = (v) => (v < 1 ? `${Math.round(v * 100)} cm` : `${+v.toFixed(2)} m`);
  if (z0 > 0.001) return `공중 ${cm(z0)}–${cm(z1)}`;
  if (z1 < 0.3) return `높이 ${cm(z1)}`;
  return '';
}

export function robotPolygon(profile, n = 32) {
  const fp = profile.footprint;
  if (fp.type === 'circle') {
    const r = fp.radius;
    return Array.from({ length: n }, (_, i) => [r * Math.cos(TAU * i / n), r * Math.sin(TAU * i / n)]);
  }
  return fp.points;
}

function hexToRgb(hex) {
  const m = hex.replace('#', '').match(/.{2}/g);
  return m ? m.map((x) => parseInt(x, 16)) : [128, 128, 128];
}

export class Viewport {
  constructor(canvas, opts = {}) {
    this.c = canvas;
    this.ctx = canvas.getContext('2d');
    this.opts = opts;
    this.view = { cx: 0, cy: 0, s: 40 };
    this.map = null;          // {meta, img (offscreen canvas)}
    this.costmaps = { global: null, local: null };
    this.layers = Object.assign({ map: true, global: true, local: true, scan: true, sensors: true, perception: true, plan: true, trail: true, grid: false, others: true }, opts.layers || {});
    this.scene = { static_obs: [], dyn_obs: [], start: null, goal: null };
    this.live = null;         // sim state
    this.sensors = null;      // latest range-sensor views {name: {type, hits, ...}} (5 Hz)
    this.perception = null;   // perception node state {confirmed: {obstacle, drop}, candidates, counts}
    this.plans = { global: null, local: null };
    this.robot = null;        // profile
    this.robotColor = null;   // overrides --robot (comparison slots)
    this.trail = [];
    this.tool = 'select';
    this.toolOpts = { poleR: 0.1, poleZ1: OBS_TOP, chairSize: 0.45, pedSpeed: 0.6, pedR: 0.22, boxZ0: 0, boxZ1: OBS_TOP, cliffDepth: 0.3 };
    this.follow = false;
    this.sel = null;          // selected object ref {kind:'static'|'dyn', idx, g}
    this.drag = null;
    this.hover = null;
    this.mouseW = null;
    this.dirty = true;
    this._colors();
    this._bind();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    // views of a comparison share one `view` object: redraw when it moved even if this one is idle
    const loop = () => {
      const sig = `${this.view.cx},${this.view.cy},${this.view.s}`;
      if (this.W > 1 && this.H > 1 && (this.dirty || this.live || sig !== this._sig)) { this._sig = sig; this.draw(); }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ setup
  _colors() {
    const v = (n) => cssVar(n);
    this.col = {
      free: v('--map-free'), occ: v('--map-occ'), unk: v('--map-unk'), stage: v('--stage'), robot: v('--robot'),
      plan: v('--plan'), lplan: v('--lplan'), scan: v('--scan'), ped: v('--ped'), obs: v('--obs'), obsInk: v('--obs-ink'),
      trail: v('--trail'), goal: v('--goal'), start: v('--start'), ink: v('--ink'), muted: v('--muted'), line: v('--line'),
      bad: v('--bad'), accent: v('--accent'), panel: v('--panel'), cliff: v('--cliff'), perc: v('--perc'),
    };
    this.dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
      (!document.documentElement.getAttribute('data-theme') && matchMedia('(prefers-color-scheme: dark)').matches);
  }

  themeChanged() {
    this._colors();
    if (this.map) this._paintMap();
    for (const w of ['global', 'local']) if (this.costmaps[w]) this._paintCostmap(w);
    this.dirty = true;
  }

  resize() {
    const r = this.c.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.W = r.width; this.H = r.height;
    this.c.width = Math.max(1, Math.round(r.width * dpr));
    this.c.height = Math.max(1, Math.round(r.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.dirty = true;
  }

  async setMap(meta, gridUrl) {
    const img = new Image();
    img.src = gridUrl;
    await img.decode();
    const off = document.createElement('canvas');
    off.width = img.width; off.height = img.height;
    const g = off.getContext('2d');
    g.drawImage(img, 0, 0);
    const changedMap = !this.map || this.map.meta.id !== meta.id;
    this.map = { meta, raw: g.getImageData(0, 0, img.width, img.height), canvas: off };
    this._paintMap();
    if (changedMap) { this.costmaps = { global: null, local: null }; this.trail = []; }
    this.fit();
  }

  // share another viewport's decoded map (comparison views show the same map)
  adoptMap(other) {
    const changed = !this.map || !other.map || this.map.meta.id !== other.map.meta.id;
    this.map = other.map;
    if (changed) { this.costmaps = { global: null, local: null }; this.trail = []; }
    this.dirty = true;
  }

  _paintMap() {
    const { raw, canvas } = this.map;
    const out = new ImageData(raw.width, raw.height);
    const cf = hexToRgb(this.col.free), co = hexToRgb(this.col.occ), cu = hexToRgb(this.col.unk);
    for (let i = 0; i < raw.data.length; i += 4) {
      const v = raw.data[i];
      const c = v === 1 ? co : v === 2 ? cu : cf;
      out.data[i] = c[0]; out.data[i + 1] = c[1]; out.data[i + 2] = c[2]; out.data[i + 3] = 255;
    }
    canvas.getContext('2d').putImageData(out, 0, 0);
    this.dirty = true;
  }

  setCostmap(which, cm, data) {
    this.costmaps[which] = { ...cm, data };
    this._paintCostmap(which);
  }

  _paintCostmap(which) {
    const cm = this.costmaps[which];
    if (!cm) return;
    if (!this.lut) this.lut = {};
    const key = this.dark ? 'd' : 'l';
    if (!this.lut[key]) {
      const lut = new Uint8ClampedArray(256 * 4);
      const lo = this.dark ? [77, 193, 228] : [13, 126, 166], hi = this.dark ? [196, 120, 220] : [192, 40, 122];
      for (let v = 1; v <= 98; v++) {
        const t = v / 98;
        lut.set([lo[0] + (hi[0] - lo[0]) * t, lo[1] + (hi[1] - lo[1]) * t, lo[2] + (hi[2] - lo[2]) * t, 30 + 120 * t], v * 4);
      }
      lut.set(this.dark ? [150, 110, 205, 150] : [110, 40, 150, 165], 99 * 4);   // inscribed
      lut.set(this.dark ? [112, 92, 150, 170] : [60, 15, 50, 215], 100 * 4);     // lethal
      this.lut[key] = lut;
    }
    const lut = this.lut[key];
    const img = new ImageData(cm.w, cm.h);
    // costmap row 0 is the bottom (min y); flip into image rows
    for (let y = 0; y < cm.h; y++) {
      const src = y * cm.w, dst = (cm.h - 1 - y) * cm.w;
      for (let x = 0; x < cm.w; x++) {
        const v = cm.data[src + x];
        img.data.set(lut.subarray(v * 4, v * 4 + 4), (dst + x) * 4);
      }
    }
    if (!cm.canvas || cm.canvas.width !== cm.w || cm.canvas.height !== cm.h) {
      cm.canvas = document.createElement('canvas');
      cm.canvas.width = cm.w; cm.canvas.height = cm.h;
    }
    cm.canvas.getContext('2d').putImageData(img, 0, 0);
    this.dirty = true;
  }

  clearLive() {
    this.costmaps = { global: null, local: null };
    this.plans = { global: null, local: null };
    this.live = null;
    this.sensors = null;
    this.perception = null;
    this.trail = [];
    this.dirty = true;
  }

  setLive(sim) {
    const prev = this.live;
    this.live = sim;
    if (sim && sim.pose) {
      const p = sim.pose;
      const last = this.trail[this.trail.length - 1];
      if (prev && prev.pose && Math.hypot(p[0] - prev.pose[0], p[1] - prev.pose[1]) > 1.0) this.trail = [];
      if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.04) this.trail.push([p[0], p[1]]);
      if (this.trail.length > 4000) this.trail.splice(0, 1000);
      if (this.follow) { this.view.cx = p[0]; this.view.cy = p[1]; }
    }
    this.dirty = true;
  }

  resetTrail() { this.trail = []; this.dirty = true; }

  // ------------------------------------------------------------ transforms
  toS(x, y) { return [(x - this.view.cx) * this.view.s + this.W / 2, this.H / 2 - (y - this.view.cy) * this.view.s]; }
  toW(sx, sy) { return [(sx - this.W / 2) / this.view.s + this.view.cx, (this.H / 2 - sy) / this.view.s + this.view.cy]; }

  fit() {
    if (!this.map) return;
    const m = this.map.meta, raw = this.map.raw;
    // fit to the known (non-unknown) area
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let y = 0; y < raw.height; y += 2) for (let x = 0; x < raw.width; x += 2) {
      if (raw.data[(y * raw.width + x) * 4] !== 2) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    }
    if (!isFinite(x0)) { x0 = 0; y0 = 0; x1 = raw.width; y1 = raw.height; }
    const wx0 = m.origin[0] + x0 * m.resolution, wx1 = m.origin[0] + x1 * m.resolution;
    const wy1 = m.origin[1] + (raw.height - y0) * m.resolution, wy0 = m.origin[1] + (raw.height - y1) * m.resolution;
    // fitPad: screen margins kept free of map (floating bars / slot header); the map is centred in what is left
    const pad = this.fitPad || { x: 20, top: 60, bottom: 60 };
    this.view.s = Math.min((this.W - 2 * pad.x) / Math.max(wx1 - wx0, 1), (this.H - pad.top - pad.bottom) / Math.max(wy1 - wy0, 1));
    this.view.s = Math.max(4, Math.min(this.view.s, 400));
    this.view.cx = (wx0 + wx1) / 2;
    this.view.cy = (wy0 + wy1) / 2 + (pad.top - pad.bottom) / 2 / this.view.s;
    this.dirty = true;
  }

  centerOn(x, y) { this.view.cx = x; this.view.cy = y; this.dirty = true; }

  // ------------------------------------------------------------ drawing
  draw() {
    this.dirty = false;
    const g = this.ctx, s = this.view.s;
    g.fillStyle = this.col.stage;
    g.fillRect(0, 0, this.W, this.H);
    if (this.map && this.layers.map) {
      const m = this.map.meta;
      const [sx, sy] = this.toS(m.origin[0], m.origin[1] + m.height * m.resolution);
      g.imageSmoothingEnabled = s / (1 / m.resolution) < 2;
      g.drawImage(this.map.canvas, sx, sy, m.width * m.resolution * s, m.height * m.resolution * s);
    }
    for (const which of ['global', 'local']) {
      const cm = this.costmaps[which];
      if (!cm || !cm.canvas || !this.layers[which]) continue;
      const [sx, sy] = this.toS(cm.ox, cm.oy + cm.h * cm.res);
      g.imageSmoothingEnabled = false;
      g.globalAlpha = which === 'global' ? 0.55 : 0.9;
      g.drawImage(cm.canvas, sx, sy, cm.w * cm.res * s, cm.h * cm.res * s);
      g.globalAlpha = 1;
      if (which === 'local') {
        g.strokeStyle = this.col.muted; g.setLineDash([4, 4]); g.lineWidth = 1;
        g.strokeRect(sx, sy, cm.w * cm.res * s, cm.h * cm.res * s); g.setLineDash([]);
      }
    }
    if (this.layers.grid) this._grid();
    this._cliffs();
    this._staticObs();
    if (this.layers.others && this.opts.others) {
      for (const o of this.opts.others(this)) if (o.trail.length > 1) this._poly(o.trail, o.color, 2, 0.55);
    }
    if (this.layers.trail && this.trail.length > 1) this._poly(this.trail, this.robotColor || this.col.trail, 2, 0.8);
    if (this.layers.plan && this.plans.global) this._poly(this.plans.global, this.col.plan, 2, 0.95);
    if (this.layers.plan && this.plans.local) this._poly(this.plans.local, this.col.lplan, 2.5, 0.95);
    this._peds();
    if (this.layers.scan && this.live && this.live.scan) {
      g.fillStyle = this.col.scan;
      const r = Math.max(1.2, Math.min(2.6, s * 0.03));
      for (const p of this.live.scan) { const [x, y] = this.toS(p[0], p[1]); g.fillRect(x - r / 2, y - r / 2, r, r); }
    }
    if (this.layers.perception && this.perception) this._perception();
    if (this.layers.sensors && this.sensors && this.live) this._sensorHits();
    if (this.scene.start && !(this.live && this.live.pose)) this._ghostRobot(this.scene.start);
    this._marker(this.scene.start, this.startBad ? this.col.bad : this.col.start, 'S');
    this._goal(this.scene.goal);
    if (this.live && this.live.pose) this._robot(this.live.pose, this.live.contact || this.live.fallen);
    this._preview();
    this.opts.onDraw && this.opts.onDraw(this);
  }

  _grid() {
    const g = this.ctx, s = this.view.s;
    const step = s > 60 ? 0.5 : s > 20 ? 1 : s > 6 ? 5 : 10;
    const [x0, y1] = this.toW(0, 0), [x1, y0] = this.toW(this.W, this.H);
    g.strokeStyle = this.col.line; g.lineWidth = 1; g.beginPath();
    for (let x = Math.floor(x0 / step) * step; x <= x1; x += step) { const [sx] = this.toS(x, 0); g.moveTo(sx, 0); g.lineTo(sx, this.H); }
    for (let y = Math.floor(y0 / step) * step; y <= y1; y += step) { const [, sy] = this.toS(0, y); g.moveTo(0, sy); g.lineTo(this.W, sy); }
    g.stroke();
  }

  _poly(pts, color, w, alpha = 1) {
    const g = this.ctx;
    g.strokeStyle = color; g.lineWidth = w; g.globalAlpha = alpha; g.lineJoin = 'round'; g.lineCap = 'round';
    g.beginPath();
    pts.forEach((p, i) => { const [x, y] = this.toS(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); });
    g.stroke(); g.globalAlpha = 1;
  }

  _staticObs() {
    const g = this.ctx, s = this.view.s;
    this.scene.static_obs.forEach((o, i) => {
      if (o.type === 'cliff') return;
      const selected = this.sel && this.sel.kind === 'static' && (this.sel.idx === i || (this.sel.g && o.g === this.sel.g));
      const [z0, z1] = obsZ(o);
      const over = z0 > 0.001, low = !over && z1 < 0.3;
      g.fillStyle = this.col.obs; g.strokeStyle = selected ? this.col.accent : this.col.obsInk; g.lineWidth = selected ? 2.5 : 1;
      g.globalAlpha = over ? 0.25 : low ? 0.55 : 1;
      const shape = () => {
        g.beginPath();
        if (o.type === 'circle') { const [x, y] = this.toS(o.x, o.y); g.arc(x, y, Math.max(o.r * s, 1.5), 0, TAU); return [x, y, o.r * s * 2]; }
        const { cx, cy, w, h, yaw } = rectOf(o), [x, y] = this.toS(cx, cy), c = Math.cos(-(yaw || 0)), n = Math.sin(-(yaw || 0));
        [[-w, -h], [w, -h], [w, h], [-w, h]].forEach(([a, b], k) => { const px = x + (a * c - b * n) * s / 2, py = y + (a * n + b * c) * s / 2; k ? g.lineTo(px, py) : g.moveTo(px, py); });
        g.closePath();
        return [x, y, Math.min(w, h) * s];
      };
      const [lx, ly, size] = shape();
      g.fill(); g.globalAlpha = 1;
      if (over) g.setLineDash([5, 3]);
      g.stroke(); g.setLineDash([]);
      const lab = heightLabel(o);
      if (lab && (size > 26 || selected)) {
        g.font = '600 10px var(--f-ui), sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
        g.fillStyle = this.col.obsInk; g.fillText(lab, lx, ly);
        g.textAlign = 'start'; g.textBaseline = 'alphabetic';
      }
    });
  }

  // drops: hatched area, the depth as a label
  _cliffs() {
    const g = this.ctx, s = this.view.s;
    this.scene.static_obs.forEach((o, i) => {
      if (o.type !== 'cliff') return;
      const selected = this.sel && this.sel.kind === 'static' && this.sel.idx === i;
      const [a, b] = [this.toS(o.x0, o.y1), this.toS(o.x1, o.y0)];
      const w = b[0] - a[0], hh = b[1] - a[1];
      g.save();
      g.fillStyle = this.col.cliff; g.globalAlpha = 0.28; g.fillRect(a[0], a[1], w, hh); g.globalAlpha = 0.7;
      g.beginPath(); g.rect(a[0], a[1], w, hh); g.clip();
      g.strokeStyle = this.col.cliff; g.lineWidth = 1; g.beginPath();
      for (let k = -hh; k < w; k += 8) { g.moveTo(a[0] + k, a[1] + hh); g.lineTo(a[0] + k + hh, a[1]); }
      g.stroke(); g.restore();
      g.strokeStyle = selected ? this.col.accent : this.col.cliff; g.lineWidth = selected ? 2.5 : 1.5; g.strokeRect(a[0], a[1], w, hh);
      if (Math.min(w, hh) > 22 || selected) {
        g.font = '600 10px var(--f-ui), sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
        const lab = heightLabel(o), tw = g.measureText(lab).width + 8;
        g.fillStyle = this.col.panel; g.globalAlpha = 0.85; g.fillRect(a[0] + w / 2 - tw / 2, a[1] + hh / 2 - 7, tw, 14); g.globalAlpha = 1;
        g.fillStyle = this.col.cliff; g.fillText(lab, a[0] + w / 2, a[1] + hh / 2);
        g.textAlign = 'start'; g.textBaseline = 'alphabetic';
      }
      void s;
    });
  }

  // where the range sensors hit (map frame, 5 Hz), each in its sensor colour
  _sensorHits() {
    const g = this.ctx, cols = Object.fromEntries(((this.robot && this.robot.sensors) || []).map((sn) => [sn.name, sn.color]));
    const r = Math.max(1.5, Math.min(3, this.view.s * 0.02));
    for (const [name, v] of Object.entries(this.sensors)) {
      if (!v || !v.hits || !v.hits.length) continue;
      g.fillStyle = cols[name] || this.col.scan;
      for (const p of v.hits) {           // floor returns faint and small; things above or below the floor solid
        const floor = Math.abs(p[2] || 0) < 0.015;
        g.globalAlpha = floor ? 0.3 : 0.95;
        const [x, y] = this.toS(p[0], p[1]), rr = floor ? r * 0.6 : r;
        g.beginPath(); g.arc(x, y, rr, 0, TAU); g.fill();
      }
    }
    g.globalAlpha = 1;
  }

  // confirmed perception marks: low obstacles (filled squares) and drops (crosses); candidates faint
  _perception() {
    const g = this.ctx, p = this.perception, h = Math.max(2, Math.min(5, this.view.s * 0.025));
    const cand = p.candidates || {}, conf = p.confirmed || {};
    g.globalAlpha = 0.35; g.fillStyle = this.col.perc;
    for (const q of cand.obstacle || []) { const [x, y] = this.toS(q[0], q[1]); g.fillRect(x - h / 2, y - h / 2, h, h); }
    g.globalAlpha = 1; g.strokeStyle = this.col.ink; g.lineWidth = 0.75;
    for (const q of conf.obstacle || []) { const [x, y] = this.toS(q[0], q[1]); g.fillRect(x - h, y - h, 2 * h, 2 * h); g.strokeRect(x - h, y - h, 2 * h, 2 * h); }
    g.strokeStyle = this.col.cliff; g.lineWidth = 1.5; g.beginPath();
    for (const q of conf.drop || []) { const [x, y] = this.toS(q[0], q[1]); g.moveTo(x - h, y - h); g.lineTo(x + h, y + h); g.moveTo(x + h, y - h); g.lineTo(x - h, y + h); }
    g.stroke();
  }

  _peds() {
    const g = this.ctx, s = this.view.s;
    this.scene.dyn_obs.forEach((d, i) => {
      const selected = this.sel && this.sel.kind === 'dyn' && this.sel.idx === i;
      g.setLineDash([5, 5]); g.strokeStyle = this.col.ped; g.lineWidth = selected ? 2.5 : 1.5; g.globalAlpha = 0.8;
      g.beginPath(); d.wps.forEach((p, k) => { const [x, y] = this.toS(p[0], p[1]); k ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
      g.setLineDash([]); g.globalAlpha = 1;
      for (const p of [d.wps[0], d.wps[d.wps.length - 1]]) { const [x, y] = this.toS(p[0], p[1]); g.fillStyle = this.col.ped; g.beginPath(); g.arc(x, y, 3, 0, TAU); g.fill(); }
    });
    const live = (this.live && this.live.dyn) || [];
    for (const [px, py, r] of live) {
      const [x, y] = this.toS(px, py);
      g.fillStyle = this.col.ped; g.globalAlpha = 0.85;
      g.beginPath(); g.arc(x, y, Math.max(r * s, 3), 0, TAU); g.fill(); g.globalAlpha = 1;
    }
    if (!live.length) {  // not running: show where pedestrians start
      for (const d of this.scene.dyn_obs) {
        const [x, y] = this.toS(d.wps[0][0], d.wps[0][1]);
        g.strokeStyle = this.col.ped; g.lineWidth = 1.5; g.beginPath(); g.arc(x, y, Math.max((d.r || 0.22) * s, 3), 0, TAU); g.stroke();
      }
    }
  }

  _robotShape(pose, fill, stroke, alpha, contact) {
    if (!this.robot) return;
    const g = this.ctx, s = this.view.s, [x, y, th] = pose;
    const poly = robotPolygon(this.robot);
    g.save(); const [sx, sy] = this.toS(x, y); g.translate(sx, sy); g.rotate(-th);
    g.globalAlpha = alpha; g.fillStyle = fill; g.strokeStyle = contact ? this.col.bad : stroke; g.lineWidth = contact ? 3 : 1.5;
    g.beginPath(); poly.forEach((p, i) => { i ? g.lineTo(p[0] * s, -p[1] * s) : g.moveTo(p[0] * s, -p[1] * s); }); g.closePath(); g.fill(); g.stroke();
    const reach = Math.max(...poly.map((p) => p[0]));
    g.strokeStyle = stroke; g.lineWidth = 2; g.beginPath(); g.moveTo(0, 0); g.lineTo(Math.max(reach, 0.1) * s, 0); g.stroke();
    for (const sn of this.robot.sensors || []) {
      if (sn.enabled === false) continue;
      g.fillStyle = sn.color || this.col.ink; g.strokeStyle = this.col.ink; g.lineWidth = 1;
      g.beginPath(); g.arc(sn.x * s, -sn.y * s, Math.max(2, Math.min(5, 0.012 * s)), 0, TAU); g.fill(); g.stroke();
    }
    g.restore(); g.globalAlpha = 1;
  }

  _robot(pose, contact) { this._robotShape(pose, this.robotColor || this.col.robot, this.col.ink, 0.9, contact); }
  _ghostRobot(pose) { this._robotShape(pose, this.startBad ? this.col.bad : this.col.robot, this.col.ink, 0.35, !!this.startBad); }

  _marker(pose, color, label) {
    if (!pose) return;
    const g = this.ctx, [x, y] = this.toS(pose[0], pose[1]);
    g.strokeStyle = color; g.fillStyle = color; g.lineWidth = 2;
    g.beginPath(); g.arc(x, y, 7, 0, TAU); g.stroke();
    const th = pose[2] || 0;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x + 18 * Math.cos(th), y - 18 * Math.sin(th)); g.stroke();
    g.font = '600 10px ui-monospace, monospace'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(label, x, y + 0.5);
  }

  _goal(pose) {
    if (!pose) return;
    const g = this.ctx, [x, y] = this.toS(pose[0], pose[1]), th = pose[2] || 0;
    g.fillStyle = this.col.goal; g.strokeStyle = this.col.goal; g.lineWidth = 2;
    g.beginPath(); g.moveTo(x, y); g.lineTo(x, y - 26); g.stroke();
    g.beginPath(); g.moveTo(x, y - 26); g.lineTo(x + 14, y - 21); g.lineTo(x, y - 16); g.closePath(); g.fill();
    g.beginPath(); g.arc(x, y, 4, 0, TAU); g.fill();
    g.globalAlpha = 0.7; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 20 * Math.cos(th), y - 20 * Math.sin(th)); g.stroke(); g.globalAlpha = 1;
  }

  _preview() {
    const d = this.drag, g = this.ctx;
    if (!d) return;
    g.strokeStyle = this.col.accent; g.lineWidth = 2; g.setLineDash([6, 4]);
    if (d.kind === 'box') {
      const [a, b] = [this.toS(d.x0, d.y0), this.toS(d.x1, d.y1)];
      g.fillStyle = d.cliff ? this.col.cliff : this.col.obs; g.globalAlpha = 0.4; g.fillRect(a[0], a[1], b[0] - a[0], b[1] - a[1]); g.globalAlpha = 1;
      g.strokeRect(a[0], a[1], b[0] - a[0], b[1] - a[1]);
    } else if (d.kind === 'person' && d.pts) {
      const pts = [...d.pts, this.mouseW];
      g.beginPath(); pts.forEach((p, i) => { const [x, y] = this.toS(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke();
    } else if (d.kind === 'pose') {
      const [x, y] = this.toS(d.x, d.y), [mx, my] = this.toS(this.mouseW[0], this.mouseW[1]);
      g.beginPath(); g.moveTo(x, y); g.lineTo(mx, my); g.stroke();
      if (this.robot) { g.setLineDash([]); this._robotShape([d.x, d.y, Math.atan2(this.mouseW[1] - d.y, this.mouseW[0] - d.x)], this.col.accent, this.col.accent, 0.3, false); }
    }
    g.setLineDash([]);
  }

  // ------------------------------------------------------------ interaction
  _bind() {
    const c = this.c;
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const r = c.getBoundingClientRect();
      const [wx, wy] = this.toW(e.clientX - r.left, e.clientY - r.top);
      const k = Math.exp(-e.deltaY * 0.0015);
      this.view.s = Math.max(2, Math.min(600, this.view.s * k));
      const [nx, ny] = this.toW(e.clientX - r.left, e.clientY - r.top);
      this.view.cx += wx - nx; this.view.cy += wy - ny;
      this.dirty = true;
    }, { passive: false });
    c.addEventListener('contextmenu', (e) => e.preventDefault());
    c.addEventListener('pointerdown', (e) => this._down(e));
    c.addEventListener('pointermove', (e) => this._move(e));
    c.addEventListener('pointerup', (e) => this._up(e));
    c.addEventListener('dblclick', () => { if (this.drag && this.drag.kind === 'person') this._finishPerson(); });
    window.addEventListener('keydown', (e) => {
      if (e.target.closest && e.target.closest('input, textarea, select')) return;
      if ((e.key === 'Delete' || e.key === 'Backspace') && this.sel) { this._deleteSel(); e.preventDefault(); }
      if (e.key === 'Escape') { this.drag = null; if (this.sel) { this.sel = null; this.opts.onSelect && this.opts.onSelect(this, null); } this.dirty = true; }
      if (e.key === 'Enter' && this.drag && this.drag.kind === 'person') this._finishPerson();
    });
  }

  _pos(e) {
    const r = this.c.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  _down(e) {
    this.opts.onActivate && this.opts.onActivate(this);
    const [sx, sy] = this._pos(e);
    const [wx, wy] = this.toW(sx, sy);
    this.c.setPointerCapture(e.pointerId);
    if (e.button === 1 || e.button === 2 || this.tool === 'pan' || (this.tool === 'select' && !this._hit(wx, wy))) {
      if (this.tool === 'select') this.sel = null;
      this.pan = { sx, sy, cx: this.view.cx, cy: this.view.cy };
      this.follow = false; this.opts.onFollowChange && this.opts.onFollowChange(false);
      return;
    }
    if (!this.opts.editable) return;
    const t = this.tool;
    if (t === 'select') {
      const hit = this._hit(wx, wy);
      this.sel = hit;
      this.move = { wx, wy, moved: false };
      this.opts.onSelect && this.opts.onSelect(this, hit);
    } else if (t === 'start' || t === 'goal') {
      this.drag = { kind: 'pose', which: t, x: wx, y: wy };
    } else if (t === 'box' || t === 'cliff') {
      this.drag = { kind: 'box', cliff: t === 'cliff', x0: wx, y0: wy, x1: wx, y1: wy };
    } else if (t === 'pole') {
      this.scene.static_obs.push({ type: 'circle', x: r3(wx), y: r3(wy), r: this.toolOpts.poleR, ...heights(0, this.toolOpts.poleZ1) });
      this._changed();
    } else if (t === 'chair') {
      const g = newGroupId(), a = this.toolOpts.chairSize / 2;
      for (const [dx, dy] of [[-a, -a], [a, -a], [a, a], [-a, a]]) this.scene.static_obs.push({ type: 'circle', x: r3(wx + dx), y: r3(wy + dy), r: 0.025, g });
      this._changed();
    } else if (t === 'person') {
      if (!this.drag || this.drag.kind !== 'person') this.drag = { kind: 'person', pts: [[r3(wx), r3(wy)]] };
      else this.drag.pts.push([r3(wx), r3(wy)]);
      if (this.drag.pts.length >= 2 && !e.shiftKey) this._finishPerson();
    } else if (t === 'eraser') {
      const hit = this._hit(wx, wy);
      if (hit) { this.sel = hit; this._deleteSel(); }
    }
    this.dirty = true;
  }

  _move(e) {
    const [sx, sy] = this._pos(e);
    const [wx, wy] = this.toW(sx, sy);
    this.mouseW = [wx, wy];
    this.opts.onMouse && this.opts.onMouse(wx, wy);
    if (this.pan) {
      this.view.cx = this.pan.cx - (sx - this.pan.sx) / this.view.s;
      this.view.cy = this.pan.cy + (sy - this.pan.sy) / this.view.s;
      this.dirty = true;
      return;
    }
    if (this.move && this.sel) {
      const dx = wx - this.move.wx, dy = wy - this.move.wy;
      if (Math.abs(dx) + Math.abs(dy) > 1e-4) {
        this._translateSel(dx, dy);
        this.move.wx = wx; this.move.wy = wy; this.move.moved = true;
      }
    }
    if (this.drag && this.drag.kind === 'box') { this.drag.x1 = wx; this.drag.y1 = wy; }
    this.c.style.cursor = this.tool === 'pan' ? 'grab' : this.tool === 'select' ? (this._hit(wx, wy) ? 'move' : 'default') :
      this.tool === 'eraser' ? (this._hit(wx, wy) ? 'pointer' : 'not-allowed') : 'crosshair';
    this.dirty = true;
  }

  _up(e) {
    if (this.pan) { this.pan = null; return; }
    if (this.move) { if (this.move.moved) this._changed(); this.move = null; return; }
    const d = this.drag;
    if (!d) return;
    if (d.kind === 'pose') {
      const th = Math.hypot(this.mouseW[0] - d.x, this.mouseW[1] - d.y) > 0.05 ? Math.atan2(this.mouseW[1] - d.y, this.mouseW[0] - d.x) : 0;
      const pose = [r3(d.x), r3(d.y), r3(th)];
      this.drag = null;
      if (d.which === 'start') this.opts.onStart && this.opts.onStart(pose);
      else this.opts.onGoal && this.opts.onGoal(pose);
    } else if (d.kind === 'box') {
      const w = Math.abs(d.x1 - d.x0), h = Math.abs(d.y1 - d.y0);
      this.drag = null;
      if (w > 0.03 && h > 0.03) {
        const r = { x0: r3(Math.min(d.x0, d.x1)), y0: r3(Math.min(d.y0, d.y1)), x1: r3(Math.max(d.x0, d.x1)), y1: r3(Math.max(d.y0, d.y1)) };
        const o = d.cliff ? { type: 'cliff', ...r, depth: this.toolOpts.cliffDepth } : { type: 'rect', ...r, ...heights(this.toolOpts.boxZ0, this.toolOpts.boxZ1) };
        this.scene.static_obs.push(o);
        this._changed();
      }
    }
    this.dirty = true;
  }

  _finishPerson() {
    const d = this.drag;
    this.drag = null;
    if (d && d.pts.length >= 2) {
      this.scene.dyn_obs.push({ wps: d.pts, speed: this.toolOpts.pedSpeed, r: this.toolOpts.pedR, phase: 0 });
      this._changed();
    }
  }

  _hit(wx, wy) {
    const so = this.scene.static_obs;
    for (const cliffs of [false, true]) {
      for (let i = so.length - 1; i >= 0; i--) {
        const o = so[i];
        if ((o.type === 'cliff') !== cliffs) continue;
        if (o.type === 'circle' ? Math.hypot(wx - o.x, wy - o.y) <= Math.max(o.r, 6 / this.view.s) : inRect(o, wx, wy)) return { kind: 'static', idx: i, g: o.g };
      }
    }
    const dy = this.scene.dyn_obs;
    for (let i = dy.length - 1; i >= 0; i--) {
      const w = dy[i].wps;
      for (let k = 0; k < w.length - 1; k++) if (segDist(wx, wy, w[k], w[k + 1]) < 8 / this.view.s) return { kind: 'dyn', idx: i };
    }
    return null;
  }

  _translateSel(dx, dy) {
    const s = this.sel;
    if (s.kind === 'dyn') { for (const p of this.scene.dyn_obs[s.idx].wps) { p[0] += dx; p[1] += dy; } return; }
    const targets = s.g ? this.scene.static_obs.filter((o) => o.g === s.g) : [this.scene.static_obs[s.idx]];
    for (const o of targets) {
      if (o.type === 'circle') { o.x += dx; o.y += dy; }
      else if ('x0' in o) { o.x0 += dx; o.x1 += dx; o.y0 += dy; o.y1 += dy; }
      else { o.cx += dx; o.cy += dy; }
    }
  }

  _deleteSel() {
    const s = this.sel;
    if (!s) return;
    if (s.kind === 'dyn') this.scene.dyn_obs.splice(s.idx, 1);
    else if (s.g) this.scene.static_obs = this.scene.static_obs.filter((o) => o.g !== s.g);
    else this.scene.static_obs.splice(s.idx, 1);
    this.sel = null;
    this.opts.onSelect && this.opts.onSelect(this, null);
    this._changed();
  }

  _changed() {
    for (const o of this.scene.static_obs) for (const k of ['x', 'y', 'x0', 'x1', 'y0', 'y1', 'cx', 'cy']) if (k in o) o[k] = r3(o[k]);
    this.dirty = true;
    this.opts.onScene && this.opts.onScene(this.scene);
  }
}

function r3(v) { return Math.round(v * 1000) / 1000; }
// z0/z1 only when they differ from the default (floor to 1 m), so ordinary scenes stay as before
function heights(z0, z1) {
  const o = {};
  if (z0 > 0.0005) o.z0 = r3(z0);
  if (Math.abs(z1 - OBS_TOP) > 0.0005) o.z1 = r3(z1);
  return o;
}
function rectOf(o) {
  if ('x0' in o) return { cx: (o.x0 + o.x1) / 2, cy: (o.y0 + o.y1) / 2, w: o.x1 - o.x0, h: o.y1 - o.y0, yaw: 0 };
  return { cx: o.cx, cy: o.cy, w: o.w, h: o.h, yaw: o.yaw || 0 };
}
function inRect(o, x, y) {
  const r = rectOf(o), c = Math.cos(-r.yaw), s = Math.sin(-r.yaw);
  const lx = c * (x - r.cx) - s * (y - r.cy), ly = s * (x - r.cx) + c * (y - r.cy);
  return Math.abs(lx) <= r.w / 2 && Math.abs(ly) <= r.h / 2;
}
function segDist(px, py, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy || 1e-9;
  const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / L));
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}
