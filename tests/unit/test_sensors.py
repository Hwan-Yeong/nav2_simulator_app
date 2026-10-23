import numpy as np
import pytest

from navstudio import paramgen, paths, robot as robotlib, sensors, sensortypes
from navstudio.sim.perception import Perception
from navstudio.sim.raycast import Scene3D


def test_builtin_types_and_schemas():
    assert set(sensortypes.types()) >= {'lidar2d', 'tof', 'ultrasonic', 'depth'}
    tof = next(s for s in sensortypes.schemas() if s['type'] == 'tof')
    keys = {p['key'] for p in tof['params']}
    assert {'zones_x', 'zone_mask', 'fov_h_deg', 'hz', 'range_max', 'noise'} <= keys
    assert any(o['topic'].endswith('/zones') for o in tof['outputs'])


def test_user_sensor_type_plugin_is_loaded(home):
    (home / 'sensor_types').mkdir()
    (home / 'sensor_types' / 'bumper.py').write_text('''
import numpy as np
from navstudio.sensortypes.base import Param, SensorType, Measurement

class Bumper(SensorType):
    type = 'bumper_ir'
    label = 'IR 범퍼'
    params = [Param('spread_deg', '퍼짐', 60.0, min=1, max=180)]
    def rays(self, p):
        return np.array([[1.0, 0.0, 0.0]])
    def measure(self, p, rays, t, rng):
        return Measurement(points=np.zeros((0, 3)))

SENSOR = Bumper()
''')
    (home / 'sensor_types' / 'broken.py').write_text('raise RuntimeError("nope")')
    sensortypes._registry = None
    try:
        assert 'bumper_ir' in sensortypes.types()
        assert 'broken.py' in sensortypes.errors
        m = sensors.normalize_mount(dict(name='bump', type='bumper_ir', spread_deg=90))
        assert m['spread_deg'] == 90 and m['hz'] == 10.0
        with pytest.raises(ValueError, match='퍼짐'):
            sensors.normalize_mount(dict(name='bump', type='bumper_ir', spread_deg=500))
    finally:
        sensortypes._registry = None
        sensortypes.errors.clear()


def test_mount_validation():
    old = sensors.normalize_mount(dict(name='scan', type='lidar2d', x=0, y=0, z=0.1, yaw_deg=0, fov_deg=360, beams=360,
                                       range_min=0.1, range_max=8, hz=10, noise=0.01))
    assert old['pitch_deg'] == 0 and old['enabled']
    with pytest.raises(ValueError, match='종류'):
        sensors.normalize_mount(dict(name='x', type='radar'))
    with pytest.raises(ValueError, match='이름'):
        sensors.normalize_mount(dict(name='1bad', type='tof'))
    with pytest.raises(ValueError, match='마스크'):
        sensors.normalize_mount(dict(name='t', type='tof', zones_x=4, zones_y=4, zone_mask=[3, 20]))
    full = sensors.normalize_mount(dict(name='t', type='tof', zones_x=2, zones_y=2, zone_mask=[3, 2, 1, 0]))
    assert full['zone_mask'] is None


def test_sensor_library_crud():
    builtin = sensors.list_models()
    assert {'tof_8x8', 'depth_camera', 'lidar_240'} <= {m['id'] for m in builtin}
    m = sensors.save_model(dict(name='My ToF 4x4', type='tof', zones_x=4, zones_y=4, fov_h_deg=60))
    assert m['id'] == 'my-tof-4x4' and not m['builtin'] and m['fov_h_deg'] == 60
    with pytest.raises(PermissionError):
        sensors.save_model(dict(name='x', type='tof'), 'tof_8x8')
    mount = sensors.mount_from_model(sensors.get_model('tof_8x8'), 'front_tof', x=0.2)
    assert mount['model'] == 'tof_8x8' and mount['pitch_deg'] == 25 and mount['x'] == 0.2
    sensors.delete_model(m['id'])
    with pytest.raises(KeyError):
        sensors.delete_model('tof_8x8')


def test_robot_merge_and_perception_layers():
    R = robotlib.load('everybot_home')
    assert robotlib.scan_sources(R) == [('scan', '/scan')]
    assert robotlib.perception_node(R)
    doc, _ = paramgen.generate('prod', R)
    lc = paramgen.node_params(doc, 'local_costmap')
    assert lc['plugins'].index('perception_layer') < lc['plugins'].index('inflation_layer')
    assert lc['obstacle_layer']['observation_sources'] == 'scan'
    assert doc['navstudio_perception']['ros__parameters']['obstacle_max_height'] == pytest.approx(0.65)
    direct = dict(R, perception={'mode': 'direct'})
    lc2 = paramgen.node_params(paramgen.generate('prod', direct)[0], 'local_costmap')
    assert 'sensor_layer' in lc2['plugins'] and 'mtof_left' in lc2['sensor_layer']['observation_sources']
    bad = dict(R, sensors=[dict(s, name='scan') if s['name'] == 'front' else s for s in R['sensors']])
    with pytest.raises(ValueError, match="'scan'"):
        robotlib.normalize(bad)


def _scene():
    occ = np.zeros((100, 100), bool)
    occ[0, :] = occ[-1, :] = occ[:, 0] = occ[:, -1] = True
    return Scene3D(occ, 0.05, (-2.5, -2.5))


def _perceive(objects):
    """Run the home robot's ToF + depth sensors at the origin (no noise) through the perception rules."""
    R = robotlib.load('everybot_home')
    sc = _scene()
    sc.set_objects(**objects)
    core = Perception(R, dict(confirm_frames=1))
    rng = np.random.default_rng(0)
    for s in robotlib.sensors_3d(R):
        s = dict(s, noise=0.0, noise_rel=0.0, noise_quad=0.0) if s['type'] != 'ultrasonic' else s
        kind = sensortypes.get(s['type'])
        rays = kind.rays(s)
        rot, pos = sensors.rotation(s['roll_deg'], s['pitch_deg'], s['yaw_deg']), np.array([s['x'], s['y'], s['z']])
        t = sc.cast(pos, rays.reshape(-1, 3) @ rot.T, s['range_max'])
        m = kind.measure(s, rays, t, rng)
        core.data[s['name']] = m.raw if s['type'] == 'tof' else m.points
    core.step((0.0, 0.0, 0.0))
    return core.confirmed


def test_perception_flat_floor_is_quiet():
    c = _perceive({})
    assert len(c['obstacle']) == 0 and len(c['drop']) == 0


def test_perception_low_box_and_drop():
    c = _perceive(dict(boxes=[[0.6, 0.0, 0.1, 0.3, 0.0, 0.0, 0.05]]))
    assert len(c['obstacle']) > 0 and c['obstacle'][:, 0].min() == pytest.approx(0.5, abs=0.06)
    c = _perceive(dict(drops=[[0.45, -1.0, 2.0, 1.0, 0.3]]))
    assert len(c['drop']) > 0 and c['drop'][:, 0].min() >= 0.4


def test_perception_clears_obstacle_when_floor_is_seen_again():
    R = robotlib.load('everybot_home')
    core = Perception(R, dict(confirm_frames=1))
    rng = np.random.default_rng(0)

    def feed(objects):
        sc = _scene()
        sc.set_objects(**objects)
        for s in robotlib.sensors_3d(R):
            s = dict(s, noise=0.0, noise_rel=0.0, noise_quad=0.0) if s['type'] != 'ultrasonic' else s
            kind = sensortypes.get(s['type'])
            rays = kind.rays(s)
            rot, pos = sensors.rotation(s['roll_deg'], s['pitch_deg'], s['yaw_deg']), np.array([s['x'], s['y'], s['z']])
            m = kind.measure(s, rays, sc.cast(pos, rays.reshape(-1, 3) @ rot.T, s['range_max']), rng)
            core.data[s['name']] = m.raw if s['type'] == 'tof' else m.points
        core.step((0.0, 0.0, 0.0))

    feed(dict(boxes=[[0.6, 0.0, 0.1, 0.3, 0.0, 0.0, 0.05]]))
    n = len(core.confirmed['obstacle'])
    assert n > 0
    feed({})                                  # the box was taken away: the sensors see floor there again
    assert len(core.confirmed['obstacle']) < n * 0.3
    core.p['clear_on_floor'] = False
    feed(dict(boxes=[[0.6, 0.0, 0.1, 0.3, 0.0, 0.0, 0.05]]))
    n = len(core.confirmed['obstacle'])
    feed({})
    assert len(core.confirmed['obstacle']) == n
