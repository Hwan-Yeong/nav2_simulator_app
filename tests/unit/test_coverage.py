import numpy as np
import pytest

from navstudio import coverage, robot as robotlib


def _grid(c):
    return np.array(c['bits'], np.uint32).reshape(c['ny'], c['nx'])


def _xy(c):
    xs = c['x0'] + np.arange(c['nx']) * c['res']
    ys = c['y0'] + np.arange(c['ny']) * c['res']
    return np.meshgrid(xs, ys)


def test_probe_spec_presets_and_validation():
    p = coverage.probe_spec({'preset': 'low', 'z1': 0.08})
    assert p['kind'] == 'box' and p['z1'] == 0.08 and p['size'] == 0.10
    assert coverage.probe_spec({'preset': 'drop'})['depth'] == 0.10
    with pytest.raises(ValueError):
        coverage.probe_spec({'preset': 'low', 'z0': 0.3, 'z1': 0.1})
    with pytest.raises(ValueError):
        coverage.probe_spec({'kind': 'sphere'})


def test_home_robot_sees_a_low_box_ahead_in_time():
    R = robotlib.load('everybot_home')
    c = coverage.compute(R, {'preset': 'low'})
    names = [s['name'] for s in c['sensors']]
    bits = _grid(c)
    X, Y = _xy(c)
    tof = (bits >> names.index('mtof_left')) & 1
    assert tof.any() and X[tof > 0].min() > 0.2                # the multizone ToF looks ahead, at the floor
    assert not ((bits >> names.index('front')) & 1).any()      # the lidars sit above a 5 cm box
    assert not bits[X < -0.3].any()                            # nothing behind the robot
    s = c['summary']
    assert s['corridor']['ok'] == 1.0 and s['corridor']['centre']['first'] > s['stop']
    assert s['ring']['back'] == 0.0 and s['ring']['front'] > 0.5


def test_lidar_only_robot_is_blind_to_low_things_and_drops():
    R = robotlib.load('everybot')
    for preset in ('low', 'drop'):
        c = coverage.compute(R, {'preset': preset})
        assert not any(c['bits']) and c['summary']['corridor']['blind'] == 1.0
    leg = coverage.compute(R, {'preset': 'leg'})
    assert leg['summary']['ring']['back'] > 0.9                 # a 360 deg lidar sees a chair leg all around


def test_drops_and_notes():
    R = robotlib.load('everybot_home')
    c = coverage.compute(R, {'preset': 'drop'})
    assert any(c['bits']) and c['summary']['corridor']['ok'] == 1.0
    th = coverage.compute(R, {'preset': 'threshold'})
    assert not any(th['bits']) and any('등반 높이' in n for n in th['notes'])
    off = coverage.compute(dict(R, perception={'mode': 'off'}), {'preset': 'low'})
    assert not any(off['bits']) and any('인식 처리가 꺼져' in n for n in off['notes'])
    direct = coverage.compute(dict(R, perception={'mode': 'direct'}), {'preset': 'drop'})
    assert not any(direct['bits']) and any('원시 점' in n for n in direct['notes'])
