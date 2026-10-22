#!/usr/bin/env python3
"""Benchmark worker: runs a list of episodes on one map with one configuration, in its own ROS domain.

Run inside a clean ROS environment (navstudio.env.clean_env) with ROS_DOMAIN_ID set:
python3 -m navstudio.bench.worker --cfg-dir D --map M --episodes E.json --ids a,b --out R.jsonl
(D contains params.yaml, robot.yaml, sim.yaml written by the runner)
"""
import argparse
import json
import math
import os
import signal
import subprocess
import sys
import time

import psutil
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import ClearEntireCostmap
from nav_msgs.msg import Path
from std_msgs.msg import String

from navstudio import stack as stacklib
from navstudio.stack import LAUNCH

NAV_PROCS = ('controller_server', 'planner_server', 'bt_navigator', 'smoother_server', 'behavior_server',
             'velocity_smoother', 'map_server')
METRIC_KEYS = ('duration', 'path_len', 'min_clear', 'collisions', 'collision_time', 'near_time', 'rot_abs',
               'lin_jerk_sq', 'ang_jerk_sq', 'w_sign_flips', 'v_sign_flips', 'stopped_time', 'max_v', 'max_w',
               'reverse_dist')


class Client(Node):
    def __init__(self):
        super().__init__('navstudio_bench')
        q = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.pub = self.create_publisher(String, '/sim/cmd', q)
        self.create_subscription(String, '/sim/reply', lambda m: self.replies.append(json.loads(m.data)), q)
        self.create_subscription(Path, '/plan', self._plan, 10)
        self.nav = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.clr = [self.create_client(ClearEntireCostmap, s) for s in
                    ('/local_costmap/clear_entirely_local_costmap', '/global_costmap/clear_entirely_global_costmap')]
        self.replies = []
        self.plans = []

    def _plan(self, msg):
        if len(self.plans) < 200:
            self.plans.append([[round(p.pose.position.x, 2), round(p.pose.position.y, 2)] for p in msg.poses[::3]])

    def spin_for(self, sec):
        end = time.monotonic() + sec
        while time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=min(0.05, max(0.0, end - time.monotonic())))

    def sim_call(self, cmd, timeout=6.0):
        self.replies = []
        for _ in range(3):
            self.pub.publish(String(data=json.dumps(cmd)))
            end = time.monotonic() + timeout / 3
            while time.monotonic() < end:
                rclpy.spin_once(self, timeout_sec=0.05)
                for r in self.replies:
                    if r.get('episode') == cmd.get('episode'):
                        return r
        return None

    def clear(self):
        futs = [c.call_async(ClearEntireCostmap.Request()) for c in self.clr if c.service_is_ready()]
        end = time.monotonic() + 3.0
        while time.monotonic() < end and not all(f.done() for f in futs):
            rclpy.spin_once(self, timeout_sec=0.05)


def nav_pids(root):
    out = {}
    try:
        for p in psutil.Process(root).children(recursive=True):
            try:
                name, cmd = p.name(), ' '.join(p.cmdline())
            except psutil.Error:
                continue
            for n in NAV_PROCS:
                if n[:15] == name[:15]:
                    out[n] = p
            if 'navstudio.sim.sim2d' in cmd:
                out['sim2d'] = p
    except psutil.Error:
        pass
    return out


class Launch:
    def __init__(self, cfg_dir, map_yaml, start, log):
        sp = '[' + ', '.join(f'{float(v):.4f}' for v in start) + ']'
        self.cmd = ['ros2', 'launch', LAUNCH, f'params_file:={cfg_dir}/params.yaml', f'map:={map_yaml}',
                    f'robot_file:={cfg_dir}/robot.yaml', f'sim_params:={cfg_dir}/sim.yaml', f'start_pose:={sp}',
                    'log_level:=warn', f'python:={sys.executable}']
        self.log = log
        self.proc = None

    def start(self):
        self.logf = open(self.log, 'a')
        self.proc = subprocess.Popen(self.cmd, stdout=self.logf, stderr=subprocess.STDOUT, preexec_fn=stacklib._die_with_parent)
        return self

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is None:
            return
        for sig, wait in ((signal.SIGINT, 10), (signal.SIGKILL, 5)):
            try:
                os.killpg(self.proc.pid, sig)
                self.proc.wait(timeout=wait)
                break
            except Exception:
                continue
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            pass
        self.logf.close()
        self.proc = None


def run_episode(cli, ep, pids, max_time):
    if cli.sim_call(dict(op='reset', episode=ep['id'], pose=ep['start'], static_obs=ep['static_obs'],
                         dyn_obs=ep['dyn_obs'])) is None:
        return dict(status='sim_timeout')
    cli.clear()
    cli.spin_for(1.0)
    cli.clear()
    cli.spin_for(0.5)
    g = NavigateToPose.Goal()
    g.pose.header.frame_id = 'map'
    gx, gy, gth = ep['goal']
    g.pose.pose.position.x, g.pose.pose.position.y = gx, gy
    g.pose.pose.orientation.z, g.pose.pose.orientation.w = math.sin(gth / 2), math.cos(gth / 2)
    fb = {'rec': 0}

    def on_fb(m):
        fb['rec'] = max(fb['rec'], m.feedback.number_of_recoveries)

    for p in pids.values():
        try:
            p.cpu_percent(None)
        except psutil.Error:
            pass
    cli.plans = []
    t0 = time.monotonic()
    send = cli.nav.send_goal_async(g, feedback_callback=on_fb)
    while not send.done() and time.monotonic() - t0 < 10:
        rclpy.spin_once(cli, timeout_sec=0.05)
    if not send.done() or not send.result().accepted:
        return dict(status='rejected')
    gh = send.result()
    res = gh.get_result_async()
    status = None
    while time.monotonic() - t0 < max_time:
        rclpy.spin_once(cli, timeout_sec=0.05)
        if res.done():
            status = res.result().status
            break
    if status is None:
        cf = gh.cancel_goal_async()
        end = time.monotonic() + 5
        while time.monotonic() < end and not (cf.done() and res.done()):
            rclpy.spin_once(cli, timeout_sec=0.05)
        stat = 'timeout'
    else:
        stat = {GoalStatus.STATUS_SUCCEEDED: 'succeeded', GoalStatus.STATUS_ABORTED: 'aborted',
                GoalStatus.STATUS_CANCELED: 'canceled'}.get(status, f'status{status}')
    cpu = {}
    for n, p in pids.items():
        try:
            cpu[n] = p.cpu_percent(None)
        except psutil.Error:
            cpu[n] = None
    s = cli.sim_call(dict(op='stats', episode=ep['id'])) or {}
    pose = s.get('pose', [math.nan] * 3)
    out = dict(status=stat, wall_time=time.monotonic() - t0, recoveries=fb['rec'],
               goal_err=math.hypot(pose[0] - gx, pose[1] - gy),
               yaw_err=abs(math.atan2(math.sin(pose[2] - gth), math.cos(pose[2] - gth))), cpu=cpu)
    for k in METRIC_KEYS:
        out[k] = s.get(k)
    if s.get('n_clear'):
        out['mean_clear'] = s['sum_clear'] / s['n_clear']
    out['_traj'] = dict(traj=s.get('traj', []), collision_pts=s.get('collision_pts', []),
                        first_plan=cli.plans[0] if cli.plans else [], last_plan=cli.plans[-1] if cli.plans else [])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cfg-dir', required=True)
    ap.add_argument('--map', required=True)
    ap.add_argument('--episodes', required=True)
    ap.add_argument('--ids', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--speed', type=float, default=0.3, help='reference speed for the per-episode timeout')
    a = ap.parse_args()
    eps = json.load(open(a.episodes))
    keep = set(a.ids.split(',')) if a.ids else None
    eps = [e for e in eps if keep is None or e['id'] in keep]
    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            try:
                done.add(json.loads(line)['id'])
            except Exception:
                pass
    eps = [e for e in eps if e['id'] not in done]
    if not eps:
        return
    launch = Launch(a.cfg_dir, stacklib.map_path(a.map), eps[0]['start'], a.out + '.launch.log').start()
    rclpy.init()
    cli = Client()
    restarts, i, ready = 0, 0, False
    tdir = os.path.join(os.path.dirname(a.out), 'traj')
    os.makedirs(tdir, exist_ok=True)
    try:
        while i < len(eps):
            if not ready:
                t0 = time.monotonic()
                ok = cli.nav.wait_for_server(timeout_sec=90.0)
                while ok and time.monotonic() - t0 < 90 and not all(c.service_is_ready() for c in cli.clr):
                    rclpy.spin_once(cli, timeout_sec=0.1)
                cli.spin_for(3.0)
                pids = nav_pids(launch.proc.pid)
                ready = ok
            ep = eps[i]
            res = run_episode(cli, ep, pids, 25.0 + 4.0 * ep['ref_len'] / a.speed) if ready else dict(status='stack_failed')
            if (not launch.alive() or res['status'] in ('sim_timeout', 'rejected', 'stack_failed')) and restarts < 2:
                restarts += 1
                launch.stop()
                launch.start()
                ready = False
                continue
            traj = res.pop('_traj', None)
            if traj is not None:
                with open(os.path.join(tdir, ep['id'].replace('/', '__') + '.json'), 'w') as f:
                    json.dump(traj, f)
            rec = dict(id=ep['id'], map=ep['map'], category=ep['category'], tags=ep.get('tags', []),
                       ref_len=ep['ref_len'], restarts=restarts, **res)
            with open(a.out, 'a') as f:
                f.write(json.dumps(rec) + '\n')
            i += 1
    finally:
        launch.stop()
        cli.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
