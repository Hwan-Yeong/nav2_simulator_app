from navstudio.bench import stats


def test_wilson_interval_contains_estimate():
    lo, hi = stats.wilson(47, 50)
    assert lo < 0.94 < hi and 0 <= lo and hi <= 1
    assert stats.wilson(0, 0) == (None, None)


def test_paired_mcnemar():
    base = [{'id': str(i), 'status': 'succeeded', 'collisions': 0} for i in range(10)]
    other = [dict(r) for r in base]
    for r in other[:4]:
        r['status'] = 'aborted'
    p = stats.paired(base, other)
    assert (p['fixed'], p['broke'], p['common']) == (0, 4, 10)
    assert abs(p['p'] - 0.125) < 1e-9
    assert stats.paired(base, base)['p'] == 1.0
