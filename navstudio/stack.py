"""Runs one simulation session: sim2d + Nav2 under `ros2 launch`, in its own process group."""
import collections
import ctypes
import os
import signal
import subprocess
import sys
import threading
import time

import yaml

from . import paths, paramgen, robot as robotlib

LAUNCH = os.path.join(paths.PKG, 'launch', 'nav_sim.launch.py')
MAX_SLOTS = 4   # live sessions that can run side by side (ROS_DOMAIN_ID base .. base+3)


def _die_with_parent():
    """Child setup: own process group + SIGINT when the server process dies (Linux)."""
    os.setsid()
    try:
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGINT)  # PR_SET_PDEATHSIG
    except Exception:
        pass


def kill_stale():
    """Stop sessions left over from a previous server run (each records its process group id on start)."""
    d = paths.user('sessions')
    files = [os.path.join(d, s, 'stack.pgid') for s in (os.listdir(d) if os.path.isdir(d) else [])]
    return sum(_kill_pgid_file(f) for f in files if os.path.exists(f)) > 0


def _kill_pgid_file(pgid_file):
    try:
        pgid = int(open(pgid_file).read().strip())
    except (OSError, ValueError):
        return False
    try:
        os.killpg(pgid, signal.SIGINT)
    except ProcessLookupError:
        os.remove(pgid_file)
        return False
    for _ in range(50):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        threading.Event().wait(0.1)
    else:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    os.remove(pgid_file)
    return True


class Stack:
    """One live session. name selects its session directory (sessions/<name>/: params, robot, pgid)."""

    def __init__(self, env, name='slot0'):
        self.env = env
        self.sdir = paths.user('sessions', name)
        self.pgid_file = os.path.join(self.sdir, 'stack.pgid')
        self.proc = None
        self.lock = threading.Lock()
        self.log = collections.deque(maxlen=2000)
        self.status = 'stopped'   # stopped | starting | ready | error
        self.message = ''
        self.session = None
        self.started_at = 0.0
        self._reader = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, map_id, robot_profile, stack_id, overrides, start_pose, sim_extra=None):
        """Generate params and (re)launch. Returns warnings from parameter generation."""
        self.status, self.message, self.started_at = 'starting', '이전 세션 정리 중', time.time()
        self.stop(keep_status=True)
        sdir = self.sdir
        os.makedirs(sdir, exist_ok=True)
        R = robotlib.normalize(robot_profile)
        doc, warn = paramgen.generate(stack_id, R, overrides)
        params = paramgen.write(doc, os.path.join(sdir, 'params.yaml'))
        robot_file = os.path.join(sdir, 'robot.yaml')
        with open(robot_file, 'w') as f:
            yaml.safe_dump(R, f, sort_keys=False, allow_unicode=True)
        sim = {'sim2d': {'ros__parameters': dict({'use_sim_time': False, 'seed': 1}, **(sim_extra or {}))}}
        sim_file = os.path.join(sdir, 'sim.yaml')
        with open(sim_file, 'w') as f:
            yaml.safe_dump(sim, f)
        map_yaml = map_path(map_id)
        sp = '[' + ', '.join(f'{float(v):.4f}' for v in start_pose) + ']'
        cmd = ['ros2', 'launch', LAUNCH, f'params_file:={params}', f'map:={map_yaml}', f'robot_file:={robot_file}',
               f'sim_params:={sim_file}', f'start_pose:={sp}', 'log_level:=warn', f'python:={sys.executable}',
               f'perception:={str(robotlib.perception_node(R)).lower()}']
        with self.lock:
            self.log.clear()
            self.session = dict(map=map_id, robot=R, stack=stack_id, overrides=overrides, start_pose=list(start_pose),
                                params_file=params, warnings=warn)
            self.proc = subprocess.Popen(cmd, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         preexec_fn=_die_with_parent, text=True, bufsize=1)
            with open(self.pgid_file, 'w') as f:
                f.write(str(self.proc.pid))
            self.status, self.message, self.started_at = 'starting', 'Nav2 시작 중', time.time()
        self._reader = threading.Thread(target=self._read, args=(self.proc,), daemon=True)
        self._reader.start()
        return warn

    def _read(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self.log.append(line)
        if self.proc is proc and self.status != 'stopped':
            self.status, self.message = 'error', f'Nav2 프로세스가 종료되었습니다 (코드 {proc.poll()})'

    def mark_ready(self):
        if self.status == 'starting':
            self.status, self.message = 'ready', f'준비됨 ({time.time() - self.started_at:.1f}s)'

    def stop(self, keep_status=False):
        with self.lock:
            proc, self.proc = self.proc, None
            if not keep_status:
                self.status, self.message = 'stopped', '정지됨'
        if proc is None:
            return
        pg = proc.pid

        def group_alive():
            try:
                os.killpg(pg, 0)
                return True
            except ProcessLookupError:
                return False
        try:
            os.killpg(pg, signal.SIGINT)
        except ProcessLookupError:
            pass
        # launch forwards SIGINT to sim2d and the Nav2 nodes; give the whole group a few seconds
        for sig, wait in ((None, 5.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            if sig is not None and group_alive():
                try:
                    os.killpg(pg, sig)
                except ProcessLookupError:
                    pass
            t0 = time.time()
            while group_alive() and time.time() - t0 < wait:
                time.sleep(0.1)
            if not group_alive():
                break
        try:
            proc.wait(timeout=1)
        except Exception:
            pass
        try:
            os.remove(self.pgid_file)
        except OSError:
            pass


# ------------------------------------------------------------------ maps
def map_dirs():
    return [paths.user('maps'), paths.data('maps')]


def map_path(map_id):
    for d in map_dirs():
        f = os.path.join(d, map_id, 'map.yaml')
        if os.path.exists(f):
            return f
    raise KeyError(map_id)
