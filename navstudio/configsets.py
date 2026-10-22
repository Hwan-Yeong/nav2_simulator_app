"""Config sets: a named driving stack + parameter changes.

Built-in sets are data/presets/<id>.yaml (read-only); the user's sets are <NAVSTUDIO_HOME>/presets/<id>.yaml.
File format: {name, description, stack, values: {param_id: value}, raw: <advanced YAML override>, updated}.
Older built-ins list compatible stacks as `stacks: [..]`; the first one is the set's stack.
"""
import datetime
import os
import re

import yaml

from . import paramgen, paths

ID_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,63}$')


def _dirs():
    return ((paths.data('presets'), True), (paths.user('presets'), False))


def _read(f, builtin):
    p = yaml.safe_load(open(f)) or {}
    sid = os.path.basename(f)[:-5]
    stacks = p.get('stacks') or [p.get('stack') or 'prod']
    return dict(id=sid, builtin=builtin, name=p.get('name') or sid, description=p.get('description') or '',
                stack=p.get('stack') or stacks[0], stacks=stacks, values=dict(p.get('values') or {}),
                raw=p.get('raw') or '', updated=p.get('updated'))


def list_sets():
    out = []
    for d, builtin in _dirs():
        if os.path.isdir(d):
            items = [_read(os.path.join(d, fn), builtin) for fn in sorted(os.listdir(d)) if fn.endswith('.yaml')]
            out += items if builtin else sorted(items, key=lambda x: x['name'])
    return out


def get(sid):
    for d, builtin in _dirs():
        f = os.path.join(d, sid + '.yaml')
        if os.path.exists(f):
            return _read(f, builtin)
    raise KeyError(sid)


def _builtin_ids():
    d = paths.data('presets')
    return {fn[:-5] for fn in os.listdir(d) if fn.endswith('.yaml')} if os.path.isdir(d) else set()


def _new_id(name):
    base = re.sub(r'[^a-z0-9_-]+', '-', name.lower()).strip('-')[:40]
    base = base if base and base[0].isalnum() else 'set'
    taken = _builtin_ids() | {s['id'] for s in list_sets()}
    sid, k = base, 2
    while sid in taken:
        sid, k = f'{base}-{k}', k + 1
    return sid


def save(body, sid=None):
    """Create (sid None) or overwrite a user set. Returns the stored set."""
    name = str(body.get('name') or '').strip()
    if not name:
        raise ValueError('설정 세트 이름을 입력하세요')
    stack = body.get('stack') or 'prod'
    if stack not in {s['id'] for s in paramgen.list_stacks()}:
        raise ValueError(f'알 수 없는 스택입니다: {stack}')
    values = body.get('values') or {}
    if not isinstance(values, dict) or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values.values()):
        raise ValueError('values 는 {파라미터: 숫자} 형태여야 합니다')
    raw = body.get('raw') or ''
    if raw.strip():
        try:
            if not isinstance(yaml.safe_load(raw), dict):
                raise ValueError
        except Exception:
            raise ValueError('고급 오버라이드는 {노드: {경로: 값}} 형태의 YAML 이어야 합니다')
    if sid is None:
        sid = _new_id(name)
    elif not ID_RE.match(sid):
        raise ValueError('잘못된 설정 세트 id 입니다')
    if sid in _builtin_ids():
        raise PermissionError('기본 설정 세트는 바꿀 수 없습니다. 다른 이름으로 저장하세요.')
    doc = dict(name=name, description=str(body.get('description') or '').strip(), stack=stack, values=values, raw=raw,
               updated=datetime.datetime.now().isoformat(timespec='seconds'))
    os.makedirs(paths.user('presets'), exist_ok=True)
    with open(paths.user('presets', sid + '.yaml'), 'w') as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    return get(sid)


def delete(sid):
    f = paths.user('presets', sid + '.yaml')
    if not ID_RE.match(sid) or not os.path.exists(f):
        raise KeyError(sid)
    os.remove(f)
