// Nav Studio bootstrap: catalog, top bar, workspaces, live connection.
import { api, Live } from './api.js';
import { S, on, emit, isDirty, isDirtySlot, visibleSlots, mapName, stackOf } from './state.js';
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
  for (const sl of S.slots) {
    if (!stacks.find((s) => s.id === sl.cfg.stack)) sl.cfg.stack = 'prod';
    if (sl.cfg.preset && !presets.find((p) => p.id === sl.cfg.preset)) sl.cfg.preset = null;
  }
  $('appVersion').textContent = 'v' + info.version;
}

// overall state of the visible slots: stopped | starting | ready | partial | error
function topState() {
  const vis = visibleSlots();
  const n = (st) => vis.filter((s) => s.stack.status === st).length;
  if (vis.length === 1) return { st: vis[0].stack.status, ready: n('ready'), total: 1, starting: n('starting'), error: n('error') };
  const st = n('starting') ? 'starting' : n('error') ? 'error' : n('ready') === vis.length ? 'ready' : n('ready') ? 'partial' : 'stopped';
  return { st, ready: n('ready'), total: vis.length, starting: n('starting'), error: n('error') };
}

function renderTop() {
  const multi = S.nSlots > 1;
  const t = topState();
  const pill = $('stackPill');
  pill.dataset.state = t.st === 'partial' ? 'ready' : t.st;
  pill.querySelector('b').textContent = !multi ? ({ stopped: '정지됨', starting: '시작 중', ready: '실행 중', error: '오류' }[t.st] || t.st)
    : { stopped: '정지됨', starting: `시작 중 ${t.ready}/${t.total}`, ready: `${t.total}개 실행 중`, partial: `${t.ready}/${t.total} 실행 중`, error: `오류 ${t.error}개` }[t.st];
  pill.title = multi ? visibleSlots().map((s) => `${'ABCD'[s.idx]}: ${s.stack.message || s.stack.status}`).join('\n') : (S.stack.message || '');
  const b = $('btnStart');
  const dirty = multi ? visibleSlots().some((s) => isDirtySlot(s.idx)) : isDirty();
  b.disabled = t.st === 'starting';
  let html;
  if (t.st === 'starting') html = '<span class="spin"></span><span>시작 중</span>';
  else if (multi) html = t.ready < t.total ? icon('play') + '<span>모두 시작</span>' : dirty ? icon('restart') + '<span>변경 적용 (재시작)</span>' : icon('restart') + '<span>모두 재시작</span>';
  else if ((t.st === 'ready' || t.st === 'error') && dirty) html = icon('restart') + '<span>변경 적용 (재시작)</span>';
  else if (t.st === 'ready') html = icon('restart') + '<span>재시작</span>';
  else html = icon('play') + '<span>시뮬레이션 시작</span>';
  // replace only on change: re-rendering between mousedown and mouseup would swallow the click
  if (b.dataset.html !== html) { b.innerHTML = html; b.dataset.html = html; }
  b.classList.toggle('primary', t.st !== 'ready' || dirty);
  b.title = multi ? '꺼져 있거나 설정이 바뀐 슬롯을 시작합니다 (모두 실행 중이면 모두 재시작)' : '';
  $('btnStop').hidden = S.slots.every((s) => s.stack.status === 'stopped');
  $('btnStop').title = multi ? '모든 슬롯 끄기' : '시뮬레이션 종료';
  const robotName = S.sel.robot ? S.sel.robot.name : ((S.robots.find((r) => r.id === S.sel.robotId) || {}).name || S.sel.robotId);
  const stack = stackOf(S.sel.stack);
  const nv = Object.keys(S.sel.values).length + ((S.sel.raw || '').trim() ? 1 : 0);
  const sig = JSON.stringify([S.sel.map, robotName, S.sel.stack, nv, S.nSlots, S.maps.length]);
  if ($('sessionChips').dataset.sig === sig) return;
  $('sessionChips').dataset.sig = sig;
  $('sessionChips').replaceChildren(
    h('span', { class: 'chip' }, '맵 ', h('b', { text: mapName(S.sel.map) })),
    h('span', { class: 'chip' }, '로봇 ', h('b', { text: robotName })),
    multi ? h('span', { class: 'chip' }, '동시 실행 ', h('b', { text: `${S.nSlots}개` }))
      : h('span', { class: 'chip', title: stack ? stack.name : '' }, '스택 ', h('b', { text: stack ? stack.name.replace(/\s*\(.*\)/, '') : S.sel.stack }), nv ? ` · 변경 ${nv}` : ''));
}

function showWorkspace(ws) {
  for (const b of document.querySelectorAll('.ws-tabs button')) b.setAttribute('aria-selected', String(b.dataset.ws === ws));
  for (const m of document.querySelectorAll('main.ws')) m.hidden = m.id !== 'ws-' + ws;
  persist('ws', ws);
  history.replaceState(null, '', '#' + ws);
  const mod = workspaces[ws];
  if (mod && mod.show) mod.show();
  if (ws === 'sim') sim.resizeViews();
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
    setInterval(() => { pre.textContent = JSON.stringify({ applied: S.applied, map: S.sel.map, status: S.stack.status, nSlots: S.nSlots, active: S.active,
      slots: S.slots.slice(0, S.nSlots).map((s) => ({ status: s.stack.status, nav: s.nav && s.nav.status, applied: s.applied !== null, result: s.result && s.result.status })),
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
      const running = sim.adoptServer(m.slots, m.scene);
      await sim.selectRobot(S.sel.robotId, S.sel.robot);
      await sim.selectMap(S.sel.map, { keepScene: running });
      emit('catalog');
      renderTop();
    },
    tick: (m) => { sim.onTick(m); emit('tick', m); },
    plan: (m) => emit('plan', m),
    costmap: (m) => emit('costmap', m),
    log: (m) => emit('log', m),
    reset: (m) => emit('reset', m),
    disconnected: () => { for (const s of S.slots) if (s.stack.status !== 'stopped') s.stack = { status: 'error', message: '서버 연결이 끊겼습니다. 다시 연결 중…' }; renderTop(); },
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
