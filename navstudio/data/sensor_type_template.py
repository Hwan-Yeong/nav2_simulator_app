"""Nav Studio sensor type: IR distance sensor array (template).

A sensor type is one .py file in ~/.navstudio/sensor_types/ (NAVSTUDIO_HOME) that sets SENSOR = SomeSensorType().
After saving, press '다시 읽기' in the sensor library (or restart navstudio); new simulations pick it up.
Everything below is a working example: N single-beam IR range sensors fanned out horizontally, publishing one
point cloud. Change it into the sensor you need. Reference: docs/SENSORS.md, navstudio/sensortypes/*.py.

Frames: the sensor looks along +x of its own frame (y left, z up). The mount pose (x, y, z, roll, pitch, yaw on the
robot; pitch > 0 looks down) is applied by the simulator, so rays() and measure() work in the sensor frame only.
"""
import math

import numpy as np

from navstudio.sensortypes.base import Measurement, Param, SensorType
from navstudio.sensortypes.geometry import mount_pose


class IrArray(SensorType):
    type = 'ir_array'                         # unique id, stored in robot profiles: do not change once used
    label = 'IR 거리 센서 배열'
    description = '한 방향씩 재는 IR 거리 센서 여러 개를 부채꼴로 놓은 것. 각 빔의 가장 가까운 거리.'
    # common params (hz, range_min, range_max, noise, dropout, color) come from the base class; change their defaults:
    defaults_override = dict(hz=20.0, range_min=0.02, range_max=0.8, noise=0.005, color='#0ca678')
    # every Param becomes a field in the sensor library and on the robot; values are checked against min / max
    params = [
        Param('count', '센서 수', 5, kind='int', min=1, max=32, step=1, group='배치'),
        Param('spread_deg', '펼친 각도', 90.0, min=0, max=180, step=1, unit='°', group='배치',
              help='맨 왼쪽 빔과 맨 오른쪽 빔 사이 각도'),
    ]
    fov = ('spread_deg', None)                # which params are the horizontal / vertical field of view (UI drawing)

    def validate(self, p, what):              # optional checks across parameters
        if p['count'] == 1 and p['spread_deg'] > 0:
            p['spread_deg'] = 0.0
        return p

    def rays(self, p):
        """Unit rays in the sensor frame, shape (n, 3). The simulator casts them into the 3D scene."""
        n = int(p['count'])
        a = np.radians(np.linspace(p['spread_deg'] / 2, -p['spread_deg'] / 2, n)) if n > 1 else np.zeros(1)
        return np.stack([np.cos(a), np.sin(a), np.zeros(n)], axis=1)

    def measure(self, p, rays, t, rng):
        """t: distance along each ray to the first surface (inf = nothing within range_max)."""
        ok = np.isfinite(t) & (rng.random(t.shape) >= p['dropout'])
        d = np.where(ok, t + rng.normal(0, p['noise'], t.shape), np.inf)
        ok &= (d >= p['range_min']) & (d <= p['range_max'])
        pts = rays[ok] * d[ok][:, None]
        return Measurement(points=pts, raw=np.where(ok, d, 0.0),
                           hit_index=np.flatnonzero(ok),                       # which rays the UI draws as hits
                           vis=dict(ranges=np.round(np.where(ok, d, 0.0), 3).tolist()))

    def outputs(self, name):
        """Topics the simulator advertises for a mount called <name>."""
        return [(f'/sensors/{name}/points', 'sensor_msgs/PointCloud2')]

    def publish(self, p, m, pubs, header, mount):
        from sensor_msgs_py import point_cloud2 as pc2
        pubs[f"/sensors/{mount['name']}/points"].publish(pc2.create_cloud_xyz32(header, m.points.astype(np.float32).tolist()))

    # perception mode 'rules': the perception node reads /sensors/<name>/points and calls these
    perception_input = ('points', 'points')

    def perceive(self, mount, pts, cfg):
        """Obstacle and drop candidates in base_link x-y. cfg = perception parameters (obstacle_min_height, ...)."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        if not len(pts):
            return np.zeros((0, 2)), np.zeros((0, 2))
        rot, pos = mount_pose(mount)
        pb = pts @ rot.T + pos
        obstacle = pb[:, 2] >= cfg['obstacle_min_height']
        return pb[obstacle, :2], np.zeros((0, 2))

    def floor_seen(self, mount, pts, cfg):
        """Optional: where bare floor is seen now; confirmed obstacles there are cleared."""
        return np.zeros((0, 2))


SENSOR = IrArray()
