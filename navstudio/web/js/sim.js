// Simulation workspace: map / robot·stack / parameter panels, stage tools, run controls, telemetry.
import { api, inflate } from './api.js';
import { S, on, emit, selKey, isDirty, saveSel, mapName, stackOf } from './state.js';
import { h, icon, btn, toast, modal, fmt, debounce, persist, diffHtml, DRIVE_LABEL } from './ui.js';
import { Viewport, robotPolygon } from './viewport.js';

let vp;
const $ = (id) => document.getElementById(id);

// ================================================================== init
export function initSim() {
  vp = new Viewport($('view'), {
    editable: true,
    onStart: setStart, onGoal: setGoal, onScene: sceneEdited,
    onMouse: (x, y) => { mouse = [x, y]; },
    onFollowChange: (f) => { renderRunbar(); },
  });
  initTools();
  initLayers();
  renderRunbar();
  initLeftTabs();
  setInterval(renderReadout, 200);
  on('theme', () => vp.themeChanged());
  on('catalog', () => { renderMapTab(); renderSetupTab(); });
  on('tick', onTick);
  on('plan', (m) => { if (liveOnThisMap()) { vp.plans[m.which] = m.pts; vp.dirty = true; } });
  on('costmap', async (m) => {
    if (!liveOnThisMap()) return;
    try { vp.setCostmap(m.which, m, await inflate(m.z)); } catch (e) { window.__err = `costmap ${m.which}: ${e.message}`; console.error(e); }
  });
  on('reset', () => vp.clearLive());
  on('log', (m) => { logs.push(...m.items); if (logs.length > 300) logs.splice(0, logs.length - 300); renderLogs(); });
  return vp;
}

export const viewport = () => vp;
let mouse = null;
const logs = [];
const spark = { v: [], w: [], c: [] };

function liveOnThisMap() { return S.applied !== null && JSON.parse(S.applied).map === S.sel.map; }

// ================================================================== selection changes
export async function selectMap(id, { keepScene = false } = {}) {
  S.sel.map = id;
  saveSel();
  const meta = await api.get(`/api/maps/${id}`);
  S.mapMeta = meta;
  await vp.setMap(meta, `/api/maps/${id}/grid.png`);
  if (!keepScene) {
    const saved = persist('scene.' + id);
    S.scene = saved || { static_obs: [], dyn_obs: [], start: meta.start, goal: null };
    if (!S.scene.start) S.scene.start = meta.start;
  }
  vp.scene = S.scene;
  if (!liveOnThisMap()) vp.clearLive();
  renderMapTab(); renderScenarios(); emit('sel');
  checkStart();
}

export async function selectRobot(id, profile = null) {
  S.sel.robotId = id;
  S.sel.robot = profile;
  const p = profile ? { profile } : await api.get(`/api/robots/${id}`);
  S.robotProfile = p.profile;
  vp.robot = p.profile; vp.dirty = true;
  const st = stackOf(S.sel.stack);
  if (st && !st.drives.includes(S.robotProfile.drive)) {
    const alt = S.stacks.find((s) => s.drives.includes(S.robotProfile.drive));
    if (alt) { S.sel.stack = alt.id; toast(`${DRIVE_LABEL[S.robotProfile.drive]} 로봇이라 스택을 '${alt.name}' 으로 바꿨습니다`); }
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
    vp.startBad = !r.ok; vp.dirty = true;
    if (!r.ok) toast(`출발점에서 로봇이 벽과 겹칩니다 (${(r.clearance * 100).toFixed(0)} cm). 출발점 도구로 넓은 곳을 고르세요.`, 'bad');
  } catch (e) { /* map not loaded yet */ }
}

function activeValues() {
  const ids = new Set((S.schema ? S.schema.params : []).map((p) => p.id));
  return Object.fromEntries(Object.entries(S.sel.values).filter(([k]) => ids.has(k)));
}

// ================================================================== session control
export async function startSession() {
  const body = { map: S.sel.map, robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: S.sel.stack,
    values: activeValues(), raw_overrides: S.sel.raw || '', start: S.scene.start };
  try {
    S.stack = { status: 'starting', message: 'Nav2 시작 중' };
    S.pendingStart = true;
    emit('stack');
    const r = await api.post('/api/session/start', body).finally(() => { S.pendingStart = false; });
    S.applied = selKey();
    S.warnings = r.warnings || [];
    vp.clearLive();
    await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, start: S.scene.start, goal: S.scene.goal, map: S.sel.map });
    for (const w of S.warnings) toast(w);
    renderTelemetry(); emit('sel');
  } catch (e) { toast(e.message, 'bad'); S.stack = { status: 'error', message: e.message }; emit('stack'); }
}

export async function stopSession() {
  await api.post('/api/session/stop');
  S.applied = null;
  vp.clearLive();
  emit('sel');
}

export function adoptServerConfig(cfg, scene) {
  // a session is already running on the server: show its configuration
  S.sel = Object.assign(S.sel, { map: cfg.map, robotId: cfg.robot_id || S.sel.robotId, robot: cfg.robot_id ? null : cfg.robot,
    stack: cfg.stack, values: cfg.values || {}, raw: cfg.raw_overrides || '' });
  saveSel();
  S.applied = selKey();
  if (scene && scene.map === cfg.map) S.scene = { static_obs: scene.static_obs || [], dyn_obs: scene.dyn_obs || [], start: scene.start, goal: scene.goal };
}

// ================================================================== scene editing
const pushScene = debounce(async () => {
  persist('scene.' + S.sel.map, S.scene);
  if (liveOnThisMap() && S.stack.status === 'ready') {
    try { await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, map: S.sel.map }); } catch (e) { toast(e.message, 'bad'); }
  }
}, 250);

function sceneEdited() { pushScene(); }

async function setStart(pose) {
  S.scene.start = pose;
  persist('scene.' + S.sel.map, S.scene);
  vp.resetTrail();
  checkStart();
  if (liveOnThisMap() && S.stack.status === 'ready') {
    try { await api.post('/api/sim/teleport', { pose }); } catch (e) { toast(e.message, 'bad'); }
  }
  vp.dirty = true;
}

async function setGoal(pose) {
  S.scene.goal = pose;
  persist('scene.' + S.sel.map, S.scene);
  vp.dirty = true;
  if (liveOnThisMap() && S.stack.status === 'ready') await go();
  else toast('목표를 정했습니다. 시뮬레이션을 시작한 뒤 ‘주행’ 을 누르세요.');
}

async function go() {
  if (!S.scene.goal) { toast('먼저 목표 도구로 목표 지점을 찍으세요'); return; }
  try { vp.resetTrail(); await api.post('/api/nav/goal', { pose: S.scene.goal }); } catch (e) { toast(e.message, 'bad'); }
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
    'aria-pressed': String(vp.tool === t[0]), onclick: () => setTool(t[0]) }) : h('hr')));
  window.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select') || e.ctrlKey || e.metaKey) return;
    const k = { v: 'select', h: 'pan', s: 'start', g: 'goal', b: 'box', p: 'pole', c: 'chair', w: 'person', e: 'eraser' }[e.key.toLowerCase()];
    if (k && document.getElementById('ws-sim').hidden === false) setTool(k);
  });
}

function setTool(t) {
  vp.tool = t; vp.drag = null; vp.dirty = true;
  for (const b of $('tools').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b.dataset.tool === t));
  const o = $('toolOpts');
  const field = (label, key, min, max, step, unit) => {
    const val = h('b', { class: 'num', text: vp.toolOpts[key] + unit });
    return h('label', { class: 'field' }, h('span', {}, label, ' ', val),
      h('input', { type: 'range', min, max, step, value: vp.toolOpts[key], oninput: (e) => { vp.toolOpts[key] = +e.target.value; val.textContent = e.target.value + unit; } }));
  };
  const tips = {
    start: '맵을 누른 채 끌어서 로봇 방향을 정합니다. 실행 중이면 로봇이 그 자리로 옮겨집니다.',
    goal: '맵을 누른 채 끌어서 도착 방향을 정합니다. 실행 중이면 바로 출발합니다.',
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

const LAYERS = [['global', '전역 costmap', '--plan'], ['local', '지역 costmap', '--lplan'], ['scan', '라이다', '--scan'], ['plan', '경로', '--plan'], ['trail', '궤적', '--trail'], ['grid', '격자', '--muted']];
function initLayers() {
  const saved = persist('layers') || {};
  Object.assign(vp.layers, saved);
  const box = $('layers');
  const items = LAYERS.map(([k, label, col]) => {
    const b = h('button', { 'aria-pressed': String(!!vp.layers[k]), onclick: () => { vp.layers[k] = !vp.layers[k]; b.setAttribute('aria-pressed', String(vp.layers[k])); vp.dirty = true; persist('layers', vp.layers); } },
      h('i', { class: 'sw', style: { color: `var(${col})` } }), label);
    return b;
  });
  box.replaceChildren(...items, h('span', { class: 'sep' }),
    h('button', { title: '전체 보기', 'aria-label': '전체 보기', html: icon('fit'), onclick: () => { vp.follow = false; vp.fit(); renderRunbar(); } }));
}

export function renderRunbar() {
  const ready = S.stack.status === 'ready' && liveOnThisMap();
  const nav = S.nav || {};
  const moving = nav.status === 'navigating' || nav.status === 'sending';
  const bar = $('runbar');
  bar.replaceChildren(
    btn(moving ? '다시 보내기' : '주행', { cls: 'primary', icon: 'play', disabled: !ready, onclick: go, title: '현재 목표로 주행' }),
    btn('정지', { icon: 'stop', disabled: !ready || !moving, onclick: () => api.post('/api/nav/cancel') }),
    btn('출발점으로', { icon: 'undo', disabled: !ready || !S.scene.start, onclick: () => setStart(S.scene.start) }),
    h('span', { class: 'sep', style: { width: '1px', alignSelf: 'stretch', background: 'var(--line)' } }),
    btn('', { cls: 'ghost icon-only', icon: 'follow', title: vp.follow ? '로봇 따라가기 끄기' : '로봇 따라가기', aria: '로봇 따라가기',
      onclick: () => { vp.follow = !vp.follow; renderRunbar(); } }),
    btn('', { cls: 'ghost icon-only', icon: 'trash', title: '장애물·보행자 모두 지우기', aria: '장애물 모두 지우기',
      onclick: () => { S.scene.static_obs = []; S.scene.dyn_obs = []; vp.scene = S.scene; vp.sel = null; vp.dirty = true; pushScene(); } }),
  );
  const f = bar.querySelector('[title^="로봇 따라가기"]');
  if (f) f.setAttribute('aria-pressed', String(vp.follow));
  if (f && vp.follow) f.style.color = 'var(--accent)';
}

function renderReadout() {
  const r = $('readout');
  const s = vp.view.s;
  const nice = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].find((m) => m * s >= 60) || 50;
  r.replaceChildren(
    h('span', { class: 'scalebar' }, h('i', { style: { width: `${nice * s}px` } }), `${nice} m`),
    mouse ? h('span', { text: `x ${mouse[0].toFixed(2)}  y ${mouse[1].toFixed(2)}` }) : '',
  );
  const ov = $('stageOverlay');
  const st = S.stack.status;
  if (st === 'starting') {
    ov.hidden = false;
    ov.replaceChildren(h('div', { class: 'card' }, h('div', { class: 'spin' }), h('h2', { text: 'Nav2 를 시작하고 있습니다' }), h('div', { class: 'hint', text: '시뮬레이터와 Nav2 노드 7개를 띄우는 중 (보통 5초 안팎)' })));
  } else if (st === 'error') {
    ov.hidden = false;
    ov.replaceChildren(h('div', { class: 'card' }, h('h2', { text: '시뮬레이션이 멈췄습니다' }), h('div', { class: 'errbox', text: S.stack.message }),
      h('div', { style: { display: 'flex', gap: '8px' } }, btn('로그 보기', { onclick: showStackLog }), btn('다시 시작', { cls: 'primary', icon: 'restart', onclick: startSession }))));
  } else ov.hidden = true;
}

async function showStackLog() {
  const t = await api.get('/api/session/log');
  modal('Nav2 실행 로그', h('pre', { class: 'code', text: t.split('\n').slice(-400).join('\n') || '(비어 있음)' }));
}

// ================================================================== live data
function onTick(m) {
  S.nav = m.nav;
  S.sim = m.sim;
  if (liveOnThisMap() && m.sim) vp.setLive(m.sim);
  renderTelemetry();
}

// ================================================================== left tabs
function initLeftTabs() {
  const tabs = $('leftTabs');
  const show = (t) => {
    for (const b of tabs.querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === t));
    for (const s of document.querySelectorAll('#ws-sim .tab')) s.hidden = s.dataset.tab !== t;
    persist('leftTab', t);
  };
  tabs.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) show(b.dataset.tab); });
  show(persist('leftTab') || 'map');
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
  const sec = [h('div', { class: 'sec' }, h('h3', {}, '맵', btn('맵 올리기', { cls: 'sm ghost act', icon: 'upload', onclick: uploadMap })), search)];
  for (const [g, list] of Object.entries(groups)) {
    sec.push(h('div', { class: 'sec' }, h('div', { class: 'grouplabel', text: g }),
      h('div', { class: 'mapgrid' }, ...list.map((m) => h('button', { class: 'mapcard', 'aria-pressed': String(m.id === S.sel.map), title: m.description,
        onclick: () => selectMap(m.id) },
        h('div', { class: 'thumb' }, h('img', { src: `/api/maps/${m.id}/thumb.png`, alt: '', loading: 'lazy' })),
        h('div', { class: 'meta' }, h('b', { text: m.name }), h('span', { class: 'num', text: `${m.width_m} × ${m.height_m} m` })))))));
  }
  sec.push(h('div', { class: 'sec', id: 'scenSec' }));
  tab.replaceChildren(...sec);
  renderScenarios();
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
  S.scene = { start: e.start, goal: e.goal, static_obs: JSON.parse(JSON.stringify(e.static_obs)), dyn_obs: JSON.parse(JSON.stringify(e.dyn_obs)) };
  vp.scene = S.scene; vp.sel = null; vp.dirty = true;
  persist('scene.' + S.sel.map, S.scene);
  checkStart();
  if (liveOnThisMap() && S.stack.status === 'ready') {
    await api.post('/api/scene', { static_obs: S.scene.static_obs, dyn_obs: S.scene.dyn_obs, map: S.sel.map });
    await api.post('/api/sim/teleport', { pose: S.scene.start });
    vp.resetTrail();
    toast('시나리오를 불러왔습니다. ‘주행’ 을 누르면 출발합니다.');
  } else toast('시나리오를 불러왔습니다. 시뮬레이션을 시작하세요.');
}

function uploadMap() {
  const name = h('input', { type: 'text', placeholder: '예: 3층 사무실', id: 'upName' });
  const y = h('input', { type: 'file', accept: '.yaml,.yml', id: 'upYaml' });
  const im = h('input', { type: 'file', accept: '.pgm,.png', id: 'upImg' });
  const close = modal('맵 올리기', [
    h('div', { class: 'hint', text: 'ROS map_server 형식의 YAML(resolution, origin 포함)과 이미지(PGM 또는 PNG)를 고르세요. 이 PC 의 ~/.navstudio/maps 에 저장됩니다.' }),
    h('label', { class: 'field' }, h('span', { text: '이름' }), name),
    h('label', { class: 'field' }, h('span', { text: '맵 YAML' }), y),
    h('label', { class: 'field' }, h('span', { text: '맵 이미지' }), im),
  ], [btn('취소', { onclick: () => close() }), btn('올리기', { cls: 'primary', icon: 'upload', onclick: async () => {
    if (!name.value || !y.files[0] || !im.files[0]) { toast('이름, YAML, 이미지를 모두 고르세요', 'bad'); return; }
    const fd = new FormData();
    fd.append('name', name.value); fd.append('yaml_file', y.files[0]); fd.append('image', im.files[0]);
    try {
      const r = await api.post('/api/maps', fd);
      S.maps = await api.get('/api/maps');
      close(); renderMapTab(); await selectMap(r.id);
      toast('맵을 추가했습니다', 'good');
    } catch (e) { toast(e.message, 'bad'); }
  } })]);
}

// ---------------------------------------------------------------- setup tab
function footprintIcon(profile, size = 40) {
  const c = h('canvas', { width: size * 2, height: size * 2 });
  const g = c.getContext('2d');
  const poly = robotPolygon(profile, 24);
  const R = Math.max(...poly.map((p) => Math.hypot(p[0], p[1]))) || 0.2;
  const k = (size * 0.85) / R;
  g.translate(size, size);
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--robot');
  g.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--ink');
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
  const presets = S.presets.filter((p) => !p.stacks || p.stacks.includes(S.sel.stack));
  const presetList = h('div', { class: 'optlist' },
    h('button', { class: 'opt', 'aria-pressed': String(!Object.keys(S.sel.values).length), onclick: () => { S.sel.values = {}; S.sel.preset = null; saveSel(); renderParams(); renderSetupTab(); emit('sel'); } },
      h('span', { html: icon('undo') }), h('div', { class: 't' }, h('b', { text: '스택 기본값' }), h('span', { text: '선택한 스택의 파라미터를 그대로 사용' }))),
    ...presets.map((p) => h('button', { class: 'opt', 'aria-pressed': String(S.sel.preset === p.id),
      onclick: () => { S.sel.values = { ...p.values }; S.sel.preset = p.id; saveSel(); renderParams(); renderSetupTab(); emit('sel'); toast(`'${p.name}' 값을 파라미터에 넣었습니다`); } },
    h('span', { html: icon('sliders') }), h('div', { class: 't' }, h('b', { text: p.name }), h('span', { text: p.description })))));
  tab.replaceChildren(
    h('div', { class: 'sec' }, h('h3', {}, '로봇', btn('로봇 설계', { cls: 'sm ghost act', icon: 'edit', onclick: () => emit('goto', 'robot') })), robotList),
    h('div', { class: 'sec' }, h('h3', { text: '주행 스택 (제어기 + 경로 계획기)' }), stackList),
    h('div', { class: 'sec' }, h('h3', { text: '튜닝 프리셋' }), presetList),
  );
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
  tab.replaceChildren(tools, warn, ...groups,
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
    if (Math.abs(v - p.default) < 1e-9) delete S.sel.values[p.id]; else S.sel.values[p.id] = v;
    S.sel.preset = null;
    saveSel(); emit('sel');
    row.classList.toggle('changed', p.id in S.sel.values);
    num.value = v; rng.value = v;
    const c = $('paramCount'); const n = Object.keys(activeValues()).length; c.hidden = !n; c.textContent = n;
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

// ================================================================== telemetry
const NAV_LABEL = { idle: '대기', sending: '목표 전송', navigating: '주행 중', succeeded: '도착', aborted: '실패 (중단)', canceled: '취소됨', rejected: '거부됨' };
export function renderTelemetry() {
  const box = $('telemetry');
  const nav = S.nav || { status: 'idle' };
  const sim = liveOnThisMap() ? S.sim : null;
  const m = (sim && sim.metrics) || {};
  if (sim) {
    const v = Math.hypot(sim.vel[0], sim.vel[1]) * Math.sign(sim.vel[0] || 1);
    for (const [k, x] of [['v', v], ['w', sim.vel[2]], ['c', Math.min(sim.clear, 1.5)]]) { spark[k].push(x); if (spark[k].length > 300) spark[k].shift(); }
  }
  if (!box.firstChild) {
    box.append(h('div', { class: 'tele' },
      h('div', { class: 'navstate', id: 'tNav' }),
      h('div', { class: 'sec' }, h('h3', { text: '속도' }), sparkBox('v', '선속도', 'm/s'), sparkBox('w', '각속도', 'rad/s')),
      h('div', { class: 'sec' }, h('h3', { text: '안전' }), sparkBox('c', '장애물 이격', 'm'), h('dl', { class: 'kv', id: 'tSafe' })),
      h('div', { class: 'sec' }, h('h3', { text: '이번 주행' }), h('dl', { class: 'kv', id: 'tRun' })),
      h('div', { class: 'sec', id: 'tWarn' }),
      h('div', { class: 'sec' }, h('h3', {}, 'Nav2 메시지', btn('실행 로그', { cls: 'sm ghost act', onclick: showStackLog })), h('div', { class: 'loglist', id: 'tLogs' }))));
  }
  const ns = $('tNav');
  ns.dataset.s = nav.status;
  ns.replaceChildren(
    h('div', { class: 'row1' }, h('span', { class: 'big', text: NAV_LABEL[nav.status] || nav.status }),
      h('span', { class: 'num muted', text: nav.status === 'navigating' ? fmt.t(nav.nav_time) : '' })),
    h('dl', { class: 'kv' },
      h('dt', { text: '남은 거리' }), h('dd', { text: nav.distance_remaining !== null && nav.distance_remaining !== undefined ? `${fmt.n(nav.distance_remaining)} m` : '–' }),
      h('dt', { text: '복구 동작' }), h('dd', { class: nav.recoveries > 3 ? 'warn' : '', text: nav.recoveries ?? 0 })));
  drawSpark('v', sim ? fmt.n(spark.v[spark.v.length - 1]) : '–');
  drawSpark('w', sim ? fmt.n(spark.w[spark.w.length - 1]) : '–');
  drawSpark('c', sim ? fmt.n(sim.clear) : '–');
  $('tSafe').replaceChildren(
    h('dt', { text: '충돌' }), h('dd', { class: m.collisions ? 'bad' : '', text: m.collisions ?? '–' }),
    h('dt', { text: '최소 이격' }), h('dd', { class: m.min_clear < 0.05 ? 'warn' : '', text: m.min_clear !== undefined ? `${fmt.n(m.min_clear * 100, 1)} cm` : '–' }),
    h('dt', { text: '근접(5cm) 시간' }), h('dd', { text: m.near_time !== undefined ? `${fmt.n(m.near_time, 1)} s` : '–' }));
  $('tRun').replaceChildren(
    h('dt', { text: '시간' }), h('dd', { text: m.duration !== undefined ? fmt.t(m.duration) : '–' }),
    h('dt', { text: '주행 거리' }), h('dd', { text: m.path_len !== undefined ? `${fmt.n(m.path_len)} m` : '–' }),
    h('dt', { text: '최고 속도' }), h('dd', { text: m.max_v !== undefined ? `${fmt.n(m.max_v)} m/s` : '–' }));
  const w = $('tWarn');
  w.replaceChildren(...(S.warnings.length ? [h('h3', { text: '설정 경고' }), h('div', { class: 'warnbox' }, ...S.warnings.map((x) => h('div', { text: x })))] : []));
}

function sparkBox(k, label, unit) {
  return h('div', { class: 'sparkwrap' }, h('div', { class: 'lbl' }, h('span', { text: `${label} (${unit})` }), h('b', { id: 'sv_' + k, text: '–' })),
    h('canvas', { class: 'spark', id: 'sp_' + k }));
}

function drawSpark(k, txt) {
  const c = document.getElementById('sp_' + k);
  if (!c) return;
  document.getElementById('sv_' + k).textContent = txt;
  const r = c.getBoundingClientRect(), dpr = devicePixelRatio || 1;
  if (c.width !== Math.round(r.width * dpr)) { c.width = Math.round(r.width * dpr); c.height = Math.round(r.height * dpr); }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, r.width, r.height);
  const d = spark[k];
  if (d.length < 2) return;
  const lo = Math.min(0, ...d), hi = Math.max(0.05, ...d);
  const y = (v) => r.height - 4 - (v - lo) / (hi - lo) * (r.height - 8);
  const css = getComputedStyle(document.documentElement);
  g.strokeStyle = css.getPropertyValue('--line'); g.lineWidth = 1; g.beginPath(); g.moveTo(0, y(0)); g.lineTo(r.width, y(0)); g.stroke();
  const col = css.getPropertyValue(k === 'c' ? '--good' : k === 'w' ? '--lplan' : '--accent');
  g.beginPath();
  d.forEach((v, i) => { const x = (i / 299) * r.width; i ? g.lineTo(x, y(v)) : g.moveTo(x, y(v)); });
  g.strokeStyle = col; g.lineWidth = 1.6; g.stroke();
  g.lineTo(((d.length - 1) / 299) * r.width, y(lo)); g.lineTo(0, y(lo)); g.closePath();
  g.globalAlpha = 0.12; g.fillStyle = col; g.fill(); g.globalAlpha = 1;
  const lx = ((d.length - 1) / 299) * r.width;
  g.fillStyle = col; g.beginPath(); g.arc(lx, y(d[d.length - 1]), 2.5, 0, Math.PI * 2); g.fill();
}

function renderLogs() {
  const box = document.getElementById('tLogs');
  if (!box) return;
  const items = logs.slice(-60).reverse();
  box.replaceChildren(...items.map((l) => h('div', { class: 'logitem ' + l.level },
    h('div', { class: 'h' }, h('b', { text: l.level }), h('span', { text: l.node }), h('span', { text: new Date(l.t * 1000).toLocaleTimeString() })),
    h('div', { text: l.msg }))));
}
