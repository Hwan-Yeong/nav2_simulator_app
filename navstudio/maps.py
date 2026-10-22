"""Bundled and user maps: listing, metadata, rendering for the UI, import / export / rename / delete.

A user map lives in <NAVSTUDIO_HOME>/maps/<id>/: map.yaml + map.pgm|png, info.json (name, group, description) and an
optional scenarios.json. The same layout, one directory per map, is the zip format for import and export.
"""
import functools
import io
import json
import os
import posixpath
import re
import shutil
import zipfile

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
                                description=info.get('description', ''), scenarios=len(scenarios(mid)), **_size(mid)))
    return out


def scenarios(mid):
    """Prepared episodes for a map: bundled data/scenarios/<id>.json or the user map's scenarios.json."""
    for f in (paths.user('maps', mid, 'scenarios.json'), paths.data('scenarios', mid + '.json')):
        if os.path.exists(f):
            try:
                return json.load(open(f))
            except ValueError:
                return []
    return []


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


IMAGE_EXT = ('.pgm', '.png', '.jpg', '.jpeg', '.bmp')


def _exists(mid):
    return os.path.isdir(paths.user('maps', mid)) or os.path.isdir(paths.data('maps', mid))


def _slug(s):
    return re.sub(r'[^a-zA-Z0-9_-]+', '_', (s or '').strip()).strip('_').lower()[:40]


def _new_id(*hints):
    base = next((_slug(h) for h in hints if _slug(h)), 'map')
    mid, k = base, 2
    while _exists(mid):
        mid, k = f'{base}_{k}', k + 1
    return mid


def _forget(mid):
    _cache.pop(mid, None)
    grid_png.cache_clear()
    thumb_png.cache_clear()


def _store(name, meta, image_bytes, image_name, info=None, scen=None, id_hint=None):
    """Write one validated user map; returns its id."""
    if not isinstance(meta, dict) or 'resolution' not in meta or 'origin' not in meta:
        raise ValueError('맵 YAML 에 resolution 과 origin 이 필요합니다')
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception:
        raise ValueError(f'맵 이미지를 읽지 못했습니다: {image_name}')
    info = dict(info or {})
    info['name'] = (info.get('name') or name).strip() or 'map'
    taken = {m['name'] for m in list_maps()}
    base, k = info['name'], 2
    while info['name'] in taken:   # keep cards distinguishable when the same map is added twice
        info['name'], k = f'{base} ({k})', k + 1
    info.setdefault('group', '내 맵')
    info.setdefault('description', '')
    mid = _new_id(id_hint, info['name'], name)
    d = paths.user('maps', mid)
    os.makedirs(d)
    try:
        ext = os.path.splitext(image_name)[1].lower() or '.pgm'
        with open(os.path.join(d, 'map' + ext), 'wb') as f:
            f.write(image_bytes)
        meta = dict(meta, image='map' + ext)
        meta.setdefault('mode', 'trinary')
        meta.setdefault('negate', 0)
        meta.setdefault('occupied_thresh', 0.65)
        meta.setdefault('free_thresh', 0.196)
        with open(os.path.join(d, 'map.yaml'), 'w') as f:
            yaml.safe_dump(meta, f)
        json.dump(info, open(os.path.join(d, 'info.json'), 'w'), ensure_ascii=False, indent=1)
        if scen:
            json.dump(scen, open(os.path.join(d, 'scenarios.json'), 'w'))
        _forget(mid)
        load(mid)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        _forget(mid)
        raise
    return mid


def save_upload(name, yaml_bytes, image_bytes, image_name):
    """Store one map from a ROS map_server YAML + image (pgm/png)."""
    return _store(name, yaml.safe_load(yaml_bytes), image_bytes, image_name)


def import_files(files, name=None):
    """Import maps from uploaded files: map zips (one directory per map) and/or loose YAML + image pairs.

    files: [(filename, bytes)]. A YAML is paired with the image its `image:` field names; a single YAML with a single
    image is paired regardless of names. Returns [(id, name)] of the imported maps.
    """
    entries = {}   # virtual path -> bytes
    for fname, data in files:
        if fname.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for zi in z.infolist():
                    if zi.is_dir() or '__MACOSX' in zi.filename or posixpath.basename(zi.filename).startswith('.'):
                        continue
                    entries[f'{fname}/{zi.filename}'] = z.read(zi)
        else:
            entries[os.path.basename(fname)] = data
    yamls = []
    for path, data in entries.items():
        if path.lower().endswith(('.yaml', '.yml')):
            try:
                meta = yaml.safe_load(data)
            except yaml.YAMLError:
                continue
            if isinstance(meta, dict) and 'resolution' in meta and 'image' in meta:
                yamls.append((path, meta))
    if not yamls:
        raise ValueError('맵 YAML(resolution, image 포함)을 찾지 못했습니다')
    images = [p for p in entries if p.lower().endswith(IMAGE_EXT)]
    out = []
    for path, meta in yamls:
        folder = posixpath.dirname(path)
        img = posixpath.normpath(posixpath.join(folder, str(meta['image']))) if folder else str(meta['image'])
        if img not in entries:
            same = [p for p in images if posixpath.basename(p) == posixpath.basename(str(meta['image']))]
            img = same[0] if len(same) == 1 else (images[0] if len(yamls) == 1 and len(images) == 1 else None)
        if img is None:
            raise ValueError(f'{posixpath.basename(path)} 의 이미지 {meta["image"]} 를 찾지 못했습니다. YAML 과 이미지를 함께 올리세요.')

        def side(fn):
            raw = entries.get(posixpath.join(folder, fn) if folder else fn)
            try:
                return json.loads(raw) if raw else None
            except ValueError:
                return None
        info = side('info.json')
        default = posixpath.basename(folder) if posixpath.basename(path) in ('map.yaml', 'map.yml') and folder else \
            os.path.splitext(posixpath.basename(path))[0]
        nm = name if (name and len(yamls) == 1) else ((info or {}).get('name') or default)
        if name and len(yamls) == 1 and info:
            info = dict(info, name=name)
        mid = _store(nm, meta, entries[img], img, info, side('scenarios.json'), id_hint=default)
        out.append((mid, _user_info(mid).get('name', mid)))
    return out


def rename(mid, name):
    f = paths.user('maps', mid, 'info.json')
    if not os.path.isdir(paths.user('maps', mid)):
        raise KeyError(mid)
    info = _user_info(mid)
    info['name'] = name.strip() or info.get('name', mid)
    json.dump(info, open(f, 'w'), ensure_ascii=False, indent=1)
    return info


def export_zip(mid):
    """Zip one map (bundled or user) in the import format: <id>/map.yaml, image, info.json, scenarios.json."""
    yp = yaml_path(mid)
    d = os.path.dirname(yp)
    meta = yaml.safe_load(open(yp))
    info = _index().get(mid, {}) if d.startswith(paths.data()) else _user_info(mid)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        img = str(meta['image'])
        z.write(os.path.join(d, img), f'{mid}/{os.path.basename(img)}')
        z.writestr(f'{mid}/map.yaml', yaml.safe_dump(dict(meta, image=os.path.basename(img))))
        z.writestr(f'{mid}/info.json', json.dumps(dict(name=info.get('name', mid), group=info.get('group', ''),
                                                      description=info.get('description', '')), ensure_ascii=False, indent=1))
        sc = scenarios(mid)
        if sc:
            z.writestr(f'{mid}/scenarios.json', json.dumps(sc))
    return buf.getvalue()


def delete(mid):
    d = paths.user('maps', mid)
    if not os.path.isdir(d):
        raise KeyError(mid)
    shutil.rmtree(d)
    _forget(mid)


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
