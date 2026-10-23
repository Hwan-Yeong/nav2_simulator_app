// Benchmark workspace: compare configurations over many scenarios, inspect and replay episodes.
import { api } from './api.js';
import { S, emit, mapName, stackOf, cfgLabel, slotRobot, slotRobotOwn, robotName, SLOT_NAMES } from './state.js';
import { h, icon, btn, toast, modal, menu, fmt, persist, DRIVE_LABEL } from './ui.js';
import { Viewport } from './viewport.js';

const $ = (id) => document.getElementById(id);
let root, left, main;
let current = null;      // open run id
let poll = null;
let draft = null;        // new-run form state
let formOpen = false;    // the new-run form is showing (survives switching workspaces)

const CATS = { nominal: '정상', unmapped: '미등록 장애물', dynamic: '보행자' };
const STATUS = { succeeded: '성공', aborted: '중단', timeout: '시간 초과', canceled: '취소', rejected: '거부', sim_timeout: '오류', stack_failed: '오류' };

export function show() {
  root = $('ws-bench');
  if (!left) {
    left = h('aside', { class: 'side left' });
    main = h('section', { class: 'page' });
    root.replaceChildren(left, main);
    draft = persist('benchDraft') || null;
  }
  renderLeft();
  if (current) openRun(current); else if (formOpen) renderForm(); else renderEmpty();
}

// ================================================================== shared pieces (also used by tune.js)
export function currentConfig(name = '현재 시뮬레이션 설정') {
  return { name, robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: S.sel.stack, values: { ...S.sel.values }, raw: S.sel.raw || '' };
}

// the configurations of the live comparison slots (simulation workspace), as benchmark configs
export function slotConfigs() {
  return S.slots.slice(0, S.nSlots).map((sl, i) => ({ name: `${SLOT_NAMES[i]} · ${cfgLabel(i).name}${slotRobotOwn(i) ? ` · ${robotName(sl.cfg.robotId)}` : ''}`,
    ...slotRobot(i), stack: sl.cfg.stack, values: { ...sl.cfg.values }, raw: sl.cfg.raw || '' }));
}

// config sets and stack defaults to pick from (menu items); pick(cfg) receives a benchmark config
export function setMenuItems(pick) {
  const robot = { robot_id: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot };
  const drive = S.robotProfile ? S.robotProfile.drive : 'diff';
  const okStack = (id) => { const st = stackOf(id); return !st || st.drives.includes(drive); };
  return [
    { heading: '설정 세트' },
    ...S.presets.map((p) => ({ label: p.name, sub: p.description, tag: p.builtin ? '기본' : '내 세트', disabled: !okStack(p.stack),
      onclick: () => pick({ name: p.name, ...robot, stack: p.stack, values: { ...p.values }, raw: p.raw || '', preset: p.id }) })),
    { heading: '스택 기본값' },
    ...S.stacks.map((st) => ({ label: st.name, sub: st.description, disabled: !okStack(st.id),
      onclick: () => pick({ name: st.name.replace(/\s*\(.*\)/, ''), ...robot, stack: st.id, values: {}, raw: '' }) })),
  ];
}

export function configLabel(c) {
  const robot = c.robot ? c.robot.name : ((S.robots.find((r) => r.id === c.robot_id) || {}).name || c.robot_id);
  const st = stackOf(c.stack);
  const n = Object.keys(c.values || {}).length + ((c.raw || '').trim() ? 1 : 0);
  return `${robot} · ${st ? st.name.replace(/\s*\(.*\)/, '') : c.stack}${n ? ` · 변경 ${n}` : ''}`;
}

export function episodeForm(spec, onchange) {
  const maps = h('div', { class: 'checklist' }, ...S.maps.map((m) => h('label', {},
    h('input', { type: 'checkbox', checked: spec.maps.includes(m.id), onchange: (e) => {
      spec.maps = e.target.checked ? [...spec.maps, m.id] : spec.maps.filter((x) => x !== m.id); onchange();
    } }), h('span', { text: m.name }), h('small', { class: 'faint', text: m.group }))));
  const src = h('div', { class: 'seg' },
    h('button', { 'aria-pressed': String(spec.source === 'bundled'), onclick: () => { spec.source = 'bundled'; onchange(true); } }, '준비된 시나리오'),
    h('button', { 'aria-pressed': String(spec.source === 'generate'), onclick: () => { spec.source = 'generate'; onchange(true); } }, '로봇 크기에 맞춰 생성'));
  const cats = h('div', { style: { display: 'flex', gap: '12px', flexWrap: 'wrap' } }, ...Object.entries(CATS).map(([k, v]) => h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center' } },
    h('input', { type: 'checkbox', checked: spec.categories.includes(k), onchange: (e) => {
      spec.categories = e.target.checked ? [...spec.categories, k] : spec.categories.filter((x) => x !== k); onchange();
    } }), v)));
  const per = h('b', { class: 'num', text: spec.per_map });
  return h('div', { class: 'sec' },
    h('h3', { text: '맵' }), maps,
    h('h3', { text: '시나리오' }), src,
    h('div', { class: 'hint', text: spec.source === 'bundled' ? '벤치마크에 썼던 고정 시나리오 (지름 0.35 m 원형 로봇 기준). 큰 로봇은 ‘생성’ 을 쓰세요.' : '선택한 로봇 크기에 맞춰 출발·목표·장애물을 새로 뽑습니다. 같은 시드면 같은 시나리오.' }),
    spec.source === 'generate' ? h('label', { class: 'field' }, h('span', { text: '시드' }), h('input', { type: 'number', value: spec.seed || 1, oninput: (e) => { spec.seed = +e.target.value; onchange(); } })) : '',
    cats,
    h('label', { class: 'field' }, h('span', {}, '맵당 에피소드 ', per), h('input', { type: 'range', min: 1, max: 22, value: spec.per_map,
      oninput: (e) => { spec.per_map = +e.target.value; per.textContent = e.target.value; onchange(); } })));
}

// ================================================================== left: history + new run form
async function renderLeft() {
  let list = [];
  try { list = await api.get('/api/runs?kind=bench'); } catch (e) { /* server busy */ }
  const hist = h('div', { class: 'optlist' }, ...list.map((r) => h('button', { class: 'opt', 'aria-pressed': String(r.id === current), onclick: () => openRun(r.id) },
    h('span', { html: icon('chart') }), h('div', { class: 't' }, h('b', { text: r.name }),
      h('span', { text: `${new Date(r.started * 1000).toLocaleString()} · ${statusLabel(r.status)}` })))));
  left.replaceChildren(h('div', { class: 'form' },
    h('div', { class: 'sec' }, h('h3', {}, '벤치마크', btn('새 벤치마크', { cls: 'sm primary act', icon: 'plus', onclick: () => newRun() })),
      list.length ? hist : h('div', { class: 'hint', text: '아직 실행한 벤치마크가 없습니다. 여러 설정을 같은 시나리오로 돌려 성공률·속도·안전 여유를 비교합니다.' }))));
}

function statusLabel(s) { return { preparing: '준비 중', running: '실행 중', done: '완료', canceled: '취소됨', error: '오류' }[s] || s; }

export function newRun(prefill) {
  current = null;
  formOpen = true;
  clearInterval(poll);
  draft = prefill || draft || {
    name: '벤치마크 ' + new Date().toLocaleDateString(), workers: 4,
    configs: [currentConfig()],
    episodes: { source: 'bundled', maps: [S.sel.map], categories: ['nominal', 'unmapped', 'dynamic'], per_map: 6, seed: 1 },
  };
  renderForm();
  renderLeft();
}

function renderForm() {
  const d = draft;
  persist('benchDraft', d);
  const sync = (rerender) => { persist('benchDraft', d); if (rerender) renderForm(); else est.textContent = estimate(); };
  const cfgList = h('div', { class: 'optlist' }, ...d.configs.map((c, i) => h('div', { class: 'opt', style: { gridTemplateColumns: '1fr auto' } },
    h('div', { class: 't' }, h('input', { type: 'text', value: c.name, 'aria-label': '설정 이름', oninput: (e) => { c.name = e.target.value; persist('benchDraft', d); } }),
      h('span', { text: configLabel(c) })),
    h('button', { class: 'reset', title: '빼기', 'aria-label': '설정 빼기', html: icon('x'), disabled: d.configs.length <= 1, onclick: () => { d.configs.splice(i, 1); sync(true); } }))));
  const addRow = h('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
    btn('현재 설정', { cls: 'sm', icon: 'plus', disabled: d.configs.length >= 4, onclick: () => { d.configs.push(currentConfig(`설정 ${d.configs.length + 1}`)); sync(true); } }),
    btn('설정 세트·스택', { cls: 'sm', icon: 'plus', disabled: d.configs.length >= 4, title: '저장한 설정 세트나 스택 기본값을 추가',
      onclick: (e) => menu(e.currentTarget, setMenuItems((c) => { if (d.configs.length < 4) { d.configs.push(c); sync(true); } })) }),
    S.nSlots > 1 ? btn(`동시 실행 슬롯 ${S.nSlots}개`, { cls: 'sm', icon: 'grid', title: '시뮬레이션 탭에서 나란히 띄운 설정들로 바꿉니다',
      onclick: () => { d.configs = slotConfigs(); sync(true); } }) : '');
  const workers = h('b', { class: 'num', text: d.workers });
  const est = h('div', { class: 'hint num', text: estimate() });
  main.replaceChildren(
    h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '새 벤치마크' })),
      h('div', { class: 'form' },
        h('label', { class: 'field' }, h('span', { text: '이름' }), h('input', { type: 'text', value: d.name, oninput: (e) => { d.name = e.target.value; persist('benchDraft', d); } })),
        h('div', { class: 'sec' }, h('h3', { text: `비교할 설정 (${d.configs.length}/4)` }), cfgList, addRow,
          h('div', { class: 'hint', text: '‘현재 설정’ 은 시뮬레이션 탭에서 고른 로봇·스택·파라미터입니다. 첫 번째 설정이 비교 기준이 됩니다.' })),
        episodeForm(d.episodes, sync),
        h('label', { class: 'field' }, h('span', {}, '동시 실행 ', workers), h('input', { type: 'range', min: 1, max: 8, value: d.workers,
          oninput: (e) => { d.workers = +e.target.value; workers.textContent = e.target.value; sync(); } })),
        h('div', { class: 'hint', text: 'Nav2 는 실시간으로 돌아서 에피소드 하나에 보통 20~60초 걸립니다. 동시 실행 1개당 CPU 약 0.5~1코어를 씁니다.' }),
        est,
        h('div', {}, btn('벤치마크 시작', { cls: 'primary', icon: 'play', onclick: start })))));
}

function estimate() {
  const d = draft;
  const n = d.episodes.maps.length * d.episodes.per_map * d.configs.length;
  const min = Math.ceil(n * 45 / Math.max(1, d.workers) / 60);
  return `에피소드 ${n}회 (맵 ${d.episodes.maps.length} × ${d.episodes.per_map} × 설정 ${d.configs.length}) · 예상 약 ${min}분`;
}

async function start() {
  try {
    const r = await api.post('/api/bench/start', draft);
    toast('벤치마크를 시작했습니다');
    await openRun(r.id);
  } catch (e) { toast(e.message, 'bad'); }
}

function renderEmpty() {
  main.replaceChildren(h('div', { class: 'panel' }, h('div', { class: 'form' },
    h('h3', { text: '벤치마크로 설정을 비교하세요' }),
    h('div', { class: 'hint', text: '같은 맵·같은 시나리오(정상, 맵에 없는 장애물, 보행자)로 여러 설정을 반복 주행해 성공률, 속도, 장애물 이격, 복구 횟수를 비교합니다. 성공률에는 95% 신뢰구간과 짝비교 검정이 붙습니다.' }),
    h('div', {}, btn('새 벤치마크', { cls: 'primary', icon: 'plus', onclick: () => newRun() })))));
}

// ================================================================== run view
async function openRun(id) {
  current = id;
  formOpen = false;
  clearInterval(poll);
  await refresh();
  renderLeft();
  poll = setInterval(async () => {
    if ($('ws-bench').hidden) return;
    const r = await refresh();
    if (r && !['running', 'preparing'].includes(r.status)) { clearInterval(poll); renderLeft(); }
  }, 3000);
}

async function refresh() {
  let r;
  try { r = await api.get(`/api/runs/${current}`); } catch (e) { toast(e.message, 'bad'); clearInterval(poll); return null; }
  renderRun(r);
  return r;
}

function pct(v) { return v === null || v === undefined ? '–' : (100 * v).toFixed(1) + '%'; }

function renderRun(r) {
  const running = ['running', 'preparing'].includes(r.status);
  const p = r.progress || { done: 0, total: 0 };
  const rep = r.report || [];
  const best = (key, dir) => {
    const vals = rep.map((c) => c.summary[key]).filter((v) => v !== null && v !== undefined);
    if (!vals.length) return null;
    return dir > 0 ? Math.max(...vals) : Math.min(...vals);
  };
  const cols = [
    ['성공률', 'success', 1, (s) => `${pct(s.success)} <span class="faint">(${s.ci_lo !== null && s.ci_lo !== undefined ? (100 * s.ci_lo).toFixed(0) + '–' + (100 * s.ci_hi).toFixed(0) : '–'})</span>`],
    ['충돌', 'collision_rate', -1, (s) => pct(s.collision_rate)],
    ['평균 속도', 'avg_speed', 1, (s) => fmt.n(s.avg_speed, 3)],
    ['평균 소요', 'time_mean', -1, (s) => s.time_mean ? s.time_mean.toFixed(1) + 's' : '–'],
    ['이격 p10', 'min_clear_p10', 1, (s) => s.min_clear_p10 !== null && s.min_clear_p10 !== undefined ? (100 * s.min_clear_p10).toFixed(1) + 'cm' : '–'],
    ['이격 중앙', 'min_clear_med', 1, (s) => s.min_clear_med !== null && s.min_clear_med !== undefined ? (100 * s.min_clear_med).toFixed(1) + 'cm' : '–'],
    ['근접 시간', 'near_time', -1, (s) => fmt.n(s.near_time, 2) + 's'],
    ['복구', 'recoveries', -1, (s) => fmt.n(s.recoveries, 2)],
    ['각 저크', 'ang_jerk_rms', -1, (s) => fmt.n(s.ang_jerk_rms, 1)],
    ['제어기 CPU', 'ctrl_cpu', -1, (s) => s.ctrl_cpu !== null && s.ctrl_cpu !== undefined ? s.ctrl_cpu.toFixed(1) + '%' : '–'],
    ['점수', 'score', 1, (s) => fmt.n(s.score, 1)],
  ];
  const summary = h('div', { class: 'tablewrap' }, h('table', { class: 't' },
    h('tr', {}, h('th', { text: '설정' }), h('th', { class: 'n', text: 'N' }), ...cols.map(([l]) => h('th', { class: 'n', text: l })), h('th', { text: '기준 대비' })),
    ...rep.map((c, k) => h('tr', {}, h('td', {}, h('b', { text: c.name }), c.blocked ? h('div', { class: 'faint', text: `통과 불가 ${c.blocked}건 제외` }) : ''),
      h('td', { class: 'n', text: c.summary.n || 0 }),
      ...cols.map(([, key, dir, f]) => {
        const v = c.summary[key];
        const isBest = rep.length > 1 && v !== null && v !== undefined && v === best(key, dir);
        return h('td', { class: 'n', html: c.summary.n ? f(c.summary) : '–', style: isBest ? { color: 'var(--accent)', fontWeight: '700' } : {} });
      }),
      h('td', { html: k === 0 ? '<span class="faint">기준</span>' : c.paired ? `${c.paired.fixed} 개선 / ${c.paired.broke} 악화 <span class="faint">(p=${c.paired.p.toFixed(2)})</span>` : '–' })))));
  const catNames = Object.keys(CATS).filter((k) => rep.some((c) => c.summary.by_category && c.summary.by_category[k]));
  const cats = h('div', { class: 'tablewrap' }, h('table', { class: 't' },
    h('tr', {}, h('th', { text: '설정' }), ...catNames.map((k) => h('th', { class: 'n', text: CATS[k] }))),
    ...rep.map((c) => h('tr', {}, h('td', { text: c.name }), ...catNames.map((k) => {
      const x = c.summary.by_category && c.summary.by_category[k];
      return h('td', { class: 'n', text: x ? `${pct(x.success)} (${x.n})` : '–' });
    })))));
  // episode matrix
  const eps = {};
  for (const e of r.episodes || []) (eps[e.id] = eps[e.id] || { id: e.id, map: e.map, category: e.category, gap: e.gap, by: {} }).by[e.cfg] = e;
  const rows = Object.values(eps).sort((a, b) => a.id.localeCompare(b.id));
  const matrix = h('div', { class: 'tablewrap' }, h('table', { class: 't' },
    h('tr', {}, h('th', { text: '에피소드' }), h('th', { text: '종류' }), h('th', { class: 'n', text: '최소 폭' }), ...rep.map((c) => h('th', { text: c.name }))),
    ...rows.map((e) => h('tr', {}, h('td', { class: 'mono', text: e.id }), h('td', { text: CATS[e.category] }), h('td', { class: 'n', text: e.gap ? e.gap.toFixed(2) + 'm' : '–' }),
      ...rep.map((c, k) => {
        const x = e.by[k];
        if (!x) return h('td', { class: 'faint', text: running ? '…' : '–' });
        const ok = x.status === 'succeeded' && !x.collisions;
        const cls = ok ? 'succeeded' : x.collisions ? 'collision' : x.status;
        return h('td', { class: 'click', style: { cursor: 'pointer' }, title: '재생', onclick: () => replay(r, k, e.id) },
          h('span', { class: 'st ' + cls, text: ok ? '성공' : x.collisions ? '충돌' : (STATUS[x.status] || x.status) }), h('span', { class: 'faint', text: ` ${x.duration ? x.duration.toFixed(0) + 's' : ''}` }));
      })))));
  main.replaceChildren(
    h('div', { class: 'panel' },
      h('header', {}, h('div', { style: { display: 'grid', gap: '2px' } }, h('h3', { text: r.spec.name }),
        h('span', { class: 'hint', text: `${new Date(r.started * 1000).toLocaleString()} · ${r.spec.configs.length}개 설정 · 맵 ${r.spec.episodes.maps.map(mapName).join(', ')}` })),
        h('div', { style: { display: 'flex', gap: '6px', alignItems: 'center' } },
          h('span', { class: 'pill', 'data-state': running ? 'starting' : r.status === 'done' ? 'ready' : r.status === 'error' ? 'error' : 'stopped' }, h('i'), h('b', { text: statusLabel(r.status) })),
          running ? btn('취소', { icon: 'stop', onclick: async () => { await api.post(`/api/runs/${r.id}/cancel`); refresh(); } }) : btn('같은 조건으로 새로', { icon: 'copy', onclick: () => newRun(JSON.parse(JSON.stringify(r.spec))) }),
          !running ? btn('', { cls: 'ghost icon-only', icon: 'trash', title: '삭제', aria: '삭제', onclick: async () => { await api.del(`/api/runs/${r.id}`); current = null; renderLeft(); renderEmpty(); } }) : '')),
      h('div', { class: 'form' },
        h('div', { class: 'progress' }, h('i', { style: { width: `${p.total ? 100 * p.done / p.total : 0}%` } })),
        h('div', { class: 'hint num', text: `${p.done} / ${p.total} 에피소드${r.message ? ' · ' + r.message : ''}` }),
        ...(r.warnings || []).map((w) => h('div', { class: 'warnbox', text: w })))),
    h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '결과 요약' }), h('span', { class: 'hint', text: '물리적으로 통과할 수 없는 에피소드(남은 틈 < 로봇 폭 + 12 cm)는 성공률에서 뺍니다' })), summary),
    rep.length && catNames.length ? h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '시나리오 종류별 성공률' })), cats) : '',
    h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '에피소드별 결과' }), h('span', { class: 'hint', text: '칸을 누르면 주행을 재생합니다' })), matrix),
  );
}

// ================================================================== replay
export async function replay(run, cfg, eid) {
  let data;
  try { data = await api.get(`/api/runs/${run.id}/episode?cfg=${cfg}&eid=${encodeURIComponent(eid)}`); } catch (e) { toast(e.message, 'bad'); return; }
  const ep = data.episode, tr = data.traj, rec = data.record || {};
  const wrap = h('div', { class: 'replay' }, h('canvas'));
  const slider = h('input', { type: 'range', min: 0, max: tr ? tr.traj.length - 1 : 0, value: 0, style: { flex: '1' }, 'aria-label': '재생 위치' });
  const tlabel = h('span', { class: 'num', text: '0.0s' });
  let playing = true;
  const playBtn = btn('', { cls: 'icon-only', icon: 'pause', aria: '재생/일시정지', onclick: () => { playing = !playing; playBtn.innerHTML = icon(playing ? 'pause' : 'play'); } });
  const bar = h('div', { class: 'rbar floating' }, playBtn, slider, tlabel);
  wrap.append(bar);
  const name = (run.spec.configs && run.spec.configs[cfg] && run.spec.configs[cfg].name) || cfg;
  const info = h('dl', { class: 'kv' },
    h('dt', { text: '결과' }), h('dd', { text: STATUS[rec.status] || rec.status || '–' }),
    h('dt', { text: '시간' }), h('dd', { text: rec.duration ? rec.duration.toFixed(1) + 's' : '–' }),
    h('dt', { text: '주행 / 기준 거리' }), h('dd', { text: rec.path_len ? `${rec.path_len.toFixed(1)} / ${rec.ref_len.toFixed(1)} m` : '–' }),
    h('dt', { text: '최소 이격' }), h('dd', { text: rec.min_clear !== undefined ? (100 * rec.min_clear).toFixed(1) + ' cm' : '–' }),
    h('dt', { text: '복구 / 충돌' }), h('dd', { text: `${rec.recoveries ?? '–'} / ${rec.collisions ?? '–'}` }));
  const close = modal(`${eid} · ${name}`, [wrap, info]);
  await new Promise((r) => requestAnimationFrame(r));
  const vp = new Viewport(wrap.querySelector('canvas'), { editable: false, layers: { global: false, local: false, scan: false } });
  vp.robot = data.robot;
  const meta = await api.get(`/api/maps/${ep.map}`);
  await vp.setMap(meta, `/api/maps/${ep.map}/grid.png`);
  vp.scene = { static_obs: ep.static_obs, dyn_obs: ep.dyn_obs, start: ep.start, goal: ep.goal };
  vp.plans.global = tr && tr.first_plan;
  // zoom to the episode
  const pts = [ep.start, ep.goal, ...(tr ? tr.traj.map((q) => [q[1], q[2]]) : [])];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  vp.centerOn((Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2);
  vp.view.s = Math.min(vp.W / (Math.max(...xs) - Math.min(...xs) + 3), vp.H / (Math.max(...ys) - Math.min(...ys) + 3));
  if (!tr || !tr.traj.length) { toast('이 에피소드에는 궤적 기록이 없습니다'); return; }
  let i = 0, last = performance.now();
  const set = (k) => {
    i = Math.max(0, Math.min(tr.traj.length - 1, k));
    const q = tr.traj[i];
    vp.trail = tr.traj.slice(0, i + 1).map((p) => [p[1], p[2]]);
    vp.live = { pose: [q[1], q[2], q[3]], dyn: (q[6] || []).map((d, j) => [d[0], d[1], (ep.dyn_obs[j] || {}).r || 0.22]), contact: false, scan: [] };
    vp.dirty = true;
    slider.value = i;
    tlabel.textContent = q[0].toFixed(1) + 's';
  };
  slider.oninput = () => { playing = false; playBtn.innerHTML = icon('play'); set(+slider.value); };
  set(0);
  const tick = (now) => {
    if (document.getElementById('modal').hidden) return;
    if (playing && now - last > 50) { last = now; set(i + 1); if (i >= tr.traj.length - 1) { playing = false; playBtn.innerHTML = icon('play'); } }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  void close;
}
