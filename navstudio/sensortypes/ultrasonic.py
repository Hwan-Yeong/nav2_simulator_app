"""Ultrasonic range sensor: the nearest echo inside a cone (no direction inside the cone)."""
import math

import numpy as np

from .base import Measurement, Param, SensorType
from .geometry import mount_pose


def cone_rays(p, rings=3, per_ring=8):
    half = math.radians(p['beam_deg']) / 2
    out = [[1.0, 0.0, 0.0]]
    for r in range(1, rings + 1):
        a = half * r / rings
        for k in range(per_ring * r):
            phi = 2 * math.pi * k / (per_ring * r)
            out.append([math.cos(a), math.sin(a) * math.cos(phi), math.sin(a) * math.sin(phi)])
    return np.array(out)


class Ultrasonic(SensorType):
    type = 'ultrasonic'
    label = '초음파'
    fov = ('beam_deg', 'beam_deg')
    description = '원뿔 안의 가장 가까운 물체까지 거리 하나를 냅니다 (방향은 모름). 유리·검은 물체처럼 빛 센서가 놓치는 것용.'
    defaults_override = dict(hz=20.0, range_min=0.03, range_max=4.0, noise=0.01, color='#2b8a3e')
    params = [Param('beam_deg', '빔 각도', 30.0, min=2, max=120, step=1, unit='°', group='빔')]

    def rays(self, p):
        return cone_rays(p)

    def measure(self, p, rays, t, rng):
        i = int(np.argmin(t))
        d = float(t[i])
        ok = math.isfinite(d) and rng.random() >= p['dropout']
        d = d + rng.normal(0, p['noise']) if ok else math.inf
        if ok and d < p['range_min']:
            ok, d = False, math.inf
        pts = np.array([[d, 0.0, 0.0]]) if ok else np.zeros((0, 3))
        return Measurement(points=pts, raw=d, hit_index=np.array([i]) if ok else np.zeros(0, int),
                           vis=dict(range=round(d, 3) if ok else None))

    def outputs(self, name):
        return [(f'/sensors/{name}/range', 'sensor_msgs/Range'), (f'/sensors/{name}/points', 'sensor_msgs/PointCloud2')]

    def publish(self, p, m, pubs, header, mount):
        from sensor_msgs.msg import Range
        from sensor_msgs_py import point_cloud2 as pc2
        name = mount['name']
        msg = Range()
        msg.header = header
        msg.radiation_type = Range.ULTRASOUND
        msg.field_of_view = math.radians(p['beam_deg'])
        msg.min_range, msg.max_range, msg.range = float(p['range_min']), float(p['range_max']), float(m.raw)
        pubs[f'/sensors/{name}/range'].publish(msg)
        pubs[f'/sensors/{name}/points'].publish(pc2.create_cloud_xyz32(header, m.points.astype(np.float32).tolist()))

    def perceive(self, mount, pts, cfg):
        pts = np.asarray(pts, float).reshape(-1, 3)
        if not len(pts):
            return np.zeros((0, 2)), np.zeros((0, 2))
        rot, pos = mount_pose(mount)
        return (pts @ rot.T + pos)[:, :2], np.zeros((0, 2))


SENSOR = Ultrasonic()
