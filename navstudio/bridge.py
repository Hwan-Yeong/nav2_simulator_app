"""rclpy bridge between the web server and the running simulation / Nav2 stack (runs in its own thread)."""
import base64
import collections
import json
import math
import threading
import time

import numpy as np
import rclpy
from rclpy.action import ActionClient
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose
from nav2_msgs.srv import ClearEntireCostmap
from nav_msgs.msg import OccupancyGrid, Path
from rcl_interfaces.msg import Log
from std_msgs.msg import String

LEVEL = {10: 'DEBUG', 20: 'INFO', 30: 'WARN', 40: 'ERROR', 50: 'FATAL'}
STATUS = {GoalStatus.STATUS_SUCCEEDED: 'succeeded', GoalStatus.STATUS_ABORTED: 'aborted',
          GoalStatus.STATUS_CANCELED: 'canceled'}


def _path_pts(msg, step=1):
    return [[round(p.pose.position.x, 3), round(p.pose.position.y, 3)] for p in msg.poses[::step]]


class Bridge(Node):
    def __init__(self):
        super().__init__('navstudio_bridge')
        rel = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.lock = threading.Lock()
        self.sim_state = None
        self.sim_state_t = 0.0
        self.plans = {'global': None, 'local': None}
        self.costmaps = {'global': None, 'local': None}
        self.seq = collections.Counter()
        self.logs = collections.deque(maxlen=500)
        self.log_seq = 0
        self.nav = dict(status='idle', recoveries=0, distance_remaining=None, nav_time=0.0, goal=None, started=None,
                        result_time=None)
        self._goal_handle = None
        self._goal_token = 0
        self.replies = collections.deque(maxlen=50)

        self.pub_cmd = self.create_publisher(String, '/sim/cmd', rel)
        self.create_subscription(String, '/sim/state', self._on_state, 10)
        self.create_subscription(String, '/sim/reply', lambda m: self.replies.append(json.loads(m.data)), rel)
        self.create_subscription(Path, '/plan', lambda m: self._on_plan('global', m), 10)
        self.create_subscription(Path, '/local_plan', lambda m: self._on_plan('local', m), 10)
        self.create_subscription(OccupancyGrid, '/global_costmap/costmap', lambda m: self._on_costmap('global', m), latched)
        self.create_subscription(OccupancyGrid, '/local_costmap/costmap', lambda m: self._on_costmap('local', m), 10)
        self.create_subscription(Log, '/rosout', self._on_log, QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE))
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.clr = [self.create_client(ClearEntireCostmap, s) for s in
                    ('/local_costmap/clear_entirely_local_costmap', '/global_costmap/clear_entirely_global_costmap')]

    # ------------------------------------------------------------ inputs
    def _on_state(self, msg):
        with self.lock:
            self.sim_state = json.loads(msg.data)
            self.sim_state_t = time.monotonic()
            self.seq['state'] += 1

    def _on_plan(self, which, msg):
        pts = _path_pts(msg, 1 if len(msg.poses) < 400 else 2)
        with self.lock:
            self.plans[which] = pts
            self.seq['plan_' + which] += 1

    def _on_costmap(self, which, msg):
        a = np.frombuffer(bytes(np.array(msg.data, dtype=np.int8).tobytes()), dtype=np.uint8)  # -1 -> 255
        info = msg.info
        cm = dict(which=which, w=info.width, h=info.height, res=info.resolution,
                  ox=info.origin.position.x, oy=info.origin.position.y,
                  data=base64.b64encode(a.tobytes()).decode())
        with self.lock:
            self.costmaps[which] = cm
            self.seq['costmap_' + which] += 1

    def _on_log(self, msg):
        if msg.level < 30 or msg.name in ('navstudio_bridge',):
            return
        with self.lock:
            self.log_seq += 1
            self.logs.append(dict(seq=self.log_seq, t=time.time(), level=LEVEL.get(msg.level, str(msg.level)),
                                  node=msg.name, msg=msg.msg[:400]))

    # ------------------------------------------------------------ commands
    def sim(self, **cmd):
        self.pub_cmd.publish(String(data=json.dumps(cmd)))

    def nav_ready(self):
        return self.nav_client.server_is_ready()

    def clear_costmaps(self):
        for c in self.clr:
            if c.service_is_ready():
                c.call_async(ClearEntireCostmap.Request())

    def send_goal(self, pose, episode=None):
        if not self.nav_ready():
            raise RuntimeError('Nav2 가 아직 준비되지 않았습니다')
        self.cancel()
        g = NavigateToPose.Goal()
        g.pose.header.frame_id = 'map'
        g.pose.pose.position.x, g.pose.pose.position.y = float(pose[0]), float(pose[1])
        th = float(pose[2]) if len(pose) > 2 else 0.0
        g.pose.pose.orientation.z, g.pose.pose.orientation.w = math.sin(th / 2), math.cos(th / 2)
        self._goal_token += 1
        token = self._goal_token
        with self.lock:
            self.nav.update(status='sending', recoveries=0, distance_remaining=None, nav_time=0.0, goal=list(pose),
                            started=time.time(), result_time=None)
        self.sim(op='metrics_reset', episode=episode or f'goal-{token}')
        fut = self.nav_client.send_goal_async(g, feedback_callback=lambda fb: self._on_feedback(token, fb))
        fut.add_done_callback(lambda f: self._on_accepted(token, f))

    def _on_feedback(self, token, fb):
        if token != self._goal_token:
            return
        f = fb.feedback
        with self.lock:
            self.nav.update(status='navigating', recoveries=int(f.number_of_recoveries),
                            distance_remaining=round(float(f.distance_remaining), 2),
                            nav_time=round(f.navigation_time.sec + f.navigation_time.nanosec * 1e-9, 1))

    def _on_accepted(self, token, fut):
        gh = fut.result()
        if token != self._goal_token:
            return
        if not gh.accepted:
            with self.lock:
                self.nav.update(status='rejected', result_time=time.time())
            return
        self._goal_handle = gh
        with self.lock:
            self.nav['status'] = 'navigating'
        gh.get_result_async().add_done_callback(lambda f: self._on_result(token, f))

    def _on_result(self, token, fut):
        if token != self._goal_token:
            return
        st = STATUS.get(fut.result().status, f'status{fut.result().status}')
        with self.lock:
            self.nav.update(status=st, result_time=time.time())
        self._goal_handle = None

    def cancel(self):
        gh, self._goal_handle = self._goal_handle, None
        if gh is not None:
            gh.cancel_goal_async()
            with self.lock:
                self.nav.update(status='canceled', result_time=time.time())

    def reset_view_state(self):
        with self.lock:
            self.sim_state = None
            self.plans = {'global': None, 'local': None}
            self.costmaps = {'global': None, 'local': None}
            self.nav.update(status='idle', recoveries=0, distance_remaining=None, nav_time=0.0, goal=None)
            self.seq['reset'] += 1

    def snapshot(self):
        with self.lock:
            return dict(sim=self.sim_state, sim_age=time.monotonic() - self.sim_state_t if self.sim_state_t else None,
                        nav=dict(self.nav), seq=dict(self.seq), plans=dict(self.plans),
                        costmaps=dict(self.costmaps), logs=list(self.logs), log_seq=self.log_seq)


class BridgeThread:
    def __init__(self):
        rclpy.init()
        self.node = Bridge()
        self.exec = MultiThreadedExecutor(num_threads=2)
        self.exec.add_node(self.node)
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()

    def _spin(self):
        try:
            self.exec.spin()
        except Exception:
            pass

    def shutdown(self):
        try:
            self.exec.shutdown()
            self.node.destroy_node()
            rclpy.try_shutdown()
        except Exception:
            pass
