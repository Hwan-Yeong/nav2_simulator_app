#!/usr/bin/env python3
"""Range-sensor perception: ToF / ultrasonic / depth data -> confirmed low obstacles and drops -> Nav2 costmap.

The rules follow the robot's on-board perception pipeline (re-implemented here):

ToF zone (multizone or single), point p in base_link from the zone distance d: p = mount * (d, d*tan_y, d*tan_z)
  obstacle   p.z >= obstacle_min_height (something stands above the floor), or two vertically adjacent zones of
             the same column hit points closer than vertical_pair_dist (both rows on one vertical face)
  drop       the zone ray should meet the floor at d_floor (mount geometry) but the return is drop_range_diff
             farther, or p.z <= -drop_min_depth, or nothing returns although d_floor < range_max - 0.1
             -> marked where the ray crosses the floor, as a short line across the robot heading
Depth camera  obstacle_min_height <= z <= obstacle_max_height with >= min_neighbors neighbours (neighbor_radius);
              z <= -drop_min_depth -> drop where the ray crosses the floor
Ultrasonic    a return within max_range -> obstacle on the cone axis
Then: obstacle candidates within lidar_check_radius of a lidar return are dropped (the lidar already sees them),
a candidate must be seen confirm_frames times in a row (within merge_radius) to be confirmed, and confirmed points
stay in the map frame until /perception/clear (the server sends it on a new run, teleport or scene change).
With clear_on_floor, a confirmed obstacle is removed when a sensor sees bare floor within clear_radius of it and no
current candidate is near (a false mark or a removed object does not trap the robot). Drops are never cleared that way.

Topics: in  /sim/truth, /sensors/<name>/zones|points, /scan or /scan_<name>, /perception/clear
        out /perception/obstacles, /perception/drops (PointCloud2, map, z = 0.05), /perception/state (JSON, 5 Hz)
"""
import json
import math
import sys

import numpy as np
import yaml
from scipy.spatial import cKDTree

from navstudio import robot as robotlib, sensortypes

DEFAULTS = dict(rate_hz=10.0, obstacle_min_height=0.02, obstacle_max_height=1.0, vertical_pair_dist=0.035,
                drop_min_depth=0.03, drop_range_diff=0.08, drop_on_no_return=True, drop_line_length=0.10,
                lidar_check_radius=0.10, confirm_frames=2, merge_radius=0.04, max_range=1.5,
                min_neighbors=3, neighbor_radius=0.05, clear_on_floor=True, clear_radius=0.05)


class Perception:
    """Pure logic (no ROS): feed sensor data, call step(pose), read confirmed points.

    Per-type rules live in each sensor type plugin (SensorType.perceive); this class does what is common:
    range limit, the lidar check, confirmation over frames and keeping confirmed points.
    """

    def __init__(self, robot, params=None):
        self.p = dict(DEFAULTS, **(params or {}))
        self.mounts = {s['name']: dict(s) for s in robotlib.sensors_3d(robot)}
        self.data = {}                       # name -> latest zones (tof) or points (sensor frame)
        self.lidar_base = np.zeros((0, 2))
        self.pending = {'obstacle': (np.zeros((0, 2)), np.zeros(0, int)), 'drop': (np.zeros((0, 2)), np.zeros(0, int))}
        self.confirmed = {'obstacle': np.zeros((0, 2)), 'drop': np.zeros((0, 2))}
        self.last_candidates = {'obstacle': np.zeros((0, 2)), 'drop': np.zeros((0, 2))}
        self.last_floor = np.zeros((0, 2))

    def clear(self):
        self.pending = {k: (np.zeros((0, 2)), np.zeros(0, int)) for k in self.pending}
        self.confirmed = {k: np.zeros((0, 2)) for k in self.confirmed}

    def candidates(self):
        """Obstacle and drop candidates in base_link x-y from the latest data of every sensor."""
        p = self.p
        obs, drops = [np.zeros((0, 2))], [np.zeros((0, 2))]
        for name, m in self.mounts.items():
            d = self.data.get(name)
            if d is None:
                continue
            o, dr = sensortypes.get(m['type']).perceive(m, d, p)
            obs.append(np.asarray(o, float).reshape(-1, 2))
            drops.append(np.asarray(dr, float).reshape(-1, 2))
        obs, drops = np.concatenate(obs), np.concatenate(drops)
        near = lambda a: a[np.hypot(a[:, 0], a[:, 1]) <= p['max_range']] if len(a) else a
        obs, drops = near(obs), near(drops)
        self.last_floor = near(self.floor())
        if len(obs) and len(self.lidar_base) and p['lidar_check_radius'] > 0:
            dist, _ = cKDTree(self.lidar_base).query(obs, distance_upper_bound=p['lidar_check_radius'])
            obs = obs[~np.isfinite(dist)]
        return obs, drops

    def floor(self):
        """Bare floor seen now (base_link x-y), from every sensor type that reports it."""
        out = [np.zeros((0, 2))]
        for name, m in self.mounts.items():
            d = self.data.get(name)
            if d is not None:
                out.append(np.asarray(sensortypes.get(m['type']).floor_seen(m, d, self.p), float).reshape(-1, 2))
        return np.concatenate(out)

    # ------------------------------------------------------------ confirmation (map frame)
    def step(self, pose):
        x, y, th = pose
        c, s = math.cos(th), math.sin(th)
        to_map = lambda a: np.stack([x + c * a[:, 0] - s * a[:, 1], y + s * a[:, 0] + c * a[:, 1]], axis=1) if len(a) else a
        obs, drops = self.candidates()
        new = {'obstacle': to_map(obs), 'drop': to_map(drops)}
        self.last_candidates = new
        r = self.p['merge_radius']
        for kind, cand in new.items():
            cand = _thin(cand, r)
            ppts, hits = self.pending[kind]
            nh = np.ones(len(cand), int)
            if len(cand) and len(ppts):
                dist, idx = cKDTree(ppts).query(cand, distance_upper_bound=2 * r)
                m = np.isfinite(dist)
                nh[m] = hits[idx[m]] + 1
            done = nh >= int(self.p['confirm_frames'])
            if done.any():
                pts = cand[done]
                if kind == 'drop':
                    pts = _lines(pts, th, self.p['drop_line_length'])
                conf = self.confirmed[kind]
                if len(conf):
                    dist, _ = cKDTree(conf).query(pts, distance_upper_bound=r)
                    pts = pts[~np.isfinite(dist)]
                self.confirmed[kind] = _thin(np.concatenate([conf, pts]), r) if len(pts) else conf
            self.pending[kind] = (cand[~done], nh[~done])
        conf, floor = self.confirmed['obstacle'], to_map(self.last_floor)
        if self.p['clear_on_floor'] and len(conf) and len(floor):
            seen, _ = cKDTree(floor).query(conf, distance_upper_bound=self.p['clear_radius'])
            gone = np.isfinite(seen)
            if gone.any() and len(new['obstacle']):
                held, _ = cKDTree(new['obstacle']).query(conf, distance_upper_bound=2 * r)
                gone &= ~np.isfinite(held)
            self.confirmed['obstacle'] = conf[~gone]

    def summary(self):
        return {k: int(len(v)) for k, v in self.confirmed.items()}


def _thin(a, r):
    """One point per r-sized cell."""
    if len(a) < 2 or r <= 0:
        return a
    keys = np.floor(a / r).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    return a[np.sort(first)]


def _lines(pts, heading, half_len, res=0.05):
    """Short line across the heading through each drop point (the robot must not cross it)."""
    if half_len <= 0:
        return pts
    ox, oy = -math.sin(heading), math.cos(heading)
    ts = np.arange(-half_len, half_len + 1e-9, res)
    return (pts[:, None, :] + np.stack([ox * ts, oy * ts], axis=1)[None, :, :]).reshape(-1, 2)


# ------------------------------------------------------------------ ROS node
def main():
    import rclpy
    from rclpy.node import Node
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan, PointCloud2
    from sensor_msgs_py import point_cloud2 as pc2
    from std_msgs.msg import Empty, Float32MultiArray, Header, String

    class PerceptionNode(Node):
        def __init__(self):
            super().__init__('navstudio_perception')
            self.declare_parameter('robot_file', '')
            for k, v in DEFAULTS.items():
                self.declare_parameter(k, v)
            R = robotlib.normalize(yaml.safe_load(open(self.get_parameter('robot_file').value)))
            params = {k: self.get_parameter(k).value for k in DEFAULTS}
            self.core = Perception(R, params)
            self.pose = None
            self.scans = {}
            self.create_subscription(Odometry, '/sim/truth', self.on_pose, 10)
            for name, m in self.core.mounts.items():   # each type says what it wants: zone grid or points
                kind, suffix = sensortypes.get(m['type']).perception_input
                if kind == 'zones':
                    self.create_subscription(Float32MultiArray, f'/sensors/{name}/{suffix}',
                                             lambda msg, n=name: self.core.data.__setitem__(n, np.array(msg.data)), 10)
                else:
                    self.create_subscription(PointCloud2, f'/sensors/{name}/{suffix}',
                                             lambda msg, n=name: self.core.data.__setitem__(n, _cloud_xyz(msg)), 10)
            # lidar returns in base_link, for the 'already seen by the lidar' check
            self.scan_mounts = {}
            for src, topic in robotlib.scan_sources(R):
                if src == 'scan' and R['scan_merge']['enabled']:
                    geo = (0.0, 0.0, 0.0)
                else:
                    s = next(x for x in robotlib.lidars(R) if x['name'] == src)
                    geo = (s['x'], s['y'], math.radians(s['yaw_deg']))
                self.create_subscription(LaserScan, topic, lambda msg, g=geo, t=topic: self.on_scan(t, g, msg), 10)
            self.create_subscription(Empty, '/perception/clear', lambda _: self.core.clear(), 10)
            self.pub = {k: self.create_publisher(PointCloud2, f'/perception/{k}s', 10) for k in ('obstacle', 'drop')}
            self.pub_state = self.create_publisher(String, '/perception/state', 10)
            self.n = 0
            self.create_timer(1.0 / float(params['rate_hz']), self.tick)

        def on_pose(self, msg):
            q = msg.pose.pose.orientation
            self.pose = (msg.pose.pose.position.x, msg.pose.pose.position.y, 2 * math.atan2(q.z, q.w))

        def on_scan(self, topic, geo, msg):
            r = np.asarray(msg.ranges, float)
            a = msg.angle_min + np.arange(len(r)) * msg.angle_increment + geo[2]
            ok = np.isfinite(r)
            self.scans[topic] = np.stack([geo[0] + np.cos(a[ok]) * r[ok], geo[1] + np.sin(a[ok]) * r[ok]], axis=1)
            self.core.lidar_base = np.concatenate(list(self.scans.values()))

        def tick(self):
            if self.pose is None:
                return
            self.core.step(self.pose)
            hd = Header()
            hd.stamp, hd.frame_id = self.get_clock().now().to_msg(), 'map'
            for k, pts in self.core.confirmed.items():
                xyz = np.column_stack([pts, np.full(len(pts), 0.05)]) if len(pts) else np.zeros((0, 3))
                self.pub[k].publish(pc2.create_cloud_xyz32(hd, xyz.astype(np.float32).tolist()))
            self.n += 1
            if self.n % max(1, int(self.core.p['rate_hz'] / 5)) == 0:
                st = dict(confirmed={k: np.round(v, 2).tolist()[:400] for k, v in self.core.confirmed.items()},
                          candidates={k: np.round(v, 2).tolist()[:200] for k, v in self.core.last_candidates.items()},
                          counts=self.core.summary())
                self.pub_state.publish(String(data=json.dumps(st)))

    def _cloud_xyz(msg):
        a = pc2.read_points_numpy(msg, field_names=('x', 'y', 'z'), skip_nans=True)
        return np.asarray(a, float).reshape(-1, 3)

    rclpy.init(args=sys.argv)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
