// Sensors in the UI: type schemas (forms are generated from them), the model library, mount geometry for drawing.
import { api } from './api.js';
import { S } from './state.js';
import { h, icon, btn, toast, modal, confirmDlg } from './ui.js';

const D2R = Math.PI / 180;

export async function loadSensorCatalog() {
  const [types, models] = await Promise.all([api.get('/api/sensor-types'), api.get('/api/sensors')]);
  S.sensorTypes = types.types;
  S.sensorModels = models;
  if (Object.keys(types.errors || {}).length) toast('불러오지 못한 센서 종류: ' + Object.entries(types.errors).map(([f, e]) => `${f} (${e})`).join(', '), 'bad');
}

export const typeOf = (t) => (S.sensorTypes || []).find((x) => x.type === t);
export const typeLabel = (t) => (typeOf(t) || {}).label || t;
export const modelOf = (id) => (S.sensorModels || []).find((m) => m.id === id);

// ------------------------------------------------------------------ geometry (same conventions as navstudio/sensortypes/geometry.py)
export function rotation(s) {
  const r = (s.roll_deg || 0) * D2R, p = (s.pitch_deg || 0) * D2R, y = (s.yaw_deg || 0) * D2R;
  const cr = Math.cos(r), sr = Math.sin(r), cp = Math.cos(p), sp = Math.sin(p), cy = Math.cos(y), sy = Math.sin(y);
  return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr], [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr], [-sp, cp * sr, cp * cr]];
}
export const apply = (R, v) => [R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2], R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2], R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]];

// horizontal / vertical half angles of the field of view (rad)
export function fovOf(s) {
  if (s.type === 'lidar2d') return [Math.min(360, s.fov_deg) * D2R / 2, 0];
  if (s.type === 'ultrasonic') return [s.beam_deg * D2R / 2, s.beam_deg * D2R / 2];
  if (s.fov_h_deg !== undefined) return [s.fov_h_deg * D2R / 2, (s.fov_v_deg ?? s.fov_h_deg) * D2R / 2];
  if (s.spread_deg !== undefined) return [s.spread_deg * D2R / 2, s.spread_deg * D2R / 2];
  return [0.2, 0.2];
}

// a ray (sensor-frame tangents) from the mount, in base_link: where it meets the floor (or its end at maxLen)
export function rayEnd(s, ty, tz, maxLen) {
  const R = rotation(s);
  const d = apply(R, [1, ty, tz]);
  const n = Math.hypot(...d);
  const u = d.map((v) => v / n);
  let t = maxLen;
  let floor = false;
  if (u[2] < -1e-6) { const tf = -s.z / u[2]; if (tf < t) { t = tf; floor = true; } }
  return { p: [s.x + u[0] * t, s.y + u[1] * t, s.z + u[2] * t], floor };
}

// outline of a sensor's field of view: corners (base_link) at the floor or at maxLen; plus zone centre rays for ToF
export function fovFootprint(s, maxLen) {
  const [h2, v2] = fovOf(s);
  const N = 12, pts = [];
  const edge = (a, b) => { for (let i = 0; i <= N; i++) { const k = i / N; pts.push(rayEnd(s, Math.tan(a[0] + (b[0] - a[0]) * k), Math.tan(a[1] + (b[1] - a[1]) * k), maxLen)); } };
  edge([h2, v2], [-h2, v2]); edge([-h2, v2], [-h2, -v2]); edge([-h2, -v2], [h2, -v2]); edge([h2, -v2], [h2, v2]);
  return pts;
}

export function zoneCentres(s) {
  const nx = s.zones_x, ny = s.zones_y, fh = s.fov_h_deg * D2R, fv = s.fov_v_deg * D2R;
  const active = s.zone_mask ? new Set(s.zone_mask) : null;
  const out = [];
  for (let i = 0; i < ny; i++) for (let j = 0; j < nx; j++) {
    const k = i * nx + j;
    out.push({ k, i, j, on: !active || active.has(k), ty: Math.tan(fh * (nx - 1 - 2 * j) / (2 * nx)), tz: Math.tan(fv * (ny - 1 - 2 * i) / (2 * ny)) });
  }
  return out;
}

// ------------------------------------------------------------------ forms generated from the type schema
export function paramFields(s, onchange, { groups = null, compact = false } = {}) {
  const t = typeOf(s.type);
  if (!t) return [h('div', { class: 'errbox', text: `알 수 없는 센서 종류: ${s.type}` })];
  const byGroup = {};
  for (const p of t.params) {
    if (groups && !groups.includes(p.group)) continue;
    (byGroup[p.group] = byGroup[p.group] || []).push(p);
  }
  return Object.entries(byGroup).map(([g, ps]) => h('div', { class: 'pfgroup' }, compact ? '' : h('div', { class: 'grouplabel', text: g }),
    h('div', { class: 'grid3' }, ...ps.filter((p) => p.kind !== 'zones').map((p) => paramField(s, p, onchange))),
    ...ps.filter((p) => p.kind === 'zones').map((p) => zoneMaskEditor(s, p, onchange))));
}

function paramField(s, p, onchange) {
  const title = p.help || '';
  if (p.kind === 'bool') {
    return h('label', { class: 'field check', title }, h('span', { text: p.label }),
      h('input', { type: 'checkbox', checked: !!s[p.key], onchange: (e) => { s[p.key] = e.target.checked; onchange(); } }));
  }
  if (p.kind === 'color') {
    return h('label', { class: 'field', title }, h('span', { text: p.label }),
      h('input', { type: 'color', value: s[p.key] || p.default, style: { height: '30px', width: '100%' }, oninput: (e) => { s[p.key] = e.target.value; onchange(); } }));
  }
  const inp = h('input', { type: 'number', step: p.step || (p.kind === 'int' ? 1 : 0.01), min: p.min, max: p.max, value: s[p.key] ?? p.default, 'aria-label': p.label,
    oninput: (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) { s[p.key] = p.kind === 'int' ? Math.round(v) : v; onchange(); } } });
  return h('label', { class: 'field', title }, h('span', { text: p.label + (p.unit ? ` (${p.unit})` : '') }), inp);
}

// clickable zone grid (row-major, index 0 top-left seen from behind the sensor)
export function zoneMaskEditor(s, p, onchange) {
  const nx = s.zones_x || 1, ny = s.zones_y || 1, n = nx * ny;
  const on = new Set(s.zone_mask || [...Array(n).keys()]);
  const count = h('span', { class: 'faint', text: `${on.size}/${n} 존` });
  const cells = [];
  const set = () => { s.zone_mask = on.size === n ? null : [...on].sort((a, b) => a - b); count.textContent = `${on.size}/${n} 존`; onchange(); };
  let painting = null;
  for (let k = 0; k < n; k++) {
    const c = h('button', { class: 'zcell', type: 'button', 'aria-pressed': String(on.has(k)), title: `존 ${k}`, text: n <= 64 ? String(k) : '',
      onpointerdown: (e) => { e.preventDefault(); painting = !on.has(k); toggle(k, painting); },
      onpointerenter: () => { if (painting !== null) toggle(k, painting); } });
    cells.push(c);
  }
  function toggle(k, val) { if (val) on.add(k); else if (on.size > 1) on.delete(k); cells[k].setAttribute('aria-pressed', String(on.has(k))); set(); }
  window.addEventListener('pointerup', () => { painting = null; });
  return h('div', { class: 'field', title: p.help || '' },
    h('span', {}, p.label, ' ', count, ' ', h('button', { class: 'linkbtn', type: 'button', text: '전부', onclick: () => { for (let k = 0; k < n; k++) on.add(k); cells.forEach((c) => c.setAttribute('aria-pressed', 'true')); set(); } })),
    h('div', { class: 'zgrid', style: { gridTemplateColumns: `repeat(${nx}, 1fr)` } }, ...cells),
    h('small', { class: 'faint', text: '센서 뒤에서 본 모습 (왼쪽 위 = 0). 누르거나 끌어서 켜고 끕니다.' }));
}

// ------------------------------------------------------------------ the sensor model library
export function libraryMenuItems(onpick) {
  const items = [];
  for (const t of S.sensorTypes || []) {
    const ms = (S.sensorModels || []).filter((m) => m.type === t.type && !m.broken);
    if (!ms.length) continue;
    items.push({ heading: t.label });
    for (const m of ms) items.push({ label: m.name, sub: m.description, tag: m.builtin ? '기본' : '내 센서', onclick: () => onpick(m) });
  }
  return items;
}

export function sensorLibrary({ onchange } = {}) {
  let sel = (S.sensorModels || [])[0] || null;
  let draft = sel && JSON.parse(JSON.stringify(sel));
  const list = h('div', { class: 'liblist' });
  const editor = h('div', { class: 'libedit' });
  const refresh = async () => { S.sensorModels = await api.get('/api/sensors'); onchange && onchange(); };
  function renderList() {
    list.replaceChildren(...(S.sensorTypes || []).map((t) => {
      const ms = S.sensorModels.filter((m) => m.type === t.type);
      return h('div', { class: 'sec' }, h('div', { class: 'grouplabel', text: t.label }),
        ...ms.map((m) => h('button', { class: 'opt slim', 'aria-pressed': String(sel && sel.id === m.id), onclick: () => { sel = m; draft = JSON.parse(JSON.stringify(m)); render(); } },
          h('i', { class: 'swatch', style: { background: m.color || '#888' } }), h('div', { class: 't' }, h('b', { text: m.name }), h('span', { text: m.builtin ? '기본' : '내 센서' })))));
    }), h('div', { class: 'sec' }, h('div', { class: 'grouplabel', text: '새 센서' }),
      ...(S.sensorTypes || []).map((t) => btn(t.label, { cls: 'sm', icon: 'plus', onclick: () => {
        const d = Object.fromEntries(t.params.map((p) => [p.key, p.default]));
        draft = { ...d, type: t.type, name: `새 ${t.label}`, description: '' }; sel = null; render();
      } }))));
  }
  function renderEditor() {
    const m = draft;
    if (!m) { editor.replaceChildren(h('div', { class: 'hint', text: '왼쪽에서 센서를 고르거나 새로 만드세요.' })); return; }
    const t = typeOf(m.type);
    const name = h('input', { type: 'text', value: m.name, oninput: (e) => { m.name = e.target.value; } });
    const desc = h('input', { type: 'text', value: m.description || '', oninput: (e) => { m.description = e.target.value; } });
    const outs = (t.outputs || []).map((o) => o.topic.replace('<name>', '<이름>'));
    const mine = sel && !sel.builtin;
    editor.replaceChildren(
      h('div', { class: 'grid2' }, h('label', { class: 'field' }, h('span', { text: '이름' }), name), h('label', { class: 'field' }, h('span', { text: '종류' }), h('input', { type: 'text', value: t.label, disabled: true }))),
      h('label', { class: 'field' }, h('span', { text: '설명' }), desc),
      h('div', { class: 'hint', text: t.description }),
      ...paramFields(m, () => {}),
      h('div', { class: 'hint', text: '발행 토픽: ' + outs.join(', ') }),
      sel && sel.builtin ? h('div', { class: 'hint', text: '기본 센서는 바꿀 수 없습니다. 고친 값은 내 센서로 복사해 저장합니다.' }) : '',
      h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
        mine ? btn('저장', { cls: 'primary', icon: 'save', onclick: () => save(m, sel.id) }) : '',
        btn(mine ? '새 센서로 저장' : (sel ? '내 센서로 저장' : '저장'), { cls: mine ? '' : 'primary', icon: 'save', onclick: () => save(m, null) }),
        mine ? btn('지우기', { cls: 'ghost danger', icon: 'trash', onclick: async () => {
          if (!await confirmDlg('센서 지우기', `'${sel.name}' 을 라이브러리에서 지웁니다. 이미 로봇에 단 센서는 그대로 남습니다.`, '지우기', true)) { reopen(); return; }
          try { await api.del(`/api/sensors/${sel.id}`); await refresh(); sel = S.sensorModels[0]; draft = sel && JSON.parse(JSON.stringify(sel)); reopen(); toast('지웠습니다'); } catch (e) { toast(e.message, 'bad'); }
        } }) : ''));
  }
  async function save(m, id) {
    const body = { ...m };
    for (const k of ['id', 'builtin', 'broken']) delete body[k];
    if (sel && !id && body.name === sel.name) body.name = `${body.name} (복사)`;
    try {
      const r = id ? await api.put(`/api/sensors/${id}`, body) : await api.post('/api/sensors', body);
      await refresh(); sel = S.sensorModels.find((x) => x.id === r.id); draft = JSON.parse(JSON.stringify(sel)); render();
      toast(`'${r.name}' 을 저장했습니다`, 'good');
    } catch (e) { toast(e.message, 'bad'); }
  }
  function render() { renderList(); renderEditor(); }
  let close;
  function reopen() { close = modal('센서 라이브러리', h('div', { class: 'libwrap' }, list, editor)); render(); }
  reopen();
}
