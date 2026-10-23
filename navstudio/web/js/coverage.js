// Detection coverage in the robot designer: where a probe object (low box, threshold, overhang, chair leg, box, drop)
// would be detected around the standing robot, by which sensor, and whether the robot could still stop in time.
// The server runs the sensors' own rays, measurement and perception rules (navstudio/coverage.py).
import { api } from './api.js';
import { h, icon, debounce, persist } from './ui.js';

const STATE_COL = { ok: '--good', late: '--warn', blind: '--bad' };

export class Coverage {
  constructor(stage, { robot, redraw, ontoggle, onfirst }) {
    this.robot = robot; this.redraw = redraw; this.ontoggle = ontoggle || (() => {}); this.onfirst = onfirst;
    this.on = false; this.data = null; this.busy = false; this.pending = false; this.stale = false; this.error = null;
    this.only = null;                                   // index of the one sensor to show, or null for all
    this.probe = persist('cov.probe') || { preset: 'low' };
    this.probes = null;
    this.panel = h('div', { class: 'covpanel floating', hidden: true });
    this.head = h('div'); this.dyn = h('div', { class: 'covdyn' });
    this.panel.append(this.head, this.dyn);
    stage.append(this.panel);
    this.request = debounce(() => this.compute(), 500);
  }

  async toggle(on = !this.on) {
    this.on = on;
    this.panel.hidden = !on;
    if (on) {
      if (!this.probes) { try { this.probes = await api.get('/api/coverage/probes'); } catch (e) { this.probes = []; } }
      this.renderHead();
      this.first = true;
      this.compute();
    }
    this.ontoggle(on);
    this.redraw();
  }

  robotChanged() {
    if (!this.on) return;
    this.stale = true;
    this.renderDyn();
    this.request();
  }

  async compute() {
    if (!this.on) return;
    if (this.busy) { this.pending = true; return; }       // one request at a time; the latest settings win
    this.busy = true; this.error = null; this.renderDyn();
    try {
      this.data = await api.post('/api/robots/coverage', { robot: this.robot(), probe: this.probe });
      this.stale = false;
      if (this.only !== null && this.only >= this.data.sensors.length) this.only = null;
    } catch (e) { this.error = e.message; }
    this.busy = false;
    if (this.pending) { this.pending = false; this.compute(); }
    else if (this.first) { this.first = false; this.onfirst && this.onfirst(); }
    this.renderDyn(); this.redraw();
  }

  preset() { return (this.probes || []).find((p) => p.id === this.probe.preset) || {}; }
  value(k) { return this.probe[k] ?? this.preset()[k]; }

  renderHead() {
    const pick = (id) => { this.probe = { preset: id }; persist('cov.probe', this.probe); this.renderHead(); this.compute(); };
    const seg = h('div', { class: 'seg wrap' }, ...(this.probes || []).map((p) => h('button', { 'aria-pressed': String(this.probe.preset === p.id), title: p.label, onclick: () => pick(p.id) }, p.short)));
    const cm = (k) => { const v = this.value(k); return v === undefined || v === null ? '' : +(v * 100).toFixed(1); };
    const num = (label, key, step) => h('label', { class: 'field' }, h('span', { text: `${label} (cm)` }),
      h('input', { type: 'number', step, min: 0, value: cm(key), oninput: (e) => {
        const v = parseFloat(e.target.value);
        if (Number.isNaN(v)) return;
        this.probe = { ...this.probe, [key]: v / 100 };
        persist('cov.probe', this.probe); this.request();
      } }));
    const kind = this.preset().kind;
    const fields = kind === 'drop' ? [num('크기', 'size', 1), num('깊이', 'depth', 1)]
      : [num(kind === 'pole' ? '지름' : '크기', 'size', 1), num('아래', 'z0', 0.5), num('위', 'z1', 0.5)];
    this.head.replaceChildren(
      h('div', { class: 'covtitle' }, h('b', { text: '감지 범위' }), h('button', { class: 'reset', title: '닫기', 'aria-label': '감지 범위 닫기', html: icon('x'), onclick: () => this.toggle(false) })),
      h('div', { class: 'hint', text: '로봇이 서 있을 때 이 물체를 각 칸에 놓으면 어느 센서가 감지하는지 (센서 광선·측정·인식 규칙 그대로).' }),
      seg, h('div', { class: 'faint', text: this.preset().label || '' }),
      h('details', { class: 'covsize' }, h('summary', {}, '물체 크기·높이'), h('div', { class: 'grid3' }, ...fields)));
  }

  renderDyn() {
    const d = this.data;
    const status = this.busy ? '계산 중…' : this.error ? '' : this.stale ? '바뀐 설계로 다시 계산합니다' : d ? `${(d.ms / 1000).toFixed(1)} s` : '';
    const out = [h('div', { class: 'faint covstatus', text: status })];
    if (this.error) out.push(h('div', { class: 'errbox', text: this.error }));
    if (d) {
      const S = d.summary, C = S.corridor;
      const pct = (x) => `${Math.round(100 * x)}%`;
      const bar = h('div', { class: 'covbar' }, ...['ok', 'late', 'blind'].map((k) => h('i', { style: { width: pct(C[k]), background: `var(${STATE_COL[k]})` } })));
      const first = C.centre && C.centre.first !== null ? `${C.centre.first.toFixed(2)} m 앞에서 처음 감지` : '정면에서 감지 못 함';
      const ring = ['front', 'left', 'right', 'back'].map((k) => `${{ front: '앞', left: '좌', right: '우', back: '뒤' }[k]} ${S.ring[k] === null ? '–' : pct(S.ring[k])}`).join(' · ');
      out.push(
        h('dl', { class: 'kv' },
          h('dt', { text: '정지 거리' }), h('dd', { title: `반응 ${S.reaction.toFixed(2)} s 동안 ${S.v} m/s 로 가고, ${S.a} m/s² 로 감속`, text: `${S.stop.toFixed(2)} m` }),
          h('dt', { text: '정면' }), h('dd', { text: first }),
          h('dt', { text: `주변 ${S.ring.width} m` }), h('dd', { text: ring })),
        h('div', { class: 'covcorr' }, h('span', { text: `앞 통로 (폭 ${(2 * C.half_width).toFixed(2)} m)` }), bar,
          h('small', {}, h('i', { class: 'dot', style: { background: 'var(--good)' } }), ` 제때 ${pct(C.ok)}  `, h('i', { class: 'dot', style: { background: 'var(--warn)' } }), ` 늦음 ${pct(C.late)}  `,
            h('i', { class: 'dot', style: { background: 'var(--bad)' } }), ` 못 봄 ${pct(C.blind)}`)),
        h('div', { class: 'covlegend' }, ...d.sensors.map((s, i) => h('button', { 'aria-pressed': String(this.only === i), disabled: !s.used,
          title: s.used ? '이 센서만 보기 (다시 누르면 전체)' : '인식 처리가 꺼져 Nav2 에 쓰이지 않음',
          onclick: () => { this.only = this.only === i ? null : i; this.renderDyn(); this.redraw(); } },
          h('i', { class: 'swatch', style: { background: s.color } }), h('span', { text: s.name }), h('small', { class: 'faint', text: s.used ? (s.cells ? `${s.cells}칸` : '못 봄') : '안 씀' })))),
        ...d.notes.map((n) => h('div', { class: 'warnbox', text: n })));
    }
    this.dyn.replaceChildren(...out);
  }

  // ---------------------------------------------------------------- drawing on the designer (top view)
  cellColor(b) {
    if (this.only !== null) return (b >>> this.only) & 1 ? this.data.sensors[this.only].color : null;
    return b ? this.data.sensors[31 - Math.clz32(b & -b)].color : null;       // the first sensor that sees it
  }

  drawUnder(cad) {
    const d = this.data;
    if (!this.on || !d) return;
    const g = cad.g, r = d.res, px = r * cad.s + 0.6;
    g.globalAlpha = this.busy || this.stale ? 0.15 : 0.4;
    for (let iy = 0; iy < d.ny; iy++) {
      for (let ix = 0; ix < d.nx; ix++) {
        const col = this.cellColor(d.bits[iy * d.nx + ix]);
        if (!col) continue;
        const [sx, sy] = cad.S(d.x0 + (ix - 0.5) * r, d.y0 + (iy + 0.5) * r);
        g.fillStyle = col; g.fillRect(sx, sy, px, px);
      }
    }
    if (this.only === null) {                      // blind cells right around the robot, hatched
      g.globalAlpha = this.busy || this.stale ? 0.3 : 0.75; g.fillStyle = this.hatch(g, cad.k.bad);
      for (const k of d.summary.ring_blind) {
        const ix = k % d.nx, iy = Math.floor(k / d.nx);
        const [sx, sy] = cad.S(d.x0 + (ix - 0.5) * r, d.y0 + (iy + 0.5) * r);
        g.fillRect(sx, sy, px, px);
      }
    }
    g.globalAlpha = 1;
  }

  hatch(g, col) {
    if (!this._hatch || this._hatchCol !== col) {
      const c = document.createElement('canvas'); c.width = c.height = 8;
      const x = c.getContext('2d'); x.strokeStyle = col; x.lineWidth = 1.2;
      x.beginPath(); x.moveTo(0, 8); x.lineTo(8, 0); x.moveTo(-2, 2); x.lineTo(2, -2); x.moveTo(6, 10); x.lineTo(10, 6); x.stroke();
      this._hatch = g.createPattern(c, 'repeat'); this._hatchCol = col;
    }
    return this._hatch;
  }

  drawOver(cad) {
    const d = this.data;
    if (!this.on || !d) return;
    const g = cad.g, S = d.summary, C = S.corridor, hw = C.half_width;
    const xEnd = d.x0 + (d.nx - 1) * d.res, xStop = C.start + S.stop;
    g.strokeStyle = cad.k.ink; g.globalAlpha = 0.6; g.lineWidth = 1; g.setLineDash([6, 4]);
    for (const y of [-hw, hw]) { const [a, b] = [cad.S(C.start, y), cad.S(xEnd, y)]; g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.stroke(); }
    g.setLineDash([]); g.globalAlpha = 1;
    // where each lateral strip of the corridor is first seen: ok (room to stop) / late / never
    const half = d.res / 2;
    for (const b of C.bins) {
      g.strokeStyle = cad.k[{ ok: 'good', late: 'warn', blind: 'bad' }[b.state]]; g.lineWidth = 5;
      const [p, q] = [cad.S(xStop, b.y - half), cad.S(xStop, b.y + half)];
      g.beginPath(); g.moveTo(...p); g.lineTo(...q); g.stroke();
    }
    g.lineWidth = 1;
    const [lx, ly] = cad.S(xStop, hw);
    g.font = '600 11px sans-serif'; g.lineJoin = 'round';
    const txt = `정지 거리 ${S.stop.toFixed(2)} m`;
    g.strokeStyle = cad.k.bg; g.lineWidth = 3; g.strokeText(txt, lx + 4, ly - 6); g.fillStyle = cad.k.ink; g.fillText(txt, lx + 4, ly - 6);
  }

  describe(wx, wy) {
    const d = this.data;
    if (!this.on || !d) return null;
    const ix = Math.round((wx - d.x0) / d.res), iy = Math.round((wy - d.y0) / d.res);
    if (ix < 0 || iy < 0 || ix >= d.nx || iy >= d.ny) return null;
    const b = d.bits[iy * d.nx + ix];
    const who = d.sensors.filter((s, i) => (b >>> i) & 1).map((s) => s.name);
    return `x ${wx.toFixed(2)} m, y ${wy.toFixed(2)} m · ${who.length ? '감지: ' + who.join(', ') : '못 봄'}`;
  }
}
