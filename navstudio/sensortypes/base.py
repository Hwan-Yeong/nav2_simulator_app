"""Base class of a sensor type. A sensor type is one module in navstudio/sensortypes/ (or a .py file in
<NAVSTUDIO_HOME>/sensor_types/) defining a subclass of SensorType and a module-level SENSOR = TheClass().

What a type defines
  type, label, description   identity shown in the UI
  params                     list of Param: the UI forms (sensor library, robot mounts) are generated from it,
                             values are validated against kind / min / max
  validate(p)                extra checks across parameters (optional)
  planar                     True for 2D scanners simulated on the occupancy grid (lidar2d); False: 3D rays
  rays(p)                    unit rays in the sensor frame, shape (n, 3)            [3D types]
  measure(p, rays, t, rng)   turn distances along the rays into a Measurement      [3D types]
  outputs(name)              ROS topics the simulator publishes: [(topic, msg_type_name)]
  publish(p, m, pubs, header, mount)  publish one Measurement
  perception_input           ('zones'|'points', topic suffix) that the perception node reads
  perceive(mount, data, cfg) obstacle / drop candidates in base_link from the latest data (perception 'rules')
  floor_seen(mount, data, cfg)  bare floor seen now (clears confirmed obstacles there)              [optional]
  fov                        (horizontal, vertical) field-of-view param keys, for drawing in the robot designer
Measurement.vis is what the UI shows in the sensor view: {zones, nx, ny} grid, {w, h, depth} image,
{range} one distance or {ranges} a list (0 / None = no return).
A template to start from: navstudio/data/sensor_type_template.py (the sensor library writes a copy for you).
"""
from dataclasses import dataclass, field

import numpy as np

KINDS = ('float', 'int', 'bool', 'color', 'zones')


@dataclass
class Param:
    key: str
    label: str
    default: object
    kind: str = 'float'
    min: float = None
    max: float = None
    step: float = None
    unit: str = ''
    help: str = ''
    group: str = '측정'

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


COMMON = [
    Param('hz', '주기', 10.0, min=0.5, max=200, step=1, unit='Hz', group='공통'),
    Param('range_min', '최소 거리', 0.05, min=0.0, max=50, step=0.01, unit='m', group='공통'),
    Param('range_max', '최대 거리', 4.0, min=0.05, max=100, step=0.1, unit='m', group='공통'),
    Param('noise', '거리 잡음 σ', 0.01, min=0.0, max=1.0, step=0.001, unit='m', group='잡음', help='매 측정에 더하는 정규분포 잡음의 표준편차'),
    Param('dropout', '측정 누락 확률', 0.0, min=0.0, max=0.99, step=0.01, group='잡음', help='빔(존·픽셀)이 아무것도 돌려주지 않을 확률'),
    Param('color', '표시 색', '#e5484d', kind='color', group='공통'),
]


@dataclass
class Measurement:
    points: np.ndarray                     # (m, 3) in the sensor frame (what the driver would turn into a cloud)
    raw: object = None                     # type-specific raw output (zone grid, range, depth image)
    vis: dict = field(default_factory=dict)  # compact data for the UI
    hit_index: np.ndarray = None           # indices of the rays whose hits the UI should draw


class SensorType:
    type = ''
    label = ''
    description = ''
    planar = False
    params = []
    defaults_override = {}
    perception_input = ('points', 'points')
    fov = None

    def all_params(self):
        own = {p.key for p in self.params}
        common = [Param(**dict(p.__dict__, default=self.defaults_override.get(p.key, p.default))) for p in COMMON if p.key not in own]
        return common + list(self.params)

    def defaults(self):
        return {p.key: p.default for p in self.all_params()}

    def check(self, p, what):
        """Generic validation from the Param list, then validate()."""
        for prm in self.all_params():
            v = p.get(prm.key, prm.default)
            if prm.kind == 'float':
                v = float(v)
            elif prm.kind == 'int':
                v = int(round(float(v)))
            elif prm.kind == 'bool':
                v = bool(v)
            elif prm.kind == 'color':
                v = str(v)
            if prm.kind in ('float', 'int'):
                if prm.min is not None and v < prm.min or prm.max is not None and v > prm.max:
                    raise ValueError(f'{what}: {prm.label} 는 {prm.min}~{prm.max}{prm.unit} 사이여야 합니다 (받은 값 {v})')
            p[prm.key] = v
        if not p['range_min'] < p['range_max']:
            raise ValueError(f'{what}: 최소 거리는 최대 거리보다 작아야 합니다')
        return self.validate(p, what)

    def validate(self, p, what):
        return p

    def schema(self):
        return dict(type=self.type, label=self.label, description=self.description, planar=self.planar, fov=self.fov,
                    params=[p.as_dict() for p in self.all_params()],
                    outputs=[dict(topic=t, msg=m) for t, m in self.outputs('<name>')])

    # ---- simulation (3D types)
    def rays(self, p):
        raise NotImplementedError

    def measure(self, p, rays, t, rng):
        raise NotImplementedError

    def outputs(self, name):
        return [(f'/sensors/{name}/points', 'sensor_msgs/PointCloud2')]

    def frames(self, name):
        """Extra static frames below <name>_link: [(child, (x, y, z), (qx, qy, qz, qw))]."""
        return []

    def publish(self, p, m, pubs, header, mount):
        pass

    # ---- perception
    def perceive(self, mount, data, cfg):
        return np.zeros((0, 2)), np.zeros((0, 2))

    def floor_seen(self, mount, data, cfg):
        """Where this sensor sees bare floor now (base_link x-y). Confirmed obstacles there are cleared
        (perception param clear_on_floor). Default: none, so marks from this type are only cleared by /perception/clear."""
        return np.zeros((0, 2))
