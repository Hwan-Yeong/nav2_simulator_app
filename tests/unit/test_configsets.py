import pytest

from navstudio import configsets


def test_builtin_sets_listed_first_and_read_only():
    sets = configsets.list_sets()
    assert sets and all(s['builtin'] for s in sets)
    with pytest.raises(PermissionError):
        configsets.save({'name': 'x', 'stack': 'prod'}, sets[0]['id'])


def test_save_load_overwrite_delete():
    s = configsets.save({'name': 'DWB 빠르게', 'description': 'speed', 'stack': 'prod', 'values': {'dwb_max_vel_x': 0.5}})
    assert s['id'] == 'dwb' and not s['builtin'] and s['values'] == {'dwb_max_vel_x': 0.5}
    s2 = configsets.save({'name': 'DWB 빠르게', 'stack': 'prod', 'values': {'dwb_max_vel_x': 0.45}}, s['id'])
    assert configsets.get(s['id'])['values'] == {'dwb_max_vel_x': 0.45} and s2['id'] == s['id']
    other = configsets.save({'name': 'DWB 빠르게', 'stack': 'prod'})
    assert other['id'] == 'dwb-2'
    configsets.delete(s['id'])
    with pytest.raises(KeyError):
        configsets.get(s['id'])


def test_non_ascii_name_gets_generic_id():
    assert configsets.save({'name': '느리게', 'stack': 'mppi'})['id'] == 'set'


@pytest.mark.parametrize('body, msg', [
    ({'name': '', 'stack': 'prod'}, '이름'),
    ({'name': 'a', 'stack': 'nope'}, '스택'),
    ({'name': 'a', 'stack': 'prod', 'values': {'x': 'fast'}}, 'values'),
    ({'name': 'a', 'stack': 'prod', 'raw': '- just a list'}, 'YAML'),
])
def test_validation(body, msg):
    with pytest.raises(ValueError, match=msg):
        configsets.save(body)


def test_delete_builtin_or_unknown_fails():
    with pytest.raises(KeyError):
        configsets.delete(configsets.list_sets()[0]['id'])
    with pytest.raises(KeyError):
        configsets.delete('../etc')
