import pytest

from navstudio import paramgen, robot as robotlib, schema

STACKS = [s['id'] for s in paramgen.list_stacks()]
ROBOTS = [r['id'] for r in robotlib.list_profiles()]


@pytest.mark.parametrize('stack', STACKS)
@pytest.mark.parametrize('rid', ROBOTS)
def test_every_stack_robot_pair_generates(stack, rid):
    R = robotlib.load(rid)
    st = paramgen.load_stack(stack)
    if R['drive'] not in st['drives']:
        pytest.skip('stack does not support this drive')
    doc, warn = paramgen.generate(stack, R)
    ctl = paramgen.node_params(doc, 'controller_server')
    assert ctl and paramgen.node_params(doc, 'planner_server')
    assert isinstance(warn, list)


def test_set_dotted_keeps_flat_keys():
    d = {'FollowPath.BaseObstacle.scale': 0.02, 'FollowPath': {'max_vel_x': 0.3}}
    paramgen.set_dotted(d, 'FollowPath.BaseObstacle.scale', 0.4)
    assert d['FollowPath.BaseObstacle.scale'] == 0.4
    paramgen.set_dotted(d, 'FollowPath.max_vel_x', 0.5)
    assert d['FollowPath']['max_vel_x'] == 0.5


def test_overrides_drop_parameters_of_other_stacks():
    R = robotlib.load('everybot')
    dwb = next(p['id'] for p in schema.load()['params'] if (p.get('when') or {}).get('controller') == ['dwb'])
    assert schema.to_overrides(R, {dwb: 1.0})
    assert schema.to_overrides(R, {dwb: 1.0}, 'mppi') == {}
    assert schema.to_overrides(R, {'not_a_param': 1.0}) == {}


def test_polygon_robot_inflation_covers_circumscribed_radius():
    R = robotlib.load('rect_amr')
    ins, circ = robotlib.inscribed_circumscribed(R)
    doc, _ = paramgen.generate('prod', R)
    infl = paramgen.get_dotted(paramgen.node_params(doc, 'local_costmap'), 'inflation_layer.inflation_radius')
    assert infl >= circ
