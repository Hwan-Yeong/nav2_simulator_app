"""Sensor type registry. Built-in types are the modules listed in BUILTIN; extra types are the .py files in
<NAVSTUDIO_HOME>/sensor_types/ (each defines SENSOR = SomeSensorType(); see base.py and docs/SENSORS.md)."""
import importlib
import importlib.util
import os

from .. import paths
from .base import COMMON, Measurement, Param, SensorType  # noqa: F401

BUILTIN = ('lidar2d', 'tof', 'ultrasonic', 'depth')
_registry = None
errors = {}


def _load():
    reg = {}
    for name in BUILTIN:
        mod = importlib.import_module(f'{__name__}.{name}')
        reg[mod.SENSOR.type] = mod.SENSOR
    d = paths.user('sensor_types')
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.py') or fn.startswith('_'):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f'navstudio_user_sensor_{fn[:-3]}', os.path.join(d, fn))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                st = mod.SENSOR
                if not isinstance(st, SensorType) or not st.type or st.type in reg:
                    raise ValueError(f'SENSOR 가 SensorType 이 아니거나 type 이 비었거나 이미 있습니다 ({st.type})')
                reg[st.type] = st
            except Exception as e:  # a broken user type must not take the app down
                errors[fn] = str(e)
    return reg


def registry():
    global _registry
    if _registry is None:
        _registry = _load()
    return _registry


def get(t):
    reg = registry()
    if t not in reg:
        raise ValueError(f"알 수 없는 센서 종류입니다: {t} (사용 가능: {', '.join(reg)})")
    return reg[t]


def types():
    return tuple(registry())


def schemas():
    return [st.schema() for st in registry().values()]
