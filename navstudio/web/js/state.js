// Application state shared by the workspaces.
//
// Up to 4 live slots (A–D) share the map, robot and scene; each has its own driving stack + parameter changes (cfg)
// and its own Nav2 session. S.sel.stack/values/raw/preset and S.stack/nav/sim/applied/warnings always refer to the
// active slot, so the single-session panels edit and show whichever slot is selected.
import { persist } from './ui.js';

export const MAX_SLOTS = 4;
export const SLOT_NAMES = ['A', 'B', 'C', 'D'];

const savedSel = persist('sel') || {};
const savedSlots = persist('slots') || [];

function newSlot(i) {
  const legacy = i === 0 ? { stack: savedSel.stack, values: savedSel.values, raw: savedSel.raw, preset: savedSel.preset } : {};   // before 0.2
  const given = Object.fromEntries(Object.entries(savedSlots[i] || legacy).filter(([, v]) => v !== undefined && v !== null));
  const cfg = Object.assign({ stack: 'prod', values: {}, raw: '', preset: null }, given);
  return { idx: i, cfg, applied: null, stack: { status: 'stopped', message: '' }, nav: null, sim: null, warnings: [], pending: false };
}

export const S = {
  info: null, maps: [], robots: [], stacks: [], presets: [],
  sel: { map: savedSel.map || 'synth_narrow', robotId: savedSel.robotId || 'everybot', robot: savedSel.robot || null },
  slots: Array.from({ length: MAX_SLOTS }, (_, i) => newSlot(i)),
  nSlots: Math.min(Math.max(persist('nSlots') || 1, 1), MAX_SLOTS),
  active: 0,
  robotProfile: null,     // resolved profile of the selection
  mapMeta: null,
  schema: null,           // {groups, params, warnings} for the active slot's stack
  scene: { static_obs: [], dyn_obs: [], start: null, goal: null },
};
S.active = Math.min(persist('activeSlot') || 0, S.nSlots - 1);

for (const k of ['stack', 'values', 'raw', 'preset']) {
  Object.defineProperty(S.sel, k, { get: () => S.slots[S.active].cfg[k], set: (v) => { S.slots[S.active].cfg[k] = v; } });
}
for (const k of ['stack', 'nav', 'sim', 'applied', 'warnings', 'pending']) {
  Object.defineProperty(S, k, { get: () => S.slots[S.active][k], set: (v) => { S.slots[S.active][k] = v; } });
}

const L = {};
export const on = (ev, fn) => (L[ev] = L[ev] || []).push(fn);
export const emit = (ev, d) => (L[ev] || []).forEach((f) => f(d));

export function slotKey(i) {
  const c = S.slots[i].cfg;
  return JSON.stringify({ map: S.sel.map, robotId: S.sel.robot ? null : S.sel.robotId, robot: S.sel.robot, stack: c.stack,
    values: c.values, raw: (c.raw || '').trim() });
}
export const selKey = () => slotKey(S.active);
export const isDirtySlot = (i) => S.slots[i].applied !== null && S.slots[i].applied !== slotKey(i);
export const isDirty = () => isDirtySlot(S.active);
export const visibleSlots = () => S.slots.slice(0, S.nSlots);
export function saveSel() {
  persist('sel', { map: S.sel.map, robotId: S.sel.robotId, robot: S.sel.robot });
  persist('slots', S.slots.map((s) => s.cfg));
  persist('nSlots', S.nSlots);
  persist('activeSlot', S.active);
}
export const mapName = (id) => (S.maps.find((m) => m.id === id) || {}).name || id;
export const stackOf = (id) => S.stacks.find((s) => s.id === id);
export const presetOf = (id) => S.presets.find((p) => p.id === id);

const sameValues = (a, b) => {
  const ka = Object.keys(a || {}), kb = Object.keys(b || {});
  return ka.length === kb.length && ka.every((k) => Math.abs((a[k] ?? NaN) - (b[k] ?? NaN)) < 1e-9);
};

// what a slot runs, for headers and lists: {name, modified}
export function cfgLabel(i) {
  const c = S.slots[i].cfg;
  const set = c.preset && presetOf(c.preset);
  if (set) {
    const modified = set.stack !== c.stack || !sameValues(set.values, c.values) || (set.raw || '').trim() !== (c.raw || '').trim();
    return { name: set.name, modified };
  }
  const st = stackOf(c.stack);
  const n = Object.keys(c.values || {}).length + ((c.raw || '').trim() ? 1 : 0);
  return { name: (st ? st.name.replace(/\s*\(.*\)/, '') : c.stack) + (n ? ` · 변경 ${n}` : ''), modified: false };
}
