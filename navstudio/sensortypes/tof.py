"""ToF range sensor, single zone (1x1) or multizone (e.g. 4x4, 8x8).

Each zone reports one axial distance (sensor x). A real multizone ToF reports the dominant target of the zone's
histogram, where near surfaces return more light (1/r^2); the simulator samples k x k sub-rays per zone and takes the
1/r^2-weighted mean of their distances (or the nearest one with nearest_target). The driver-side
point of a zone is (d, d*tan_y, d*tan_z) with the zone-centre tangents below. Zone index 0 is the top-left zone
seen from behind the sensor (row-major), so zone_mask lists match the real driver's indices.
"""
import math

import numpy as np

from .base import Measurement, Param, SensorType
from .geometry import mount_pose


def zone_tangents(p):
    nx, ny = int(p['zones_x']), int(p['zones_y'])
    fh, fv = math.radians(p['fov_h_deg']), math.radians(p['fov_v_deg'])
    j = np.tile(np.arange(nx), ny)
    i = np.repeat(np.arange(ny), nx)
    return np.tan(fh * (nx - 1 - 2 * j) / (2 * nx)), np.tan(fv * (ny - 1 - 2 * i) / (2 * ny))


def active_zones(p):
    n = int(p['zones_x']) * int(p['zones_y'])
    return np.array(sorted(p['zone_mask']) if p.get('zone_mask') is not None else range(n), dtype=int)


def zone_rays(p):
    """(n_active, k*k, 3) unit sub-rays spread over each active zone (sensor frame)."""
    nx, ny, k = int(p['zones_x']), int(p['zones_y']), int(p['rays_per_zone'])
    fh, fv = math.radians(p['fov_h_deg']), math.radians(p['fov_v_deg'])
    zones = active_zones(p)
    j, i = zones % nx, zones // nx
    off = (np.arange(k) + 0.5) / k - 0.5
    a_y = fh * ((nx - 1 - 2 * j)[:, None] / (2 * nx) - off[None, :] / nx)
    a_z = fv * ((ny - 1 - 2 * i)[:, None] / (2 * ny) - off[None, :] / ny)
    ty = np.tan(a_y)[:, :, None].repeat(k, 2)
    tz = np.tan(a_z)[:, None, :].repeat(k, 1)
    d = np.stack([np.ones_like(ty), ty, tz], axis=-1).reshape(len(zones), k * k, 3)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


class Tof(SensorType):
    type = 'tof'
    label = 'ToF (단일·멀티존)'
    description = '존마다 가장 가까운 물체까지의 거리(센서 x 축 방향)를 냅니다. 1×1 이면 1D ToF, 4×4·8×8 이면 멀티존.'
    defaults_override = dict(hz=15.0, range_min=0.02, range_max=4.0, noise=0.005, color='#d9480f')
    perception_input = ('zones', 'zones')
    params = [
        Param('zones_x', '가로 존 수', 8, kind='int', min=1, max=16, step=1, group='존'),
        Param('zones_y', '세로 존 수', 8, kind='int', min=1, max=16, step=1, group='존'),
        Param('fov_h_deg', '가로 시야각', 45.0, min=1, max=120, step=1, unit='°', group='존'),
        Param('fov_v_deg', '세로 시야각', 45.0, min=1, max=120, step=1, unit='°', group='존'),
        Param('zone_mask', '사용할 존', None, kind='zones', group='존',
              help='켜진 존만 측정·발행합니다 (예: 8×8 중 16존). 비우면 전부. 번호는 센서 뒤에서 본 왼쪽 위가 0.'),
        Param('noise_rel', '거리 비례 잡음', 0.01, min=0.0, max=0.2, step=0.001, group='잡음', help='σ = 거리 잡음 + 비례 잡음 × 거리'),
        Param('rays_per_zone', '존당 광선 (축마다)', 3, kind='int', min=1, max=5, step=1, group='시뮬레이션',
              help='존 하나를 k×k 광선으로 훑습니다. 크면 정확하지만 느립니다.'),
        Param('nearest_target', '가장 가까운 물체만', False, kind='bool', group='시뮬레이션',
              help='끄면 존 안 거리들을 신호 세기(1/거리²)로 가중 평균합니다 (실제 센서에 가까움). 켜면 가장 가까운 값.'),
    ]

    def validate(self, p, what):
        n = p['zones_x'] * p['zones_y']
        if p.get('zone_mask') is not None:
            m = sorted({int(i) for i in p['zone_mask']})
            if not m or m[0] < 0 or m[-1] >= n:
                raise ValueError(f'{what}: 존 마스크는 0~{n - 1} 사이 번호여야 합니다')
            p['zone_mask'] = None if len(m) == n else m
        return p

    def rays(self, p):
        return zone_rays(p)

    def measure(self, p, rays, t, rng):
        k = rays.shape[1]
        tz = t.reshape(-1, k)
        axial = tz * rays[:, :, 0]
        fin = np.isfinite(axial)
        nearest = np.argmin(np.where(fin, axial, np.inf), axis=1)
        rows = np.arange(len(axial))
        if p.get('nearest_target'):
            d = axial[rows, nearest]
        else:   # signal-weighted: near returns are brighter (1/r^2)
            w = np.where(fin, 1.0 / np.maximum(np.where(fin, axial, 1.0), 1e-3) ** 2, 0.0)
            ws = w.sum(axis=1)
            with np.errstate(invalid='ignore', divide='ignore'):
                d = np.where(ws > 0, (w * np.where(fin, axial, 0.0)).sum(axis=1) / ws, np.inf)
        ok = np.isfinite(d)
        sigma = p['noise'] + p['noise_rel'] * np.where(ok, d, 0.0)
        d = np.where(ok, d + rng.normal(0, 1, d.shape) * sigma, 0.0)
        ok &= (d >= p['range_min']) & (rng.random(d.shape) >= p['dropout'])
        d = np.where(ok, d, 0.0)
        zones = active_zones(p)
        grid = np.zeros(int(p['zones_x']) * int(p['zones_y']), np.float32)
        grid[zones] = d
        ty, tzz = zone_tangents(p)
        zi = zones[ok]
        pts = np.stack([d[ok], d[ok] * ty[zi], d[ok] * tzz[zi]], axis=1)
        return Measurement(points=pts, raw=grid, hit_index=(rows * k + nearest)[ok],
                           vis=dict(zones=np.round(grid, 3).tolist(), nx=int(p['zones_x']), ny=int(p['zones_y'])))

    def outputs(self, name):
        return [(f'/sensors/{name}/zones', 'std_msgs/Float32MultiArray'), (f'/sensors/{name}/points', 'sensor_msgs/PointCloud2')]

    def publish(self, p, m, pubs, header, mount):
        from std_msgs.msg import Float32MultiArray, MultiArrayDimension
        from sensor_msgs_py import point_cloud2 as pc2
        name = mount['name']
        msg = Float32MultiArray()
        msg.layout.dim = [MultiArrayDimension(label='rows', size=int(p['zones_y']), stride=int(m.raw.size)),
                          MultiArrayDimension(label='cols', size=int(p['zones_x']), stride=int(p['zones_x']))]
        msg.data = m.raw.tolist()
        pubs[f'/sensors/{name}/zones'].publish(msg)
        pubs[f'/sensors/{name}/points'].publish(pc2.create_cloud_xyz32(header, m.points.astype(np.float32).tolist()))

    # ---------------------------------------------------------------- perception
    def _geom(self, mount):
        g = mount.get('_tof')
        if g is None:
            rot, pos = mount_pose(mount)
            ty, tz = zone_tangents(mount)
            v = np.stack([np.ones_like(ty), ty, tz], axis=1) @ rot.T
            with np.errstate(divide='ignore'):
                d_floor = np.where(v[:, 2] < -1e-9, -pos[2] / v[:, 2], np.inf)
            floor_pts = pos[None, :2] + v[:, :2] * np.where(np.isfinite(d_floor), d_floor, 0)[:, None]
            g = mount['_tof'] = dict(rot=rot, pos=pos, ty=ty, tz=tz, d_floor=d_floor, floor_pts=floor_pts, zones=active_zones(mount))
        return g

    def perceive(self, mount, grid, cfg):
        """Obstacle and drop candidates (base_link x-y) from one zone grid; see sim/perception.py for the rules."""
        g = self._geom(mount)
        z = g['zones']
        grid = np.asarray(grid, float)
        dist = grid[z]
        ok = dist > 0
        pb = np.stack([dist, dist * g['ty'][z], dist * g['tz'][z]], axis=1) @ g['rot'].T + g['pos']
        obstacle = ok & (pb[:, 2] >= cfg['obstacle_min_height']) & (pb[:, 2] <= cfg['obstacle_max_height'])
        floor = np.isfinite(g['d_floor'][z])
        far = ok & floor & (dist - g['d_floor'][z] > cfg['drop_range_diff'])
        below = ok & (pb[:, 2] <= -cfg['drop_min_depth'])
        missing = ~ok & floor & (g['d_floor'][z] < float(mount['range_max']) - 0.1) & bool(cfg['drop_on_no_return'])
        drop = far | below | missing
        nx = int(mount['zones_x'])
        index = {int(k): i for i, k in enumerate(z)}
        for i, k in enumerate(z):              # vertical face: zone and the zone below hit nearly the same point
            j = index.get(int(k) + nx)
            if j is not None and ok[i] and ok[j] and not drop[i] and not drop[j] \
                    and np.linalg.norm(pb[i] - pb[j]) < cfg['vertical_pair_dist']:
                obstacle[j] = True
        drops = np.where(floor[:, None], g['floor_pts'][z], pb[:, :2])[drop]
        return pb[obstacle, :2], drops

    def floor_seen(self, mount, grid, cfg):
        g = self._geom(mount)
        z = g['zones']
        dist = np.asarray(grid, float)[z]
        ok = dist > 0
        pb = np.stack([dist, dist * g['ty'][z], dist * g['tz'][z]], axis=1) @ g['rot'].T + g['pos']
        return pb[ok & (np.abs(pb[:, 2]) < cfg['obstacle_min_height']), :2]


SENSOR = Tof()
