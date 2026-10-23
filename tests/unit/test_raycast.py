import math

import numpy as np
import pytest

from navstudio import sensors
from navstudio.sim.raycast import Scene3D


def scene(wall_x=None):
    occ = np.zeros((80, 120), bool)          # 6 m x 4 m at 5 cm, origin (-1, -2)
    if wall_x is not None:
        occ[:, int((wall_x + 1) / 0.05):] = True
    return Scene3D(occ, 0.05, (-1.0, -2.0))


def ray(pitch_deg=0.0, yaw_deg=0.0):
    p, y = math.radians(pitch_deg), math.radians(yaw_deg)
    return np.array([[math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), -math.sin(p)]])


def test_floor_hit_of_a_down_tilted_ray():
    t = scene().cast((0, 0, 0.1), ray(45), 4.0)
    assert t[0] == pytest.approx(0.1 * math.sqrt(2), abs=1e-9)


def test_out_of_range_is_inf():
    assert np.isinf(scene().cast((0, 0, 0.1), ray(5), 0.5)[0])


def test_drop_lower_floor_and_side_wall():
    s = scene()
    s.set_objects(drops=[[0.5, -1, 3.0, 1, 0.2]])
    t = s.cast((0, 0, 0.1), ray(10), 4.0)[0]
    assert t == pytest.approx(0.3 / math.sin(math.radians(10)), rel=1e-6)          # reaches the lower floor
    s.set_objects(drops=[[0.5, -1, 1.0, 1, 0.5]])
    t = s.cast((0, 0, 0.1), ray(10), 4.0)[0]
    assert t == pytest.approx(1.0 / math.cos(math.radians(10)), rel=1e-6)          # hits the far side wall at x=1


def test_low_box_seen_only_below_its_top():
    s = scene()
    s.set_objects(boxes=[[1.1, 0, 0.1, 0.1, 0, 0.0, 0.05]])
    assert np.isinf(s.cast((0, 0, 0.1), ray(0), 4.0)[0])
    assert s.cast((0, 0, 0.03), ray(0), 4.0)[0] == pytest.approx(1.0)


def test_overhang_box_and_rotated_box():
    s = scene()
    s.set_objects(boxes=[[1.1, 0, 0.1, 0.5, 0, 0.5, 0.8]])
    assert np.isinf(s.cast((0, 0, 0.1), ray(0), 4.0)[0])
    up = s.cast((0, 0, 0.1), ray(-30), 4.0)[0]
    assert up == pytest.approx(1.0 / math.cos(math.radians(30)), rel=1e-6)          # front face at x = 1.0, z = 0.68
    s.set_objects(boxes=[[1.0, 0, 0.1, 0.1, math.pi / 4, 0, 1]])
    assert s.cast((0, 0, 0.1), ray(0), 4.0)[0] == pytest.approx(1.0 - 0.1 * math.sqrt(2), rel=1e-6)


def test_cylinder_side_and_top_cap():
    s = scene()
    s.set_objects(cyls=[[1.0, 0, 0.1, 0, 1.7]])
    assert s.cast((0, 0, 0.5), ray(0), 4.0)[0] == pytest.approx(0.9)
    s.set_objects(cyls=[[1.0, 0, 0.3, 0, 0.05]])
    t = s.cast((0, 0, 0.3), ray(15), 4.0)[0]
    x = t * math.cos(math.radians(15))
    assert 0.7 <= x <= 1.3 and 0.3 - t * math.sin(math.radians(15)) == pytest.approx(0.05, abs=1e-6)


def test_walls_from_the_grid_and_moving_cylinders():
    s = scene(wall_x=2.0)
    t = s.cast((0, 0, 0.2), ray(0), 4.0)[0]
    assert abs(t - 2.0) <= 0.05
    t = s.cast((0, 0, 0.2), ray(0), 4.0, extra_cyls=[[1.0, 0, 0.2, 0, 1.7]])[0]
    assert t == pytest.approx(0.8)


def test_zone_layout_matches_the_driver():
    s = sensors.normalize_mount(dict(name='m', type='tof', zones_x=8, zones_y=8, fov_h_deg=45, fov_v_deg=45))
    ty, tz = sensors.zone_tangents(s)
    assert ty[0] == pytest.approx(math.tan(math.radians(45) * 7 / 16))      # top-left zone looks left and up
    assert tz[63] == pytest.approx(-math.tan(math.radians(45) * 7 / 16))
    rays = sensors.zone_rays(dict(s, rays_per_zone=1))
    assert rays.shape == (64, 1, 3)
    assert rays[0, 0, 1] / rays[0, 0, 0] == pytest.approx(ty[0])
    masked = sensors.zone_rays(dict(s, zone_mask=[0, 63], rays_per_zone=2))
    assert masked.shape == (2, 4, 3)


def test_pitch_down_meets_the_floor():
    s = sensors.normalize_mount(dict(name='m', type='tof', z=0.08, pitch_deg=30))
    assert sensors.floor_distance(s) == pytest.approx(0.08 / math.sin(math.radians(30)), rel=1e-9)
    assert math.isinf(sensors.floor_distance(dict(s, pitch_deg=-5)))
