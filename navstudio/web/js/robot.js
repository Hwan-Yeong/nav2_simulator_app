// Robot designer: spec form (left), top-view CAD editor (centre), 3D preview + derived values (right).
import { api } from './api.js';
import { S, emit, on } from './state.js';
import { h, icon, btn, toast, fmt, debounce, cssVar, DRIVE_LABEL, persist } from './ui.js';
import { robotPolygon } from './viewport.js';
import * as sim from './sim.js';

const $ = (id) => document.getElementById(id);
let R = null;            // profile being edited
let srcId = null;        // id it was loaded from
let srcBuiltin = true;
let derived = null;
let error = null;
let preview3d = null;
let cad = null;
let inited = false;

const TEMPLATE_SENSOR = { name: 'lidar', type: 'lidar2d', x: 0, y: 0, z: 0.2, yaw_deg: 0, fov_deg: 270, beams: 540, range_min: 0.05, range_max: 12, hz: 15, noise: 0.01 };

export async function show() {
  if (!inited) {
    inited = true;
    cad = new Cad($('cad'));
    initCadTools();
    try {
      const { Robot3D } = await import('./robot3d.js');
      $('robot3d').replaceChildren(h('div', { class: 'three-wrap', id: 'threeWrap' }), h('div', { class: 'derived', id: 'derived' }));
      preview3d = new Robot3D($('threeWrap'));
    } catch (e) {
      $('robot3d').replaceChildren(h('div', { class: 'derived', id: 'derived' }), h('div', { class: 'errbox', text: '3D 미리보기를 열지 못했습니다 (WebGL): ' + e.message }));
    }
    on('theme', () => { cad.colors(); cad.draw(); preview3d && preview3d.themeChanged(); });
    await load(S.sel.robot ? null : S.sel.robotId, S.sel.robot);
  }
  cad.resize();
  preview3d && preview3d.resize();
}

async function load(id, profile = null) {
  if (profile) { R = JSON.parse(JSON.stringify(profile)); srcId = null; srcBuiltin = false; }
  else {
    const r = await api.get(`/api/robots/${id}`);
    R = r.profile; srcId = id; srcBuiltin = !!(S.robots.find((x) => x.id === id) || {}).builtin;
  }
  changed(true);
  cad.fit();
}

const validate = debounce(async () => {
  try {
    const r = await api.post('/api/robots/validate', R);
    derived = r.derived; error = null;
  } catch (e) { error = e.message; }
  renderDerived();
}, 200);

function changed(rebuildForm = false) {
  if (rebuildForm) renderForm();
  cad.robot = R; cad.draw();
  preview3d && preview3d.update(R);
  validate();
}

// ================================================================== form
function num(label, obj, key, opts = {}) {
  const inp = h('input', { type: 'number', step: opts.step || 0.01, min: opts.min, max: opts.max, value: obj[key], 'aria-label': label,
    oninput: (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) { obj[key] = opts.int ? Math.round(v) : v; changed(); } } });
  return h('label', { class: 'field' }, h('span', { text: label + (opts.unit ? ` (${opts.unit})` : '') }), inp);
}

function renderForm() {
  const f = $('robotForm');
  const list = h('select', { 'aria-label': '불러올 로봇', onchange: (e) => load(e.target.value) },
    ...S.robots.map((r) => h('option', { value: r.id, selected: r.id === srcId }, `${r.name}${r.builtin ? '' : ' (내 로봇)'}`)));
  if (!srcId) list.prepend(h('option', { value: '', selected: true }, '(저장되지 않은 로봇)'));
  const drive = h('div', { class: 'seg', role: 'radiogroup' }, ...Object.entries(DRIVE_LABEL).map(([k, v]) =>
    h('button', { 'aria-pressed': String(R.drive === k), onclick: () => {
      R.drive = k;
      if (k === 'ackermann' && !(R.wheels.wheelbase > 0)) { R.wheels.wheelbase = 0.5; R.wheels.max_steer_deg = 30; }
      if (k === 'omni' && !(R.limits.vy_max > 0)) R.limits.vy_max = 0.4;
      if (k === 'ackermann' && R.footprint.type === 'circle') toast('차량형은 보통 base_link 가 뒷바퀴 축입니다. 다각형 footprint 를 권장합니다.');
      changed(true);
    } }, v)));
  const fpType = h('div', { class: 'seg' },
    h('button', { 'aria-pressed': String(R.footprint.type === 'circle'), onclick: () => { R.footprint.type = 'circle'; R.footprint.radius = R.footprint.radius || 0.2; changed(true); } }, '원형'),
    h('button', { 'aria-pressed': String(R.footprint.type === 'polygon'), onclick: () => {
      if (R.footprint.type !== 'polygon') {
        const r = R.footprint.radius || 0.25;
        R.footprint.points = (R.footprint.points && R.footprint.points.length >= 3) ? R.footprint.points : [[r, r * 0.7], [-r, r * 0.7], [-r, -r * 0.7], [r, -r * 0.7]];
      }
      R.footprint.type = 'polygon'; changed(true);
    } }, '다각형'));
  const fpBody = R.footprint.type === 'circle'
    ? h('div', { class: 'grid2' }, num('반지름', R.footprint, 'radius', { unit: 'm', step: 0.005, min: 0.02 }), num('여유(padding)', R, 'footprint_padding', { unit: 'm', step: 0.005, min: 0 }))
    : h('div', { class: 'sec' },
      h('div', { class: 'ptable' }, ...R.footprint.points.map((p, i) => h('div', { class: 'pr' }, h('span', { text: i + 1 }),
        h('input', { type: 'number', step: 0.005, value: p[0], 'aria-label': `꼭짓점 ${i + 1} x`, oninput: (e) => { p[0] = +e.target.value; changed(); } }),
        h('input', { type: 'number', step: 0.005, value: p[1], 'aria-label': `꼭짓점 ${i + 1} y`, oninput: (e) => { p[1] = +e.target.value; changed(); } }),
        h('button', { class: 'reset', title: '꼭짓점 삭제', 'aria-label': '꼭짓점 삭제', html: icon('x'), disabled: R.footprint.points.length <= 3,
          onclick: () => { R.footprint.points.splice(i, 1); changed(true); } })))),
      h('div', { class: 'grid2' }, num('여유(padding)', R, 'footprint_padding', { unit: 'm', step: 0.005, min: 0 }),
        h('div', { class: 'hint', style: { alignSelf: 'end' }, text: '편집기에서 변을 더블클릭하면 꼭짓점이 추가됩니다.' })));
  const L = R.limits, W = R.wheels, A = R.actuator;
  const wheelFields = [num('윤거 (좌우 바퀴 간격)', W, 'track', { unit: 'm', step: 0.005 }), num('바퀴 반지름', W, 'radius', { unit: 'm', step: 0.005 })];
  if (R.drive !== 'diff') wheelFields.push(num(R.drive === 'ackermann' ? '축거 (앞뒤 축 간격)' : '앞뒤 바퀴 간격', W, 'wheelbase', { unit: 'm', step: 0.01 }));
  if (R.drive === 'ackermann') wheelFields.push(num('최대 조향각', W, 'max_steer_deg', { unit: '°', step: 1, min: 1, max: 89 }));
  const limFields = [num('최대 전진', L, 'vx_max', { unit: 'm/s', step: 0.05 }), num('최대 후진 (음수)', L, 'vx_min', { unit: 'm/s', step: 0.05 })];
  if (R.drive === 'omni') limFields.push(num('최대 횡이동', L, 'vy_max', { unit: 'm/s', step: 0.05 }));
  limFields.push(num('최대 회전', L, 'wz_max', { unit: 'rad/s', step: 0.05 }), num('가속 한계', L, 'ax_max', { unit: 'm/s²', step: 0.05 }), num('회전 가속 한계', L, 'az_max', { unit: 'rad/s²', step: 0.1 }));
  if (R.drive === 'omni') limFields.push(num('횡 가속 한계', L, 'ay_max', { unit: 'm/s²', step: 0.05 }));
  const sensors = R.sensors.map((s, i) => h('div', { class: 'sensor' },
    h('header', {}, h('input', { type: 'text', value: s.name, 'aria-label': '센서 이름', style: { width: '120px' },
      oninput: (e) => { s.name = e.target.value.replace(/[^a-zA-Z0-9_]/g, '_'); changed(); } }),
    h('span', { class: 'tag', text: s.name === 'scan' ? '/scan' : '/scan_' + s.name }),
    h('button', { class: 'reset', title: '센서 삭제', 'aria-label': '센서 삭제', html: icon('trash'), disabled: R.sensors.length <= 1, onclick: () => { R.sensors.splice(i, 1); changed(true); } })),
    h('div', { class: 'grid3' }, num('x', s, 'x', { unit: 'm', step: 0.005 }), num('y', s, 'y', { unit: 'm', step: 0.005 }), num('높이 z', s, 'z', { unit: 'm', step: 0.005 })),
    h('div', { class: 'grid3' }, num('방향', s, 'yaw_deg', { unit: '°', step: 1 }), num('시야각', s, 'fov_deg', { unit: '°', step: 1, min: 1, max: 360 }), num('빔 수', s, 'beams', { step: 10, int: true })),
    h('div', { class: 'grid3' }, num('최소 거리', s, 'range_min', { unit: 'm', step: 0.01 }), num('최대 거리', s, 'range_max', { unit: 'm', step: 0.5 }), num('주기', s, 'hz', { unit: 'Hz', step: 1 })),
    h('div', { class: 'grid3' }, num('거리 잡음 σ', s, 'noise', { unit: 'm', step: 0.005 }))));
  f.replaceChildren(h('div', { class: 'form' },
    h('div', { class: 'sec' }, h('h3', { text: '로봇' }), h('div', { style: { display: 'flex', gap: '6px' } }, list,
      btn('', { cls: 'icon-only', icon: 'plus', title: '새 로봇 (원형 템플릿)', aria: '새 로봇', onclick: () => { R = JSON.parse(JSON.stringify(TEMPLATE)); srcId = null; srcBuiltin = false; changed(true); cad.fit(); } }))),
    h('div', { class: 'grid2' },
      h('label', { class: 'field' }, h('span', { text: '이름' }), h('input', { type: 'text', value: R.name, oninput: (e) => { R.name = e.target.value; } })),
      h('label', { class: 'field' }, h('span', { text: '차체 색' }), h('input', { type: 'color', value: R.body.color, style: { height: '32px', width: '100%' }, oninput: (e) => { R.body.color = e.target.value; changed(); } }))),
    h('label', { class: 'field' }, h('span', { text: '설명' }), h('input', { type: 'text', value: R.description || '', oninput: (e) => { R.description = e.target.value; } })),
    h('div', { class: 'sec' }, h('h3', { text: '구동 방식' }), drive,
      h('div', { class: 'hint', text: { diff: '두 바퀴 속도 차로 움직입니다. 제자리 회전 가능.', omni: '메카넘 휠 등으로 옆으로도 움직입니다 (vy).', ackermann: '자동차처럼 앞바퀴를 조향합니다. 제자리 회전 불가. base_link 는 뒷바퀴 축 중심.' }[R.drive] })),
    h('div', { class: 'sec' }, h('h3', { text: 'Footprint (외곽)' }), fpType, fpBody),
    h('div', { class: 'sec' }, h('h3', { text: '차체·바퀴' }), h('div', { class: 'grid2' }, num('차체 높이', R.body, 'height', { unit: 'm', step: 0.01 }), ...wheelFields)),
    h('div', { class: 'sec' }, h('h3', { text: '물리 한계 (시뮬레이터)' }), h('div', { class: 'grid2' }, ...limFields),
      h('div', { class: 'hint', text: 'Nav2 속도 한계와 별개로, 실제 모터가 낼 수 있는 값입니다. Nav2 쪽은 파라미터 탭에서 정합니다.' })),
    h('div', { class: 'sec' }, h('h3', { text: '구동계 응답·오도메트리' }), h('div', { class: 'grid3' },
      num('응답 지연 τ', A, 'tau', { unit: 's', step: 0.01 }), num('직진 슬립 σ', A, 'slip_lin', { step: 0.005 }), num('회전 슬립 σ', A, 'slip_ang', { step: 0.005 }))),
    h('div', { class: 'sec' }, h('h3', {}, `라이다 (${R.sensors.length})`, btn('추가', { cls: 'sm ghost act', icon: 'plus', onclick: () => {
      const n = R.sensors.length; R.sensors.push({ ...TEMPLATE_SENSOR, name: `lidar${n}` }); changed(true);
    } })), ...sensors),
    h('div', { class: 'sec', id: 'saveSec' })));
  renderSave();
}

const TEMPLATE = {
  name: '새 로봇', description: '', drive: 'diff', footprint: { type: 'circle', radius: 0.2, points: [] }, footprint_padding: 0.02,
  body: { height: 0.15, color: '#4a6572' }, wheels: { track: 0.3, radius: 0.05, wheelbase: 0, max_steer_deg: 0 },
  limits: { vx_max: 0.6, vx_min: -0.2, vy_max: 0, wz_max: 1.5, ax_max: 1.0, ay_max: 1.0, az_max: 3.0 },
  actuator: { tau: 0.08, slip_lin: 0.02, slip_ang: 0.03 },
  sensors: [{ ...TEMPLATE_SENSOR, name: 'scan', fov_deg: 360, beams: 360, range_min: 0.12, range_max: 10, hz: 10, z: 0.18 }],
};

function renderSave() {
  const sec = $('saveSec');
  if (!sec) return;
  const idIn = h('input', { type: 'text', id: 'robotId', placeholder: 'my_robot', value: srcBuiltin ? '' : (srcId || ''), 'aria-label': '저장할 로봇 ID' });
  sec.replaceChildren(h('h3', { text: '저장·사용' }),
    h('label', { class: 'field' }, h('span', { text: srcBuiltin ? '기본 제공 로봇은 새 ID 로 저장합니다' : '로봇 ID (영문/숫자/-/_)' }), idIn),
    h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      btn('저장', { icon: 'download', onclick: async () => {
        const id = idIn.value.trim();
        if (!id) { toast('저장할 ID 를 입력하세요', 'bad'); return; }
        try { await api.put(`/api/robots/${id}`, R); S.robots = await api.get('/api/robots'); srcId = id; srcBuiltin = false; renderForm(); toast(`'${id}' 로 저장했습니다`, 'good'); emit('catalog'); }
        catch (e) { toast(e.message, 'bad'); }
      } }),
      btn('시뮬레이션에 사용', { cls: 'primary', icon: 'play', onclick: async () => {
        if (error) { toast('먼저 오류를 고치세요: ' + error, 'bad'); return; }
        if (srcId && !srcBuiltin) { try { await api.put(`/api/robots/${srcId}`, R); } catch (e) { toast(e.message, 'bad'); return; } await sim.selectRobot(srcId); }
        else await sim.selectRobot(null, JSON.parse(JSON.stringify(R)));
        emit('goto', 'sim');
        toast('로봇을 바꿨습니다. ‘변경 적용’ 을 누르면 반영됩니다.');
      } }),
      (!srcBuiltin && srcId) ? btn('삭제', { cls: 'ghost danger', icon: 'trash', onclick: async () => {
        try { await api.del(`/api/robots/${srcId}`); S.robots = await api.get('/api/robots'); await load('everybot'); emit('catalog'); toast('삭제했습니다'); }
        catch (e) { toast(e.message, 'bad'); }
      } }) : ''));
}

function renderDerived() {
  const d = $('derived');
  if (!d) return;
  const items = derived ? [
    ['내접원 반지름', `${fmt.n(derived.inscribed, 3)} m`], ['외접원 반지름', `${fmt.n(derived.circumscribed, 3)} m`],
    ['Nav2 footprint', R.footprint.type === 'circle' ? `robot_radius ${fmt.n(R.footprint.radius + R.footprint_padding, 3)}` : `다각형 ${R.footprint.points.length}점 + padding ${R.footprint_padding}`],
    ['최소 회전 반경', R.drive === 'ackermann' ? `${fmt.n(derived.min_turning_radius, 2)} m` : '0 (제자리 회전)'],
    ['라이다', R.sensors.map((s) => `${s.name} ${s.fov_deg}°`).join(', ')],
    ['통과 가능 최소 폭', `약 ${fmt.n(2 * (derived.inscribed + (R.footprint_padding || 0)), 2)} m`],
  ] : [];
  d.replaceChildren(
    h('div', { class: 'sec' }, h('h3', { text: '계산값' }),
      error ? h('div', { class: 'errbox', text: error }) : h('dl', { class: 'kv' }, ...items.flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { text: v })]))),
    h('div', { class: 'hint', text: '3D: 드래그로 회전, 휠로 확대, 오른쪽 드래그로 이동' }));
}

// ================================================================== CAD canvas
function initCadTools() {
  const t = $('cadTools');
  const mk = (key, label, ic) => h('button', { 'aria-pressed': String(cad[key]), onclick: (e) => { cad[key] = !cad[key]; e.currentTarget.setAttribute('aria-pressed', String(cad[key])); cad.draw(); persist('cad.' + key, cad[key]); } },
    h('span', { html: icon(ic) }), label);
  t.replaceChildren(mk('snap', '5 mm 스냅', 'fit'), mk('mirror', '좌우 대칭 편집', 'vertex'), mk('dims', '치수', 'sliders'),
    h('button', { onclick: () => { cad.fit(); } }, h('span', { html: icon('fit') }), '맞춤'));
  $('cadHint').textContent = '꼭짓점·센서를 끌어 옮기기 · 변 더블클릭: 꼭짓점 추가 · 꼭짓점 우클릭: 삭제 · 센서 방향 핸들 끌기 · 휠: 확대';
}

class Cad {
  constructor(canvas) {
    this.c = canvas; this.g = canvas.getContext('2d');
    this.s = 600; this.cx = 0.1; this.cy = 0;
    this.snap = persist('cad.snap') ?? true; this.mirror = persist('cad.mirror') ?? true; this.dims = persist('cad.dims') ?? true;
    this.robot = null; this.drag = null; this.hover = null;
    this.colors();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    canvas.addEventListener('wheel', (e) => { e.preventDefault(); const k = Math.exp(-e.deltaY * 0.0015); this.s = Math.max(60, Math.min(4000, this.s * k)); this.draw(); }, { passive: false });
    canvas.addEventListener('pointerdown', (e) => this.down(e));
    canvas.addEventListener('pointermove', (e) => this.move(e));
    canvas.addEventListener('pointerup', () => { if (this.drag) { this.drag = null; changed(true); } });
    canvas.addEventListener('dblclick', (e) => this.dbl(e));
    canvas.addEventListener('contextmenu', (e) => { e.preventDefault(); this.ctx(e); });
  }
  colors() {
    this.k = { bg: cssVar('--panel-2'), grid: cssVar('--line'), grid2: cssVar('--line-strong'), ink: cssVar('--ink'), muted: cssVar('--muted'),
      faint: cssVar('--faint'), accent: cssVar('--accent'), scan: cssVar('--scan'), robot: cssVar('--robot'), panel: cssVar('--panel'), good: cssVar('--good') };
  }
  resize() {
    const r = this.c.parentElement.getBoundingClientRect(), dpr = devicePixelRatio || 1;
    this.W = r.width; this.H = r.height;
    this.c.width = Math.max(1, r.width * dpr); this.c.height = Math.max(1, r.height * dpr);
    this.g.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!this.fitted && this.robot) { this.fit(); this.fitted = true; }
    this.draw();
  }
  fit() {
    if (!this.robot) return;
    const pts = robotPolygon(this.robot).concat(this.robot.sensors.map((s) => [s.x, s.y]));
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const w = Math.max(...xs) - Math.min(...xs) + 0.6, hh = Math.max(...ys) - Math.min(...ys) + 0.6;
    this.cx = (Math.max(...xs) + Math.min(...xs)) / 2; this.cy = (Math.max(...ys) + Math.min(...ys)) / 2;
    this.s = Math.max(80, Math.min(3000, Math.min(this.W / w, this.H / hh) * 0.8));
    this.draw();
  }
  S(x, y) { return [(x - this.cx) * this.s + this.W / 2, this.H / 2 - (y - this.cy) * this.s]; }
  Wd(sx, sy) { return [(sx - this.W / 2) / this.s + this.cx, (this.H / 2 - sy) / this.s + this.cy]; }
  q(v) { return this.snap ? Math.round(v / 0.005) * 0.005 : Math.round(v * 10000) / 10000; }

  draw() {
    const g = this.g, R0 = this.robot;
    if (!this.W) return;
    g.fillStyle = this.k.bg; g.fillRect(0, 0, this.W, this.H);
    // grid: 1 cm / 10 cm / 50 cm
    const steps = [[0.01, this.k.grid, 0.4], [0.1, this.k.grid, 1], [0.5, this.k.grid2, 1]];
    const [x0, y1] = this.Wd(0, 0), [x1, y0] = this.Wd(this.W, this.H);
    for (const [st, col, a] of steps) {
      if (st * this.s < 6) continue;
      g.strokeStyle = col; g.globalAlpha = a; g.lineWidth = 1; g.beginPath();
      for (let x = Math.ceil(x0 / st) * st; x <= x1; x += st) { const [sx] = this.S(x, 0); g.moveTo(Math.round(sx) + 0.5, 0); g.lineTo(Math.round(sx) + 0.5, this.H); }
      for (let y = Math.ceil(y0 / st) * st; y <= y1; y += st) { const [, sy] = this.S(0, y); g.moveTo(0, Math.round(sy) + 0.5); g.lineTo(this.W, Math.round(sy) + 0.5); }
      g.stroke(); g.globalAlpha = 1;
    }
    // axes
    const [ox, oy] = this.S(0, 0);
    g.lineWidth = 1.5; g.strokeStyle = this.k.scan; g.beginPath(); g.moveTo(ox, oy); g.lineTo(ox + 60, oy); g.stroke();
    g.strokeStyle = this.k.good; g.beginPath(); g.moveTo(ox, oy); g.lineTo(ox, oy - 60); g.stroke();
    g.fillStyle = this.k.muted; g.font = '11px ui-monospace, monospace';
    g.fillText('x 전방', ox + 64, oy + 4); g.fillText('y 좌', ox + 4, oy - 64);
    if (!R0) return;
    const poly = robotPolygon(R0, 64);
    // padding outline
    if (R0.footprint_padding > 0) {
      g.setLineDash([5, 4]); g.strokeStyle = this.k.accent; g.lineWidth = 1;
      g.beginPath();
      if (R0.footprint.type === 'circle') { g.arc(ox, oy, (R0.footprint.radius + R0.footprint_padding) * this.s, 0, Math.PI * 2); }
      else poly.forEach((p, i) => { const r = Math.hypot(p[0], p[1]) || 1, k = (r + R0.footprint_padding) / r; const [x, y] = this.S(p[0] * k, p[1] * k); i ? g.lineTo(x, y) : g.moveTo(x, y); });
      g.closePath(); g.stroke(); g.setLineDash([]);
    }
    // inscribed / circumscribed
    if (derived) {
      g.setLineDash([2, 4]); g.strokeStyle = this.k.faint; g.lineWidth = 1;
      for (const r of [derived.inscribed, derived.circumscribed]) { g.beginPath(); g.arc(ox, oy, r * this.s, 0, Math.PI * 2); g.stroke(); }
      g.setLineDash([]);
      if (R0.drive === 'ackermann' && derived.min_turning_radius > 0) {
        const [cx, cy] = this.S(0, derived.min_turning_radius);
        g.strokeStyle = this.k.accent; g.globalAlpha = 0.35; g.beginPath(); g.arc(cx, cy, derived.min_turning_radius * this.s, 0, Math.PI * 2); g.stroke(); g.globalAlpha = 1;
        g.fillStyle = this.k.accent; g.fillText(`최소 회전반경 ${derived.min_turning_radius.toFixed(2)} m`, cx + 6, cy);
      }
    }
    // wheels
    g.fillStyle = this.k.ink; g.globalAlpha = 0.8;
    const wr = R0.wheels.radius, ww = Math.max(0.02, wr * 0.6), tw = R0.wheels.track / 2;
    const wheel = (x, y, st = 0) => { g.save(); const [sx, sy] = this.S(x, y); g.translate(sx, sy); g.rotate(-st); g.fillRect(-wr * this.s, -ww * this.s / 2, 2 * wr * this.s, ww * this.s); g.restore(); };
    if (R0.drive === 'diff') { wheel(0, tw); wheel(0, -tw); }
    else if (R0.drive === 'omni') { const L = R0.wheels.wheelbase / 2; for (const sx of [L, -L]) { wheel(sx, tw); wheel(sx, -tw); } }
    else { const L = R0.wheels.wheelbase; wheel(0, tw); wheel(0, -tw); wheel(L, tw, 0.25); wheel(L, -tw, 0.25); }
    g.globalAlpha = 1;
    // body
    g.fillStyle = R0.body.color; g.globalAlpha = 0.55; g.strokeStyle = this.k.ink; g.lineWidth = 2;
    g.beginPath(); poly.forEach((p, i) => { const [x, y] = this.S(p[0], p[1]); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.fill(); g.globalAlpha = 1; g.stroke();
    // vertex / radius handles
    if (R0.footprint.type === 'polygon') {
      R0.footprint.points.forEach((p, i) => this.handle(p[0], p[1], this.hover && this.hover.kind === 'v' && this.hover.i === i));
    } else this.handle(R0.footprint.radius, 0, this.hover && this.hover.kind === 'r');
    // sensors
    for (const [i, s] of R0.sensors.entries()) {
      const [sx, sy] = this.S(s.x, s.y), yaw = s.yaw_deg * Math.PI / 180, fov = Math.min(s.fov_deg, 360) * Math.PI / 180;
      const rr = this.fanR(s);
      g.fillStyle = this.k.scan; g.globalAlpha = 0.12; g.beginPath(); g.moveTo(sx, sy);
      g.arc(sx, sy, rr, -(yaw + fov / 2), -(yaw - fov / 2)); g.closePath(); g.fill(); g.globalAlpha = 1;
      g.strokeStyle = this.k.scan; g.lineWidth = 1; g.stroke();
      const [hx, hy] = [sx + Math.cos(yaw) * rr, sy - Math.sin(yaw) * rr];
      g.beginPath(); g.moveTo(sx, sy); g.lineTo(hx, hy); g.stroke();
      g.fillStyle = this.k.panel; g.strokeStyle = this.k.scan; g.lineWidth = 2;
      g.beginPath(); g.arc(hx, hy, 5, 0, Math.PI * 2); g.fill(); g.stroke();
      g.fillStyle = (this.hover && this.hover.kind === 's' && this.hover.i === i) ? this.k.accent : this.k.ink;
      g.beginPath(); g.arc(sx, sy, 6, 0, Math.PI * 2); g.fill();
      g.fillStyle = this.k.ink; g.font = '600 11px var(--f-ui), sans-serif'; g.fillText(s.name, sx + 9, sy - 8);
    }
    if (this.dims) this.dimensions(poly);
  }
  fanR(s) {
    const circ = Math.max(...robotPolygon(this.robot, 32).map(([x, y]) => Math.hypot(x, y)), 0.1);
    return Math.min(s.range_max, Math.max(0.1, circ * 0.45)) * this.s;
  }
  handle(x, y, hot) {
    const g = this.g, [sx, sy] = this.S(x, y);
    g.fillStyle = hot ? this.k.accent : this.k.panel; g.strokeStyle = this.k.accent; g.lineWidth = 2;
    g.fillRect(sx - 5, sy - 5, 10, 10); g.strokeRect(sx - 5, sy - 5, 10, 10);
  }
  dimensions(poly) {
    const g = this.g;
    const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
    const [a, b, c, d] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    g.strokeStyle = this.k.muted; g.fillStyle = this.k.muted; g.lineWidth = 1; g.font = '11px ui-monospace, monospace'; g.textAlign = 'center';
    const [l0, ly] = this.S(a, c), [l1] = this.S(b, c);
    const yy = ly + 26;
    g.beginPath(); g.moveTo(l0, ly + 6); g.lineTo(l0, yy + 4); g.moveTo(l1, ly + 6); g.lineTo(l1, yy + 4); g.moveTo(l0, yy); g.lineTo(l1, yy); g.stroke();
    g.fillText(`${((b - a) * 1000).toFixed(0)} mm`, (l0 + l1) / 2, yy - 4);
    const [rx, r0] = this.S(b, c), [, r1] = this.S(b, d);
    const xx = rx + 26;
    g.beginPath(); g.moveTo(rx + 6, r0); g.lineTo(xx + 4, r0); g.moveTo(rx + 6, r1); g.lineTo(xx + 4, r1); g.moveTo(xx, r0); g.lineTo(xx, r1); g.stroke();
    g.save(); g.translate(xx + 12, (r0 + r1) / 2); g.rotate(-Math.PI / 2); g.fillText(`${((d - c) * 1000).toFixed(0)} mm`, 0, 0); g.restore();
    g.textAlign = 'start';
  }
  pick(sx, sy) {
    const R0 = this.robot;
    for (const [i, s] of R0.sensors.entries()) {
      const [px, py] = this.S(s.x, s.y), yaw = s.yaw_deg * Math.PI / 180, rr = this.fanR(s);
      if (Math.hypot(sx - (px + Math.cos(yaw) * rr), sy - (py - Math.sin(yaw) * rr)) < 8) return { kind: 'yaw', i };
      if (Math.hypot(sx - px, sy - py) < 8) return { kind: 's', i };
    }
    if (R0.footprint.type === 'polygon') {
      for (const [i, p] of R0.footprint.points.entries()) { const [px, py] = this.S(p[0], p[1]); if (Math.abs(sx - px) < 7 && Math.abs(sy - py) < 7) return { kind: 'v', i }; }
    } else {
      const [px, py] = this.S(R0.footprint.radius, 0);
      if (Math.abs(sx - px) < 7 && Math.abs(sy - py) < 7) return { kind: 'r' };
    }
    return null;
  }
  pos(e) { const r = this.c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
  down(e) {
    const [sx, sy] = this.pos(e);
    const hit = this.pick(sx, sy);
    this.c.setPointerCapture(e.pointerId);
    if (hit) { this.drag = hit; if (hit.kind === 'v' && this.mirror) this.drag.mate = this.mate(hit.i); }
    else this.drag = { kind: 'pan', sx, sy, cx: this.cx, cy: this.cy };
  }
  mate(i) {
    const pts = this.robot.footprint.points, p = pts[i];
    let best = -1, bd = 0.004;
    pts.forEach((q, j) => { if (j !== i) { const d = Math.hypot(q[0] - p[0], q[1] + p[1]); if (d < bd) { bd = d; best = j; } } });
    return best;
  }
  move(e) {
    const [sx, sy] = this.pos(e);
    const d = this.drag;
    if (!d) {
      const hv = this.pick(sx, sy);
      if (JSON.stringify(hv) !== JSON.stringify(this.hover)) { this.hover = hv; this.draw(); }
      this.c.style.cursor = hv ? (hv.kind === 'yaw' ? 'alias' : 'move') : 'grab';
      return;
    }
    const [wx, wy] = this.Wd(sx, sy);
    const R0 = this.robot;
    if (d.kind === 'pan') { this.cx = d.cx - (sx - d.sx) / this.s; this.cy = d.cy + (sy - d.sy) / this.s; this.draw(); return; }
    if (d.kind === 'v') {
      const p = R0.footprint.points[d.i]; p[0] = this.q(wx); p[1] = this.q(wy);
      if (d.mate >= 0) { const m = R0.footprint.points[d.mate]; m[0] = p[0]; m[1] = -p[1]; }
    } else if (d.kind === 'r') R0.footprint.radius = Math.max(0.02, this.q(Math.hypot(wx, wy)));
    else if (d.kind === 's') { const s = R0.sensors[d.i]; s.x = this.q(wx); s.y = this.q(wy); }
    else if (d.kind === 'yaw') {
      const s = R0.sensors[d.i]; let a = Math.atan2(wy - s.y, wx - s.x) * 180 / Math.PI;
      if (this.snap) a = Math.round(a / 5) * 5;
      s.yaw_deg = Math.round(a * 10) / 10;
    }
    changed();
  }
  dbl(e) {
    const R0 = this.robot;
    if (R0.footprint.type !== 'polygon') return;
    const [sx, sy] = this.pos(e), [wx, wy] = this.Wd(sx, sy), pts = R0.footprint.points;
    let best = -1, bd = 12 / this.s;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length], dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy || 1e-9;
      const t = Math.max(0, Math.min(1, ((wx - a[0]) * dx + (wy - a[1]) * dy) / L));
      const dd = Math.hypot(wx - (a[0] + t * dx), wy - (a[1] + t * dy));
      if (dd < bd) { bd = dd; best = i; }
    }
    if (best >= 0) { pts.splice(best + 1, 0, [this.q(wx), this.q(wy)]); changed(true); }
  }
  ctx(e) {
    const [sx, sy] = this.pos(e), hit = this.pick(sx, sy);
    if (hit && hit.kind === 'v' && this.robot.footprint.points.length > 3) { this.robot.footprint.points.splice(hit.i, 1); changed(true); }
  }
}
