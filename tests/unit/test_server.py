"""REST API without ROS: sessions are never started here (no bridge is created)."""
import io
import os

import pytest
from fastapi.testclient import TestClient

from navstudio import maps, server


@pytest.fixture()
def client():
    server.create(dict(os.environ), 91)
    return TestClient(server.app)


def test_info_has_four_stopped_slots(client):
    info = client.get('/api/info').json()
    assert info['max_slots'] == 4 and [s['domain'] for s in info['slots']] == [91, 92, 93, 94]
    assert all(s['status'] == 'stopped' for s in info['slots'])


def test_presets_crud(client):
    r = client.post('/api/presets', json={'name': 'MPPI 느리게', 'stack': 'mppi', 'values': {}})
    assert r.status_code == 200
    sid = r.json()['id']
    assert client.put(f'/api/presets/{sid}', json={'name': 'MPPI 느리게', 'stack': 'mppi', 'values': {}, 'description': 'd'}).json()['description'] == 'd'
    builtin = next(s['id'] for s in client.get('/api/presets').json() if s['builtin'])
    assert client.put(f'/api/presets/{builtin}', json={'name': 'x', 'stack': 'prod'}).status_code == 403
    assert client.delete(f'/api/presets/{builtin}').status_code == 404
    assert client.delete(f'/api/presets/{sid}').status_code == 200
    assert client.post('/api/presets', json={'name': '', 'stack': 'prod'}).status_code == 400


def test_map_upload_rename_export_delete(client):
    z = client.get('/api/maps/synth_clutter/export.zip')
    assert z.status_code == 200 and z.headers['content-type'] == 'application/zip'
    r = client.post('/api/maps', files=[('files', ('m.zip', io.BytesIO(z.content), 'application/zip'))], data={'name': ''})
    mid = r.json()['maps'][0]['id']
    assert client.get(f'/api/scenarios/{mid}').json()
    assert client.patch(f'/api/maps/{mid}', json={'name': '테스트'}).json()['name'] == '테스트'
    assert client.delete(f'/api/maps/{mid}').status_code == 200
    assert client.delete('/api/maps/synth_clutter').status_code == 404
    bad = client.post('/api/maps', files=[('files', ('x.txt', io.BytesIO(b'x'), 'text/plain'))])
    assert bad.status_code == 400


def test_driving_needs_a_running_slot(client):
    assert client.post('/api/nav/goal', json={'pose': [1, 1, 0]}).status_code == 409
    assert client.post('/api/sim/teleport', json={'pose': [1, 1, 0], 'slots': [2]}).status_code == 409
    assert client.post('/api/session/stop', json={}).status_code == 200
    assert client.post('/api/nav/cancel', json={'slots': [0, 1]}).status_code == 200
    assert client.get('/api/session/log?slot=9').status_code == 404


def test_params_preview_and_schema(client):
    r = client.post('/api/params/preview', json={'stack': 'prod', 'values': {'dwb_max_vel_x': 0.31}})
    assert r.status_code == 200 and 'max_vel_x: 0.31' in r.json()['yaml']
    s = client.post('/api/params/schema', json={'stack': 'mppi'}).json()
    assert s['params'] and not any(p['id'].startswith('dwb_') for p in s['params'])


def test_sensor_library_and_types(client):
    from navstudio import sensortypes
    t = client.get('/api/sensor-types').json()
    assert {'lidar2d', 'tof', 'ultrasonic', 'depth'} <= {x['type'] for x in t['types']} and t['dir'].endswith('sensor_types')
    assert next(x for x in t['types'] if x['type'] == 'tof')['fov'] == ['fov_h_deg', 'fov_v_deg']
    r = client.post('/api/sensors', json={'name': '앞 ToF', 'type': 'tof', 'zones_x': 4, 'zones_y': 4})
    assert r.status_code == 200 and r.json()['zones_x'] == 4
    mid = r.json()['id']
    assert client.put(f'/api/sensors/{mid}', json={'name': '앞 ToF', 'type': 'tof', 'zones_x': 2, 'zones_y': 2}).json()['zones_x'] == 2
    assert client.put('/api/sensors/tof_8x8', json={'name': 'x', 'type': 'tof'}).status_code == 403
    assert client.post('/api/sensors', json={'name': 'x', 'type': 'tof', 'fov_h_deg': 500}).status_code == 400
    m = client.post('/api/sensors/mount', json={'model': 'tof_8x8', 'name': 'front_tof', 'x': 0.2}).json()
    assert m['model'] == 'tof_8x8' and m['x'] == 0.2 and m['pitch_deg'] == 25
    assert client.post('/api/sensors/mount', json={'model': 'nope', 'name': 'a'}).status_code == 404
    assert client.delete(f'/api/sensors/{mid}').status_code == 200 and client.delete('/api/sensors/tof_8x8').status_code == 404
    path = client.post('/api/sensor-types/template', json={'name': 'Bumper IR'}).json()['path']
    try:
        assert path.endswith('bumper_ir.py')
        types = client.post('/api/sensor-types/reload').json()
        assert 'bumper_ir' in {x['type'] for x in types['types']} and not types['errors']
    finally:
        os.remove(path)
        sensortypes.reload()
