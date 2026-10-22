// Application state shared by the workspaces.
import { persist } from './ui.js';

export const S = {
  info: null, maps: [], robots: [], stacks: [], presets: [],
  sel: Object.assign({ map: 'synth_narrow', robotId: 'everybot', robot: null, stack: 'prod', values: {}, raw: '', preset: null },
    persist('sel') || {}),
  applied: null,          // selection key of the running session
  stack: { status: 'stopped', message: '' },
  robotProfile: null,     // resolved profile of the selection
  mapMeta: null,
  schema: null,           // {groups, params, warnings}
  scene: { static_obs: [], dyn_obs: [], start: null, goal: null },
  nav: null, sim: null,
  warnings: [],
};

const L = {};
export const on = (ev, fn) => (L[ev] = L[ev] || []).push(fn);
export const emit = (ev, d) => (L[ev] || []).forEach((f) => f(d));

export function selKey(sel = S.sel) {
  return JSON.stringify({ map: sel.map, robotId: sel.robot ? null : sel.robotId, robot: sel.robot, stack: sel.stack,
    values: sel.values, raw: (sel.raw || '').trim() });
}
export const isDirty = () => S.applied !== null && S.applied !== selKey();
export const saveSel = () => persist('sel', S.sel);
export const mapName = (id) => (S.maps.find((m) => m.id === id) || {}).name || id;
export const stackOf = (id) => S.stacks.find((s) => s.id === id);
