"""Detection coverage: where around a standing robot a probe object would be detected, and by which sensor.

A probe is one object put on a grid cell: a box (low box, threshold, overhang: footprint `size`, heights z0..z1),
a pole (cylinder, diameter `size`) or a drop (square hole `size`, `depth`). For every cell this runs the pieces the
simulator and the perception node use, so plugin sensor types work too:
  2D lidar     sees the probe when its scan plane height lies in z0..z1 and a beam (fov, beams, range) meets it
  3D sensors   the type's rays are cast at the probe (noise and dropout off), measure() turns distances into the
               driver output, and perceive() (perception mode 'rules') must put an obstacle / drop candidate on the
               probe. Mode 'direct': a raw point inside the probe within the voxel layer's height band. Mode 'off':
               3D sensors do not reach Nav2 (reported, not counted).
Cells are only evaluated where some ray of the sensor passes through the probe's height band (or meets the floor,
for drops); elsewhere nothing can be seen. A static robot, one frame: confirmation over frames always succeeds.

Summary for the UI:
  stop       distance needed to stop from vx_max: vx_max * reaction + vx_max^2 / (2 ax_max)
  corridor   the strip the robot drives through (robot width + probe), per lateral bin: 'ok' when the probe is seen
             while there is still room to stop, 'late' when it is only seen closer, 'blind' when never
  ring       share of cells detected within `ring` m around the footprint, by direction (front / left / right / back)
"""
import math
import time

import numpy as np

from . import robot as robotlib, sensortypes
from .sensortypes.geometry import mount_pose
from .sim.raycast import Scene3D

PROBES = {
    'low': dict(kind='box', size=0.10, z0=0.0, z1=0.05, label='낮은 턱 5 cm'),
    'threshold': dict(kind='box', size=0.10, z0=0.0, z1=0.015, label='문턱 1.5 cm'),
    'overhang': dict(kind='box', size=0.30, z0=0.25, z1=0.30, label='공중 25~30 cm'),
    'leg': dict(kind='pole', size=0.05, z0=0.0, z1=0.45, label='의자 다리 지름 5 cm'),
    'box': dict(kind='box', size=0.30, z0=0.0, z1=1.0, label='박스 30 cm'),
    'drop': dict(kind='drop', size=0.30, depth=0.10, label='단차 깊이 10 cm'),
}
REACTION_S = 0.1          # sensor + costmap update, on top of the perception confirmation time
MAX_CELLS = 40000


def probe_spec(p):
    """A probe from a preset id and/or explicit fields -> validated dict."""
    p = dict(p or {})
    base = dict(PROBES.get(p.get('preset') or 'low', PROBES['low']))
    base.update({k: v for k, v in p.items() if k in ('kind', 'size', 'z0', 'z1', 'depth', 'label') and v is not None})
    if base['kind'] not in ('box', 'pole', 'drop'):
        raise ValueError(f"알 수 없는 물체 종류: {base['kind']}")
    base['size'] = float(base['size'])
    if not 0.01 <= base['size'] <= 2.0:
        raise ValueError('물체 크기는 0.01~2 m 사이여야 합니다')
    if base['kind'] == 'drop':
        base['depth'] = float(base.get('depth', 0.1))
        if not 0.005 <= base['depth'] <= 3.0:
            raise ValueError('단차 깊이는 0.005~3 m 사이여야 합니다')
    else:
        base['z0'], base['z1'] = float(base.get('z0', 0.0)), float(base.get('z1', 1.0))
        if not 0.0 <= base['z0'] < base['z1'] <= 3.0:
            raise ValueError('물체 높이는 0 ≤ 아래 < 위 ≤ 3 m 이어야 합니다')
    return base


def perception_params(R, overrides=None):
    from .sim.perception import DEFAULTS
    p = dict(DEFAULTS, obstacle_max_height=round(float(R['body']['height']) + 0.05, 3))
    p.update(overrides or {})
    return p


# ------------------------------------------------------------------ footprint
def _footprint(R):
    fp = R['footprint']
    if fp['type'] == 'circle':
        r = float(fp['radius'])
        return dict(circle=r, front=r, half_width=r, poly=None)
    pts = np.asarray(fp['points'], float)
    return dict(circle=None, front=float(pts[:, 0].max()), half_width=float(np.abs(pts[:, 1]).max()), poly=pts)


def _footprint_distance(fp, x, y):
    """Distance from points to the footprint outline (negative inside)."""
    if fp['circle'] is not None:
        return np.hypot(x, y) - fp['circle']
    P = fp['poly']
    a, b = P, np.roll(P, -1, axis=0)
    px, py = x[..., None], y[..., None]
    dx, dy = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
    L = np.maximum(dx * dx + dy * dy, 1e-12)
    t = np.clip(((px - a[:, 0]) * dx + (py - a[:, 1]) * dy) / L, 0, 1)
    d = np.hypot(px - (a[:, 0] + t * dx), py - (a[:, 1] + t * dy)).min(axis=-1)
    cross = ((a[:, 1] > py) != (b[:, 1] > py)) & (px < (b[:, 0] - a[:, 0]) * (py - a[:, 1]) / np.where(np.abs(b[:, 1] - a[:, 1]) < 1e-12, 1e-12, b[:, 1] - a[:, 1]) + a[:, 0])
    inside = cross.sum(axis=-1) % 2 == 1
    return np.where(inside, -d, d)


# ------------------------------------------------------------------ per sensor
def _probe_region(probe, cx, cy, margin):
    """Mask function: points (x, y) on the probe grown by margin."""
    h = probe['size'] / 2 + margin
    if probe['kind'] == 'pole':
        return lambda x, y: np.hypot(x - cx, y - cy) <= h
    return lambda x, y: (np.abs(x - cx) <= h) & (np.abs(y - cy) <= h)


def _lidar(s, probe, X, Y):
    """Planar scanner: the probe crosses the scan plane and one beam meets it within range."""
    if probe['kind'] == 'drop' or not probe['z0'] <= s['z'] <= probe['z1']:
        return np.zeros(X.shape, bool)
    fov = math.radians(min(float(s['fov_deg']), 360.0))
    n = int(s['beams'])
    full = fov >= 2 * math.pi - 1e-6
    inc = 2 * math.pi / n if full else fov / max(n - 1, 1)
    dx, dy = X - s['x'], Y - s['y']
    dist = np.hypot(dx, dy)
    half = probe['size'] / 2
    near = dist - (half * math.sqrt(2) if probe['kind'] == 'box' else half)     # conservative for boxes
    ang = np.arctan2(dy, dx) - math.radians(s['yaw_deg'])
    ang = (ang + math.pi) % (2 * math.pi) - math.pi
    alpha = np.arcsin(np.clip(half / np.maximum(dist, 1e-6), 0, 1))
    if full:
        lo = np.ceil((ang - alpha + math.pi) / inc)
        hi = np.floor((ang + alpha + math.pi) / inc)
        beam = hi >= lo
    else:
        lo = np.maximum(np.ceil((ang - alpha + fov / 2) / inc), 0)
        hi = np.minimum(np.floor((ang + alpha + fov / 2) / inc), n - 1)
        beam = hi >= lo
    return beam & (near <= float(s['range_max'])) & (dist >= float(s['range_min']))


def _clean_mount(s, kind):
    """The mount with every noise / dropout parameter of its type set to 0."""
    m = dict(s)
    for p in kind.all_params():
        if p.group == '잡음' and p.kind in ('float', 'int'):
            m[p.key] = 0
    return m


def _candidate_cells(probe, o, d, t_floor, rmax, xs, ys, res):
    """Cells where the probe could meet a ray: the part of each ray inside the probe's height band (obstacles),
    or where the ray meets the floor (drops)."""
    nx, ny = len(xs), len(ys)
    mask = np.zeros((ny, nx), bool)
    grow = probe['size'] / 2 + res
    if probe['kind'] == 'drop':
        tf = np.where(np.isfinite(t_floor) & (t_floor <= rmax), t_floor, np.nan)
        ok = np.isfinite(tf)
        pts = o[None, :2] + d[ok, :2] * tf[ok, None]
    else:
        z0, z1 = probe['z0'], probe['z1']
        with np.errstate(divide='ignore', invalid='ignore'):
            ta = np.where(np.abs(d[:, 2]) > 1e-9, (z0 - o[2]) / d[:, 2], np.where((o[2] >= z0) & (o[2] <= z1), 0.0, np.nan))
            tb = np.where(np.abs(d[:, 2]) > 1e-9, (z1 - o[2]) / d[:, 2], np.where((o[2] >= z0) & (o[2] <= z1), rmax, np.nan))
        t0 = np.clip(np.minimum(ta, tb), 0, None)
        t1 = np.minimum(np.maximum(ta, tb), np.minimum(np.where(np.isfinite(t_floor), t_floor, rmax), rmax))
        ok = np.isfinite(t0) & np.isfinite(t1) & (t1 >= t0)
        if not ok.any():
            return mask
        t0, t1, dd = t0[ok], t1[ok], d[ok]
        step = max(res / 2, 0.01)
        n = np.maximum(np.ceil((t1 - t0) / step).astype(int), 0) + 1
        idx = np.repeat(np.arange(len(t0)), n)
        k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
        tt = np.minimum(t0[idx] + k * step, t1[idx])
        pts = o[None, :2] + dd[idx, :2] * tt[:, None]
    if not len(pts):
        return mask
    r = int(math.ceil(grow / res))
    ix = np.round((pts[:, 0] - xs[0]) / res).astype(int)
    iy = np.round((pts[:, 1] - ys[0]) / res).astype(int)
    keep = (ix >= -r) & (ix < nx + r) & (iy >= -r) & (iy < ny + r)
    ix, iy = ix[keep], iy[keep]
    for ox in range(-r, r + 1):
        for oy in range(-r, r + 1):
            jx, jy = ix + ox, iy + oy
            ok2 = (jx >= 0) & (jx < nx) & (jy >= 0) & (jy < ny)
            mask[jy[ok2], jx[ok2]] = True
    return mask


def _sensor_3d(s, probe, xs, ys, mode, cfg, inside):
    """Cells where a 3D sensor's data, through the perception rules (or raw points), shows the probe."""
    kind = sensortypes.get(s['type'])
    m = _clean_mount(s, kind)
    rays = kind.rays(m)
    rot, pos = mount_pose(m)
    d = rays.reshape(-1, 3) @ rot.T
    rmax = float(m['range_max'])
    scene = Scene3D(np.zeros((1, 1), bool), 1.0, (1e6, 1e6), wall_height=0.0)
    t_floor = scene._floor(pos, d)
    cand = _candidate_cells(probe, pos, d, t_floor, rmax, xs, ys, xs[1] - xs[0]) & ~inside
    out = np.zeros(cand.shape, bool)
    if mode == 'off':
        return out, cand
    rng = np.random.default_rng(0)
    zones = kind.perception_input[0] == 'zones'
    margin = max(cfg['merge_radius'], 0.03)

    def run(t):
        t = np.where(t <= rmax, t, np.inf)
        meas = kind.measure(m, rays, t, rng)
        if mode == 'direct':
            pb = np.asarray(meas.points, float).reshape(-1, 3) @ rot.T + pos
            top = cfg['obstacle_max_height']
            return pb[(pb[:, 2] >= 0.02) & (pb[:, 2] <= top), :2], np.zeros((0, 2))
        ob, dr = kind.perceive(m, meas.raw if zones else meas.points, cfg)
        near = lambda a: a[np.hypot(a[:, 0], a[:, 1]) <= cfg['max_range']] if len(a) else a
        return near(np.asarray(ob, float).reshape(-1, 2)), near(np.asarray(dr, float).reshape(-1, 2))

    base_ob, base_dr = run(t_floor)
    for iy, ix in zip(*np.nonzero(cand)):
        cx, cy = xs[ix], ys[iy]
        if probe['kind'] == 'drop':
            if mode == 'direct':
                continue                                   # raw points never mark a drop
            scene.drops = np.array([[cx - probe['size'] / 2, cy - probe['size'] / 2, cx + probe['size'] / 2, cy + probe['size'] / 2, probe['depth']]])
            t = scene._floor(pos, d)
            scene.drops = np.zeros((0, 5))
            _, pts = run(t)
            base = base_dr
        else:
            h = probe['size'] / 2
            if probe['kind'] == 'pole':
                to = Scene3D._cylinders(pos, d, np.array([[cx, cy, h, probe['z0'], probe['z1']]]))
            else:
                to = Scene3D._boxes(pos, d, np.array([[cx, cy, h, h, 0.0, probe['z0'], probe['z1']]]))
            pts, _ = run(np.minimum(t_floor, to))
            base = base_ob
        if not len(pts):
            continue
        hit = _probe_region(probe, cx, cy, margin)
        out[iy, ix] = hit(pts[:, 0], pts[:, 1]).sum() > (hit(base[:, 0], base[:, 1]).sum() if len(base) else 0)
    return out, cand


# ------------------------------------------------------------------ main
def compute(R, probe=None, extent=None, res=0.05, params=None):
    """Coverage grid and summary for robot profile R (normalized here) and a probe (see PROBES)."""
    t_start = time.monotonic()
    R = robotlib.normalize(R)
    probe = probe_spec(probe)
    cfg = perception_params(R, params)
    res = float(min(max(res, 0.02), 0.2))
    fp = _footprint(R)
    reach = max([fp['front'], fp['half_width']] + [math.hypot(s['x'], s['y']) for s in R['sensors']])
    if extent is None:
        far = max([min(float(s['range_max']), 2.0) for s in R['sensors'] if s['enabled']] + [1.0])
        extent = reach + far
    extent = float(min(max(extent, 0.5), 4.0))
    n = int(math.ceil(extent / res))
    if (2 * n + 1) ** 2 > MAX_CELLS:
        n = int((math.sqrt(MAX_CELLS) - 1) / 2)
        res = extent / n
    xs = ys = (np.arange(-n, n + 1) * res)
    X, Y = np.meshgrid(xs, ys)
    dist = _footprint_distance(fp, X, Y)
    clear = probe['size'] / 2 if probe['kind'] != 'drop' else 0.0
    inside = dist < clear                       # the probe would overlap the robot (obstacles) / lie under it (drops)
    mode = R['perception']['mode']
    sensors, masks, notes = [], [], []
    for s in R['sensors']:
        if not s['enabled']:
            continue
        if s['type'] == 'lidar2d':
            det, used = _lidar(s, probe, X, Y) & ~inside, True
        else:
            det, cand = _sensor_3d(s, probe, xs, ys, mode, cfg, inside)
            used = mode != 'off'
            if not used and cand.any():
                notes.append(f"{s['name']}: 인식 처리가 꺼져 있어 Nav2 에 쓰이지 않습니다")
        sensors.append(dict(name=s['name'], type=s['type'], color=s.get('color') or '#888888', used=used, cells=int(det.sum())))
        masks.append(det if used else np.zeros_like(det))
    bits = np.zeros(X.shape, np.uint32)
    for i, m in enumerate(masks[:32]):
        bits |= (m.astype(np.uint32) << np.uint32(i))
    any_det = bits > 0
    # notes the user should read with the picture
    if probe['kind'] == 'box' and probe['z1'] <= float(R['climb_height']):
        notes.append(f"높이 {probe['z1'] * 100:.1f} cm 는 등반 높이({float(R['climb_height']) * 100:.1f} cm) 이하라 로봇이 넘어갑니다. 감지할 필요가 없습니다")
    elif probe['kind'] == 'box' and probe['z0'] >= float(R['body']['height']):
        notes.append('차체보다 높이 떠 있어 로봇이 아래로 지나갑니다')
    elif probe['kind'] != 'drop' and probe['z1'] < cfg['obstacle_min_height'] and mode == 'rules':
        notes.append(f"높이가 인식 최소 높이({cfg['obstacle_min_height'] * 100:.0f} cm)보다 낮아 ToF·Depth 규칙으로는 장애물이 되지 않습니다")
    if probe['kind'] == 'drop' and mode == 'direct':
        notes.append('원시 점 모드는 단차를 표시하지 않습니다 (규칙 기반 인식을 쓰세요)')
    summary = _summary(R, probe, cfg, fp, xs, ys, X, Y, dist, any_det, inside)
    return dict(res=res, x0=float(xs[0]), y0=float(ys[0]), nx=len(xs), ny=len(ys), probe=probe, sensors=sensors,
                bits=bits.ravel().tolist(), inside=np.flatnonzero(inside.ravel()).tolist() if inside.sum() < 4000 else [],
                summary=summary, notes=notes, mode=mode, ms=round((time.monotonic() - t_start) * 1000))


def _summary(R, probe, cfg, fp, xs, ys, X, Y, dist, det, inside):
    lim = R['limits']
    v, a = float(lim['vx_max']), max(float(lim['ax_max']), 1e-3)
    react = REACTION_S + float(cfg['confirm_frames']) / float(cfg['rate_hz'])
    stop = v * react + v * v / (2 * a)
    drop = probe['kind'] == 'drop'
    half = probe['size'] / 2
    # corridor straight ahead: lateral bins across the swept width (+ probe), first sighting distance in each
    width = (half if drop else fp['half_width'] + half)
    res = xs[1] - xs[0]
    cols = np.abs(ys) <= width + 1e-9
    room = (X - half) - (0.0 if drop else fp['front'])          # free distance left between robot and probe
    bins = []
    for iy in np.nonzero(cols)[0]:
        row = det[iy] & (X[iy] > 0) & ~inside[iy]
        seen = room[iy][row]
        first = float(seen.max()) if len(seen) else None
        state = 'blind' if first is None else ('ok' if first >= stop else 'late')
        bins.append(dict(y=round(float(ys[iy]), 3), state=state, first=None if first is None else round(first, 3)))
    cnt = lambda st: sum(b['state'] == st for b in bins) / max(len(bins), 1)
    centre = min(bins, key=lambda b: abs(b['y'])) if bins else None
    # ring around the footprint, by direction
    ring_w = 0.5
    ring = (dist >= (0.0 if drop else half)) & (dist <= ring_w + (0.0 if drop else half)) & ~inside
    ang = np.degrees(np.arctan2(Y, X))
    sectors = dict(front=np.abs(ang) <= 45, left=(ang > 45) & (ang < 135), right=(ang < -45) & (ang > -135), back=np.abs(ang) >= 135)
    ring_cov = {k: round(float(det[ring & m].mean()), 3) if (ring & m).any() else None for k, m in sectors.items()}
    return dict(v=v, a=a, reaction=round(react, 3), stop=round(stop, 3), front=round(fp['front'], 3),
                corridor=dict(half_width=round(width, 3), ok=round(cnt('ok'), 3), late=round(cnt('late'), 3), blind=round(cnt('blind'), 3),
                              centre=centre, bins=bins),
                ring=dict(width=ring_w, **ring_cov), res=round(float(res), 4))
