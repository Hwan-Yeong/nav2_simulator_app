"""Depth camera: one ray per pixel; publishes a depth image (16UC1, mm) + CameraInfo like a real camera driver,
and the point cloud in the camera link frame."""
import math

import numpy as np
from scipy.spatial import cKDTree

from .base import Measurement, Param, SensorType
from .geometry import mount_pose


def depth_rays(p):
    w, h = int(p['width']), int(p['height'])
    fh, fv = math.radians(p['fov_h_deg']), math.radians(p['fov_v_deg'])
    ty = np.tan(fh / 2) * (1 - (2 * np.arange(w) + 1) / w)
    tz = np.tan(fv / 2) * (1 - (2 * np.arange(h) + 1) / h)
    d = np.stack([np.ones((h, w)), np.tile(ty, (h, 1)), np.tile(tz[:, None], (1, w))], axis=-1).reshape(-1, 3)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def thin(a, r):
    if len(a) < 2 or r <= 0:
        return a
    _, first = np.unique(np.floor(a / r).astype(np.int64), axis=0, return_index=True)
    return a[np.sort(first)]


class Depth(SensorType):
    type = 'depth'
    label = 'Depth 카메라'
    description = '픽셀마다 깊이(카메라 앞 방향 거리)를 냅니다. depth 영상(16UC1, mm)과 CameraInfo, 포인트 클라우드를 발행합니다.'
    defaults_override = dict(hz=10.0, range_min=0.2, range_max=4.0, noise=0.002, color='#1971c2')
    params = [
        Param('width', '가로 해상도', 64, kind='int', min=4, max=160, step=4, unit='px', group='영상', help='시뮬레이터 해상도 (실제보다 낮게 두어 계산을 줄입니다)'),
        Param('height', '세로 해상도', 48, kind='int', min=4, max=120, step=4, unit='px', group='영상'),
        Param('fov_h_deg', '가로 시야각', 87.0, min=10, max=150, step=1, unit='°', group='영상'),
        Param('fov_v_deg', '세로 시야각', 58.0, min=10, max=120, step=1, unit='°', group='영상'),
        Param('noise_quad', '거리² 비례 잡음', 0.003, min=0.0, max=0.1, step=0.0005, group='잡음', help='스테레오 depth 오차 σ = 거리 잡음 + 계수 × 거리²'),
    ]

    def rays(self, p):
        return depth_rays(p)

    def measure(self, p, rays, t, rng):
        ok = np.isfinite(t)
        depth = np.where(ok, t * rays[:, 0], 0.0)
        ok &= (depth >= p['range_min']) & (rng.random(t.shape) >= p['dropout'])
        depth = np.where(ok, depth + rng.normal(0, 1, depth.shape) * (p['noise'] + p['noise_quad'] * depth ** 2), 0.0)
        scale = np.where(ok, depth / np.maximum(rays[:, 0], 1e-6), 0.0)
        pts = (rays * scale[:, None])[ok]
        w, h = int(p['width']), int(p['height'])
        img = depth.reshape(h, w)
        sy, sx = max(1, h // 24), max(1, w // 32)
        small = img[::sy, ::sx]
        idx = np.flatnonzero(ok)
        return Measurement(points=pts, raw=img, hit_index=idx[::4],
                           vis=dict(w=small.shape[1], h=small.shape[0], depth=np.round(small, 2).ravel().tolist()))

    def outputs(self, name):
        return [(f'/sensors/{name}/points', 'sensor_msgs/PointCloud2'), (f'/sensors/{name}/depth/image_raw', 'sensor_msgs/Image'),
                (f'/sensors/{name}/depth/camera_info', 'sensor_msgs/CameraInfo')]

    def frames(self, name):
        # camera optical frame: z forward, x right, y down (REP 103)
        return [(f'{name}_optical_frame', (0.0, 0.0, 0.0), (-0.5, 0.5, -0.5, 0.5))]

    def publish(self, p, m, pubs, header, mount):
        from sensor_msgs.msg import CameraInfo, Image
        from sensor_msgs_py import point_cloud2 as pc2
        name = mount['name']
        pubs[f'/sensors/{name}/points'].publish(pc2.create_cloud_xyz32(header, m.points.astype(np.float32).tolist()))
        h, w = m.raw.shape
        img = Image()
        img.header.stamp, img.header.frame_id = header.stamp, f'{name}_optical_frame'
        img.height, img.width, img.encoding, img.is_bigendian, img.step = h, w, '16UC1', 0, w * 2
        img.data = np.clip(m.raw * 1000.0, 0, 65535).astype('<u2').tobytes()
        pubs[f'/sensors/{name}/depth/image_raw'].publish(img)
        fx = (w / 2) / math.tan(math.radians(p['fov_h_deg']) / 2)
        fy = (h / 2) / math.tan(math.radians(p['fov_v_deg']) / 2)
        ci = CameraInfo()
        ci.header = img.header
        ci.width, ci.height, ci.distortion_model = w, h, 'plumb_bob'
        ci.d = [0.0] * 5
        ci.k = [fx, 0.0, w / 2, 0.0, fy, h / 2, 0.0, 0.0, 1.0]
        ci.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        ci.p = [fx, 0.0, w / 2, 0.0, 0.0, fy, h / 2, 0.0, 0.0, 0.0, 1.0, 0.0]
        pubs[f'/sensors/{name}/depth/camera_info'].publish(ci)

    def perceive(self, mount, pts, cfg):
        pts = np.asarray(pts, float).reshape(-1, 3)
        if not len(pts):
            return np.zeros((0, 2)), np.zeros((0, 2))
        rot, pos = mount_pose(mount)
        pb = pts @ rot.T + pos
        band = (pb[:, 2] >= cfg['obstacle_min_height']) & (pb[:, 2] <= cfg['obstacle_max_height'])
        obs = pb[band, :2]
        if len(obs) and cfg['min_neighbors'] > 0:
            cnt = np.array([len(x) for x in cKDTree(obs).query_ball_point(obs, cfg['neighbor_radius'])]) - 1
            obs = obs[cnt >= cfg['min_neighbors']]
        low = pb[pb[:, 2] <= -cfg['drop_min_depth']]
        drops = pos[None, :2] + (low[:, :2] - pos[None, :2]) * (pos[2] / (pos[2] - low[:, 2]))[:, None] if len(low) else np.zeros((0, 2))
        return thin(obs, cfg['merge_radius']), thin(drops, cfg['merge_radius'])

    def floor_seen(self, mount, pts, cfg):
        pts = np.asarray(pts, float).reshape(-1, 3)
        if not len(pts):
            return np.zeros((0, 2))
        rot, pos = mount_pose(mount)
        pb = pts @ rot.T + pos
        return thin(pb[np.abs(pb[:, 2]) < cfg['obstacle_min_height'], :2], cfg['merge_radius'])


SENSOR = Depth()
