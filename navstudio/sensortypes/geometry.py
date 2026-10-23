"""Mount geometry shared by the sensor types, the simulator and the perception node.

Sensor frame: x forward, y left, z up (REP 103), rotated by roll, pitch, yaw (deg) and placed at x, y, z on base_link
(z = height above the floor). Positive pitch tilts the sensor's x axis DOWN toward the floor (ROS convention).
"""
import math

import numpy as np


def rotation(roll_deg, pitch_deg, yaw_deg):
    """Sensor -> base_link rotation matrix (R = Rz(yaw) Ry(pitch) Rx(roll))."""
    r, p, y = (math.radians(v) for v in (roll_deg, pitch_deg, yaw_deg))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array([[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
                     [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
                     [-sp, cp * sr, cp * cr]])


def quaternion(roll_deg, pitch_deg, yaw_deg):
    r, p, y = (math.radians(v) / 2 for v in (roll_deg, pitch_deg, yaw_deg))
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return (sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy)


def mount_pose(s):
    """(rotation, position) of a mount."""
    return rotation(s['roll_deg'], s['pitch_deg'], s['yaw_deg']), np.array([s['x'], s['y'], s['z']], float)


def unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def floor_distance(s, tan_y=0.0, tan_z=0.0):
    """Axial distance at which a ray (1, tan_y, tan_z) from the mount meets the floor z=0; inf if it never does."""
    d = rotation(s['roll_deg'], s['pitch_deg'], s['yaw_deg']) @ np.array([1.0, tan_y, tan_z])
    if d[2] >= -1e-9:
        return math.inf
    return float(-s['z'] / d[2])
