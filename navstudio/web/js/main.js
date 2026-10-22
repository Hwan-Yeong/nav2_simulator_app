// Nav Studio bootstrap: catalog, top bar, workspaces, live connection.
import { api, Live } from './api.js';
import { S, on, emit, selKey, isDirty, mapName, stackOf } from './state.js';
import { h, icon, toast, initTheme, persist } from './ui.js';
import * as sim from './sim.js';

const $ = (id) => document.getElementById(id);
const workspaces = {};

async function loadCatalog() {
  const [info, maps, robots, stacks, presets] = await Promise.all([
    api.get('/api/info'), api.get('/api/maps'), api.get('/api/robots'), api.get('/api/stacks'), api.get('/api/presets')]);
  Object.assign(S, { info, maps, robots, stacks, presets });
  if (!maps.find((m) => m.id === S.sel.map)) S.sel.map = maps[0].id;
  if (!robots.find((r) => r.id === S.sel.robotId)) S.sel.robotId = 'everybot';
  if (!stacks.find((s) => s.id === S.sel.stack)) S.sel.stack = 'prod';
}

function renderTop() {
  const st = S.stack.status;
  const pill = $('stackPill');
  pill.dataset.state = st;
  pill.querySelector('b').textContent = { stopped: '정지됨', starting: '시작 중', ready: '실행 중', error: '오류' }[st] || st;
  pill.title = S.stack.message || '';
  const b = $('btnStart');
  const dirty = isDirty();
  b.disabled = st === 'starting';
  let html;
  if (st === 'starting') html = '<span class="spin"></span><span>시작 중</span>';
  else if ((st === 'ready' || st === 'error') && dirty) html = icon('restart') + '<span>변경 적용 (재시작)</span>';
  else if (st === 'ready') html = icon('restart') + '<span>재시작</span>';
  else html = icon('play') + '<span>시뮬레이션 시작</span>';
  // replace only on change: re-rendering between mousedown and mouseup would swallow the click
  if (b.dataset.html !== html) { b.innerHTML = html; b.dataset.html = html; }
  b.classList.toggle('primary', st !== 'ready' || dirty);
  $('btnStop').hidden = st === 'stopped';
  const robotName = S.sel.robot ? S.sel.robot.name : ((S.robots.find((r) => r.id === S.sel.robotId) || {}).name || S.sel.robotId);
  const stack = stackOf(S.sel.stack);
  const nv = Object.keys(S.sel.values).length + ((S.sel.raw || '').trim() ? 1 : 0);
  $('sessionChips').replaceChildren(
    h('span', { class: 'chip' }, '맵 ', h('b', { text: mapName(S.sel.map) })),
    h('span', { class: 'chip' }, '로봇 ', h('b', { text: robotName })),
    h('span', { class: 'chip', title: stack ? stack.name : '' }, '스택 ', h('b', { text: stack ? stack.name.replace(/\s*\(.*\)/, '') : S.sel.stack }), nv ? ` · 변경 ${nv}` : ''));
}

function showWorkspace(ws) {
  for (const b of document.querySelectorAll('.ws-tabs button')) b.setAttribute('aria-selected', String(b.dataset.ws === ws));
  for (const m of document.querySelectorAll('main.ws')) m.hidden = m.id !== 'ws-' + ws;
  persist('ws', ws);
  history.replaceState(null, '', '#' + ws);
  const mod = workspaces[ws];
  if (mod && mod.show) mod.show();
  if (ws === 'sim') sim.viewport().resize();
}

async function main() {
  initTheme($('btnTheme'), () => emit('theme'));
  $('btnStop').innerHTML = icon('stop');
  $('modalClose').innerHTML = icon('x');
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('modal').hidden = true; });
  $('btnStop').onclick = async () => { await sim.stopSession(); };
  $('btnStart').onclick = () => sim.startSession();
  document.querySelector('.ws-tabs').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) showWorkspace(b.dataset.ws); });
  on('goto', showWorkspace);
  on('sel', renderTop);
  on('stack', renderTop);

  try { await loadCatalog(); } catch (e) { toast('서버에 연결하지 못했습니다: ' + e.message, 'bad'); return; }
  const vp = sim.initSim();
  if (location.search.includes('debug')) {   // test hook: expose viewport state in the DOM
    window.__vp = vp; window.__S = S;
    const pre = h('pre', { id: 'nsdebug', hidden: true });
    document.body.append(pre);
    setInterval(() => { pre.textContent = JSON.stringify({ applied: S.applied, map: S.sel.map, status: S.stack.status,
      costmaps: Object.fromEntries(Object.entries(vp.costmaps).map(([k, c]) => [k, c ? { w: c.w, h: c.h, canvas: !!c.canvas } : null])),
      live: !!vp.live, mapLoaded: !!vp.map, layers: vp.layers, nav: S.nav && S.nav.status, metrics: S.sim && S.sim.metrics,
      err: window.__err || null }); }, 500);
    window.addEventListener('error', (e) => { window.__err = String(e.message); });
    window.addEventListener('unhandledrejection', (e) => { window.__err = String(e.reason && e.reason.message || e.reason); });
  }

  let first = true;
  new Live({
    hello: async (m) => {
      if (!first) return;
      first = false;
      if (m.config) sim.adoptServerConfig(m.config, m.scene);
      await sim.selectRobot(S.sel.robotId, S.sel.robot);
      await sim.selectMap(S.sel.map, { keepScene: !!m.config });
      emit('catalog');
      renderTop();
    },
    tick: (m) => {
      const prev = S.stack.status;
      S.stack = S.pendingStart ? { status: 'starting', message: 'Nav2 시작 중' } : m.stack;
      S.nav = m.nav;
      if (prev !== m.stack.status) {
        if (S.stack.status === 'ready') toast('시뮬레이션이 준비되었습니다. 목표 도구로 목적지를 찍으세요.', 'good');
        if (S.stack.status === 'stopped' && S.applied !== null && prev === 'ready') S.applied = null;
        emit('stack'); sim.renderRunbar();
      }
      const ns = m.nav && m.nav.status;
      if (ns !== (S._lastNav || null)) { S._lastNav = ns; sim.renderRunbar();
        if (ns === 'succeeded') toast('목표에 도착했습니다', 'good');
        if (ns === 'aborted') toast('Nav2 가 주행을 중단했습니다 (Nav2 메시지 확인)', 'bad'); }
      emit('tick', m);
    },
    plan: (m) => emit('plan', m),
    costmap: (m) => emit('costmap', m),
    log: (m) => emit('log', m),
    reset: () => emit('reset'),
    disconnected: () => { S.stack = { status: 'error', message: '서버 연결이 끊겼습니다. 다시 연결 중…' }; renderTop(); },
  });

  // other workspaces load lazily
  const lazy = { robot: './robot.js', bench: './bench.js', tune: './tune.js' };
  for (const [ws, path] of Object.entries(lazy)) {
    workspaces[ws] = { show: async () => { const mod = await import(path); workspaces[ws] = mod; mod.show(); } };
  }
  const fromHash = location.hash.slice(1);
  showWorkspace(['sim', 'robot', 'bench', 'tune'].includes(fromHash) ? fromHash : (persist('ws') || 'sim'));
}

main();
