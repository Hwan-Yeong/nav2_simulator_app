// Shared UI helpers: DOM builder, icons, toasts, modal, formatting, theme.

const P = {
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  restart: '<path d="M20 12a8 8 0 1 1-2.4-5.7L20 8.5"/><path d="M20 3.5v5h-5"/>',
  select: '<path d="M5 3.5l6.5 16 2.2-6.6 6.6-2.2z"/>',
  pan: '<path d="M5 9l-3 3 3 3M9 5l3-3 3 3M15 19l-3 3-3-3M19 9l3 3-3 3M2 12h20M12 2v20"/>',
  start: '<circle cx="12" cy="12" r="7"/><path d="M12 12l5-3"/>',
  goal: '<path d="M6 21V4"/><path d="M6 4h11l-2.5 4L17 12H6"/>',
  box: '<rect x="4.5" y="4.5" width="15" height="15" rx="1.5"/>',
  pole: '<circle cx="12" cy="12" r="5.5"/>',
  chair: '<circle cx="7" cy="7" r="1.8"/><circle cx="17" cy="7" r="1.8"/><circle cx="7" cy="17" r="1.8"/><circle cx="17" cy="17" r="1.8"/>',
  person: '<circle cx="12" cy="4.6" r="2.1"/><path d="M12 7.5v6.5l-3 7M12 14l3 7M7.5 10.5h9"/>',
  eraser: '<path d="M8 20h12"/><path d="M4 15.5l9.5-9.5 5.5 5.5-8 8H8z"/>',
  trash: '<path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  follow: '<circle cx="12" cy="12" r="6.5"/><circle cx="12" cy="12" r="1.6"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
  download: '<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  undo: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 3.5v5h5"/>',
  code: '<path d="M8.5 6l-6 6 6 6M15.5 6l6 6-6 6"/>',
  edit: '<path d="M4 20h4L19.5 8.5l-4-4L4 16z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  copy: '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="1.5"/><path d="M15.5 8.5V4H4v11.5h4.5"/>',
  lidar: '<circle cx="12" cy="12" r="3"/><path d="M5.6 5.6a9 9 0 0 1 12.8 0M8 8a5.6 5.6 0 0 1 8 0"/>',
  chart: '<path d="M4 20V11M10 20V5M16 20v-7M21 20H3"/>',
  sliders: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  robot: '<circle cx="12" cy="12" r="8"/><path d="M12 12l6-3"/>',
  vertex: '<path d="M5 19L12 5l7 14z"/><circle cx="12" cy="5" r="1.8"/><circle cx="5" cy="19" r="1.8"/><circle cx="19" cy="19" r="1.8"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
  tune: '<path d="M3 17l5-6 4 4 4-7 5 9"/>',
};

export function icon(name, cls = 'i') {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[name] || ''}</svg>`;
}

export function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'html') e.innerHTML = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return e;
}

export function btn(label, opts = {}) {
  const b = h('button', { class: 'btn ' + (opts.cls || ''), type: 'button', title: opts.title, 'aria-label': opts.aria || null,
    onclick: opts.onclick, disabled: opts.disabled });
  b.innerHTML = (opts.icon ? icon(opts.icon) : '') + (label ? `<span>${label}</span>` : '');
  return b;
}

export function toast(msg, kind = '') {
  const t = h('div', { class: 'toast ' + kind, text: msg });
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 7000 : 3500);
}

export function modal(title, body, foot = []) {
  const m = document.getElementById('modal');
  document.getElementById('modalTitle').textContent = title;
  const b = document.getElementById('modalBody');
  b.replaceChildren(...[body].flat());
  document.getElementById('modalFoot').replaceChildren(...foot);
  m.hidden = false;
  const close = () => { m.hidden = true; };
  document.getElementById('modalClose').onclick = close;
  m.onclick = (e) => { if (e.target === m) close(); };
  return close;
}

export const fmt = {
  n: (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '–' : Number(v).toFixed(d),
  pct: (v, d = 1) => (v === null || v === undefined) ? '–' : (100 * v).toFixed(d) + '%',
  t: (s) => { if (s === null || s === undefined) return '–'; const m = Math.floor(s / 60); return m ? `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}` : `${s.toFixed(1)}s`; },
  deg: (r) => (r * 180 / Math.PI).toFixed(0) + '°',
};

export const DRIVE_LABEL = { diff: '차동 구동', omni: '전방향 (메카넘)', ackermann: '차량형 (Ackermann)' };

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// theme: 'system' | 'light' | 'dark' (explicit choice stored per browser)
export function initTheme(button, onchange) {
  const order = ['system', 'light', 'dark'];
  let cur = 'system';
  try { cur = localStorage.getItem('ns.theme') || 'system'; } catch (e) { /* storage blocked */ }
  const apply = () => {
    if (cur === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', cur);
    const dark = cur === 'dark' || (cur === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    button.innerHTML = icon(dark ? 'moon' : 'sun');
    button.title = { system: '테마: 시스템', light: '테마: 밝게', dark: '테마: 어둡게' }[cur];
    onchange && onchange();
  };
  button.onclick = () => {
    cur = order[(order.indexOf(cur) + 1) % order.length];
    try { localStorage.setItem('ns.theme', cur); } catch (e) { /* ignore */ }
    apply();
  };
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', apply);
  apply();
}

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function persist(key, val) {
  try {
    if (val === undefined) return JSON.parse(localStorage.getItem('ns.' + key));
    localStorage.setItem('ns.' + key, JSON.stringify(val));
  } catch (e) { return undefined; }
  return val;
}

// small diff highlighter for unified diffs
export function diffHtml(text) {
  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return text.split('\n').map((l) => {
    const c = l.startsWith('@@') ? 'hunk' : (l.startsWith('+') && !l.startsWith('+++')) ? 'add' : (l.startsWith('-') && !l.startsWith('---')) ? 'del' : '';
    return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
  }).join('\n');
}
