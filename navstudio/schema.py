"""UI parameter schema: filtering by stack/robot, current values, UI values -> Nav2 overrides."""
import copy

import yaml

from . import paths, paramgen, robot as robotlib

_schema = None


def load():
    global _schema
    if _schema is None:
        _schema = yaml.safe_load(open(paths.data('param_schema.yaml')))
    return _schema


def _targets(p, robot):
    tg = p.get('targets') or [[p['node'], p['path']]]
    out = []
    for node, path in tg:
        if '{sensor}' in path:
            out += [[node, path.replace('{sensor}', name)] for name, _ in robotlib.scan_sources(robot)]
        else:
            out.append([node, path])
    return out


def applicable(p, stack):
    w = p.get('when') or {}
    return all(stack.get(k) in v for k, v in w.items())


def resolve(stack_id, robot, user_values=None):
    """Schema entries that apply, each with the default (stack+robot) value and the user's value if set."""
    st = paramgen.load_stack(stack_id)
    doc, warn = paramgen.generate(st, robot)
    sch = load()
    params = []
    for p in sch['params']:
        if not applicable(p, st):
            continue
        tg = _targets(p, robot)
        node, path = tg[0]
        default = paramgen.get_dotted(paramgen.node_params(doc, node), path)
        if default is None:
            continue
        q = {k: v for k, v in p.items() if k not in ('targets', 'when')}
        q['default'] = default
        if user_values and p['id'] in user_values:
            q['value'] = user_values[p['id']]
        params.append(q)
    return dict(groups=sch['groups'], params=params, warnings=warn)


def to_overrides(robot, values, stack_id=None):
    """{param_id: value} -> override dict. With stack_id, values of parameters that do not apply to it are dropped."""
    by_id = {p['id']: p for p in load()['params']}
    st = paramgen.load_stack(stack_id) if stack_id else None
    ov = {}
    for pid, v in (values or {}).items():
        p = by_id.get(pid)
        if p is None or v is None or (st is not None and not applicable(p, st)):
            continue
        if p['type'] == 'int':
            v = int(round(float(v)))
        elif p['type'] == 'float':
            v = float(v)
        for node, path in _targets(p, robot):
            ov.setdefault(node, {})[path] = v
    return ov
