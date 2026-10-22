"""Robot profiles: drive type, footprint, sensors and physical limits.

A profile describes the *physical* robot. The simulator uses all of it; Nav2 gets the footprint, the
sensor topics and the kinematic structure (paramgen.robot_overrides). Nav2 speed limits stay Nav2 parameters
(the parameter panel can copy them from the profile with one click).
"""
import copy
import math
import os

import yaml

from . import paths

DRIVES = ('diff', 'omni', 'ackermann')

DEFAULT = {
    'name': 'Robot',
    'description': '',
    'drive': 'diff',
    'footprint': {'type': 'circle', 'radius': 0.175, 'points': []},
    'footprint_padding': 0.015,
    'body': {'height': 0.09, 'color': '#3d4b55'},
    'wheels': {'track': 0.27, 'radius': 0.045, 'wheelbase': 0.0, 'max_steer_deg': 0.0},
    'limits': {'vx_max': 0.5, 'vx_min': -0.2, 'vy_max': 0.0, 'wz_max': 1.5,
               'ax_max': 1.0, 'ay_max': 1.0, 'az_max': 4.0},
    'actuator': {'tau': 0.08, 'slip_lin': 0.02, 'slip_ang': 0.03},
    'sensors': [{'name': 'scan', 'type': 'lidar2d', 'x': 0.0, 'y': 0.0, 'z': 0.107, 'yaw_deg': 0.0,
                 'fov_deg': 360.0, 'beams': 360, 'range_min': 0.17, 'range_max': 8.0, 'hz': 10.0, 'noise': 0.01}],
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def normalize(profile):
    """Fill defaults and validate. Raises ValueError with a user-readable message."""
    p = _merge(DEFAULT, profile)
    if p['drive'] not in DRIVES:
        raise ValueError(f"구동 방식은 {', '.join(DRIVES)} 중 하나여야 합니다 (받은 값: {p['drive']})")
    fp = p['footprint']
    if fp['type'] == 'circle':
        if not 0.02 <= float(fp['radius']) <= 3.0:
            raise ValueError('원형 footprint 반지름은 0.02~3.0 m 사이여야 합니다')
    elif fp['type'] == 'polygon':
        pts = fp.get('points') or []
        if len(pts) < 3:
            raise ValueError('다각형 footprint 는 꼭짓점이 3개 이상 필요합니다')
        fp['points'] = [[float(x), float(y)] for x, y in pts]
    else:
        raise ValueError("footprint.type 은 'circle' 또는 'polygon' 이어야 합니다")
    if p['drive'] == 'ackermann':
        if p['wheels']['wheelbase'] <= 0 or not 1 <= p['wheels']['max_steer_deg'] < 89:
            raise ValueError('차량형(ackermann)은 wheelbase > 0, 최대 조향각 1~89° 가 필요합니다')
    if p['drive'] != 'omni':
        p['limits']['vy_max'] = 0.0
    names = set()
    for s in p['sensors']:
        s.update(_merge(DEFAULT['sensors'][0], s))
        if s['name'] in names or not s['name'].replace('_', '').isalnum():
            raise ValueError(f"센서 이름 '{s['name']}' 이 중복되었거나 영문/숫자/_ 가 아닙니다")
        names.add(s['name'])
        if not 1 <= float(s['fov_deg']) <= 360:
            raise ValueError('라이다 FOV 는 1~360° 입니다')
    if not p['sensors']:
        raise ValueError('라이다가 최소 1개 필요합니다')
    return p


def polygon(profile, n_circle=24):
    """Footprint outline as a polygon in base_link frame."""
    fp = profile['footprint']
    if fp['type'] == 'circle':
        r = fp['radius']
        return [[r * math.cos(2 * math.pi * i / n_circle), r * math.sin(2 * math.pi * i / n_circle)] for i in range(n_circle)]
    return fp['points']


def outline_samples(profile, spacing=0.02):
    """Points along the footprint outline (for collision/clearance checks in the simulator)."""
    poly = polygon(profile, 48)
    out = []
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / spacing)))
        for k in range(n):
            a = k / n
            out.append([x0 + a * (x1 - x0), y0 + a * (y1 - y0)])
    return out


def inscribed_circumscribed(profile):
    poly = polygon(profile, 48)
    circ = max(math.hypot(x, y) for x, y in poly)
    if profile['footprint']['type'] == 'circle':
        return profile['footprint']['radius'], circ
    # distance from origin to each edge
    ins = 1e9
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        L = math.hypot(x1 - x0, y1 - y0) or 1e-9
        ins = min(ins, abs((x1 - x0) * y0 - (y1 - y0) * x0) / L)
    return ins, circ


def min_turning_radius(profile):
    w = profile['wheels']
    if profile['drive'] != 'ackermann':
        return 0.0
    return w['wheelbase'] / math.tan(math.radians(w['max_steer_deg']))


# ------------------------------------------------------------------ storage
def list_profiles():
    out = []
    for d, builtin in ((paths.data('robots'), True), (paths.user('robots'), False)):
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith('.yaml'):
                rid = fn[:-5]
                try:
                    p = normalize(yaml.safe_load(open(os.path.join(d, fn))))
                except Exception as e:  # keep listing the rest
                    p = dict(DEFAULT, name=f'{rid} (오류: {e})')
                out.append(dict(id=rid, builtin=builtin, name=p['name'], drive=p['drive'],
                                description=p.get('description', '')))
    return out


def load(rid):
    for d in (paths.user('robots'), paths.data('robots')):
        f = os.path.join(d, rid + '.yaml')
        if os.path.exists(f):
            return normalize(yaml.safe_load(open(f)))
    raise KeyError(rid)


def save(rid, profile):
    if not rid.replace('_', '').replace('-', '').isalnum():
        raise ValueError('로봇 ID 는 영문/숫자/-/_ 만 쓸 수 있습니다')
    p = normalize(profile)
    os.makedirs(paths.user('robots'), exist_ok=True)
    with open(os.path.join(paths.user('robots'), rid + '.yaml'), 'w') as f:
        yaml.safe_dump(p, f, sort_keys=False, allow_unicode=True)
    return p


def delete(rid):
    f = os.path.join(paths.user('robots'), rid + '.yaml')
    if not os.path.exists(f):
        raise KeyError(rid)
    os.remove(f)
