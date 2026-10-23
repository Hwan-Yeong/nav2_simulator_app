"""2D lidar: a planar scan at the mount height, simulated on the occupancy grid (fast), published as LaserScan."""
from .base import Param, SensorType


class Lidar2D(SensorType):
    type = 'lidar2d'
    label = '2D 라이다'
    description = '한 평면을 도는 레이저 스캐너. 장착 높이를 가로지르는 장애물만 봅니다. Nav2 장애물 레이어 입력.'
    planar = True
    fov = ('fov_deg', None)
    defaults_override = dict(hz=10.0, range_min=0.12, range_max=8.0, noise=0.01, color='#e5484d')
    params = [
        Param('fov_deg', '시야각', 360.0, min=1, max=360, step=1, unit='°', group='스캔'),
        Param('beams', '빔 수', 360, kind='int', min=8, max=4000, step=10, group='스캔', help='시야각 안의 측정 개수 (각 해상도 = 시야각 / 빔 수)'),
    ]

    def outputs(self, name):
        return [(f'/scan_{name}', 'sensor_msgs/LaserScan')]


SENSOR = Lidar2D()
