"""Sensor models (the library) and sensor mounts (a model placed on a robot).

Sensor *types* are plugins (navstudio/sensortypes/: lidar2d, tof, ultrasonic, depth, plus any .py in
<NAVSTUDIO_HOME>/sensor_types/); each declares its parameters, how it is simulated and what it publishes.

A *model* is a type + parameter values with a name (e.g. "8x8 multizone ToF"). Built-in models are
data/sensors/<id>.yaml, the user's are <NAVSTUDIO_HOME>/sensors/<id>.yaml.

A *mount* is one sensor on a robot: a unique name, its pose on base_link (x, y, z above the floor, roll/pitch/yaw in
degrees; positive pitch tilts the sensor down) and the full parameters copied from the model (robot files stay
self-contained); `model` remembers where they came from. Old robot files list 2D lidars only; they load unchanged.
"""
import copy
import os
import re

import yaml

from . import paths, sensortypes
from .sensortypes.geometry import floor_distance, quaternion, rotation  # noqa: F401  (re-exported)
from .sensortypes.depth import depth_rays  # noqa: F401
from .sensortypes.tof import active_zones, zone_rays, zone_tangents  # noqa: F401
from .sensortypes.ultrasonic import cone_rays  # noqa: F401

POSE = {'x': 0.0, 'y': 0.0, 'z': 0.1, 'roll_deg': 0.0, 'pitch_deg': 0.0, 'yaw_deg': 0.0}
MODEL_KEYS = ('name', 'type', 'description', 'mount_hint')
ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')
NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,31}$')


def types():
    return sensortypes.types()


def label(t):
    return sensortypes.get(t).label


def params_of(d):
    """Measurement parameters of a model or mount (no pose, no names)."""
    st = sensortypes.get(d.get('type', 'lidar2d'))
    return {p.key: d[p.key] for p in st.all_params() if p.key in d}


def normalize_model(m):
    st = sensortypes.get((m or {}).get('type', 'lidar2d'))
    out = st.defaults()
    out.update({k: v for k, v in m.items() if k in out})
    out.update(type=st.type, name=str(m.get('name') or st.label).strip(), description=str(m.get('description') or ''))
    if m.get('mount_hint'):
        out['mount_hint'] = {k: float(v) for k, v in m['mount_hint'].items() if k in POSE}
    return st.check(out, out['name'])


def normalize_mount(s):
    """A robot's sensor entry: name + pose + full parameters (+ model id)."""
    st = sensortypes.get(s.get('type', 'lidar2d'))
    out = dict(st.defaults(), **POSE)
    if st.type == 'lidar2d':
        out['z'] = 0.107
    keys = set(out)
    out.update({k: v for k, v in s.items() if k in keys})
    out.update(name=str(s.get('name', '')), type=st.type, enabled=bool(s.get('enabled', True)))
    if s.get('model'):
        out['model'] = str(s['model'])
    if not NAME_RE.match(out['name']):
        raise ValueError(f"센서 이름 '{out['name']}' 은 영문으로 시작하는 영문/숫자/_ 32자 이내여야 합니다")
    for k in POSE:
        out[k] = float(out[k])
    if not -0.5 <= out['z'] <= 3.0:
        raise ValueError(f"센서 '{out['name']}': 높이 z 는 바닥 기준 -0.5~3 m 입니다")
    return st.check(out, f"센서 '{out['name']}'")


# ------------------------------------------------------------------ library storage
def _read(f, builtin):
    m = normalize_model(yaml.safe_load(open(f)) or {})
    m.update(id=os.path.basename(f)[:-5], builtin=builtin)
    return m


def list_models():
    out = []
    for d, builtin in ((paths.data('sensors'), True), (paths.user('sensors'), False)):
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.yaml'):
                    try:
                        out.append(_read(os.path.join(d, fn), builtin))
                    except Exception as e:  # keep listing the rest
                        out.append(dict(id=fn[:-5], builtin=builtin, type='?', name=f'{fn[:-5]} (오류: {e})', broken=True))
    return out


def get_model(mid):
    for d, builtin in ((paths.user('sensors'), False), (paths.data('sensors'), True)):
        f = os.path.join(d, mid + '.yaml')
        if os.path.exists(f):
            return _read(f, builtin)
    raise KeyError(mid)


def _builtin_ids():
    d = paths.data('sensors')
    return {fn[:-5] for fn in os.listdir(d) if fn.endswith('.yaml')} if os.path.isdir(d) else set()


def save_model(body, mid=None):
    m = normalize_model(body)
    if mid is None:
        base = re.sub(r'[^a-z0-9_-]+', '-', m['name'].lower()).strip('-')[:40]
        base = base if base and base[0].isalnum() else m['type']
        taken = _builtin_ids() | {x['id'] for x in list_models()}
        mid, k = base, 2
        while mid in taken:
            mid, k = f'{base}-{k}', k + 1
    if not ID_RE.match(mid):
        raise ValueError('잘못된 센서 id 입니다')
    if mid in _builtin_ids():
        raise PermissionError('기본 센서는 바꿀 수 없습니다. 다른 이름으로 저장하세요.')
    os.makedirs(paths.user('sensors'), exist_ok=True)
    doc = {k: m[k] for k in MODEL_KEYS if k in m}
    doc.update(params_of(m))
    with open(paths.user('sensors', mid + '.yaml'), 'w') as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    return get_model(mid)


def delete_model(mid):
    f = paths.user('sensors', mid + '.yaml')
    if not ID_RE.match(mid) or not os.path.exists(f):
        raise KeyError(mid)
    os.remove(f)


def mount_from_model(model, name, **pose):
    """A new mount of a library model (pose: mount_hint, then the given values)."""
    m = dict(params_of(model), type=model['type'], name=name, model=model.get('id'))
    m.update(copy.deepcopy(model.get('mount_hint') or {}))
    m.update(pose)
    return normalize_mount(m)
