"""Benchmark statistics without pandas: per-config summaries, Wilson intervals, paired comparison, score."""
import math
from math import comb


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _quantile(v, q):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    i = (len(v) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return v[lo] + (v[hi] - v[lo]) * (i - lo)


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def is_success(r):
    return r.get('status') == 'succeeded' and not (r.get('collisions') or 0)


DEFAULT_WEIGHTS = dict(success=1.0, speed=1.0, clearance=1.0, smooth=1.0)


def score(s, w=None):
    """Higher is better. Success dominates; collisions are penalised on top; then speed, margin, smoothness."""
    w = dict(DEFAULT_WEIGHTS, **(w or {}))
    if not s or s.get('n', 0) == 0:
        return None
    return (w['success'] * (100.0 * s['success'] - 50.0 * s['collision_rate'])
            + w['speed'] * 40.0 * (s['avg_speed'] or 0)
            + w['clearance'] * 20.0 * min(s['min_clear_p10'] if s['min_clear_p10'] is not None else 0, 0.25)
            - 2.0 * (s['recoveries'] or 0)
            - w['smooth'] * (s['ang_jerk_rms'] or 0) / 10.0)


def summarize(records, weights=None):
    rs = list(records)
    n = len(rs)
    if not n:
        return dict(n=0)
    ok = [r for r in rs if r.get('status') == 'succeeded']
    k = sum(1 for r in rs if is_success(r))
    lo, hi = wilson(k, n)
    dur = lambda r: max(r.get('duration') or 0, 1.0)
    s = dict(
        n=n, success=k / n, ci_lo=lo, ci_hi=hi,
        collision_rate=sum(1 for r in rs if (r.get('collisions') or 0) > 0) / n,
        timeout_rate=sum(1 for r in rs if r.get('status') == 'timeout') / n,
        avg_speed=_mean([r['ref_len'] / r['duration'] for r in ok if r.get('duration')]),
        time_mean=_mean([r.get('duration') for r in ok]),
        path_ratio=_median([r['path_len'] / r['ref_len'] for r in ok if r.get('ref_len')]),
        min_clear_p10=_quantile([r.get('min_clear') for r in rs], 0.10),
        min_clear_med=_median([r.get('min_clear') for r in rs]),
        near_time=_mean([r.get('near_time') for r in rs]),
        recoveries=_mean([r.get('recoveries') for r in rs]),
        ang_jerk_rms=_median([math.sqrt((r.get('ang_jerk_sq') or 0) / dur(r)) for r in rs]),
        ctrl_cpu=_mean([(r.get('cpu') or {}).get('controller_server') for r in rs]),
        by_category={},
    )
    for cat in sorted({r['category'] for r in rs}):
        sub = [r for r in rs if r['category'] == cat]
        s['by_category'][cat] = dict(n=len(sub), success=sum(map(is_success, sub)) / len(sub))
    s['score'] = score(s, weights)
    return s


def paired(base, other):
    """Episodes where only one of two configurations succeeded; exact two-sided binomial (McNemar) p-value."""
    a = {r['id']: is_success(r) for r in base}
    b = {r['id']: is_success(r) for r in other}
    common = set(a) & set(b)
    fixed = sum(1 for i in common if not a[i] and b[i])
    broke = sum(1 for i in common if a[i] and not b[i])
    m = fixed + broke
    p = 1.0 if m == 0 else min(1.0, 2 * sum(comb(m, i) for i in range(min(fixed, broke) + 1)) / 2 ** m)
    return dict(common=len(common), fixed=fixed, broke=broke, p=p)
