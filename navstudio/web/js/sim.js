// Simulation workspace: map / robot·stack / parameter panels, stage tools, run controls, telemetry.
//
// One to four live slots (A–D) run side by side. They share the map, robot and scene; each slot has its own stack and
// parameter changes, its own view and its own Nav2 session. The left panels edit the active slot.
import { api, inflate } from './api.js';
import { S, on, emit, slotKey, isDirty, isDirtySlot, saveSel, mapName, stackOf, presetOf, cfgLabel, visibleSlots, MAX_SLOTS, SLOT_NAMES } from './state.js';
import { h, icon, btn, toast, modal, menu, confirmDlg, fmt, debounce, persist, diffHtml, cssVar, DRIVE_LABEL } from './ui.js';
import { Viewport, robotPolygon } from './viewport.js';

const vps = [];
const av = () => vps[S.active];
const $ = (id) => document.getElementById(id);
const slotColor = (i) => cssVar(`--s${i}`);
const NAV_LABEL = { idle: '대기', sending: '목표 전송', navigating: '주행 중', succeeded: '도착', aborted: '실패 (중단)', canceled: '취소됨', rejected: '거부됨' };
const DONE = ['succeeded', 'aborted', 'canceled', 'rejected'];
const STACK_LABEL = { stopped: '꺼짐', starting: '시작 중', ready: '실행 중', error: '오류' };

// ================================================================== init
export function initSim() {
  const box = $('views');
  const addCell = h('button', { class: 'vcell addslot', id: 'addSlot', hidden: true, onclick: () => setSlotCount(4) },
    h('span', { html: icon('plus') }), h('b', { text: '슬롯 D 추가' }), h('small', { text: '설정을 하나 더 띄워 비교합니다' }));
  for (let i = 0; i < MAX_SLOTS; i++) {
    const canvas = h('canvas', { id: i ? `view${i}` : 'view', 'aria-label': `시뮬레이션 화면 ${SLOT_NAMES[i]}` });
    box.append(h('div', { class: 'vcell', 'data-slot': i, hidden: i >= S.nSlots },
      canvas, h('div', { class: 'vhead', id: `vhead${i}`, hidden: true, onpointerdown: () => setActive(i) }),
      h('div', { class: 'overlay', id: i ? `vover${i}` : 'stageOverlay', hidden: true })));
    const v = new Viewport(canvas, {
      editable: true,
      onStart: setStart, onGoal: setGoal, onScene: sceneEdited,
      onMouse: (x, y) => { mouse = [x, y]; if (vps.some((o) => o.move || o.drag)) vps.forEach((o) => { o.dirty = true; }); },
      onFollowChange: () => renderRunbar(),
      onActivate: (o) => setActive(vps.indexOf(o)),
      others: (o) => (S.nSlots < 2 ? [] : vps.slice(0, S.nSlots).filter((x) => x !== o).map((x) => ({ trail: x.trail, color: slotColor(vps.indexOf(x)) }))),
    });
    if (i) { v.view = vps[0].view; v.layers = vps[0].layers; v.toolOpts = vps[0].toolOpts; }
    vps.push(v);
    sparks.push({ v: [], w: [], c: [] });
  }
  box.append(addCell);
  initTools();
  initLayers();
  initLeftTabs();
  applyLayout();
  renderRunbar();
  setInterval(renderReadout, 200);
  on('theme', () => { vps.forEach((v) => v.themeChanged()); applyLayout(); });
  on('catalog', () => { renderMapTab(); renderSetupTab(); renderSlotHeads(true); });
  on('sel', () => { renderSlotHeads(); renderEditing(); });
  on('plan', (m) => { const v = vps[m.slot]; if (v && liveOnMap(m.slot)) { v.plans[m.which] = m.pts; v.dirty = true; } });
  on('costmap', async (m) => {
    const v = vps[m.slot];
    if (!v || !liveOnMap(m.slot)) return;
    try { v.setCostmap(m.which, m, await inflate(m.z)); } catch (e) { window.__err = `costmap ${m.which}: ${e.message}`; console.error(e); }
  });
  on('reset', (m) => { if (vps[m.slot]) vps[m.slot].clearLive(); });
  on('log', (m) => { logs.push(...m.items.map((l) => ({ ...l, slot: m.slot }))); if (logs.length > 300) logs.splice(0, logs.length - 300); renderLogs(); });
  window.addEventListener('keydown', (e) => {   // 1–4: make that slot active (comparison only)
    if (e.target.closest('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey || $('ws-sim').hidden) return;
    const n = +e.key;
    if (n >= 1 && n <= S.nSlots && S.nSlots > 1) setActive(n - 1);
  });
  return vps[0];
}

export const viewport = () => av();
export const resizeViews = () => vps.forEach((v) => v.resize());
let mouse = null;
const logs = [];
const sparks = [];

export function liveOnMap(i) { const a = S.slots[i].applied; return a !== null && JSON.parse(a).map === S.sel.map; }
const readySlots = () => visibleSlots().filter((s) => s.stack.status === 'ready' && liveOnMap(s.idx));
const eachVp = (f) => vps.forEach(f);

function setScene(sc) { S.scene = sc; eachVp((v) => { v.scene = sc; v.sel = null; v.dirty = true; }); }

// ================================================================== layout: 1 view or a comparison grid
function applyLayout() {
  const n = S.nSlots;
  $('views').dataset.n = n;
  $('stage').classList.toggle('multi', n > 1);
  document.querySelectorAll('#views .vcell').forEach((c, i) => { c.hidden = i >= n; c.classList.toggle('active', n > 1 && i === S.active); c.style.setProperty('--slot', slotColor(i)); });
  $('addSlot').hidden = n !== 3;
  vps.forEach((v, i) => { v.robotColor = n > 1 ? slotColor(i) : null; v.fitPad = n > 1 ? { x: 10, top: 46, bottom: 10 } : null; if (i !== S.active) v.follow = false; v.dirty = true; });
  renderSlotHeads(true);
  renderEditing();
  renderTelemetry();
}

async function setSlotCount(n) {
  if (n === S.nSlots) return;
  const off = S.slots.slice(n, S.nSlots).filter((s) => s.stack.status !== 'stopped');
  if (off.length) {
    const names = off.map((s) => SLOT_NAMES[s.idx]).join(', ');
    if (!await confirmDlg('슬롯 끄기', `실행 중인 슬롯 ${names} 를 끄고 화면을 ${n}개로 줄입니다.`, '끄고 줄이기')) return;
    await api.post('/api/session/stop', { slots: off.map((s) => s.idx) });
    off.forEach((s) => { s.applied = null; vps[s.idx].clearLive(); });
  }
  const grew = n > S.nSlots;
  for (let i = S.nSlots; i < n; i++) {   // a slot that was never set up starts as a copy of the active one
    const c = S.slots[i].cfg;
    if (c.stack === 'prod' && !Object.keys(c.values).length && !(c.raw || '').trim() && !c.preset) S.slots[i].cfg = JSON.parse(JSON.stringify(S.slots[S.active].cfg));
  }
  S.nSlots = n;
  if (S.active >= n) S.active = 0;
  saveSel();
  applyLayout();
  requestAnimationFrame(() => { resizeViews(); av().fit(); });
  renderRunbar();
  emit('stack');
  await loadSchema();
  renderSetupTab();
  const cpus = (S.info && S.info.cpus) || 0;
  if (grew && cpus && n > cpus / 2) toast(`CPU ${cpus}코어에서 ${n}개를 동시에 돌리면 Nav2 제어 주기가 밀려 결과가 달라질 수 있습니다 (슬롯 하나당 약 1코어).`, 'bad');
  if (grew && n > 1 && !persist('hint.compare')) {
    persist('hint.compare', true);
    toast('슬롯 머리글의 설정 이름을 눌러 슬롯마다 다른 설정 세트를 고르고, 위의 ‘모두 시작’ 을 누르세요.');
  }
}

export async function setActive(i) {
  if (i < 0 || i >= S.nSlots || i === S.active) return;
  const follow = av().follow;
  av().follow = false;
  S.active = i;
  av().follow = follow;
  saveSel();
  document.querySelectorAll('#views .vcell').forEach((c, k) => c.classList.toggle('active', S.nSlots > 1 && k === S.active));
  renderEditing(); renderRunbar(); renderTelemetry();   // headers do not depend on the active slot: re-rendering one mid-click would swallow it
  emit('sel'); emit('stack');
  await loadSchema();
  renderSetupTab();
}

// ================================================================== selection changes
export async function selectMap(id, { keepScene = false } = {}) {
  S.sel.map = id;
  saveSel();
  const meta = await api.get(`/api/maps/${id}`);
  S.mapMeta = meta;
  await vps[0].setMap(meta, `/api/maps/${id}/grid.png`);
  for (const v of vps.slice(1)) v.adoptMap(vps[0]);
  if (!keepScene) {
    const saved = persist('scene.' + id);
    const sc = saved || { static_obs: [], dyn_obs: [], start: meta.start, goal: null };
    if (!sc.start) sc.start = meta.start;
    setScene(sc);
  } else setScene(S.scene);
  vps.forEach((v, i) => { if (!liveOnMap(i)) v.clearLive(); });
  renderMapTab(); renderScenarios(); emit('sel');
  checkStart();
}

export async function selectRobot(id, profile = null) {
  S.sel.robotId = id;
  S.sel.robot = profile;
  const p = profile ? { profile } : await api.get(`/api/robots/${id}`);
  S.robotProfile = p.profile;
  eachVp((v) => { v.robot = p.profile; v.dirty = true; });
  for (const sl of S.slots) {
    const st = stackOf(sl.cfg.stack);
    if (st && !st.drives.includes(S.robotProfile.drive)) {
      const alt = S.stacks.find((s) => s.drives.includes(S.robotProfile.drive));
      if (alt) {
        sl.cfg.stack = alt.id;
        if (sl.idx < S.nSlots) toast(`${DRIVE_LABEL[S.robotProfile.drive]} 로봇이라 ${S.nSlots > 1 ? `슬롯 ${SLOT_NAMES[sl.idx]} 의 ` : ''}스택을 '${alt.name}' 으로 바꿨습니다`);
      }
    }
  }
  saveSel();
  await loadSchema();
  renderSetupTab(); emit('sel');
  checkStart();
}

export async function selectStack(id) {
  S.sel.stack = id;
  saveSel();
  await loadSchema();
  renderSetupTab(); emit('sel');
}

async function loadSchema() {
  try {
    S.schema = await api.post('/api/params/schema', { robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: S.sel.stack });
  } catch (e) { S.schema = null; toast(e.message, 'bad'); }
  renderParams();
}

async function checkStart() {
  if (!S.scene.start || !S.robotProfile) return;
  try {
    const r = await api.post(`/api/maps/${S.sel.map}/check_pose`, { robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, pose: S.scene.start });
    eachVp((v) => { v.startBad = !r.ok; v.dirty = true; });
    if (!r.ok) toast(`출발점에서 로봇이 벽과 겹칩니다 (${(r.clearance * 100).toFixed(0)} cm). 출발점 도구로 넓은 곳을 고르세요.`, 'bad');
  } catch (e) { /* map not loaded yet */ }
}

function activeValues() {
  const ids = new Set((S.schema ? S.schema.params : []).map((p) => p.id));
  return Object.fromEntries(Object.entries(S.sel.values).filter(([k]) => ids.has(k)));
}

// ================================================================== session control
const tag = (i) => (S.nSlots > 1 ? `슬롯 ${SLOT_NAMES[i]}: ` : '');

export async function startSlot(i) {
  const sl = S.slots[i];
  const c = sl.cfg;
  const body = { slot: i, map: S.sel.map, robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: c.stack,
    values: c.values, raw_overrides: c.raw || '', start: S.scene.start };
  sl.stack = { status: 'starting', message: 'Nav2 시작 중' };
  sl.pending = true;
  emit('stack');
  try {
    const r = await api.post('/api/session/start', body).finally(() => { sl.pending = false; });
    sl.applied = slotKey(i);
    sl.warnings = r.warnings || [];
    sl.result = null;
    vps[i].clearLive();
    sparks[i] = { v: [], w: [], c: [] };
    await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, start: S.scene.start, goal: S.scene.goal, map: S.sel.map });
    if (S.nSlots === 1) for (const w of sl.warnings) toast(w);
    renderTelemetry(); emit('sel');
    return true;
  } catch (e) {
    toast(tag(i) + e.message, 'bad');
    sl.stack = { status: 'error', message: e.message };
    emit('stack');
    return false;
  }
}

// top bar button: the single session, or every comparison slot that is not running its current settings
export async function startSession() {
  if (S.nSlots === 1) return startSlot(0);
  let idx = visibleSlots().filter((s) => s.stack.status !== 'ready' || isDirtySlot(s.idx)).map((s) => s.idx);
  if (!idx.length) idx = visibleSlots().map((s) => s.idx);
  await Promise.all(idx.map(startSlot));
}

export async function stopSlot(i) {
  await api.post('/api/session/stop', { slots: [i] });
  S.slots[i].applied = null;
  vps[i].clearLive();
  emit('sel');
}

export async function stopSession() {
  await api.post('/api/session/stop', {});
  for (const s of S.slots) s.applied = null;
  eachVp((v) => v.clearLive());
  emit('sel');
}

// a session is already running on the server (page reload): show its configuration
export function adoptServer(slots, scene) {
  const running = (slots || []).filter((s) => s.config);
  if (!running.length) return false;
  const c0 = running[0].config;
  S.sel.map = c0.map;
  S.sel.robotId = c0.robot_id || S.sel.robotId;
  S.sel.robot = c0.robot_id ? null : c0.robot;
  for (const s of running) Object.assign(S.slots[s.slot].cfg, { stack: s.config.stack, values: s.config.values || {}, raw: s.config.raw_overrides || '' });
  S.nSlots = Math.max(S.nSlots, ...running.map((s) => s.slot + 1));
  for (const s of running) S.slots[s.slot].applied = slotKey(s.slot);
  if (scene && scene.map === c0.map) S.scene = { static_obs: scene.static_obs || [], dyn_obs: scene.dyn_obs || [], start: scene.start, goal: scene.goal };
  saveSel();
  applyLayout();
  return true;
}

// ================================================================== live data (20 Hz)
let lastHeads = '';
export function onTick(m) {
  let changed = false, navChanged = false;
  for (const t of m.slots) {
    const sl = S.slots[t.slot];
    if (!sl) continue;
    const prev = sl.stack.status;
    sl.stack = sl.pending ? { status: 'starting', message: 'Nav2 시작 중' } : t.stack;
    if (prev !== sl.stack.status) {
      changed = true;
      if (sl.stack.status === 'stopped' && sl.applied !== null && prev === 'ready') sl.applied = null;
      if (sl.stack.status === 'ready' && t.slot < S.nSlots) {
        if (S.nSlots === 1) toast('시뮬레이션이 준비되었습니다. 목표 도구로 목적지를 찍으세요.', 'good');
        else if (visibleSlots().every((s) => s.stack.status === 'ready')) toast(`${S.nSlots}개 슬롯이 모두 준비되었습니다. 목표를 찍거나 ‘동시 출발’ 을 누르세요.`, 'good');
      }
      if (sl.stack.status === 'error' && S.nSlots > 1 && t.slot < S.nSlots) toast(`슬롯 ${SLOT_NAMES[t.slot]}: ${sl.stack.message}`, 'bad');
    }
    const prevNav = sl.nav && sl.nav.status;
    sl.nav = t.nav;
    sl.sim = t.sim;
    const ns = t.nav && t.nav.status;
    if (ns !== prevNav) {
      navChanged = true;
      if (ns === 'sending' || ns === 'navigating') sl.result = null;
      if (DONE.includes(ns) && !sl.result) sl.result = { status: ns, recoveries: t.nav.recoveries, ...((t.sim && t.sim.metrics) || {}) };
      if (DONE.includes(ns) && prevNav && !DONE.includes(prevNav)) {
        if (S.nSlots === 1) {
          if (ns === 'succeeded') toast('목표에 도착했습니다', 'good');
          if (ns === 'aborted') toast('Nav2 가 주행을 중단했습니다 (Nav2 메시지 확인)', 'bad');
        } else if (visibleSlots().every((s) => !s.nav || DONE.includes(s.nav.status) || s.stack.status !== 'ready')) {
          toast('모든 슬롯의 주행이 끝났습니다. 오른쪽 비교표를 확인하세요.', 'good');
        }
      }
    }
    if (t.sim && liveOnMap(t.slot)) {
      vps[t.slot].setLive(t.sim);
      const sp = sparks[t.slot];
      const v = Math.hypot(t.sim.vel[0], t.sim.vel[1]) * Math.sign(t.sim.vel[0] || 1);
      for (const [k, x] of [['v', v], ['w', t.sim.vel[2]], ['c', Math.min(t.sim.clear, 1.5)]]) { sp[k].push(x); if (sp[k].length > 300) sp[k].shift(); }
    }
  }
  if (changed) { emit('stack'); renderRunbar(); }
  if (navChanged) renderRunbar();
  renderSlotHeads();
  renderTelemetry();
}

// ================================================================== scene editing
const anyLive = () => readySlots().length > 0;

const pushScene = debounce(async () => {
  persist('scene.' + S.sel.map, S.scene);
  if (anyLive()) {
    try { await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, map: S.sel.map }); } catch (e) { toast(e.message, 'bad'); }
  }
}, 250);

function sceneEdited() { eachVp((v) => { v.dirty = true; }); pushScene(); }

async function setStart(pose) {
  S.scene.start = pose;
  persist('scene.' + S.sel.map, S.scene);
  eachVp((v) => { v.resetTrail(); v.dirty = true; });
  checkStart();
  if (anyLive()) {
    try { await api.post('/api/sim/teleport', { pose, slots: readySlots().map((s) => s.idx) }); } catch (e) { toast(e.message, 'bad'); }
  }
}

async function setGoal(pose) {
  S.scene.goal = pose;
  persist('scene.' + S.sel.map, S.scene);
  eachVp((v) => { v.dirty = true; });
  if (anyLive()) await go();
  else toast(S.nSlots > 1 ? '목표를 정했습니다. ‘모두 시작’ 후 ‘동시 출발’ 을 누르세요.' : '목표를 정했습니다. 시뮬레이션을 시작한 뒤 ‘주행’ 을 누르세요.');
}

// send the goal. Comparison: every robot goes back to the start and leaves at the same moment (reset).
async function go({ slots = null, reset = null } = {}) {
  if (!S.scene.goal) { toast('먼저 목표 도구로 목표 지점을 찍으세요'); return; }
  const idx = slots || readySlots().map((s) => s.idx);
  if (!idx.length) return;
  const doReset = reset ?? S.nSlots > 1;
  for (const i of idx) { vps[i].resetTrail(); sparks[i] = { v: [], w: [], c: [] }; S.slots[i].result = null; }
  try {
    const r = await api.post('/api/nav/goal', { pose: S.scene.goal, slots: idx, reset: doReset });
    for (const e of r.errors || []) toast(e, 'bad');
  } catch (e) { toast(e.message, 'bad'); }
}

// ================================================================== stage UI
const TOOLS = [
  ['select', 'select', '선택·이동 (드래그: 화면 이동)'],
  ['pan', 'pan', '화면 이동'],
  null,
  ['start', 'start', '출발점 (드래그로 방향)'],
  ['goal', 'goal', '목표 (드래그로 방향) — 실행 중이면 바로 주행'],
  null,
  ['box', 'box', '박스 (드래그)'],
  ['pole', 'pole', '기둥'],
  ['chair', 'chair', '의자 (다리 4개)'],
  ['person', 'person', '보행자 (두 점 클릭: 왕복 경로)'],
  ['eraser', 'eraser', '지우개'],
];

function initTools() {
  const box = $('tools');
  box.replaceChildren(...TOOLS.map((t) => t ? h('button', { 'data-tool': t[0], 'data-tip': t[2], 'aria-label': t[2], html: icon(t[1]),
    'aria-pressed': String(vps[0].tool === t[0]), onclick: () => setTool(t[0]) }) : h('hr')));
  window.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select') || e.ctrlKey || e.metaKey) return;
    const k = { v: 'select', h: 'pan', s: 'start', g: 'goal', b: 'box', p: 'pole', c: 'chair', w: 'person', e: 'eraser' }[e.key.toLowerCase()];
    if (k && $('ws-sim').hidden === false) setTool(k);
  });
}

function setTool(t) {
  eachVp((v) => { v.tool = t; v.drag = null; v.dirty = true; });
  for (const b of $('tools').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.tool === t));
  const o = $('toolOpts');
  const opts = vps[0].toolOpts;
  const field = (label, key, min, max, step, unit) => {
    const val = h('b', { class: 'num', text: opts[key] + unit });
    return h('label', { class: 'field' }, h('span', {}, label, ' ', val),
      h('input', { type: 'range', min, max, step, value: opts[key], oninput: (e) => { opts[key] = +e.target.value; val.textContent = e.target.value + unit; } }));
  };
  const tips = {
    start: '맵을 누른 채 끌어서 로봇 방향을 정합니다. 실행 중이면 로봇이 그 자리로 옮겨집니다.',
    goal: S.nSlots > 1 ? '맵을 누른 채 끌어서 도착 방향을 정합니다. 실행 중이면 모든 로봇이 출발점에서 동시에 출발합니다.' : '맵을 누른 채 끌어서 도착 방향을 정합니다. 실행 중이면 바로 출발합니다.',
    box: '드래그해서 맵에 없는 박스를 놓습니다. 라이다에는 보이지만 맵에는 없습니다.',
    eraser: '지울 장애물이나 보행자 경로를 누르세요.',
    select: '장애물을 끌어 옮기고 Delete 로 지웁니다. 빈 곳을 끌면 화면이 움직입니다.',
  };
  if (t === 'pole') o.replaceChildren(h('h4', { text: '기둥' }), field('반지름', 'poleR', 0.02, 0.5, 0.01, ' m'));
  else if (t === 'chair') o.replaceChildren(h('h4', { text: '의자' }), field('다리 간격', 'chairSize', 0.3, 0.8, 0.01, ' m'), h('div', { class: 'hint', text: '지름 5 cm 다리 4개. 2D 라이다로는 잘 안 보이는 장애물입니다.' }));
  else if (t === 'person') o.replaceChildren(h('h4', { text: '보행자' }), field('속도', 'pedSpeed', 0.1, 1.5, 0.05, ' m/s'), field('반지름', 'pedR', 0.1, 0.4, 0.01, ' m'),
    h('div', { class: 'hint', text: '시작점과 끝점을 누르면 그 사이를 왕복합니다 (Shift 로 경유점 추가). 로봇 앞에서는 멈춰 양보합니다.' }));
  else if (tips[t]) o.replaceChildren(h('div', { class: 'hint', text: tips[t] }));
  else { o.hidden = true; return; }
  o.hidden = false;
}

const LAYERS = [['global', '전역 costmap', '--plan'], ['local', '지역 costmap', '--lplan'], ['scan', '라이다', '--scan'], ['plan', '경로', '--plan'], ['trail', '궤적', '--trail'],
  ['others', '다른 슬롯 궤적', '--s1', true], ['grid', '격자', '--muted']];
function initLayers() {
  Object.assign(vps[0].layers, persist('layers') || {});
  renderLayers();
}

function renderLayers() {
  const L = vps[0].layers;
  const items = LAYERS.filter((l) => !l[3] || S.nSlots > 1).map(([k, label, col]) => {
    const b = h('button', { 'aria-pressed': String(!!L[k]), onclick: () => { L[k] = !L[k]; b.setAttribute('aria-pressed', String(L[k])); eachVp((v) => { v.dirty = true; }); persist('layers', L); } },
      h('i', { class: 'sw', style: { color: `var(${col})` } }), h('span', { class: 'lb', text: label }));
    b.title = label;
    return b;
  });
  $('layers').replaceChildren(...items, h('span', { class: 'sep' }),
    h('button', { title: '전체 보기', 'aria-label': '전체 보기', html: icon('fit'), onclick: () => { av().follow = false; av().fit(); renderRunbar(); } }));
}

export function renderRunbar() {
  const multi = S.nSlots > 1;
  const live = readySlots();
  const ready = live.length > 0;
  const moving = live.some((s) => ['navigating', 'sending'].includes((s.nav || {}).status));
  const bar = $('runbar');
  const sep = () => h('span', { class: 'sep', style: { width: '1px', alignSelf: 'stretch', background: 'var(--line)' } });
  const seg = h('div', { class: 'seg slots', role: 'group', 'aria-label': '동시 실행 개수', title: '서로 다른 설정을 2~4개 동시에 띄워 비교합니다 (슬롯 하나당 CPU 약 1코어)' },
    h('span', { class: 'lbl', html: icon('grid') }),
    ...[1, 2, 3, 4].map((n) => h('button', { 'aria-pressed': String(n === S.nSlots), 'data-n': n, title: n === 1 ? '하나만 실행' : `${n}개 동시 실행`, onclick: () => setSlotCount(n) }, String(n))));
  bar.replaceChildren(seg, sep(),
    btn(multi ? '동시 출발' : (moving ? '다시 보내기' : '주행'), { cls: 'primary', icon: 'play', disabled: !ready, onclick: () => go(),
      title: multi ? '모든 로봇을 출발점에 다시 놓고 같은 순간에 목표로 보냅니다' : '현재 목표로 주행' }),
    btn('정지', { icon: 'stop', disabled: !moving, onclick: () => api.post('/api/nav/cancel', {}) }),
    btn('출발점으로', { icon: 'undo', disabled: !ready || !S.scene.start, onclick: () => setStart(S.scene.start) }),
    sep(),
    btn('', { cls: 'ghost icon-only', icon: 'follow', title: av().follow ? '로봇 따라가기 끄기' : '로봇 따라가기', aria: '로봇 따라가기',
      onclick: () => { av().follow = !av().follow; renderRunbar(); } }),
    btn('', { cls: 'ghost icon-only', icon: 'trash', title: '장애물·보행자 모두 지우기', aria: '장애물 모두 지우기',
      onclick: () => { S.scene.static_obs = []; S.scene.dyn_obs = []; setScene(S.scene); pushScene(); } }),
  );
  const f = bar.querySelector('[title^="로봇 따라가기"]');
  if (f) f.setAttribute('aria-pressed', String(av().follow));
  if (f && av().follow) f.style.color = 'var(--accent)';
  renderLayersIfNeeded();
}

let layersFor = 0;
function renderLayersIfNeeded() { if (layersFor !== S.nSlots) { layersFor = S.nSlots; renderLayers(); } }

// comparison slot header: what runs there, its state, start/stop and drive controls
export function renderSlotHeads(force = false) {
  const sig = JSON.stringify([S.nSlots, S.presets.length, visibleSlots().map((s) => [s.stack.status, isDirtySlot(s.idx), cfgLabel(s.idx), (s.nav || {}).status, liveOnMap(s.idx)])]);
  if (!force && sig === lastHeads) return;
  lastHeads = sig;
  for (let i = 0; i < MAX_SLOTS; i++) {
    const el = $(`vhead${i}`);
    if (!el) continue;
    if (S.nSlots < 2 || i >= S.nSlots) { el.hidden = true; continue; }
    el.hidden = false;
    const sl = S.slots[i], st = sl.stack.status, dirty = isDirtySlot(i);
    const lab = cfgLabel(i);
    const ready = st === 'ready' && liveOnMap(i);
    const moving = ['navigating', 'sending'].includes((sl.nav || {}).status);
    const state = st === 'ready' && dirty ? 'dirty' : st;
    const ib = (ic, title, onclick, disabled, cls = '') => h('button', { class: 'ib ' + cls, title, 'aria-label': title, html: icon(ic), disabled, onclick: (e) => { e.stopPropagation(); onclick(e); } });
    el.replaceChildren(
      h('b', { class: 'slotbadge', text: SLOT_NAMES[i] }),
      h('button', { class: 'cfgname', title: '이 슬롯의 설정 세트 바꾸기', onclick: (e) => { e.stopPropagation(); slotMenu(i, e.currentTarget); } },
        h('span', { text: lab.name + (lab.modified ? ' *' : '') }), h('span', { html: icon('chevron') })),
      h('span', { class: 'sst', 'data-state': state, title: sl.stack.message || '' }, h('i'), state === 'dirty' ? '변경됨' : STACK_LABEL[st] || st),
      h('span', { class: 'grow' }),
      ib(st === 'ready' ? 'restart' : 'play', st === 'ready' ? (dirty ? '변경 적용 (재시작)' : '재시작') : '시작', () => startSlot(i), st === 'starting', dirty || st !== 'ready' ? 'go' : ''),
      ib('power', '끄기', () => stopSlot(i), st === 'stopped'),
      h('span', { class: 'vsep' }),
      ib('flag', '이 슬롯만 출발점에서 다시 주행', () => go({ slots: [i], reset: true }), !ready || !S.scene.goal),
      ib('stop', '이 슬롯 주행 멈춤', () => api.post('/api/nav/cancel', { slots: [i] }), !moving),
    );
  }
}

function slotMenu(i, anchor) {
  const drive = S.robotProfile ? S.robotProfile.drive : 'diff';
  const ok = (id) => { const st = stackOf(id); return !st || st.drives.includes(drive); };
  const cur = S.slots[i].cfg;
  const assign = (cfg) => assignSlot(i, cfg);
  menu(anchor, [
    { heading: `슬롯 ${SLOT_NAMES[i]} 설정 세트` },
    ...S.presets.map((p) => ({ label: p.name, sub: `${(stackOf(p.stack) || {}).name || p.stack}${p.description ? ' · ' + p.description : ''}`, tag: p.builtin ? '기본' : '내 세트',
      checked: cur.preset === p.id, disabled: !ok(p.stack), onclick: () => assign({ stack: p.stack, values: p.values, raw: p.raw, preset: p.id }) })),
    { heading: '스택 기본값' },
    ...S.stacks.map((st) => ({ label: st.name.replace(/\s*\(.*\)/, ''), sub: st.description, disabled: !ok(st.id),
      checked: !cur.preset && cur.stack === st.id && !Object.keys(cur.values).length, onclick: () => assign({ stack: st.id, values: {}, raw: '', preset: null }) })),
    'sep',
    ...(i !== S.active ? [{ label: `슬롯 ${SLOT_NAMES[S.active]} 설정 복사`, icon: 'copy', onclick: () => assign(JSON.parse(JSON.stringify(S.slots[S.active].cfg))) }] : []),
    { label: '파라미터 직접 편집', icon: 'sliders', onclick: async () => { await setActive(i); showLeftTab('params'); } },
  ]);
}

async function assignSlot(i, cfg) {
  const st = stackOf(cfg.stack);
  if (st && S.robotProfile && !st.drives.includes(S.robotProfile.drive)) { toast(`${DRIVE_LABEL[S.robotProfile.drive]} 로봇에는 '${st.name}' 을 쓸 수 없습니다`, 'bad'); return; }
  S.slots[i].cfg = { stack: cfg.stack, values: { ...(cfg.values || {}) }, raw: cfg.raw || '', preset: cfg.preset || null };
  saveSel();
  if (i === S.active) { await loadSchema(); renderSetupTab(); }
  renderSlotHeads(true);
  emit('sel');
}

function renderEditing() {
  const el = $('editingSlot');
  if (S.nSlots < 2) { el.hidden = true; return; }
  el.hidden = false;
  el.style.setProperty('--slot', slotColor(S.active));
  const lab = cfgLabel(S.active);
  el.replaceChildren(h('b', { class: 'slotbadge', text: SLOT_NAMES[S.active] }),
    h('div', {}, h('b', { text: `슬롯 ${SLOT_NAMES[S.active]} 편집 중` }), h('span', { text: lab.name + (lab.modified ? ' (수정됨)' : '') })),
    h('span', { class: 'hint', text: '화면을 누르거나 1~4 키로 슬롯 선택' }));
}

function renderReadout() {
  const r = $('readout');
  const s = vps[0].view.s;
  const nice = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].find((m) => m * s >= 60) || 50;
  r.replaceChildren(
    h('span', { class: 'scalebar' }, h('i', { style: { width: `${nice * s}px` } }), `${nice} m`),
    mouse ? h('span', { text: `x ${mouse[0].toFixed(2)}  y ${mouse[1].toFixed(2)}` }) : '',
  );
  for (let i = 0; i < S.nSlots; i++) renderOverlay(i);
}

function renderOverlay(i) {
  const ov = $(i ? `vover${i}` : 'stageOverlay');
  const sl = S.slots[i];
  const st = sl.stack.status;
  const sig = `${st}|${sl.stack.message}|${S.nSlots}`;
  if (ov.dataset.sig === sig) return;
  ov.dataset.sig = sig;
  const small = S.nSlots > 1;
  if (st === 'starting') {
    ov.hidden = false;
    ov.replaceChildren(h('div', { class: 'card' + (small ? ' small' : '') }, h('div', { class: 'spin' }), h('h2', { text: small ? `${SLOT_NAMES[i]} 시작 중` : 'Nav2 를 시작하고 있습니다' }),
      small ? '' : h('div', { class: 'hint', text: '시뮬레이터와 Nav2 노드 7개를 띄우는 중 (보통 5초 안팎)' })));
  } else if (st === 'error') {
    ov.hidden = false;
    ov.replaceChildren(h('div', { class: 'card' + (small ? ' small' : '') }, h('h2', { text: small ? `${SLOT_NAMES[i]} 멈춤` : '시뮬레이션이 멈췄습니다' }), h('div', { class: 'errbox', text: sl.stack.message }),
      h('div', { style: { display: 'flex', gap: '8px' } }, btn('로그 보기', { onclick: () => showStackLog(i) }), btn('다시 시작', { cls: 'primary', icon: 'restart', onclick: () => startSlot(i) }))));
  } else ov.hidden = true;
}

async function showStackLog(i = S.active) {
  const t = await api.get(`/api/session/log?slot=${i}`);
  modal(S.nSlots > 1 ? `Nav2 실행 로그 — 슬롯 ${SLOT_NAMES[i]}` : 'Nav2 실행 로그', h('pre', { class: 'code', text: t.split('\n').slice(-400).join('\n') || '(비어 있음)' }));
}

// ================================================================== left tabs
function initLeftTabs() {
  $('leftTabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) showLeftTab(b.dataset.tab); });
  showLeftTab(persist('leftTab') || 'map');
}

function showLeftTab(t) {
  for (const b of $('leftTabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === t));
  for (const s of document.querySelectorAll('#ws-sim .tab')) s.hidden = s.dataset.tab !== t;
  persist('leftTab', t);
}

// ---------------------------------------------------------------- map tab
let mapFilter = '';
let scenFilter = 'all';
export function renderMapTab() {
  const tab = $('tabMap');
  const groups = {};
  for (const m of S.maps) if (!mapFilter || (m.name + m.id + m.description).toLowerCase().includes(mapFilter)) (groups[m.group] = groups[m.group] || []).push(m);
  const search = h('div', { class: 'search', html: icon('search') },
    h('input', { type: 'text', id: 'mapSearch', placeholder: '맵 검색', value: mapFilter, 'aria-label': '맵 검색',
      oninput: (e) => { mapFilter = e.target.value.toLowerCase(); renderMapTab(); document.getElementById('mapSearch').focus(); } }));
  const sec = [h('div', { class: 'sec' }, h('h3', {}, '맵', btn('맵 추가', { cls: 'sm ghost act', icon: 'upload', onclick: () => importMaps() })), search)];
  for (const [g, list] of Object.entries(groups)) {
    sec.push(h('div', { class: 'sec' }, h('div', { class: 'grouplabel', text: g }),
      h('div', { class: 'mapgrid' }, ...list.map((m) => h('div', { class: 'mapitem' },
        h('button', { class: 'mapcard', 'aria-pressed': String(m.id === S.sel.map), title: m.description, onclick: () => selectMap(m.id) },
          h('div', { class: 'thumb' }, h('img', { src: `/api/maps/${m.id}/thumb.png?v=${encodeURIComponent(m.name)}`, alt: '', loading: 'lazy' })),
          h('div', { class: 'meta' }, h('b', { text: m.name }), h('span', { class: 'num', text: `${m.width_m} × ${m.height_m} m` }))),
        h('button', { class: 'mapmore', title: '맵 관리', 'aria-label': `${m.name} 관리`, html: icon('more'), onclick: (e) => mapMenu(m, e.currentTarget) }))))));
  }
  sec.push(h('div', { class: 'sec' }, h('div', { class: 'dropzone', id: 'mapDrop' }, h('span', { html: icon('upload') }),
    h('span', { text: '맵 파일(YAML + 이미지, 또는 zip)을 여기에 끌어다 놓으면 추가됩니다' }))));
  sec.push(h('div', { class: 'sec', id: 'scenSec' }));
  tab.replaceChildren(...sec);
  bindDrop(tab);
  renderScenarios();
}

function bindDrop(el) {
  if (el.dataset.drop) return;
  el.dataset.drop = '1';
  el.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); el.classList.add('dragging'); } });
  el.addEventListener('dragleave', (e) => { if (!el.contains(e.relatedTarget)) el.classList.remove('dragging'); });
  el.addEventListener('drop', (e) => { e.preventDefault(); el.classList.remove('dragging'); if (e.dataTransfer.files.length) importMaps([...e.dataTransfer.files]); });
}

function mapMenu(m, anchor) {
  menu(anchor, [
    { heading: m.name },
    { label: '내보내기 (zip)', sub: '다른 PC 의 Nav Studio 에서 ‘맵 추가’ 로 가져올 수 있습니다', icon: 'download',
      onclick: () => { h('a', { href: `/api/maps/${m.id}/export.zip`, download: `${m.id}.zip` }).click(); } },
    { label: '이름 바꾸기', icon: 'edit', disabled: m.builtin, onclick: () => renameMap(m) },
    { label: '지우기', icon: 'trash', disabled: m.builtin, sub: m.builtin ? '기본 맵은 지울 수 없습니다' : '', onclick: () => deleteMap(m) },
  ]);
}

async function renameMap(m) {
  const inp = h('input', { type: 'text', value: m.name });
  const close = modal('맵 이름 바꾸기', [h('label', { class: 'field' }, h('span', { text: '이름' }), inp)], [btn('취소', { onclick: () => close() }),
    btn('바꾸기', { cls: 'primary', onclick: async () => {
      try { await api.patch(`/api/maps/${m.id}`, { name: inp.value }); S.maps = await api.get('/api/maps'); close(); renderMapTab(); emit('sel'); } catch (e) { toast(e.message, 'bad'); }
    } })]);
  inp.focus(); inp.select();
}

async function deleteMap(m) {
  if (!await confirmDlg('맵 지우기', `'${m.name}' 맵을 지웁니다. 이 맵에 저장한 장면도 쓸 수 없게 됩니다. 되돌릴 수 없습니다.`, '지우기', true)) return;
  try {
    if (m.id === S.sel.map && visibleSlots().some((s) => s.stack.status !== 'stopped' && liveOnMap(s.idx))) await stopSession();
    await api.del(`/api/maps/${m.id}`);
    S.maps = await api.get('/api/maps');
    if (m.id === S.sel.map) await selectMap(S.maps[0].id);
    renderMapTab();
    toast(`'${m.name}' 맵을 지웠습니다`);
  } catch (e) { toast(e.message, 'bad'); }
}

function importMaps(files = null) {
  let picked = files || [];
  const list = h('ul', { class: 'filelist' });
  const name = h('input', { type: 'text', placeholder: '비우면 파일 이름을 씁니다', id: 'upName' });
  const nameRow = h('label', { class: 'field' }, h('span', { text: '표시 이름 (맵 하나일 때)' }), name);
  const input = h('input', { type: 'file', multiple: true, accept: '.yaml,.yml,.pgm,.png,.jpg,.jpeg,.zip', id: 'upFiles', hidden: true,
    onchange: (e) => { picked = [...picked, ...e.target.files]; show(); } });
  const drop = h('div', { class: 'dropzone big', onclick: () => input.click() }, h('span', { html: icon('upload') }),
    h('span', {}, h('b', { text: '파일을 끌어다 놓거나 눌러서 고르세요' }), h('small', { text: 'ROS map_server 형식 YAML + 이미지(PGM·PNG), 또는 맵 zip (여러 맵 가능)' })));
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('dragging'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragging'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('dragging'); picked = [...picked, ...e.dataTransfer.files]; show(); });
  function show() {
    const yamls = picked.filter((f) => /\.ya?ml$/i.test(f.name)).length;
    nameRow.hidden = !(yamls === 1 && !picked.some((f) => /\.zip$/i.test(f.name)));
    list.replaceChildren(...picked.map((f, k) => h('li', {}, h('span', { text: f.name }), h('small', { class: 'num', text: `${Math.ceil(f.size / 1024)} KB` }),
      h('button', { class: 'reset', html: icon('x'), title: '빼기', onclick: () => { picked.splice(k, 1); show(); } }))));
  }
  const close = modal('맵 추가', [drop, input, list, nameRow,
    h('div', { class: 'hint', text: '추가한 맵은 이 PC 의 Nav Studio 데이터 폴더(maps/)에 저장되고 ‘내 맵’ 에 나타납니다. 맵 카드의 ⋯ 메뉴에서 이름 바꾸기·내보내기·지우기를 할 수 있습니다.' })],
  [btn('취소', { onclick: () => close() }), btn('추가', { cls: 'primary', icon: 'upload', onclick: async () => {
    if (!picked.length) { toast('맵 파일을 고르세요', 'bad'); return; }
    const fd = new FormData();
    for (const f of picked) fd.append('files', f, f.name);
    fd.append('name', nameRow.hidden ? '' : name.value);
    try {
      const r = await api.post('/api/maps', fd);
      S.maps = await api.get('/api/maps');
      close(); renderMapTab();
      if (r.maps.length) await selectMap(r.maps[0].id);
      toast(r.maps.length > 1 ? `맵 ${r.maps.length}개를 추가했습니다` : `'${r.maps[0].name}' 맵을 추가했습니다`, 'good');
      emit('catalog');
    } catch (e) { toast(e.message, 'bad'); }
  } })]);
  show();
}

async function renderScenarios() {
  const box = document.getElementById('scenSec');
  if (!box) return;
  let eps = [];
  try { eps = await api.get(`/api/scenarios/${S.sel.map}`); } catch (e) { /* none */ }
  const cats = { all: '전체', nominal: '정상', unmapped: '미등록 장애물', dynamic: '보행자' };
  const list = eps.filter((e) => scenFilter === 'all' || e.category === scenFilter);
  box.replaceChildren(
    h('h3', {}, `시나리오 (${mapName(S.sel.map)})`),
    eps.length ? h('div', { class: 'seg' }, ...Object.entries(cats).map(([k, v]) => h('button', { 'aria-pressed': String(scenFilter === k), onclick: () => { scenFilter = k; renderScenarios(); } }, v))) :
      h('div', { class: 'hint', text: '이 맵에는 준비된 시나리오가 없습니다. 도구로 출발점·목표·장애물을 직접 놓으세요.' }),
    h('div', { class: 'scenlist' }, ...list.map((e) => h('button', { class: 'scen', title: '불러오기: 출발점·목표·장애물을 이 시나리오로 바꿉니다', onclick: () => loadScenario(e) },
      h('i', { class: 'dot ' + e.category }), h('span', {}, e.id.split('/').slice(1).join(' / '), e.tags && e.tags.length ? h('small', { text: '  ' + e.tags.join(', ') }) : ''),
      h('small', { text: `${e.ref_len.toFixed(1)} m` })))),
  );
}

async function loadScenario(e) {
  setScene({ start: e.start, goal: e.goal, static_obs: JSON.parse(JSON.stringify(e.static_obs)), dyn_obs: JSON.parse(JSON.stringify(e.dyn_obs)) });
  persist('scene.' + S.sel.map, S.scene);
  checkStart();
  if (anyLive()) {
    await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, map: S.sel.map });
    await api.post('/api/sim/teleport', { pose: S.scene.start, slots: readySlots().map((s) => s.idx) });
    eachVp((v) => v.resetTrail());
    toast(S.nSlots > 1 ? '시나리오를 불러왔습니다. ‘동시 출발’ 을 누르면 모두 출발합니다.' : '시나리오를 불러왔습니다. ‘주행’ 을 누르면 출발합니다.');
  } else toast('시나리오를 불러왔습니다. 시뮬레이션을 시작하세요.');
}

// ---------------------------------------------------------------- setup tab
function footprintIcon(profile, size = 40) {
  const c = h('canvas', { width: size * 2, height: size * 2 });
  const g = c.getContext('2d');
  const poly = robotPolygon(profile, 24);
  const R = Math.max(...poly.map((p) => Math.hypot(p[0], p[1]))) || 0.2;
  const k = (size * 0.85) / R;
  g.translate(size, size);
  g.fillStyle = cssVar('--robot');
  g.strokeStyle = cssVar('--ink');
  g.lineWidth = 2;
  g.beginPath(); poly.forEach((p, i) => (i ? g.lineTo(p[0] * k, -p[1] * k) : g.moveTo(p[0] * k, -p[1] * k))); g.closePath(); g.fill(); g.stroke();
  g.beginPath(); g.moveTo(0, 0); g.lineTo(R * k, 0); g.stroke();
  return c;
}

const profileCache = {};
export async function renderSetupTab() {
  const tab = $('tabSetup');
  const robots = await Promise.all(S.robots.map(async (r) => {
    if (!profileCache[r.id]) { try { profileCache[r.id] = (await api.get(`/api/robots/${r.id}`)).profile; } catch (e) { profileCache[r.id] = null; } }
    return [r, profileCache[r.id]];
  }));
  const drive = S.robotProfile ? S.robotProfile.drive : 'diff';
  const plugins = (S.info && S.info.plugins) || {};
  const robotList = h('div', { class: 'optlist' }, ...robots.map(([r, p]) => h('button', { class: 'opt', 'aria-pressed': String(!S.sel.robot && r.id === S.sel.robotId),
    onclick: () => selectRobot(r.id) }, p ? footprintIcon(p) : h('span'), h('div', { class: 't' }, h('b', {}, r.name, r.builtin ? '' : ' ', r.builtin ? '' : h('span', { class: 'tag', text: '내 로봇' })),
    h('span', { text: `${DRIVE_LABEL[r.drive]} · ${r.description || ''}` })))));
  if (S.sel.robot) robotList.prepend(h('div', { class: 'opt', 'aria-pressed': 'true' }, footprintIcon(S.sel.robot), h('div', { class: 't' }, h('b', { text: S.sel.robot.name + ' (편집 중, 저장 안 됨)' }), h('span', { text: DRIVE_LABEL[S.sel.robot.drive] }))));
  const stackList = h('div', { class: 'optlist' }, ...S.stacks.map((s) => {
    const ok = s.drives.includes(drive);
    const missing = (s.requires || []).filter((p) => !plugins[p]);
    return h('button', { class: 'opt', 'aria-pressed': String(s.id === S.sel.stack), 'aria-disabled': String(!ok),
      title: ok ? s.description : `${DRIVE_LABEL[drive]} 로봇에는 쓸 수 없습니다`,
      onclick: () => { if (ok) selectStack(s.id); } },
    h('span', { html: icon(s.controller === 'mppi' ? 'tune' : s.controller === 'rpp' ? 'goal' : 'sliders') }),
    h('div', { class: 't' }, h('b', { text: s.name }), h('span', { text: s.description }),
      h('div', {}, ...s.drives.map((d) => h('span', { class: 'tag', text: DRIVE_LABEL[d], style: { marginRight: '4px' } })),
        missing.length ? h('span', { class: 'tag warn', text: '플러그인 없음 → 표준 플래너로 대체' }) : '')));
  }));
  const multi = S.nSlots > 1 ? ` — 슬롯 ${SLOT_NAMES[S.active]}` : '';
  tab.replaceChildren(
    h('div', { class: 'sec' }, h('h3', {}, '로봇', btn('로봇 설계', { cls: 'sm ghost act', icon: 'edit', onclick: () => emit('goto', 'robot') })), robotList,
      S.nSlots > 1 ? h('div', { class: 'hint', text: '로봇은 모든 슬롯이 같이 씁니다.' }) : ''),
    h('div', { class: 'sec' }, h('h3', { text: `주행 스택 (제어기 + 경로 계획기)${multi}` }), stackList),
    setsSection(drive),
  );
}

// ---------------------------------------------------------------- config sets (stack + parameter changes, saved by name)
function setsSection(drive) {
  const cur = S.sel.preset;
  const lab = cfgLabel(S.active);
  const nChanged = Object.keys(S.sel.values).length + ((S.sel.raw || '').trim() ? 1 : 0);
  const item = (p) => {
    const st = stackOf(p.stack);
    const ok = !st || st.drives.includes(drive);
    const n = Object.keys(p.values || {}).length + ((p.raw || '').trim() ? 1 : 0);
    return h('div', { class: 'setitem' },
      h('button', { class: 'opt', 'aria-pressed': String(cur === p.id), 'aria-disabled': String(!ok), title: ok ? p.description : `${DRIVE_LABEL[drive]} 로봇에는 쓸 수 없는 스택입니다`,
        onclick: () => { if (ok) loadSet(p); } },
      h('span', { html: icon(p.builtin ? 'sliders' : 'save') }),
      h('div', { class: 't' }, h('b', {}, p.name, ' ', h('span', { class: 'tag', text: p.builtin ? '기본' : '내 세트' })),
        h('span', { text: `${st ? st.name.replace(/\s*\(.*\)/, '') : p.stack} · 변경 ${n}${p.description ? ' · ' + p.description : ''}` }))),
      p.builtin ? '' : h('button', { class: 'reset', title: '설정 세트 지우기', 'aria-label': `${p.name} 지우기`, html: icon('trash'), onclick: () => deleteSet(p) }));
  };
  return h('div', { class: 'sec', id: 'setsSec' },
    h('h3', {}, '설정 세트', btn('현재 설정 저장', { cls: 'sm ghost act', icon: 'save', onclick: saveSetDialog })),
    h('div', { class: 'hint', text: `지금: ${lab.name}${lab.modified ? ' (수정됨)' : ''} · 스택 ${((stackOf(S.sel.stack) || {}).name || S.sel.stack).replace(/\s*\(.*\)/, '')} · 변경 ${nChanged}개` }),
    h('div', { class: 'optlist' },
      h('button', { class: 'opt', 'aria-pressed': String(!cur && !nChanged), onclick: () => { S.sel.values = {}; S.sel.raw = ''; S.sel.preset = null; saveSel(); renderParams(); renderSetupTab(); emit('sel'); } },
        h('span', { html: icon('undo') }), h('div', { class: 't' }, h('b', { text: '스택 기본값' }), h('span', { text: '선택한 스택의 파라미터를 그대로 사용' }))),
      ...S.presets.map(item)),
    h('div', { class: 'hint', text: '설정 세트 = 주행 스택 + 바꾼 파라미터 묶음. 저장해 두면 동시 실행 슬롯·벤치마크에서 이름으로 고를 수 있습니다.' }));
}

async function loadSet(p) {
  const st = stackOf(p.stack);
  if (st && S.robotProfile && !st.drives.includes(S.robotProfile.drive)) { toast(`${DRIVE_LABEL[S.robotProfile.drive]} 로봇에는 '${st.name}' 을 쓸 수 없습니다`, 'bad'); return; }
  S.sel.stack = p.stack; S.sel.values = { ...p.values }; S.sel.raw = p.raw || ''; S.sel.preset = p.id;
  saveSel();
  await loadSchema();
  renderSetupTab(); emit('sel');
  toast(`'${p.name}' 을 ${S.nSlots > 1 ? `슬롯 ${SLOT_NAMES[S.active]} 에 ` : ''}불러왔습니다${S.stack.status === 'ready' ? '. ‘변경 적용’ 으로 실행하세요.' : ''}`);
}

export async function saveSet(body, sid = null) {
  const r = sid ? await api.put(`/api/presets/${sid}`, body) : await api.post('/api/presets', body);
  S.presets = await api.get('/api/presets');
  return r;
}

function saveSetDialog(prefill = null) {
  const cur = presetOf(S.sel.preset);
  const mine = !prefill && cur && !cur.builtin ? cur : null;
  const name = h('input', { type: 'text', value: prefill ? prefill.name : (mine ? mine.name : ''), placeholder: '예: DWB 빠르게', id: 'setName' });
  const desc = h('input', { type: 'text', value: prefill ? (prefill.description || '') : (mine ? mine.description : ''), placeholder: '무엇을 바꿨는지 (선택)', id: 'setDesc' });
  const values = prefill ? prefill.values : activeValues();
  const raw = prefill ? (prefill.raw || '') : (S.sel.raw || '');
  const stack = prefill ? prefill.stack : S.sel.stack;
  const n = Object.keys(values).length;
  const body = () => ({ name: name.value.trim(), description: desc.value.trim(), stack, values, raw });
  const done = (r) => {
    if (!prefill) { S.sel.preset = r.id; saveSel(); }
    renderSetupTab(); renderParams(); renderSlotHeads(true); emit('sel');
    toast(`설정 세트 '${r.name}' 을 저장했습니다`, 'good');
  };
  const close = modal('설정 세트 저장', [
    h('label', { class: 'field' }, h('span', { text: '이름' }), name),
    h('label', { class: 'field' }, h('span', { text: '설명' }), desc),
    h('div', { class: 'hint', text: `스택 ${((stackOf(stack) || {}).name || stack)} · 바꾼 파라미터 ${n}개${raw.trim() ? ' · 고급 오버라이드 포함' : ''}` }),
  ], [
    btn('취소', { onclick: () => close() }),
    mine ? btn(`'${mine.name}' 덮어쓰기`, { onclick: async () => { try { done(await saveSet(body(), mine.id)); close(); } catch (e) { toast(e.message, 'bad'); } } }) : '',
    btn('새 세트로 저장', { cls: 'primary', icon: 'save', onclick: async () => {
      const b = body();
      if (!b.name) { toast('이름을 입력하세요', 'bad'); return; }
      const same = S.presets.find((p) => !p.builtin && p.name === b.name);
      try {
        if (same) {
          close();
          if (!await confirmDlg('같은 이름의 설정 세트', `'${b.name}' 이 이미 있습니다. 덮어쓸까요?`, '덮어쓰기')) return;
          done(await saveSet(b, same.id));
        } else { done(await saveSet(b)); close(); }
      } catch (e) { toast(e.message, 'bad'); }
    } }),
  ]);
  name.focus();
}
export const saveSetFrom = (cfg) => saveSetDialog(cfg);

async function deleteSet(p) {
  if (!await confirmDlg('설정 세트 지우기', `'${p.name}' 을 지웁니다. 이 세트를 쓰던 슬롯은 값은 그대로 두고 이름만 사라집니다.`, '지우기', true)) return;
  try {
    await api.del(`/api/presets/${p.id}`);
    S.presets = await api.get('/api/presets');
    for (const sl of S.slots) if (sl.cfg.preset === p.id) sl.cfg.preset = null;
    saveSel(); renderSetupTab(); renderParams(); renderSlotHeads(true); emit('sel');
  } catch (e) { toast(e.message, 'bad'); }
}

// ---------------------------------------------------------------- params tab
let pFilter = '';
let pChangedOnly = false;
export function renderParams() {
  const tab = $('tabParams');
  const cnt = $('paramCount');
  const nChanged = Object.keys(activeValues()).length + ((S.sel.raw || '').trim() ? 1 : 0);
  cnt.hidden = !nChanged; cnt.textContent = nChanged;
  if (!S.schema) { tab.replaceChildren(h('div', { class: 'hint', text: '파라미터를 불러오는 중…' })); return; }
  const lab = cfgLabel(S.active);
  const setbar = h('div', { class: 'setbar' }, h('span', { html: icon('save') }),
    h('div', { class: 't' }, h('small', { text: S.nSlots > 1 ? `설정 세트 — 슬롯 ${SLOT_NAMES[S.active]}` : '설정 세트' }), h('b', { text: lab.name + (lab.modified ? ' (수정됨)' : '') })),
    btn('저장', { cls: 'sm', icon: 'save', title: '현재 스택과 파라미터를 이름 붙여 저장', onclick: () => saveSetDialog() }));
  const tools = h('div', { class: 'ptools' },
    h('div', { class: 'search', html: icon('search') }, h('input', { type: 'text', id: 'pSearch', placeholder: '파라미터 검색', value: pFilter, 'aria-label': '파라미터 검색',
      oninput: (e) => { pFilter = e.target.value.toLowerCase(); renderParams(); document.getElementById('pSearch').focus(); } })),
    h('button', { class: 'btn sm' + (pChangedOnly ? ' primary' : ''), onclick: () => { pChangedOnly = !pChangedOnly; renderParams(); } }, '변경만'));
  const groups = S.schema.groups.map((g) => {
    const ps = S.schema.params.filter((p) => p.group === g.id &&
      (!pFilter || (p.label + p.path + p.id).toLowerCase().includes(pFilter)) && (!pChangedOnly || p.id in S.sel.values));
    if (!ps.length) return null;
    const changed = ps.filter((p) => p.id in S.sel.values).length;
    const open = persist('pg.' + g.id);
    const d = h('details', { class: 'pgroup', open: open === null || open === undefined ? g.id === 'speed' || g.id === 'costmap' || !!pFilter : open || !!pFilter },
      h('summary', {}, g.label, h('span', { class: 'cnt', text: changed ? `${changed}개 변경 · ${ps.length}` : `${ps.length}` })), ...ps.map(paramRow));
    d.addEventListener('toggle', () => persist('pg.' + g.id, d.open));
    return d;
  }).filter(Boolean);
  const warn = (S.schema.warnings || []).length ? h('div', { class: 'warnbox' }, ...S.schema.warnings.map((w) => h('div', { text: w }))) : '';
  tab.replaceChildren(setbar, tools, warn, ...groups,
    h('div', { class: 'sec' }, h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      btn('YAML 미리보기', { cls: 'sm', icon: 'code', onclick: previewYaml }),
      btn('고급 오버라이드', { cls: 'sm' + ((S.sel.raw || '').trim() ? ' primary' : ''), icon: 'edit', onclick: editRaw }),
      btn('모두 초기화', { cls: 'sm ghost', icon: 'undo', disabled: !nChanged, onclick: () => { S.sel.values = {}; S.sel.raw = ''; S.sel.preset = null; saveSel(); renderParams(); emit('sel'); } }))),
    h('div', { class: 'hint', text: '값을 바꾸면 상단 버튼이 ‘변경 적용’ 으로 바뀝니다. Nav2 를 다시 띄워 적용합니다 (약 5초).' }));
}

function paramRow(p) {
  const has = p.id in S.sel.values;
  const val = has ? S.sel.values[p.id] : p.default;
  const set = (v) => {
    if (v === '' || v === null || Number.isNaN(+v)) return;
    v = p.type === 'int' ? Math.round(+v) : +v;
    const values = { ...S.sel.values };
    if (Math.abs(v - p.default) < 1e-9) delete values[p.id]; else values[p.id] = v;
    S.sel.values = values;
    saveSel(); emit('sel');
    row.classList.toggle('changed', p.id in S.sel.values);
    num.value = v; rng.value = v;
    const c = $('paramCount'); const n = Object.keys(activeValues()).length; c.hidden = !n; c.textContent = n;
    const lab = cfgLabel(S.active);
    const sb = document.querySelector('.setbar .t b');
    if (sb) sb.textContent = lab.name + (lab.modified ? ' (수정됨)' : '');
  };
  const lo = Math.min(p.min, val), hi = Math.max(p.max, val);
  const rng = h('input', { type: 'range', min: lo, max: hi, step: p.step, value: val, 'aria-label': p.label, oninput: (e) => set(e.target.value) });
  const num = h('input', { type: 'number', min: lo, max: hi, step: p.step, value: val, 'aria-label': p.label + ' 값', onchange: (e) => set(e.target.value) });
  const row = h('div', { class: 'prow' + (has ? ' changed' : '') },
    h('div', { class: 'top' }, h('label', { text: p.label }), h('span', { class: 'unit', text: `${p.unit || ''}${p.unit ? ' · ' : ''}기본 ${p.default}` })),
    h('div', { class: 'ctl' }, rng, num, h('button', { class: 'reset', title: '기본값으로', 'aria-label': '기본값으로', html: icon('undo'), onclick: () => set(p.default) })),
    p.help ? h('div', { class: 'help', text: p.help }) : '',
    h('div', { class: 'path', text: `${p.node}: ${p.path}` }));
  return row;
}

async function previewYaml() {
  try {
    const r = await api.post('/api/params/preview', { robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: S.sel.stack, values: activeValues(), raw_overrides: S.sel.raw || '' });
    const tabs = h('div', { class: 'seg' });
    const pre = h('pre', { class: 'code' });
    const show = (k) => { for (const b of tabs.children) b.setAttribute('aria-selected', String(b.dataset.k === k)); pre.innerHTML = k === 'diff' ? diffHtml(r.diff || '(운영 기본값과 같습니다)') : r.yaml.replace(/&/g, '&amp;').replace(/</g, '&lt;'); };
    tabs.append(h('button', { 'data-k': 'diff', onclick: () => show('diff') }, '운영 기본값 대비 변경'), h('button', { 'data-k': 'yaml', onclick: () => show('yaml') }, '전체 Nav2 params'));
    show('diff');
    modal('Nav2 파라미터', [tabs, ...(r.warnings || []).map((w) => h('div', { class: 'warnbox', text: w })), pre], [
      btn('복사', { icon: 'copy', onclick: () => navigator.clipboard.writeText(r.yaml).then(() => toast('복사했습니다'), () => toast('복사하지 못했습니다', 'bad')) }),
      btn('YAML 저장', { cls: 'primary', icon: 'download', onclick: () => { const a = h('a', { href: URL.createObjectURL(new Blob([r.yaml], { type: 'text/yaml' })), download: `nav2_params_${S.sel.stack}.yaml` }); a.click(); } }),
    ]);
  } catch (e) { toast(e.message, 'bad'); }
}

function editRaw() {
  const ta = h('textarea', { rows: 14, id: 'rawOv', spellcheck: 'false', placeholder: 'controller_server:\n  FollowPath.max_vel_x: 0.3\nlocal_costmap:\n  inflation_layer.inflation_radius: 0.5' });
  ta.value = S.sel.raw || '';
  const close = modal('고급 오버라이드 (YAML)', [
    h('div', { class: 'hint', text: '목록에 없는 파라미터를 바꿀 때 씁니다. {노드: {ros__parameters 아래 점 경로: 값}} 형식. 노드 이름 뒤에 ! 를 붙이면 하위 트리를 통째로 바꿉니다.' }), ta,
  ], [btn('취소', { onclick: () => close() }), btn('저장', { cls: 'primary', onclick: () => { S.sel.raw = ta.value; saveSel(); close(); renderParams(); emit('sel'); } })]);
}

// ================================================================== telemetry: one session, or a comparison of the slots
export function renderTelemetry() {
  const box = $('telemetry');
  if (!box.firstChild) {
    box.append(
      h('div', { class: 'tele single' },
        h('div', { class: 'navstate', id: 'tNav' }),
        h('div', { class: 'sec' }, h('h3', { text: '속도' }), sparkBox('v', '선속도', 'm/s'), sparkBox('w', '각속도', 'rad/s')),
        h('div', { class: 'sec' }, h('h3', { text: '안전' }), sparkBox('c', '장애물 이격', 'm'), h('dl', { class: 'kv', id: 'tSafe' })),
        h('div', { class: 'sec' }, h('h3', { text: '이번 주행' }), h('dl', { class: 'kv', id: 'tRun' })),
        h('div', { class: 'sec', id: 'tWarn' })),
      h('div', { class: 'tele compare', hidden: true },
        h('div', { class: 'sec' }, h('h3', { text: '슬롯' }), h('div', { class: 'slotrows', id: 'cRows' })),
        h('div', { class: 'sec' }, h('h3', { text: '선속도 (m/s)' }), h('canvas', { class: 'spark tall', id: 'cmp_v' })),
        h('div', { class: 'sec' }, h('h3', { text: '장애물 이격 (m)' }), h('canvas', { class: 'spark tall', id: 'cmp_c' })),
        h('div', { class: 'sec' }, h('h3', { text: '이번 주행 비교' }), h('table', { class: 'cmp', id: 'cTable' }),
          h('div', { class: 'hint', text: '모든 슬롯이 도착하면 항목마다 가장 좋은 값을 굵게 표시합니다. 한 번의 주행이라 우연이 섞입니다. 확실히 비교하려면 벤치마크를 돌리세요.' }),
          btn('이 설정들로 벤치마크', { cls: 'sm', icon: 'chart', onclick: toBenchmark }))),
      h('div', { class: 'tele' }, h('div', { class: 'sec' }, h('h3', {}, 'Nav2 메시지', btn('실행 로그', { cls: 'sm ghost act', onclick: () => showStackLog() })), h('div', { class: 'loglist', id: 'tLogs' }))));
  }
  const multi = S.nSlots > 1;
  box.querySelector('.tele.single').hidden = multi;
  box.querySelector('.tele.compare').hidden = !multi;
  if (multi) renderCompare(); else renderSingle();
}

function shownMetrics(sl) {
  if (sl.result) return sl.result;
  const ns = (sl.nav || {}).status;
  return liveOnMap(sl.idx) && sl.sim && ns && ns !== 'idle' ? (sl.sim.metrics || {}) : {};
}

function renderSingle() {
  const sl = S.slots[S.active];
  const nav = sl.nav || { status: 'idle' };
  const sim = liveOnMap(S.active) ? sl.sim : null;
  const m = shownMetrics(sl);
  const ns = $('tNav');
  ns.dataset.s = nav.status;
  ns.replaceChildren(
    h('div', { class: 'row1' }, h('span', { class: 'big', text: NAV_LABEL[nav.status] || nav.status }),
      h('span', { class: 'num muted', text: nav.status === 'navigating' ? fmt.t(nav.nav_time) : '' })),
    h('dl', { class: 'kv' },
      h('dt', { text: '남은 거리' }), h('dd', { text: nav.distance_remaining !== null && nav.distance_remaining !== undefined ? `${fmt.n(nav.distance_remaining)} m` : '–' }),
      h('dt', { text: '복구 동작' }), h('dd', { class: nav.recoveries > 3 ? 'warn' : '', text: nav.recoveries ?? 0 })));
  const sp = sparks[S.active];
  drawSpark('v', sp, sim ? fmt.n(sp.v[sp.v.length - 1]) : '–');
  drawSpark('w', sp, sim ? fmt.n(sp.w[sp.w.length - 1]) : '–');
  drawSpark('c', sp, sim ? fmt.n(sim.clear) : '–');
  $('tSafe').replaceChildren(
    h('dt', { text: '충돌' }), h('dd', { class: m.collisions ? 'bad' : '', text: m.collisions ?? '–' }),
    h('dt', { text: '최소 이격' }), h('dd', { class: m.min_clear < 0.05 ? 'warn' : '', text: m.min_clear !== undefined ? `${fmt.n(m.min_clear * 100, 1)} cm` : '–' }),
    h('dt', { text: '근접(5cm) 시간' }), h('dd', { text: m.near_time !== undefined ? `${fmt.n(m.near_time, 1)} s` : '–' }));
  $('tRun').replaceChildren(
    h('dt', { text: '시간' }), h('dd', { text: m.duration !== undefined ? fmt.t(m.duration) : '–' }),
    h('dt', { text: '주행 거리' }), h('dd', { text: m.path_len !== undefined ? `${fmt.n(m.path_len)} m` : '–' }),
    h('dt', { text: '최고 속도' }), h('dd', { text: m.max_v !== undefined ? `${fmt.n(m.max_v)} m/s` : '–' }));
  const w = $('tWarn');
  w.replaceChildren(...(sl.warnings.length ? [h('h3', { text: '설정 경고' }), h('div', { class: 'warnbox' }, ...sl.warnings.map((x) => h('div', { text: x })))] : []));
}

const CMP_ROWS = [
  ['시간', (m) => m.duration, (v) => fmt.t(v), 'min'],
  ['주행 거리', (m) => m.path_len, (v) => `${fmt.n(v)} m`, 'min'],
  ['평균 속도', (m) => (m.duration > 0 && m.path_len !== undefined ? m.path_len / m.duration : undefined), (v) => `${fmt.n(v)} m/s`, 'max'],
  ['최고 속도', (m) => m.max_v, (v) => `${fmt.n(v)} m/s`, null],
  ['최소 이격', (m) => m.min_clear, (v) => `${fmt.n(v * 100, 1)} cm`, 'max'],
  ['근접(5cm) 시간', (m) => m.near_time, (v) => `${fmt.n(v, 1)} s`, 'min'],
  ['충돌', (m) => m.collisions, (v) => String(v), 'min'],
  ['복구 동작', (m, sl) => (sl.result ? sl.result.recoveries : (sl.nav || {}).recoveries), (v) => String(v ?? 0), 'min'],
];

function renderCompare() {
  const slots = visibleSlots();
  $('cRows').replaceChildren(...slots.map((sl) => {
    const nav = sl.nav || {};
    const st = sl.stack.status;
    const lab = cfgLabel(sl.idx);
    const navTxt = st !== 'ready' ? STACK_LABEL[st] : (NAV_LABEL[nav.status] || '대기');
    return h('button', { class: 'slotrow' + (sl.idx === S.active ? ' active' : ''), style: { '--slot': slotColor(sl.idx) }, onclick: () => setActive(sl.idx) },
      h('b', { class: 'slotbadge', text: SLOT_NAMES[sl.idx] }),
      h('span', { class: 'nm', text: lab.name + (lab.modified ? ' *' : '') }),
      h('span', { class: 'ns', 'data-s': st === 'ready' ? nav.status : st, text: navTxt }),
      h('span', { class: 'num', text: nav.status === 'navigating' ? `${fmt.n(nav.distance_remaining, 1)} m 남음` : (sl.result && sl.result.duration !== undefined ? fmt.t(sl.result.duration) : '') }));
  }));
  drawMulti('cmp_v', 'v', slots);
  drawMulti('cmp_c', 'c', slots);
  const ms = slots.map((sl) => shownMetrics(sl));
  const finished = slots.filter((sl) => sl.result && sl.result.status === 'succeeded');
  const head = h('tr', {}, h('th'), ...slots.map((sl) => h('th', { style: { color: slotColor(sl.idx) }, text: SLOT_NAMES[sl.idx] })));
  const statusRow = h('tr', {}, h('td', { text: '결과' }), ...slots.map((sl) => {
    const s = sl.result ? sl.result.status : (sl.nav || {}).status;
    return h('td', { class: s === 'succeeded' ? 'good' : s === 'aborted' ? 'bad' : '', text: sl.stack.status !== 'ready' ? '–' : (NAV_LABEL[s] || '–') });
  }));
  const rows = CMP_ROWS.map(([label, get, show, better]) => {
    const vals = slots.map((sl, k) => get(ms[k], sl));
    let best = null;
    if (better && finished.length >= 2) {
      const cand = slots.map((sl, k) => (sl.result && sl.result.status === 'succeeded' && vals[k] !== undefined ? vals[k] : null)).filter((v) => v !== null);
      if (cand.length >= 2 && new Set(cand.map((v) => v.toFixed(3))).size > 1) best = better === 'min' ? Math.min(...cand) : Math.max(...cand);
    }
    return h('tr', {}, h('td', { text: label }), ...vals.map((v, k) => h('td', {
      class: best !== null && v !== undefined && slots[k].result && slots[k].result.status === 'succeeded' && Math.abs(v - best) < 1e-9 ? 'best' : '',
      text: v === undefined || v === null || Number.isNaN(v) ? '–' : show(v) })));
  });
  $('cTable').replaceChildren(head, statusRow, ...rows);
}

function toBenchmark() {
  import('./bench.js').then((m) => {
    emit('goto', 'bench');
    setTimeout(() => m.newRun({ name: `동시 실행 비교 ${new Date().toLocaleDateString()}`, workers: 4, configs: m.slotConfigs(),
      episodes: { source: 'bundled', maps: [S.sel.map], categories: ['nominal', 'unmapped', 'dynamic'], per_map: 6, seed: 1 } }), 0);
  });
}

function sparkBox(k, label, unit) {
  return h('div', { class: 'sparkwrap' }, h('div', { class: 'lbl' }, h('span', { text: `${label} (${unit})` }), h('b', { id: 'sv_' + k, text: '–' })),
    h('canvas', { class: 'spark', id: 'sp_' + k }));
}

function sizeCanvas(c) {
  const r = c.getBoundingClientRect(), dpr = devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, r.width, r.height);
  return [g, r];
}

function drawSpark(k, sp, txt) {
  const c = document.getElementById('sp_' + k);
  if (!c || !c.offsetParent) return;
  document.getElementById('sv_' + k).textContent = txt;
  const [g, r] = sizeCanvas(c);
  const d = sp[k];
  if (d.length < 2) return;
  const lo = Math.min(0, ...d), hi = Math.max(0.05, ...d);
  const y = (v) => r.height - 4 - (v - lo) / (hi - lo) * (r.height - 8);
  g.strokeStyle = cssVar('--line'); g.lineWidth = 1; g.beginPath(); g.moveTo(0, y(0)); g.lineTo(r.width, y(0)); g.stroke();
  const col = cssVar(k === 'c' ? '--good' : k === 'w' ? '--lplan' : '--accent');
  g.beginPath();
  d.forEach((v, i) => { const x = (i / 299) * r.width; i ? g.lineTo(x, y(v)) : g.moveTo(x, y(v)); });
  g.strokeStyle = col; g.lineWidth = 1.6; g.stroke();
  g.lineTo(((d.length - 1) / 299) * r.width, y(lo)); g.lineTo(0, y(lo)); g.closePath();
  g.globalAlpha = 0.12; g.fillStyle = col; g.fill(); g.globalAlpha = 1;
  const lx = ((d.length - 1) / 299) * r.width;
  g.fillStyle = col; g.beginPath(); g.arc(lx, y(d[d.length - 1]), 2.5, 0, Math.PI * 2); g.fill();
}

function drawMulti(id, k, slots) {
  const c = document.getElementById(id);
  if (!c || !c.offsetParent) return;
  const [g, r] = sizeCanvas(c);
  const series = slots.map((sl) => [sparks[sl.idx][k], slotColor(sl.idx)]).filter(([d]) => d.length > 1);
  if (!series.length) return;
  const all = series.flatMap(([d]) => d);
  const lo = Math.min(0, ...all), hi = Math.max(0.05, ...all);
  const y = (v) => r.height - 4 - (v - lo) / (hi - lo) * (r.height - 8);
  g.strokeStyle = cssVar('--line'); g.lineWidth = 1; g.beginPath(); g.moveTo(0, y(0)); g.lineTo(r.width, y(0)); g.stroke();
  for (const [d, col] of series) {
    g.beginPath();
    d.forEach((v, i) => { const x = (i / 299) * r.width; i ? g.lineTo(x, y(v)) : g.moveTo(x, y(v)); });
    g.strokeStyle = col; g.lineWidth = 1.6; g.stroke();
    g.fillStyle = col; g.beginPath(); g.arc(((d.length - 1) / 299) * r.width, y(d[d.length - 1]), 2.5, 0, Math.PI * 2); g.fill();
  }
}

function renderLogs() {
  const box = document.getElementById('tLogs');
  if (!box) return;
  const items = logs.filter((l) => l.slot < S.nSlots).slice(-60).reverse();
  box.replaceChildren(...items.map((l) => h('div', { class: 'logitem ' + l.level },
    h('div', { class: 'h' }, S.nSlots > 1 ? h('b', { class: 'slotbadge sm', style: { background: slotColor(l.slot) }, text: SLOT_NAMES[l.slot] }) : '',
      h('b', { text: l.level }), h('span', { text: l.node }), h('span', { text: new Date(l.t * 1000).toLocaleTimeString() })),
    h('div', { text: l.msg }))));
}
