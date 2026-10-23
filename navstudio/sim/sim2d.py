#!/usr/bin/env python3
"""Nav Studio 2D simulator.

Robot from a profile (navstudio.robot): diff / omni / ackermann drive, circle or polygon footprint, body height,
2D lidars and range sensors (ToF single/multizone, ultrasonic, depth camera; navstudio.sensors).
World (2.5D): occupancy-grid map (walls) + static obstacles (circle/rect with z0..z1: low obstacles, overhangs) +
drops (type 'cliff': floor `depth` lower) + pedestrians (ping-pong routes, yield to the robot, 1.7 m cylinders).
Obstacles block the robot when they overlap climb_height..body height; each lidar sees what crosses its height;
range sensors cast 3D rays (sim/raycast.py). Driving the robot centre into a drop deeper than climb_height is a fall.

Topics
  /clock, /odom, TF map->odom->base_link (+ static base_link->laser_<name> / <name>_link / base_scan),
  /scan_<name> (LaserScan; a lidar named 'scan' publishes on /scan), /scan (merged lidars, scan_merge),
  /sensors/<name>/zones (ToF zone distances, Float32MultiArray rows x cols, 0 = no target),
  /sensors/<name>/range (ultrasonic, Range), /sensors/<name>/points (PointCloud2 in <name>_link),
  subscribes cmd_vel (param cmd_topic).
  /sim/state  (String JSON, 20 Hz) pose, velocity, pedestrians, scan hit points, contact, live metrics, sensor data
  /sim/cmd    (String JSON) ops: reset{pose,static_obs,dyn_obs,episode} | world{static_obs,dyn_obs}
              | teleport{pose} | stats{episode} | metrics_reset
  /sim/reply  (String JSON) ack / stats
Ground-truth localisation: map->odom absorbs odometry drift so map->base_link is the true pose.
Real-time factor is 1.0 because Nav2 Humble's controller/behavior loops run on wall-clock rates.
"""
import json
import math
import os
import sys
import time

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rosgraph_msgs.msg import Clock
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster
from builtin_interfaces.msg import Time as TimeMsg

from navstudio import robot as robotlib, sensors as sensorlib, sensortypes
from navstudio.sim.raycast import Scene3D

PED_HEIGHT = 1.7          # pedestrians are 1.7 m cylinders
OBS_TOP = 1.0             # top of obstacles that do not give a height


def load_map(yaml_path):
    with open(yaml_path) as f:
        meta = yaml.safe_load(f)
    img_path = meta['image']
    if not os.path.isabs(img_path):
        img_path = os.path.join(os.path.dirname(yaml_path), img_path)
    img = np.array(Image.open(img_path).convert('L'), dtype=np.float32)
    p = (255.0 - img) / 255.0 if not meta.get('negate', 0) else img / 255.0
    occ = p > meta.get('occupied_thresh', 0.65)
    unknown = (p > meta.get('free_thresh', 0.196)) & ~occ
    return np.flipud(occ), np.flipud(unknown), float(meta['resolution']), [float(v) for v in meta['origin'][:2]]


def msg_class(name):
    """'sensor_msgs/PointCloud2' -> the message class."""
    import importlib
    pkg, cls = name.split('/')
    return getattr(importlib.import_module(pkg + '.msg'), cls)


def rect_bounds(o):
    x0 = o.get('x0', o.get('cx', 0) - o.get('w', 0) / 2)
    x1 = o.get('x1', o.get('cx', 0) + o.get('w', 0) / 2)
    y0 = o.get('y0', o.get('cy', 0) - o.get('h', 0) / 2)
    y1 = o.get('y1', o.get('cy', 0) + o.get('h', 0) / 2)
    return min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)


def quat(th):
    return 0.0, 0.0, math.sin(th / 2.0), math.cos(th / 2.0)


def wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


class Lidar:
    def __init__(self, s, res, R):
        self.name = s['name']
        self.frame = 'laser_' + self.name
        self.topic = robotlib.lidar_topic(s, R)
        self.x, self.y, self.z = float(s['x']), float(s['y']), float(s['z'])
        self.yaw = math.radians(float(s['yaw_deg']))
        fov = math.radians(float(s['fov_deg']))
        n = int(s['beams'])
        if fov >= 2 * math.pi - 1e-6:
            self.angles = np.linspace(-math.pi, math.pi, n, endpoint=False)
        else:
            self.angles = np.linspace(-fov / 2, fov / 2, n)
        self.rmin, self.rmax = float(s['range_min']), float(s['range_max'])
        self.steps = np.arange(self.rmin, self.rmax, res * 0.5)
        self.period = 1.0 / float(s['hz'])
        self.noise = float(s['noise'])
        self.next_t = 0.0
        self.last_hits = np.zeros((0, 2))
        self.last_base = np.zeros((0, 2))   # hit points in base_link (for the merged scan)
        self.grid = None                     # occupancy at this lidar's height


class RangeSensor:
    """A 3D sensor mount (ToF, ultrasonic, depth, or a user sensor type): rays from its type plugin."""

    def __init__(self, s):
        self.s, self.name, self.type = s, s['name'], s['type']
        self.kind = sensortypes.get(s['type'])
        self.frame = s['name'] + '_link'
        self.rot = sensorlib.rotation(s['roll_deg'], s['pitch_deg'], s['yaw_deg'])
        self.pos = np.array([s['x'], s['y'], s['z']])
        self.rays = self.kind.rays(s)                              # sensor frame, any leading shape
        self.flat = self.rays.reshape(-1, 3)
        self.dirs_b = self.flat @ self.rot.T                       # base_link frame
        self.period = 1.0 / float(s['hz'])
        self.next_t = 0.0
        self.vis = None


class Sim2D(Node):
    def __init__(self):
        super().__init__('sim2d')
        p = self.declare_parameter
        p('map_yaml', '')
        p('robot_file', '')
        p('physics_hz', 100.0)
        p('odom_hz', 50.0)
        p('state_hz', 20.0)
        p('cmd_timeout', 0.5)
        p('unknown_is_obstacle', True)
        p('cmd_topic', '/cmd_vel_smoothed')
        p('seed', 0)
        p('ped_yield_margin', 0.25)
        p('traj_period', 0.2)
        p('start_pose', [0.0, 0.0, 0.0])
        # legacy single-lidar knobs (benchmark profiles); robot profile wins when given
        p('scan_noise', -1.0)
        p('max_lin_acc', -1.0)
        p('max_ang_acc', -1.0)
        p('motor_tau', -1.0)
        p('odom_slip_lin', -1.0)
        p('odom_slip_ang', -1.0)
        gp = lambda n: self.get_parameter(n).value

        rf = gp('robot_file')
        self.robot = robotlib.normalize(yaml.safe_load(open(rf)) if rf else {})
        R = self.robot
        act, lim = R['actuator'], R['limits']
        ov = lambda name, v: gp(name) if gp(name) >= 0 else v
        self.tau = ov('motor_tau', act['tau'])
        self.slip_lin = ov('odom_slip_lin', act['slip_lin'])
        self.slip_ang = ov('odom_slip_ang', act['slip_ang'])
        self.ax = ov('max_lin_acc', lim['ax_max'])
        self.ay = lim['ay_max']
        self.az = ov('max_ang_acc', lim['az_max'])
        self.drive = R['drive']
        self.L = R['wheels']['wheelbase']
        self.max_steer = math.radians(R['wheels']['max_steer_deg'])
        self.circle = R['footprint']['type'] == 'circle'
        self.rr = R['footprint']['radius'] if self.circle else robotlib.inscribed_circumscribed(R)[1]
        self.outline = np.array(robotlib.outline_samples(R, 0.025))
        self.dt = 1.0 / gp('physics_hz')
        self.rng = np.random.default_rng(gp('seed'))

        occ, unknown, self.res, self.origin = load_map(gp('map_yaml'))
        base = occ | unknown if gp('unknown_is_obstacle') else occ
        base[0, :] = base[-1, :] = base[:, 0] = base[:, -1] = True
        self.base_occ = base
        H, W = base.shape
        yy, xx = np.mgrid[0:H, 0:W]
        self._cx = self.origin[0] + (xx + 0.5) * self.res
        self._cy = self.origin[1] + (yy + 0.5) * self.res
        self.climb = float(R['climb_height'])
        self.top = float(R['body']['height'])
        self.scene = Scene3D(base, self.res, self.origin)
        self.lidars = [Lidar(s, self.res, R) for s in robotlib.lidars(R)]
        if gp('scan_noise') >= 0:
            for l in self.lidars:
                l.noise = gp('scan_noise')
        self.ranges = [RangeSensor(s) for s in robotlib.sensors_3d(R)]
        self.merge = R['scan_merge'] if R['scan_merge']['enabled'] else None
        if self.merge:
            self.merge_z = robotlib.merge_height(R)
            self.merge_inc = math.radians(float(self.merge['angle_increment_deg']))
            self.merge_src = [l for l in self.lidars if l.name in self.merge['sources']]
            self.merge_due = False
        self.static_obs = []
        self.drops = []
        self.fallen = False
        self.set_world([])

        sp = list(gp('start_pose'))
        self.x, self.y, self.th = sp if len(sp) == 3 else (0.0, 0.0, 0.0)
        self.vx = self.vy = self.w = 0.0          # body-frame velocities
        self.cmd = (0.0, 0.0, 0.0)
        self.last_cmd_t = -1e9
        self.ox = self.oy = self.oth = 0.0
        self.ovx = self.ovy = self.ow = 0.0
        self.dyn = []
        self.sim_t = 1.0
        self.episode = None
        self.in_contact = False
        self.reset_metrics()

        rel = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST)
        self.pub_clock = self.create_publisher(Clock, '/clock', 10)
        self.pub_odom = self.create_publisher(Odometry, '/odom', 10)
        self.pub_scans = {l.name: self.create_publisher(LaserScan, l.topic, 10) for l in self.lidars}
        self.pub_merged = self.create_publisher(LaserScan, '/scan', 10) if self.merge else None
        for r in self.ranges:          # each sensor type plugin declares its topics and message types
            r.pubs = {topic: self.create_publisher(msg_class(mt), topic, 10) for topic, mt in r.kind.outputs(r.name)}
        self.state_count = 0
        self.pub_reply = self.create_publisher(String, '/sim/reply', rel)
        self.pub_state = self.create_publisher(String, '/sim/state', 10)
        self.pub_truth = self.create_publisher(Odometry, '/sim/truth', 10)
        self.tfb = TransformBroadcaster(self)
        self.stfb = StaticTransformBroadcaster(self)
        self.create_subscription(Twist, gp('cmd_topic'), self.on_cmd, 10)
        self.create_subscription(String, '/sim/cmd', lambda m: self.pending.append(json.loads(m.data)), rel)
        self.pending = []
        self.odom_period = 1.0 / gp('odom_hz')
        self.state_period = 1.0 / gp('state_hz')
        self.next_odom = self.next_state = 0.0
        self.publish_static_tf()

    # ---------------------------------------------------------------- world
    def _footprint_mask(self, o):
        if o['type'] == 'circle':
            return (self._cx - o['x']) ** 2 + (self._cy - o['y']) ** 2 <= o['r'] ** 2
        if 'yaw' in o and abs(o.get('yaw', 0)) > 1e-6:   # rotated box: cx, cy, w, h, yaw
            c, s = math.cos(-o['yaw']), math.sin(-o['yaw'])
            dx, dy = self._cx - o['cx'], self._cy - o['cy']
            lx, ly = c * dx - s * dy, s * dx + c * dy
            return (np.abs(lx) <= o['w'] / 2) & (np.abs(ly) <= o['h'] / 2)
        x0, x1, y0, y1 = rect_bounds(o)
        return (self._cx >= x0) & (self._cx <= x1) & (self._cy >= y0) & (self._cy <= y1)

    def set_world(self, static_obs):
        """Obstacles (with z0..z1) and drops; rebuilds the collision grid, each lidar's grid and the 3D scene."""
        occ = self.base_occ.copy()
        layers, boxes, cyls, drops = [], [], [], []
        for o in static_obs:
            if o.get('type') == 'cliff':
                x0, x1, y0, y1 = rect_bounds(o)
                drops.append([x0, y0, x1, y1, max(float(o.get('depth', 0.3)), 0.005)])
                continue
            z0, z1 = float(o.get('z0', 0.0)), float(o.get('z1', OBS_TOP))
            mask = self._footprint_mask(o)
            if z0 < self.top and z1 > self.climb:
                occ |= mask
            layers.append((mask, z0, z1))
            if o['type'] == 'circle':
                cyls.append([o['x'], o['y'], o['r'], z0, z1])
            elif 'yaw' in o and abs(o.get('yaw', 0)) > 1e-6:
                boxes.append([o['cx'], o['cy'], o['w'] / 2, o['h'] / 2, o['yaw'], z0, z1])
            else:
                x0, x1, y0, y1 = rect_bounds(o)
                boxes.append([(x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2, 0.0, z0, z1])
        self.static_obs = static_obs
        self.occ = occ
        self.dist = ndimage.distance_transform_edt(~occ) * self.res
        self.drops = [d for d in drops if d[4] > self.climb]
        self.scene.set_objects(boxes, cyls, drops)
        for l in self.lidars:
            g = self.base_occ.copy()
            for mask, z0, z1 in layers:
                if z0 <= l.z <= z1:
                    g |= mask
            l.grid = g

    def in_drop(self, x, y):
        return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1, _ in self.drops)

    def set_dyn(self, dyn_obs):
        self.dyn = []
        for d in dyn_obs:
            wps = [tuple(w) for w in d['wps']]
            if len(wps) == 1:
                wps = wps * 2
            seg = [math.hypot(wps[i + 1][0] - wps[i][0], wps[i + 1][1] - wps[i][1]) for i in range(len(wps) - 1)]
            self.dyn.append(dict(wps=wps, seg_len=seg, total=sum(seg), speed=d.get('speed', 0.5), r=d.get('r', 0.22),
                                 s=d.get('phase', 0.0) * 2 * sum(seg), wait=0.0))

    def lookup_dist(self, xs, ys):
        ix = ((np.asarray(xs) - self.origin[0]) / self.res).astype(np.int64)
        iy = ((np.asarray(ys) - self.origin[1]) / self.res).astype(np.int64)
        H, W = self.occ.shape
        ok = (ix >= 0) & (iy >= 0) & (ix < W) & (iy < H)
        out = np.zeros(ix.shape)
        out[ok] = self.dist[iy[ok], ix[ok]]
        return out

    def _dyn_pos(self, d, s):
        total = d['total']
        if total <= 0:
            return d['wps'][0]
        s = s % (2 * total)
        if s > total:
            s = 2 * total - s
        wps = d['wps']
        for i, L in enumerate(d['seg_len']):
            if s <= L or i == len(d['seg_len']) - 1:
                a = min(s / L, 1.0) if L > 0 else 0.0
                return wps[i][0] + a * (wps[i + 1][0] - wps[i][0]), wps[i][1] + a * (wps[i + 1][1] - wps[i][1])
            s -= L

    def update_dyn(self, dt):
        margin = self.get_parameter('ped_yield_margin').value
        for d in self.dyn:
            x0, y0 = self._dyn_pos(d, d['s'])
            s1 = d['s'] + d['speed'] * dt
            x1, y1 = self._dyn_pos(d, s1)
            d0, d1 = math.hypot(x0 - self.x, y0 - self.y), math.hypot(x1 - self.x, y1 - self.y)
            if d1 < d['r'] + self.rr + margin and d1 < d0:
                d['wait'] += dt
                if d['wait'] >= 4.0 and d['total'] > 0:   # waited long enough: turn around
                    d['s'] = (2 * d['total'] - d['s']) % (2 * d['total'])
                    d['wait'] = 0.0
                continue
            d['wait'] = 0.0
            d['s'] = s1

    def dyn_positions(self):
        return [(*self._dyn_pos(d, d['s']), d['r']) for d in self.dyn]

    def clearance(self, x, y, th):
        """Distance from the footprint outline to the nearest obstacle (negative = overlap)."""
        if self.circle:
            c = float(self.lookup_dist([x], [y])[0]) - self.rr
            for ox, oy, r in self.dyn_positions():
                c = min(c, math.hypot(x - ox, y - oy) - r - self.rr)
            return c
        cs, sn = math.cos(th), math.sin(th)
        px = x + cs * self.outline[:, 0] - sn * self.outline[:, 1]
        py = y + sn * self.outline[:, 0] + cs * self.outline[:, 1]
        d = self.lookup_dist(px, py)
        # EDT is measured from cell centres: a point inside an occupied cell has distance 0
        c = float(d.min()) - self.res * 0.5
        for ox, oy, r in self.dyn_positions():
            c = min(c, float(np.min(np.hypot(px - ox, py - oy))) - r)
        return c

    # ---------------------------------------------------------------- ROS IO
    def on_cmd(self, msg):
        self.cmd = (msg.linear.x, msg.linear.y, msg.angular.z)
        self.last_cmd_t = self.sim_t

    def handle_pending(self):
        while self.pending:
            c = self.pending.pop(0)
            op = c.get('op')
            if op == 'reset':
                self.set_world(c.get('static_obs', []))
                self.set_dyn(c.get('dyn_obs', []))
                self.x, self.y, self.th = c['pose']
                self.vx = self.vy = self.w = 0.0
                self.cmd = (0.0, 0.0, 0.0)
                self.fallen = False
                self.episode = c.get('episode')
                self.reset_metrics()
                self.reply(dict(op='ack', episode=self.episode, clearance=self.clearance(self.x, self.y, self.th)))
            elif op == 'world':
                if 'static_obs' in c:
                    self.set_world(c['static_obs'])
                if 'dyn_obs' in c:
                    self.set_dyn(c['dyn_obs'])
                self.reply(dict(op='ack', episode=c.get('episode')))
            elif op == 'teleport':
                self.x, self.y, self.th = c['pose']
                self.vx = self.vy = self.w = 0.0
                self.fallen = False
                self.reply(dict(op='ack', episode=c.get('episode')))
            elif op == 'metrics_reset':
                self.episode = c.get('episode')
                self.reset_metrics()
                self.reply(dict(op='ack', episode=self.episode))
            elif op == 'stats':
                m = {k: v for k, v in self.m.items() if not k.startswith('_')}
                m.update(op='stats', episode=c.get('episode'), pose=[self.x, self.y, self.th],
                         sim_t=self.sim_t, duration=self.sim_t - self.m['t_start'])
                self.reply(m)

    def reply(self, d):
        self.pub_reply.publish(String(data=json.dumps(d)))

    def reset_metrics(self):
        self.m = dict(t_start=self.sim_t, path_len=0.0, min_clear=1e9, collisions=0, collision_time=0.0,
                      in_collision=False, near_time=0.0, rot_abs=0.0, lin_jerk_sq=0.0, ang_jerk_sq=0.0,
                      w_sign_flips=0, v_sign_flips=0, stopped_time=0.0, max_v=0.0, max_w=0.0, falls=0,
                      reverse_dist=0.0, cmd_count=0, sum_clear=0.0, n_clear=0,
                      traj=[], collision_pts=[], _next_traj=0.0)
        self._prev_acc = (0.0, 0.0)
        self._prev_wsign = self._prev_vsign = 0

    def stamp(self):
        sec = int(self.sim_t)
        return TimeMsg(sec=sec, nanosec=int((self.sim_t - sec) * 1e9))

    # ---------------------------------------------------------------- physics
    def target_velocity(self):
        lim = self.robot['limits']
        if self.sim_t - self.last_cmd_t > self.get_parameter('cmd_timeout').value:
            return 0.0, 0.0, 0.0
        vx, vy, w = self.cmd
        vx = min(max(vx, lim['vx_min']), lim['vx_max'])
        vy = 0.0 if self.drive != 'omni' else min(max(vy, -lim['vy_max']), lim['vy_max'])
        w = min(max(w, -lim['wz_max']), lim['wz_max'])
        if self.drive == 'ackermann':
            # cmd (v, w) -> steering angle; a car cannot turn on the spot
            if abs(vx) < 1e-3:
                w = 0.0
            else:
                steer = math.atan(w * self.L / vx)
                steer = min(max(steer, -self.max_steer), self.max_steer)
                w = vx * math.tan(steer) / self.L
        return vx, vy, w

    def step(self):
        dt = self.dt
        self.update_dyn(dt)
        if self.fallen:          # stuck in a drop until the next reset / teleport
            self.vx = self.vy = self.w = 0.0
            self.ovx = self.ovy = self.ow = 0.0
            self.sim_t += dt
            return
        tvx, tvy, tw = self.target_velocity()
        tau = max(self.tau, dt)
        clip = lambda d, a: min(max(d, -a * dt), a * dt)
        vx_prev, w_prev = self.vx, self.w
        self.vx += clip((tvx - self.vx) * dt / tau, self.ax)
        self.vy += clip((tvy - self.vy) * dt / tau, self.ay)
        self.w += clip((tw - self.w) * dt / tau, self.az)
        if self.drive == 'ackermann' and abs(self.vx) > 1e-3:
            wmax = abs(self.vx) * math.tan(self.max_steer) / self.L
            self.w = min(max(self.w, -wmax), wmax)
        elif self.drive == 'ackermann':
            self.w = 0.0

        thm = self.th + 0.5 * self.w * dt
        nx = self.x + (self.vx * math.cos(thm) - self.vy * math.sin(thm)) * dt
        ny = self.y + (self.vx * math.sin(thm) + self.vy * math.cos(thm)) * dt
        nth = wrap(self.th + self.w * dt)
        m = self.m
        if self.clearance(nx, ny, nth) < 0.0:
            if not m['in_collision']:
                m['collisions'] += 1
                m['collision_pts'].append([round(self.x, 3), round(self.y, 3)])
            m['in_collision'] = True
            m['collision_time'] += dt
            # blocked: keep pose; allow pure rotation if it does not overlap
            if self.clearance(self.x, self.y, nth) >= 0.0 and self.drive != 'ackermann':
                nx, ny = self.x, self.y
            else:
                nx, ny, nth = self.x, self.y, self.th
                self.w = 0.0
            self.vx = self.vy = 0.0
        else:
            m['in_collision'] = False
        self.in_contact = m['in_collision']
        if self.sim_t - m['t_start'] >= m['_next_traj']:
            m['_next_traj'] += self.get_parameter('traj_period').value
            m['traj'].append([round(self.sim_t - m['t_start'], 2), round(self.x, 3), round(self.y, 3), round(self.th, 3),
                              round(math.hypot(self.vx, self.vy), 3), round(self.w, 3),
                              [[round(a, 2), round(b, 2)] for a, b, _ in self.dyn_positions()]])
        if self.drops and self.in_drop(nx, ny):
            self.fallen = True
            m['falls'] += 1
            m['collision_pts'].append([round(nx, 3), round(ny, 3)])
            self.vx = self.vy = self.w = 0.0
        step_len = math.hypot(nx - self.x, ny - self.y)
        m['path_len'] += step_len
        if self.vx < -0.005:
            m['reverse_dist'] += step_len
        self.x, self.y, self.th = nx, ny, nth
        self.sim_t += dt

        # odometry with slip noise; map->odom absorbs the drift (ground-truth localisation)
        self.ovx = self.vx * (1.0 + self.rng.normal(0, self.slip_lin))
        self.ovy = self.vy * (1.0 + self.rng.normal(0, self.slip_lin))
        self.ow = self.w * (1.0 + self.rng.normal(0, self.slip_ang))
        self.oth += self.ow * dt
        self.ox += (self.ovx * math.cos(self.oth) - self.ovy * math.sin(self.oth)) * dt
        self.oy += (self.ovx * math.sin(self.oth) + self.ovy * math.cos(self.oth)) * dt

        c = self.clearance(self.x, self.y, self.th)
        self.cur_clear = c
        m['min_clear'] = min(m['min_clear'], c)
        m['sum_clear'] += c
        m['n_clear'] += 1
        if c < 0.05:
            m['near_time'] += dt
        m['rot_abs'] += abs(self.w) * dt
        v = math.hypot(self.vx, self.vy) * (1 if self.vx >= 0 else -1)
        acc = ((self.vx - vx_prev) / dt, (self.w - w_prev) / dt)
        m['lin_jerk_sq'] += ((acc[0] - self._prev_acc[0]) / dt) ** 2 * dt
        m['ang_jerk_sq'] += ((acc[1] - self._prev_acc[1]) / dt) ** 2 * dt
        self._prev_acc = acc
        ws = 0 if abs(self.w) < 0.05 else (1 if self.w > 0 else -1)
        if ws and self._prev_wsign and ws != self._prev_wsign:
            m['w_sign_flips'] += 1
        if ws:
            self._prev_wsign = ws
        vs = 0 if abs(v) < 0.02 else (1 if v > 0 else -1)
        if vs and self._prev_vsign and vs != self._prev_vsign:
            m['v_sign_flips'] += 1
        if vs:
            self._prev_vsign = vs
        if abs(v) < 0.01 and abs(self.w) < 0.02:
            m['stopped_time'] += dt
        m['max_v'] = max(m['max_v'], abs(v))
        m['max_w'] = max(m['max_w'], abs(self.w))

    # ---------------------------------------------------------------- publishing
    def publish_static_tf(self):
        def tf(child, xyz, q):
            t = TransformStamped()
            t.header.frame_id = 'base_link'
            t.child_frame_id = child
            t.transform.translation.x, t.transform.translation.y, t.transform.translation.z = (float(v) for v in xyz)
            t.transform.rotation.x, t.transform.rotation.y, t.transform.rotation.z, t.transform.rotation.w = q
            return t
        tfs = [tf(l.frame, (l.x, l.y, l.z), quat(l.yaw)) for l in self.lidars]
        for r in self.ranges:
            s = r.s
            tfs.append(tf(r.frame, r.pos, sensorlib.quaternion(s['roll_deg'], s['pitch_deg'], s['yaw_deg'])))
            for child, xyz, q in r.kind.frames(r.name):
                t = tf(child, xyz, q)
                t.header.frame_id = r.frame
                tfs.append(t)
        if self.merge:
            tfs.append(tf(self.merge['frame'], (0.0, 0.0, self.merge_z), (0.0, 0.0, 0.0, 1.0)))
        self.stfb.sendTransform(tfs)

    def publish_odom_tf(self):
        st = self.stamp()
        q = quat(self.oth)
        od = Odometry()
        od.header.stamp = st
        od.header.frame_id = 'odom'
        od.child_frame_id = 'base_link'
        od.pose.pose.position.x, od.pose.pose.position.y = self.ox, self.oy
        od.pose.pose.orientation.z, od.pose.pose.orientation.w = q[2], q[3]
        od.twist.twist.linear.x, od.twist.twist.linear.y, od.twist.twist.angular.z = self.ovx, self.ovy, self.ow
        self.pub_odom.publish(od)
        t1 = TransformStamped()
        t1.header.stamp = st
        t1.header.frame_id, t1.child_frame_id = 'odom', 'base_link'
        t1.transform.translation.x, t1.transform.translation.y = self.ox, self.oy
        t1.transform.rotation.z, t1.transform.rotation.w = q[2], q[3]
        dth = self.th - self.oth
        c, s = math.cos(dth), math.sin(dth)
        t0 = TransformStamped()
        t0.header.stamp = st
        t0.header.frame_id, t0.child_frame_id = 'map', 'odom'
        t0.transform.translation.x = self.x - (c * self.ox - s * self.oy)
        t0.transform.translation.y = self.y - (s * self.ox + c * self.oy)
        q0 = quat(dth)
        t0.transform.rotation.z, t0.transform.rotation.w = q0[2], q0[3]
        self.tfb.sendTransform([t0, t1])
        tr = Odometry()
        tr.header.stamp = st
        tr.header.frame_id, tr.child_frame_id = 'map', 'base_link'
        tr.pose.pose.position.x, tr.pose.pose.position.y = self.x, self.y
        qt = quat(self.th)
        tr.pose.pose.orientation.z, tr.pose.pose.orientation.w = qt[2], qt[3]
        tr.twist.twist.linear.x, tr.twist.twist.linear.y, tr.twist.twist.angular.z = self.vx, self.vy, self.w
        self.pub_truth.publish(tr)

    def publish_scan(self, l):
        cs, sn = math.cos(self.th), math.sin(self.th)
        lx = self.x + cs * l.x - sn * l.y
        ly = self.y + sn * l.x + cs * l.y
        ang = l.angles + self.th + l.yaw
        ca, sa = np.cos(ang), np.sin(ang)
        px = lx + np.outer(ca, l.steps)
        py = ly + np.outer(sa, l.steps)
        ix = ((px - self.origin[0]) / self.res).astype(np.int32)
        iy = ((py - self.origin[1]) / self.res).astype(np.int32)
        H, W = self.occ.shape
        np.clip(ix, 0, W - 1, out=ix)
        np.clip(iy, 0, H - 1, out=iy)
        hit = (l.grid if l.grid is not None else self.occ)[iy, ix]
        rng = np.where(hit.any(axis=1), l.steps[hit.argmax(axis=1)], np.inf)
        for ox, oy, r in self.dyn_positions():
            dx, dy = ox - lx, oy - ly
            b = dx * ca + dy * sa
            disc = b * b - (dx * dx + dy * dy - r * r)
            ok = disc >= 0
            tnear = b - np.sqrt(np.where(ok, disc, 0))
            ok &= tnear > 0
            rng = np.where(ok & (tnear < rng), tnear, rng)
        rng = np.where(np.isfinite(rng), rng + self.rng.normal(0, l.noise, rng.shape), np.inf)
        rng = np.where(rng < l.rmin, np.inf, rng)
        fin = np.isfinite(rng)
        l.last_hits = np.stack([lx + ca[fin] * rng[fin], ly + sa[fin] * rng[fin]], axis=1)
        ab = l.angles[fin] + l.yaw
        l.last_base = np.stack([l.x + np.cos(ab) * rng[fin], l.y + np.sin(ab) * rng[fin]], axis=1)
        if self.merge and l is self.merge_src[0]:
            self.merge_due = True
        msg = LaserScan()
        msg.header.stamp = self.stamp()
        msg.header.frame_id = l.frame
        msg.angle_min = float(l.angles[0])
        msg.angle_increment = float(l.angles[1] - l.angles[0])
        msg.angle_max = float(l.angles[-1])
        msg.range_min, msg.range_max = l.rmin, l.rmax
        msg.scan_time = l.period
        msg.ranges = rng.astype(np.float32).tolist()
        self.pub_scans[l.name].publish(msg)

    def publish_merged(self):
        """Merged scan of the source lidars in the merge frame (base_scan): min range per angle bin."""
        mg = self.merge
        pts = np.concatenate([l.last_base for l in self.merge_src]) if self.merge_src else np.zeros((0, 2))
        n = int(round(2 * math.pi / self.merge_inc))
        ranges = np.full(n, np.inf)
        if len(pts):
            r = np.hypot(pts[:, 0], pts[:, 1])
            ok = (r >= mg['range_min']) & (r <= mg['range_max'])
            a = np.arctan2(pts[ok, 1], pts[ok, 0])
            b = np.clip(((a + math.pi) / self.merge_inc).astype(int), 0, n - 1)
            np.minimum.at(ranges, b, r[ok])
        msg = LaserScan()
        msg.header.stamp = self.stamp()
        msg.header.frame_id = mg['frame']
        msg.angle_min, msg.angle_increment = -math.pi, self.merge_inc
        msg.angle_max = -math.pi + (n - 1) * self.merge_inc
        msg.range_min, msg.range_max = float(mg['range_min']), float(mg['range_max'])
        msg.scan_time = self.merge_src[0].period if self.merge_src else 0.1
        msg.ranges = ranges.astype(np.float32).tolist()
        self.pub_merged.publish(msg)

    def cast_sensor(self, r):
        """Cast one range sensor into the scene; its type plugin turns distances into the driver's output."""
        cs, sn = math.cos(self.th), math.sin(self.th)
        Rz = np.array([[cs, -sn, 0.0], [sn, cs, 0.0], [0.0, 0.0, 1.0]])
        origin = np.array([self.x, self.y, 0.0]) + Rz @ r.pos
        dirs = r.dirs_b @ Rz.T
        peds = [[px, py, rad, 0.0, PED_HEIGHT] for px, py, rad in self.dyn_positions()]
        t = self.scene.cast(origin, dirs, float(r.s['range_max']), extra_cyls=peds)
        m = r.kind.measure(r.s, r.rays, t, self.rng)
        r.last = m
        r.kind.publish(r.s, m, r.pubs, self._header(self.stamp(), r.frame), r.s)
        idx = m.hit_index if m.hit_index is not None else np.zeros(0, int)
        hits = origin + dirs[idx] * t[idx][:, None] if len(idx) else np.zeros((0, 3))
        r.vis = dict(m.vis, type=r.type, hits=np.round(hits, 3).tolist())

    @staticmethod
    def _header(stamp, frame):
        from std_msgs.msg import Header
        hd = Header()
        hd.stamp, hd.frame_id = stamp, frame
        return hd

    def publish_state(self):
        m = self.m
        hits = np.concatenate([l.last_hits for l in self.lidars]) if self.lidars else np.zeros((0, 2))
        st = dict(t=round(self.sim_t, 2), pose=[round(self.x, 4), round(self.y, 4), round(self.th, 4)],
                  vel=[round(self.vx, 3), round(self.vy, 3), round(self.w, 3)],
                  dyn=[[round(a, 3), round(b, 3), r] for a, b, r in self.dyn_positions()],
                  contact=self.in_contact, fallen=self.fallen, clear=round(getattr(self, 'cur_clear', 0.0), 3),
                  scan=np.round(hits[::2], 2).tolist(),
                  metrics=dict(path_len=round(m['path_len'], 2), min_clear=round(min(m['min_clear'], 99), 3),
                               collisions=m['collisions'], near_time=round(m['near_time'], 2),
                               duration=round(self.sim_t - m['t_start'], 2), max_v=round(m['max_v'], 3),
                               falls=m['falls']),
                  episode=self.episode)
        self.state_count += 1
        if self.ranges and self.state_count % 4 == 0:       # sensor views for the UI at 5 Hz
            st['sensors'] = {r.name: r.vis for r in self.ranges if r.vis is not None}
        self.pub_state.publish(String(data=json.dumps(st)))

    def run(self):
        wall0, sim0 = time.monotonic(), self.sim_t
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.0)
            self.handle_pending()
            self.step()
            self.pub_clock.publish(Clock(clock=self.stamp()))
            if self.sim_t >= self.next_odom:
                self.publish_odom_tf()
                self.next_odom = self.sim_t + self.odom_period
            for l in self.lidars:
                if self.sim_t >= l.next_t:
                    self.publish_scan(l)
                    l.next_t = self.sim_t + l.period
            if self.merge and self.merge_due:
                self.merge_due = False
                self.publish_merged()
            for r in self.ranges:
                if self.sim_t >= r.next_t:
                    self.cast_sensor(r)
                    r.next_t = self.sim_t + r.period
            if self.sim_t >= self.next_state:
                self.publish_state()
                self.next_state = self.sim_t + self.state_period
            target = wall0 + (self.sim_t - sim0)
            now = time.monotonic()
            if target > now:
                time.sleep(target - now)
            elif now - target > 1.0:
                wall0, sim0 = now, self.sim_t


def main():
    try:  # exit with the launch process even if it is SIGKILLed
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6').prctl(1, signal.SIGTERM)
    except Exception:
        pass
    rclpy.init(args=sys.argv)
    node = Sim2D()
    try:
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
