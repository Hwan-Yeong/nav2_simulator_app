import io
import json
import os
import zipfile

import pytest
import yaml

from navstudio import maps, paths


def _files(mid):
    d = paths.data('maps', mid)
    meta = yaml.safe_load(open(os.path.join(d, 'map.yaml')))
    return meta, open(os.path.join(d, meta['image']), 'rb').read(), meta['image']


def test_builtin_maps_have_scenarios_and_names():
    ms = {m['id']: m for m in maps.list_maps()}
    assert {'synth_narrow', 'synth_clutter', 'synth_corridor', 'synth_warehouse'} <= set(ms)
    assert all(m['builtin'] and m['scenarios'] > 0 and m['group'] == '합성' for m in ms.values())


def test_export_import_roundtrip_keeps_info_and_scenarios():
    z = maps.export_zip('synth_narrow')
    got = maps.import_files([('pack.zip', z)])
    assert len(got) == 1
    mid, name = got[0]
    assert mid == 'synth_narrow_2' and name == '좁은 문 (2)'     # id and name never collide with the bundled map
    assert len(maps.scenarios(mid)) == len(maps.scenarios('synth_narrow'))
    assert maps.meta(mid)['width'] == maps.meta('synth_narrow')['width']


def test_zip_with_several_maps():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for mid in ('synth_clutter', 'synth_corridor'):
            with zipfile.ZipFile(io.BytesIO(maps.export_zip(mid))) as src:
                for n in src.namelist():
                    zf.writestr('pack/' + n.replace(mid, 'pack_' + mid[6:], 1), src.read(n))
    got = dict(maps.import_files([('pack.zip', buf.getvalue())]))
    assert set(got) == {'pack_clutter', 'pack_corridor'}


def test_loose_yaml_and_image_pair_by_name_and_display_name():
    meta, img, fn = _files('synth_clutter')
    ext = os.path.splitext(fn)[1]
    y = yaml.safe_dump(dict(meta, image='office3' + ext)).encode()
    got = maps.import_files([('office3.yaml', y), ('office3' + ext, img)], name='3층 사무실')
    assert got == [('office3', '3층 사무실')]
    assert [m for m in maps.list_maps() if m['id'] == 'office3'][0]['group'] == '내 맵'


def test_single_yaml_single_image_pair_even_if_names_differ():
    meta, img, fn = _files('synth_clutter')
    got = maps.import_files([('a.yaml', yaml.safe_dump(dict(meta, image='x.pgm')).encode()), ('scan' + os.path.splitext(fn)[1], img)])
    assert got[0][0] == 'a'


def test_missing_image_and_bad_yaml():
    meta, _, _ = _files('synth_clutter')
    with pytest.raises(ValueError, match='이미지'):
        maps.import_files([('a.yaml', yaml.safe_dump(meta).encode())])
    with pytest.raises(ValueError, match='YAML'):
        maps.import_files([('notes.txt', b'hello')])
    with pytest.raises(ValueError):
        maps.import_files([('a.yaml', yaml.safe_dump(dict(meta, image='a.png')).encode()), ('a.png', b'not an image')])
    assert not [m for m in maps.list_maps() if not m['builtin']]   # nothing half-written


def test_rename_and_delete_user_map_only():
    mid, _ = maps.import_files([('p.zip', maps.export_zip('synth_corridor'))])[0]
    maps.rename(mid, '새 이름')
    assert [m['name'] for m in maps.list_maps() if m['id'] == mid] == ['새 이름']
    with pytest.raises(KeyError):
        maps.delete('synth_corridor')
    with pytest.raises(KeyError):
        maps.rename('synth_corridor', 'x')
    maps.delete(mid)
    assert mid not in {m['id'] for m in maps.list_maps()}


def test_footprint_clearance_at_map_start_is_positive():
    m = maps.meta('synth_narrow')
    square = [[0.2, 0.2], [-0.2, 0.2], [-0.2, -0.2], [0.2, -0.2]]
    assert maps.footprint_clearance('synth_narrow', m['start'], square) > 0
