// Auto-tuning workspace: Optuna (TPE) search over chosen parameters, live leaderboard, apply / verify the best.
import { api } from './api.js';
import { S, emit, mapName } from './state.js';
import { h, icon, btn, toast, fmt, persist, cssVar } from './ui.js';
import { currentConfig, configLabel, episodeForm, newRun } from './bench.js';
import * as sim from './sim.js';

const $ = (id) => document.getElementById(id);
let left, main, current = null, poll = null, draft = null, schemaCache = null;

const WEIGHTS = [['success', '성공률'], ['speed', '속도'], ['clearance', '안전 여유'], ['smooth', '부드러움']];

export function show() {
  const root = $('ws-tune');
  if (!left) {
    left = h('aside', { class: 'side left' });
    main = h('section', { class: 'page' });
    root.replaceChildren(left, main);
    draft = persist('tuneDraft') || null;
  }
  renderLeft();
  if (current) openRun(current); else newTune();
}

async function renderLeft() {
  let list = [];
  try { list = await api.get('/api/runs?kind=tune'); } catch (e) { /* busy */ }
  left.replaceChildren(h('div', { class: 'form' }, h('div', { class: 'sec' },
    h('h3', {}, '자동 튜닝', btn('새 튜닝', { cls: 'sm primary act', icon: 'plus', onclick: () => { current = null; clearInterval(poll); newTune(); renderLeft(); } })),
    list.length ? h('div', { class: 'optlist' }, ...list.map((r) => h('button', { class: 'opt', 'aria-pressed': String(r.id === current), onclick: () => openRun(r.id) },
      h('span', { html: icon('tune') }), h('div', { class: 't' }, h('b', { text: r.name }),
        h('span', { text: `${new Date(r.started * 1000).toLocaleString()} · ${{ running: '실행 중', preparing: '준비 중', done: '완료', canceled: '취소됨', error: '오류' }[r.status] || r.status}` })))))
      : h('div', { class: 'hint', text: '파라미터 범위를 정하면 Optuna(TPE)가 시나리오 주행 점수를 높이는 조합을 찾습니다.' }))));
}

async function loadSchema(base) {
  const r = await api.post('/api/params/schema', { robot_id: base.robot_id, robot: base.robot, stack: base.stack });
  schemaCache = r;
  return r;
}

async function newTune() {
  if (!draft) {
    draft = {
      name: '자동 튜닝 ' + new Date().toLocaleDateString(), base: currentConfig('기준 (현재 설정)'), params: [],
      weights: { success: 1, speed: 1, clearance: 1, smooth: 1 }, trials: 24, parallel: 2, workers: 3,
      episodes: { source: 'bundled', maps: [S.sel.map], categories: ['unmapped', 'dynamic'], per_map: 8, seed: 1 },
    };
  }
  await loadSchema(draft.base);
  renderForm();
}

function renderForm() {
  const d = draft;
  persist('tuneDraft', d);
  const sync = (re) => { persist('tuneDraft', d); if (re) renderForm(); else est.textContent = estimate(); };
  const sch = schemaCache;
  const chosen = new Map(d.params.map((p) => [p.id, p]));
  const groups = sch.groups.map((g) => {
    const ps = sch.params.filter((p) => p.group === g.id);
    if (!ps.length) return null;
    return h('details', { class: 'pgroup', open: ps.some((p) => chosen.has(p.id)) || g.id === 'dwb' || g.id === 'costmap' },
      h('summary', {}, g.label, h('span', { class: 'cnt', text: `${ps.filter((p) => chosen.has(p.id)).length} / ${ps.length}` })),
      ...ps.map((p) => {
        const c = chosen.get(p.id);
        const cur = (d.base.values || {})[p.id] ?? p.default;
        const lo = c ? c.low : Math.max(p.min, roundStep(cur * 0.5, p)), hi = c ? c.high : Math.min(p.max, roundStep(cur * 1.5 || p.max, p));
        const loIn = h('input', { type: 'number', step: p.step, value: lo, 'aria-label': p.label + ' 최소', disabled: !c, oninput: (e) => { chosen.get(p.id).low = +e.target.value; sync(); } });
        const hiIn = h('input', { type: 'number', step: p.step, value: hi, 'aria-label': p.label + ' 최대', disabled: !c, oninput: (e) => { chosen.get(p.id).high = +e.target.value; sync(); } });
        return h('div', { class: 'prow' + (c ? ' changed' : '') },
          h('div', { class: 'top' }, h('label', { style: { display: 'flex', gap: '6px', alignItems: 'center' } },
            h('input', { type: 'checkbox', checked: !!c, onchange: (e) => {
              if (e.target.checked) d.params.push({ id: p.id, low: Math.min(lo, hi), high: Math.max(lo, hi), log: p.max / Math.max(p.min, 1e-6) > 20 && p.min > 0, default: cur });
              else d.params = d.params.filter((x) => x.id !== p.id);
              sync(true);
            } }), p.label), h('span', { class: 'unit', text: `현재 ${cur}${p.unit ? ' ' + p.unit : ''}` })),
          h('div', { class: 'grid2' }, loIn, hiIn));
      }));
  }).filter(Boolean);
  const weights = h('div', { class: 'grid2' }, ...WEIGHTS.map(([k, label]) => {
    const v = h('b', { class: 'num', text: d.weights[k] });
    return h('label', { class: 'field' }, h('span', {}, label, ' ×', v), h('input', { type: 'range', min: 0, max: 3, step: 0.25, value: d.weights[k],
      oninput: (e) => { d.weights[k] = +e.target.value; v.textContent = e.target.value; sync(); } }));
  }));
  const slider = (label, key, min, max) => {
    const v = h('b', { class: 'num', text: d[key] });
    return h('label', { class: 'field' }, h('span', {}, label, ' ', v), h('input', { type: 'range', min, max, value: d[key], oninput: (e) => { d[key] = +e.target.value; v.textContent = e.target.value; sync(); } }));
  };
  const est = h('div', { class: 'hint num', text: estimate() });
  main.replaceChildren(h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '새 자동 튜닝' })),
    h('div', { class: 'form' },
      h('label', { class: 'field' }, h('span', { text: '이름' }), h('input', { type: 'text', value: d.name, oninput: (e) => { d.name = e.target.value; persist('tuneDraft', d); } })),
      h('div', { class: 'sec' }, h('h3', {}, '기준 설정', btn('현재 설정으로', { cls: 'sm ghost act', icon: 'undo', onclick: async () => { d.base = currentConfig('기준 (현재 설정)'); d.params = []; await loadSchema(d.base); sync(true); } })),
        h('div', { class: 'opt' }, h('span', { html: icon('robot') }), h('div', { class: 't' }, h('b', { text: d.base.name }), h('span', { text: configLabel(d.base) })))),
      h('div', { class: 'sec' }, h('h3', { text: `튜닝할 파라미터 (${d.params.length})` }),
        h('div', { class: 'hint', text: '체크한 파라미터를 [최소, 최대] 범위에서 찾습니다. 3~8개가 적당합니다. 첫 trial 은 현재 값으로 시작합니다.' }), ...groups),
      h('div', { class: 'sec' }, h('h3', { text: '점수 가중치' }), weights,
        h('div', { class: 'hint', text: '점수 = 성공률·충돌 + 평균 속도 + 장애물 이격(p10) − 복구 횟수 − 각 저크. 가중치로 무엇을 우선할지 정합니다.' })),
      episodeForm(d.episodes, sync),
      h('div', { class: 'grid3' }, slider('trial 수', 'trials', 4, 80), slider('동시 trial', 'parallel', 1, 4), slider('trial 당 동시 주행', 'workers', 1, 6)),
      est,
      h('div', {}, btn('튜닝 시작', { cls: 'primary', icon: 'play', onclick: start })))));
}

function roundStep(v, p) { const s = p.step || 0.01; return Math.round(v / s) * s; }

function estimate() {
  const d = draft;
  const eps = d.episodes.maps.length * d.episodes.per_map;
  const perTrial = eps * 45 / Math.max(1, d.workers);
  const min = Math.ceil(perTrial * d.trials / Math.max(1, d.parallel) / 60);
  return `trial 하나에 주행 ${eps}회 (약 ${Math.ceil(perTrial / 60)}분) × ${d.trials} trial ÷ 동시 ${d.parallel} · 예상 약 ${min >= 120 ? (min / 60).toFixed(1) + '시간' : min + '분'} · 동시 주행 ${d.parallel * d.workers}개`;
}

async function start() {
  if (!draft.params.length) { toast('튜닝할 파라미터를 하나 이상 체크하세요', 'bad'); return; }
  try {
    const r = await api.post('/api/tune/start', draft);
    toast('튜닝을 시작했습니다. 창을 닫아도 서버에서 계속 돕니다.');
    openRun(r.id);
  } catch (e) { toast(e.message, 'bad'); }
}

async function openRun(id) {
  current = id;
  clearInterval(poll);
  const r = await refresh();
  renderLeft();
  if (r && ['running', 'preparing'].includes(r.status)) {
    poll = setInterval(async () => {
      if ($('ws-tune').hidden) return;
      const x = await refresh();
      if (x && !['running', 'preparing'].includes(x.status)) { clearInterval(poll); renderLeft(); }
    }, 4000);
  }
}

async function refresh() {
  try { const r = await api.get(`/api/runs/${current}`); renderRun(r); return r; } catch (e) { toast(e.message, 'bad'); return null; }
}

function renderRun(r) {
  const running = ['running', 'preparing'].includes(r.status);
  const trials = (r.report && r.report.trials) || [];
  const done = trials.filter((t) => t.state === 'COMPLETE');
  const best = done.reduce((a, t) => (!a || t.value > a.value ? t : a), null);
  const base = done.find((t) => t.number === 0);
  const p = r.progress || {};
  const ids = r.spec.params.map((x) => x.id);
  const label = (id) => ((schemaCache && schemaCache.params.find((q) => q.id === id)) || {}).label || id;
  const bestCard = best ? h('div', { class: 'panel' }, h('header', {}, h('h3', { text: `최고 trial #${best.number}` }),
    h('div', { style: { display: 'flex', gap: '6px' } },
      btn('시뮬레이션에 적용', { cls: 'primary', icon: 'play', onclick: () => applyBest(r, best) }),
      btn('검증 벤치마크', { icon: 'chart', title: '기준과 최고 설정을 다른 맵에서 비교', onclick: () => verify(r, best) }))),
  h('div', { class: 'form' },
    h('div', { class: 'cards' },
      stat('점수', fmt.n(best.value, 1), base ? `기준 ${fmt.n(base.value, 1)}` : ''),
      stat('성공률', fmt.pct(best.attrs.success), base ? `기준 ${fmt.pct(base.attrs.success)}` : ''),
      stat('평균 속도', fmt.n(best.attrs.avg_speed, 3) + ' m/s', base ? `기준 ${fmt.n(base.attrs.avg_speed, 3)}` : ''),
      stat('이격 p10', best.attrs.min_clear_p10 !== null && best.attrs.min_clear_p10 !== undefined ? (100 * best.attrs.min_clear_p10).toFixed(1) + ' cm' : '–', base && base.attrs.min_clear_p10 !== undefined ? `기준 ${(100 * base.attrs.min_clear_p10).toFixed(1)}` : ''),
      stat('복구', fmt.n(best.attrs.recoveries, 2), base ? `기준 ${fmt.n(base.attrs.recoveries, 2)}` : '')),
    h('div', { class: 'tablewrap' }, h('table', { class: 't' }, h('tr', {}, h('th', { text: '파라미터' }), h('th', { class: 'n', text: '기준' }), h('th', { class: 'n', text: '최고' })),
      ...ids.map((id) => h('tr', {}, h('td', { text: label(id) }), h('td', { class: 'n', text: fmtv(base ? base.params[id] : (r.spec.base.values || {})[id] ?? r.spec.params.find((x) => x.id === id).default) }),
        h('td', { class: 'n', text: fmtv(best.params[id]) }))))),
    h('div', { class: 'hint', text: '점수는 튜닝에 쓴 시나리오에서만 잰 값이라 우연히 좋게 나올 수 있습니다. 적용 전에 ‘검증 벤치마크’ 로 다른 맵에서 확인하세요.' }))) : '';
  main.replaceChildren(
    h('div', { class: 'panel' },
      h('header', {}, h('div', { style: { display: 'grid', gap: '2px' } }, h('h3', { text: r.spec.name }),
        h('span', { class: 'hint', text: `${ids.length}개 파라미터 · 맵 ${r.spec.episodes.maps.map(mapName).join(', ')} · ${configLabel(r.spec.base)}` })),
        h('div', { style: { display: 'flex', gap: '6px', alignItems: 'center' } },
          h('span', { class: 'pill', 'data-state': running ? 'starting' : r.status === 'done' ? 'ready' : r.status === 'error' ? 'error' : 'stopped' }, h('i'), h('b', { text: running ? '실행 중' : r.status === 'done' ? '완료' : r.status === 'error' ? '오류' : '중단' })),
          running ? btn('중단', { icon: 'stop', onclick: async () => { await api.post(`/api/runs/${r.id}/cancel`); toast('진행 중인 trial 을 정리하고 멈춥니다'); } }) :
            btn('', { cls: 'ghost icon-only', icon: 'trash', title: '삭제', aria: '삭제', onclick: async () => { await api.del(`/api/runs/${r.id}`); current = null; renderLeft(); newTune(); } }))),
      h('div', { class: 'form' }, h('div', { class: 'progress' }, h('i', { style: { width: `${p.total ? 100 * p.done / p.total : 0}%` } })),
        h('div', { class: 'hint num', text: `trial ${p.done || 0} / ${p.total || r.spec.trials}${r.message ? ' · ' + r.message : ''}` }),
        ...(r.warnings || []).map((w) => h('div', { class: 'warnbox', text: w })))),
    bestCard,
    done.length ? h('div', { class: 'panel' }, h('header', {}, h('h3', { text: '점수 추이' }), h('span', { class: 'hint', text: '점: trial 점수 · 선: 그때까지 최고' })), scoreChart(trials)) : '',
    h('div', { class: 'panel' }, h('header', {}, h('h3', { text: `trial (${trials.length})` })), h('div', { class: 'tablewrap' }, h('table', { class: 't' },
      h('tr', {}, h('th', { class: 'n', text: '#' }), h('th', { class: 'n', text: '점수' }), h('th', { class: 'n', text: '성공률' }), h('th', { class: 'n', text: '속도' }), h('th', { class: 'n', text: '이격 p10' }), h('th', { class: 'n', text: '복구' }), ...ids.map((id) => h('th', { class: 'n', text: label(id) }))),
      ...[...trials].sort((a, b) => (b.value ?? -1e9) - (a.value ?? -1e9)).map((t) => h('tr', { class: best && t.number === best.number ? 'best' : '' },
        h('td', { class: 'n', text: t.number }), h('td', { class: 'n', text: t.state === 'COMPLETE' ? fmt.n(t.value, 1) : t.state === 'RUNNING' ? '실행 중' : t.state }),
        h('td', { class: 'n', text: fmt.pct(t.attrs.success) }), h('td', { class: 'n', text: fmt.n(t.attrs.avg_speed, 3) }),
        h('td', { class: 'n', text: t.attrs.min_clear_p10 !== undefined && t.attrs.min_clear_p10 !== null ? (100 * t.attrs.min_clear_p10).toFixed(1) : '–' }),
        h('td', { class: 'n', text: fmt.n(t.attrs.recoveries, 2) }), ...ids.map((id) => h('td', { class: 'n', text: fmtv(t.params[id]) }))))))),
  );
}

function fmtv(v) { return v === undefined || v === null ? '–' : (Math.abs(v) >= 100 ? v.toFixed(0) : +Number(v).toFixed(3)); }
function stat(label, value, sub) { return h('div', { class: 'stat' }, h('span', { text: label }), h('b', { text: value }), sub ? h('span', { class: 'faint', text: sub }) : ''); }

function scoreChart(trials) {
  const pts = trials.filter((t) => t.state === 'COMPLETE').sort((a, b) => a.number - b.number);
  const W = 720, H = 220, L = 44, R = 12, T = 12, B = 28;
  const xs = pts.map((t) => t.number), ys = pts.map((t) => t.value);
  const x0 = Math.min(...xs, 0), x1 = Math.max(...xs, 1), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = (y1 - y0) * 0.1 || 1;
  const sx = (x) => L + (x - x0) / (x1 - x0 || 1) * (W - L - R), sy = (y) => H - B - (y - (y0 - pad)) / ((y1 + pad) - (y0 - pad)) * (H - T - B);
  let run = -Infinity;
  const bestLine = pts.map((t) => { run = Math.max(run, t.value); return `${sx(t.number).toFixed(1)},${sy(run).toFixed(1)}`; }).join(' ');
  const ticks = [y0 - pad, (y0 + y1) / 2, y1 + pad].map((v) => `<line x1="${L}" x2="${W - R}" y1="${sy(v)}" y2="${sy(v)}" stroke="var(--line)"/><text x="${L - 6}" y="${sy(v) + 4}" text-anchor="end" font-size="11" fill="var(--muted)" font-family="var(--f-mono)">${v.toFixed(0)}</text>`).join('');
  const dots = pts.map((t) => `<circle cx="${sx(t.number)}" cy="${sy(t.value)}" r="4" fill="var(--accent)" fill-opacity="0.55"><title>#${t.number}: ${t.value.toFixed(1)}</title></circle>`).join('');
  const svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:900px;height:auto;display:block" role="img" aria-label="trial 점수 추이">${ticks}
    <polyline points="${bestLine}" fill="none" stroke="var(--good)" stroke-width="2"/>${dots}
    <text x="${(L + W - R) / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="var(--muted)">trial</text></svg>`;
  return h('div', { style: { padding: '8px 12px' }, html: svg });
}

async function applyBest(r, best) {
  const b = r.spec.base;
  S.sel.values = { ...(b.values || {}), ...best.params };
  S.sel.raw = b.raw || '';
  S.sel.preset = null;
  if (b.stack !== S.sel.stack) await sim.selectStack(b.stack);
  if (b.robot) await sim.selectRobot(null, b.robot); else if (b.robot_id !== S.sel.robotId) await sim.selectRobot(b.robot_id);
  sim.renderParams();
  emit('sel');
  emit('goto', 'sim');
  toast(`trial #${best.number} 값을 파라미터에 넣었습니다. ‘변경 적용’ 으로 실행해 보세요.`);
}

function verify(r, best) {
  const b = r.spec.base;
  const others = S.maps.map((m) => m.id).filter((m) => !r.spec.episodes.maps.includes(m)).slice(0, 3);
  emit('goto', 'bench');
  setTimeout(() => newRun({
    name: `${r.spec.name} 검증`, workers: 4,
    configs: [{ ...b, name: '기준' }, { ...b, name: `trial #${best.number}`, values: { ...(b.values || {}), ...best.params } }],
    episodes: { ...r.spec.episodes, maps: others.length ? others : r.spec.episodes.maps, per_map: 8 },
  }), 50);
}
