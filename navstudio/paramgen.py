"""Nav2 parameter generation.

params = base YAML (production)  -> sim adaptation  -> stack preset  -> robot profile  -> user changes

Override format:
  {"controller_server": {"FollowPath.max_vel_x": 0.3},      dotted path under ros__parameters
   "local_costmap": {"inflation_layer.cost_scaling_factor": 3.0},
   "controller_server!": {"FollowPath": {...}}}              trailing '!' replaces whole sub-trees
A value of None deletes the key. Production files use flat dotted keys ('BaseObstacle.scale'); they are kept.
"""
import copy
import math
import os

import yaml

from . import paths, robot as robotlib

ARM_ONLY_LAYERS = ('perception_replace_layer', 'cliff_replace_layer')
PERCEPTION_NODE = 'navstudio_perception'
PERCEPTION_LAYER = 'perception_layer'      # perception mode 'rules': confirmed obstacles / drops
SENSOR_LAYER = 'sensor_layer'              # perception mode 'direct': raw range-sensor clouds in a voxel layer
COSTMAPS = ('local_costmap', 'global_costmap')
CUSTOM_PLUGINS = ('everybot_path_planner', 'everybot_theta_star_planner', 'everybot_behavior_plugins')


def base_params_path():
    p = paths.user('base', 'navigation_params.yaml')
    return p if os.path.exists(p) else paths.data('base', 'navigation_params.yaml')


def bt_path(name='everybot_behavior_obstacle.xml'):
    return paths.data('base', name)


def node_params(doc, node):
    if node in COSTMAPS:
        return doc.setdefault(node, {}).setdefault(node, {}).setdefault('ros__parameters', {})
    return doc.setdefault(node, {}).setdefault('ros__parameters', {})


_IDX = __import__('re').compile(r'^(.*)\[(\d+)\]$')


def set_dotted(d, path, value, replace=False):
    m = _IDX.match(path)
    if m:  # list element, e.g. 'max_velocity[0]'
        lst = get_dotted(d, m.group(1))
        if not isinstance(lst, list) or int(m.group(2)) >= len(lst):
            raise KeyError(f'{m.group(1)} 는 길이가 충분한 리스트가 아닙니다')
        lst[int(m.group(2))] = copy.deepcopy(value)
        return
    keys = path.split('.')
    for i in range(len(keys) - 1):
        rest = '.'.join(keys[i:])
        if rest in d:  # keep the production file's flat dotted key form
            keys = keys[:i] + [rest]
            break
        d = d.setdefault(keys[i], {})
    last = keys[-1]
    if value is None:
        d.pop(last, None)
    elif isinstance(value, dict) and not replace and isinstance(d.get(last), dict):
        for k, v in value.items():
            set_dotted(d[last], k, v)
    else:
        d[last] = copy.deepcopy(value)


def get_dotted(d, path, default=None):
    m = _IDX.match(path)
    if m:
        lst = get_dotted(d, m.group(1))
        i = int(m.group(2))
        return lst[i] if isinstance(lst, list) and i < len(lst) else default
    keys = path.split('.')
    i = 0
    while i < len(keys):
        if not isinstance(d, dict):
            return default
        for j in range(len(keys), i, -1):  # longest flat key first
            k = '.'.join(keys[i:j])
            if k in d:
                d = d[k]
                i = j
                break
        else:
            return default
    return d


def apply_overrides(doc, overrides):
    for node, kv in sorted((overrides or {}).items(), key=lambda it: not it[0].endswith('!')):
        replace = node.endswith('!')
        p = node_params(doc, node.rstrip('!'))
        for path, v in (kv or {}).items():
            set_dotted(p, path, v, replace=replace)


def merge_overrides(*ovs):
    out = {}
    for ov in ovs:
        for node, kv in (ov or {}).items():
            out.setdefault(node, {}).update(copy.deepcopy(kv or {}))
    return out


def sim_adapt(doc, bt_xml):
    for node, body in doc.items():
        if node in COSTMAPS:
            body[node]['ros__parameters']['use_sim_time'] = True
        elif isinstance(body, dict) and 'ros__parameters' in body:
            body['ros__parameters']['use_sim_time'] = True
    for cm in COSTMAPS:
        p = node_params(doc, cm)
        p['plugins'] = [pl for pl in p.get('plugins', []) if pl not in ARM_ONLY_LAYERS]
        for pl in ARM_ONLY_LAYERS:
            p.pop(pl, None)
        p.pop('filters', None)
        p.pop('keepout_filter', None)
        ol = p.get('obstacle_layer')
        if ol and 'keepout_zones' in ol:
            ol.pop('keepout_zones')
    node_params(doc, 'bt_navigator')['default_nav_to_pose_bt_xml'] = bt_xml
    doc.pop('recoveries_server', None)
    return doc


def _controller_kind(doc):
    fp = node_params(doc, 'controller_server').get('FollowPath', {})
    plug = fp.get('plugin', '') + ' ' + fp.get('primary_controller', '')
    if 'mppi' in plug.lower():
        return 'mppi'
    if 'regulated_pure_pursuit' in plug:
        return 'rpp'
    if 'dwb' in plug.lower():
        return 'dwb'
    if 'graceful' in plug.lower():
        return 'graceful'
    return 'other'


def robot_overrides(doc, R):
    """Footprint, sensor observation sources and kinematic structure from the robot profile."""
    poly = robotlib.polygon(R)
    for cm in COSTMAPS:
        p = node_params(doc, cm)
        if R['footprint']['type'] == 'circle':
            p['robot_radius'] = round(R['footprint']['radius'] + R['footprint_padding'], 4)
            p.pop('footprint', None)
            p.pop('footprint_padding', None)
        else:
            p.pop('robot_radius', None)
            p['footprint'] = '[' + ', '.join(f'[{x:.3f}, {y:.3f}]' for x, y in poly) + ']'
            p['footprint_padding'] = float(R['footprint_padding'])
        if R['footprint']['type'] == 'polygon' and isinstance(p.get('inflation_layer'), dict):
            # Nav2: for non-circular footprints the inflation must reach the circumscribed radius
            ins, circ = robotlib.inscribed_circumscribed(R)
            need = round(circ + R['footprint_padding'] + 0.05, 2)
            if float(p['inflation_layer'].get('inflation_radius', 0)) < need:
                p['inflation_layer']['inflation_radius'] = need
            # cost at the circumscribed radius must stay > 0 (252*exp(-k*(circ-ins)) >= ~3)
            kmax = round(math.log(252 / 3) / max(circ - ins, 0.05), 2)
            if float(p['inflation_layer'].get('cost_scaling_factor', 10)) > kmax:
                p['inflation_layer']['cost_scaling_factor'] = kmax
        ol = p.get('obstacle_layer')
        if ol is not None:
            names = [s for s in str(ol.get('observation_sources', 'scan')).split() if s in ol]
            tmpl = copy.deepcopy(ol.get(names[0])) if names else {}
            for n in names:
                ol.pop(n, None)
            srcs = []
            lid = {s['name']: s for s in robotlib.lidars(R)}
            mg = R['scan_merge']
            for name, topic in robotlib.scan_sources(R):
                rmin, rmax = (mg['range_min'], mg['range_max']) if name == 'scan' and mg['enabled'] else \
                    (lid[name]['range_min'], lid[name]['range_max'])
                src = copy.deepcopy(tmpl) or dict(clearing=True, marking=True, data_type='LaserScan',
                                                  obstacle_max_range=2.5, raytrace_max_range=3.0,
                                                  observation_persistence=0.0)
                src['topic'] = topic
                src['data_type'] = 'LaserScan'
                src['obstacle_min_range'] = float(rmin)
                src['raytrace_min_range'] = float(rmin)
                src['obstacle_max_range'] = min(float(src.get('obstacle_max_range', 2.5)), float(rmax))
                src['raytrace_max_range'] = min(float(src.get('raytrace_max_range', 3.0)), float(rmax))
                ol[name] = src
                srcs.append(name)
            ol['observation_sources'] = ' '.join(srcs)
        _range_sensor_layers(p, R, cm)
    if robotlib.perception_node(R):
        from .sim.perception import DEFAULTS
        prm = dict(DEFAULTS, use_sim_time=True, obstacle_max_height=round(float(R['body']['height']) + 0.05, 3))
        doc[PERCEPTION_NODE] = {'ros__parameters': prm}
    kind = _controller_kind(doc)
    fp = node_params(doc, 'controller_server').setdefault('FollowPath', {})
    vy = R['limits']['vy_max'] if R['drive'] == 'omni' else 0.0
    if kind == 'mppi':
        fp['motion_model'] = {'diff': 'DiffDrive', 'omni': 'Omni', 'ackermann': 'Ackermann'}[R['drive']]
        fp['vy_max'] = vy
        if R['drive'] == 'ackermann':
            fp.setdefault('AckermannConstraints', {})['min_turning_r'] = round(robotlib.min_turning_radius(R), 3)
    elif kind == 'dwb' and vy > 0:
        fp['max_vel_y'] = vy
        fp['min_vel_y'] = -vy
        fp['vy_samples'] = max(int(fp.get('vy_samples', 5)), 5)
        fp['acc_lim_y'] = R['limits']['ay_max']
        fp['decel_lim_y'] = -R['limits']['ay_max']
    gb = node_params(doc, 'planner_server').get('GridBased', {})
    if 'SmacPlannerHybrid' in gb.get('plugin', '') or 'SmacPlannerLattice' in gb.get('plugin', ''):
        gb['minimum_turning_radius'] = round(max(robotlib.min_turning_radius(R), 0.05), 3)
    vs = node_params(doc, 'velocity_smoother')
    for key in ('max_velocity', 'min_velocity', 'max_accel', 'max_decel'):
        if isinstance(vs.get(key), list) and len(vs[key]) == 3:
            sign = -1 if key in ('min_velocity', 'max_decel') else 1
            ref = vy if 'velocity' in key else R['limits']['ay_max']
            vs[key][1] = sign * ref if vy > 0 else 0.0
    return doc


def _insert_layer(p, name):
    plugins = list(p.get('plugins', []))
    if name not in plugins:
        at = plugins.index('inflation_layer') if 'inflation_layer' in plugins else len(plugins)
        plugins.insert(at, name)
    p['plugins'] = plugins


def _range_sensor_layers(p, R, cm):
    """Costmap layer for ToF / ultrasonic / depth: perception output ('rules') or the raw clouds ('direct')."""
    s3 = robotlib.sensors_3d(R)
    mode = R['perception']['mode']
    local = cm == 'local_costmap'
    if s3 and mode == 'rules':
        src = lambda topic: dict(topic=topic, data_type='PointCloud2', sensor_frame='base_link', marking=True, clearing=False,
                                 min_obstacle_height=-1.0, max_obstacle_height=2.0, obstacle_min_range=0.0,
                                 obstacle_max_range=3.0 if local else 10.0, observation_persistence=0.0,
                                 expected_update_rate=0.0, inf_is_valid=False)
        p[PERCEPTION_LAYER] = dict(plugin='nav2_costmap_2d::ObstacleLayer', enabled=True, footprint_clearing_enabled=False,
                                   combination_method=1, observation_sources='perception_obstacles perception_drops',
                                   perception_obstacles=src('/perception/obstacles'), perception_drops=src('/perception/drops'))
        _insert_layer(p, PERCEPTION_LAYER)
    elif s3 and mode == 'direct':
        top = round(float(R['body']['height']) + 0.05, 3)
        names = []
        layer = dict(plugin='nav2_costmap_2d::VoxelLayer', enabled=True, footprint_clearing_enabled=True, combination_method=1,
                     publish_voxel_map=False, origin_z=0.0, z_resolution=0.05, z_voxels=max(4, min(16, int(top / 0.05) + 1)),
                     max_obstacle_height=top, mark_threshold=0, unknown_threshold=15)
        for s in s3:
            names.append(s['name'])
            layer[s['name']] = dict(topic=f"/sensors/{s['name']}/points", data_type='PointCloud2', marking=True, clearing=True,
                                    min_obstacle_height=0.02, max_obstacle_height=top, obstacle_min_range=0.0,
                                    obstacle_max_range=min(float(s['range_max']), 2.5), raytrace_min_range=0.0,
                                    raytrace_max_range=min(float(s['range_max']), 3.0), observation_persistence=0.0,
                                    expected_update_rate=0.0, inf_is_valid=False)
        layer['observation_sources'] = ' '.join(names)
        p[SENSOR_LAYER] = layer
        _insert_layer(p, SENSOR_LAYER)


def available_packages():
    """ROS packages discoverable in the current environment (ament index)."""
    try:
        from ament_index_python.packages import get_packages_with_prefixes
        return set(get_packages_with_prefixes().keys())
    except Exception:
        return set()


def plugin_fallbacks(doc, have):
    """Swap custom plugins that are not built for stock Nav2 ones. Returns human-readable warnings."""
    warn = []
    ps = node_params(doc, 'planner_server')
    for pid, pl in list(ps.items()):
        if isinstance(pl, dict) and isinstance(pl.get('plugin'), str):
            pkg = pl['plugin'].split('/')[0]
            if pkg in CUSTOM_PLUGINS and pkg not in have:
                if pkg == 'everybot_path_planner':
                    ps[pid] = dict(plugin='nav2_navfn_planner/NavfnPlanner', tolerance=0.5, use_astar=True,
                                   allow_unknown=pl.get('allow_unknown', False))
                else:
                    ps[pid] = dict(plugin='nav2_theta_star_planner/ThetaStarPlanner', how_many_corners=8,
                                   w_euc_cost=1.0, w_traversal_cost=2.0, allow_unknown=pl.get('allow_unknown', True))
                warn.append(f'{pkg} 가 빌드되어 있지 않아 {pid} 를 {ps[pid]["plugin"]} 로 대체했습니다 '
                            f'(navstudio build-plugins 로 빌드).')
    bt = node_params(doc, 'bt_navigator')
    libs = bt.get('plugin_lib_names')
    if isinstance(libs, list) and 'everybot_behavior_plugins' not in have:
        kept = [l for l in libs if not l.startswith('everybot_')]
        if len(kept) != len(libs):
            bt['plugin_lib_names'] = kept
            warn.append('everybot_behavior_plugins 가 없어 BT 플러그인 2개를 목록에서 뺐습니다 (기본 BT 는 사용하지 않음).')
    return warn


def load_stack(sid):
    for d in (paths.user('stacks'), paths.data('stacks')):
        f = os.path.join(d, sid + '.yaml')
        if os.path.exists(f):
            st = yaml.safe_load(open(f)) or {}
            st['id'] = sid
            return st
    raise KeyError(sid)


def list_stacks():
    out = []
    for d in (paths.data('stacks'), paths.user('stacks')):
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.yaml'):
                    st = load_stack(fn[:-5])
                    out.append({k: st.get(k) for k in ('id', 'name', 'description', 'drives', 'requires', 'controller', 'planner')})
    return out


def generate(stack, robot, user_overrides=None, base=None, bt_xml=None, have=None):
    """Returns (params_doc, warnings)."""
    with open(base or base_params_path()) as f:
        doc = yaml.safe_load(f)
    st = load_stack(stack) if isinstance(stack, str) else stack
    R = robotlib.normalize(robot)
    warn = []
    if R['drive'] not in st.get('drives', ['diff']):
        warn.append(f"스택 '{st.get('name')}' 은 {R['drive']} 구동을 지원하지 않습니다 (지원: {', '.join(st.get('drives', []))}).")
    bt = bt_xml or (paths.data('base', st['bt_xml']) if st.get('bt_xml') else bt_path())
    doc = sim_adapt(doc, bt)
    apply_overrides(doc, st.get('nav'))
    robot_overrides(doc, R)
    warn += plugin_fallbacks(doc, available_packages() if have is None else have)
    apply_overrides(doc, user_overrides)
    return doc, warn


def write(doc, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=None, allow_unicode=True)
    return path
