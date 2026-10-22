"""Bundled and user maps: listing, metadata, rendering for the UI, upload."""
import functools
import io
import json
import os
import re
import shutil

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

from . import paths

_cache = {}


def _index():
    f = paths.data('maps', 'index.yaml')
    return yaml.safe_load(open(f)) if os.path.exists(f) else {}


def list_maps():
    idx = _index()
    out = []
    for d, builtin in ((paths.data('maps'), True), (paths.user('maps'), False)):
        if not os.path.isdir(d):
            continue
        for mid in sorted(os.listdir(d)):
            y = os.path.join(d, mid, 'map.yaml')
            if os.path.exists(y):
                info = idx.get(mid, {}) if builtin else _user_info(mid)
                out.append(dict(id=mid, builtin=builtin, name=info.get('name', mid), group=info.get('group', '내 맵'),
                                description=info.get('description', ''), **_size(mid)))
    return out


def _user_info(mid):
    f = paths.user('maps', mid, 'info.json')
    return json.load(open(f)) if os.path.exists(f) else {}


def yaml_path(mid):
    for d in (paths.user('maps'), paths.data('maps')):
        f = os.path.join(d, mid, 'map.yaml')
        if os.path.exists(f):
            return f
    raise KeyError(mid)


def load(mid):
    if mid in _cache:
        return _cache[mid]
    yp = yaml_path(mid)
    meta = yaml.safe_load(open(yp))
    img = np.array(Image.open(os.path.join(os.path.dirname(yp), meta['image'])).convert('L'), dtype=np.float32)
    p = (255.0 - img) / 255.0 if not meta.get('negate', 0) else img / 255.0
    occ = p > meta.get('occupied_thresh', 0.65)
    unk = (p > meta.get('free_thresh', 0.196)) & ~occ
    m = dict(occ=np.flipud(occ), unk=np.flipud(unk), res=float(meta['resolution']),
             origin=[float(v) for v in meta['origin'][:2]])
    m['H'], m['W'] = m['occ'].shape
    _cache[mid] = m
    return m


def _size(mid):
    try:
        m = load(mid)
        return dict(width_m=round(m['W'] * m['res'], 1), height_m=round(m['H'] * m['res'], 1))
    except Exception:
        return {}


def meta(mid):
    m = load(mid)
    if 'start' not in m:
        solid = m['occ'] | m['unk']
        dist = ndimage.distance_transform_edt(~solid) * m['res']
        lab, n = ndimage.label(dist > 0.3)
        start = [m['origin'][0] + m['W'] * m['res'] / 2, m['origin'][1] + m['H'] * m['res'] / 2, 0.0]
        if n:
            sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
            main = int(np.argmax(sizes)) + 1
            d2 = np.where(lab == main, dist, 0)
            iy, ix = np.unravel_index(np.argmax(d2), d2.shape)
            start = [m['origin'][0] + (ix + 0.5) * m['res'], m['origin'][1] + (iy + 0.5) * m['res'], 0.0]
        m['start'] = [round(v, 3) for v in start]
        m['dist'] = dist
    return dict(id=mid, resolution=m['res'], origin=m['origin'], width=m['W'], height=m['H'], start=m['start'])


@functools.lru_cache(maxsize=64)
def grid_png(mid):
    """3-level PNG for the UI to colourise per theme: 0 free, 1 occupied, 2 unknown (row 0 = top)."""
    m = load(mid)
    g = np.zeros(m['occ'].shape, np.uint8)
    g[m['unk']] = 2
    g[m['occ']] = 1
    buf = io.BytesIO()
    Image.fromarray(np.flipud(g)).save(buf, format='PNG', optimize=True)
    return buf.getvalue()


@functools.lru_cache(maxsize=128)
def thumb_png(mid, size=240):
    m = load(mid)
    solid = m['occ'] | m['unk']
    free = ~solid
    ys, xs = np.where(free)
    if len(xs):
        pad = 10
        y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad, m['H'])
        x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad, m['W'])
    else:
        y0, y1, x0, x1 = 0, m['H'], 0, m['W']
    rgba = np.zeros((m['H'], m['W'], 4), np.uint8)
    rgba[free] = (255, 255, 255, 255)
    rgba[m['occ']] = (60, 70, 78, 255)
    crop = np.flipud(rgba[y0:y1, x0:x1])
    im = Image.fromarray(crop)
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def save_upload(name, yaml_bytes, image_bytes, image_name):
    """Store a user map. Accepts a ROS map_server YAML + image (pgm/png)."""
    mid = re.sub(r'[^a-zA-Z0-9_-]+', '_', name.strip()).strip('_').lower() or 'map'
    d = paths.user('maps', mid)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    meta = yaml.safe_load(yaml_bytes)
    if not isinstance(meta, dict) or 'resolution' not in meta or 'origin' not in meta:
        raise ValueError('맵 YAML 에 resolution 과 origin 이 필요합니다')
    ext = os.path.splitext(image_name)[1].lower() or '.pgm'
    with open(os.path.join(d, 'map' + ext), 'wb') as f:
        f.write(image_bytes)
    meta['image'] = 'map' + ext
    meta.setdefault('mode', 'trinary')
    meta.setdefault('negate', 0)
    meta.setdefault('occupied_thresh', 0.65)
    meta.setdefault('free_thresh', 0.196)
    with open(os.path.join(d, 'map.yaml'), 'w') as f:
        yaml.safe_dump(meta, f)
    json.dump(dict(name=name.strip(), group='내 맵', description='업로드한 맵'), open(os.path.join(d, 'info.json'), 'w'),
              ensure_ascii=False)
    _cache.pop(mid, None)
    grid_png.cache_clear()
    thumb_png.cache_clear()
    load(mid)  # validate the image
    return mid


def delete(mid):
    d = paths.user('maps', mid)
    if not os.path.isdir(d):
        raise KeyError(mid)
    shutil.rmtree(d)
    _cache.pop(mid, None)
    grid_png.cache_clear()
    thumb_png.cache_clear()


def footprint_clearance(mid, pose, polygon):
    """Smallest distance (m) from the footprint outline at pose to a wall/unknown cell (negative: overlaps)."""
    import math
    m = load(mid)
    meta(mid)
    dist = m['dist']
    c, s_ = math.cos(pose[2]), math.sin(pose[2])
    best = 1e9
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        k = max(1, int(math.hypot(x1 - x0, y1 - y0) / (m['res'] / 2)))
        for j in range(k):
            a = j / k
            bx, by = x0 + a * (x1 - x0), y0 + a * (y1 - y0)
            wx, wy = pose[0] + c * bx - s_ * by, pose[1] + s_ * bx + c * by
            ix, iy = int((wx - m['origin'][0]) / m['res']), int((wy - m['origin'][1]) / m['res'])
            d = dist[iy, ix] if 0 <= ix < m['W'] and 0 <= iy < m['H'] else 0.0
            best = min(best, d - m['res'] / 2)
    return round(float(best), 3)
