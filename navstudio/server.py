"""Nav Studio web server: REST API + WebSocket stream + static UI.

Live sessions run in up to MAX_SLOTS slots. Slot i uses ROS_DOMAIN_ID = base domain + i, its own `ros2 launch`
process group (stack.Stack) and its own rclpy bridge, so several configurations can drive side by side. The scene
(start, goal, obstacles, pedestrians) is shared by all slots.
"""
import asyncio
import base64
import contextlib
import difflib
import json
import os
import threading
import time
import zlib

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, configsets, maps, paramgen, paths, robot as robotlib, schema, sensors as sensorlib
from .stack import MAX_SLOTS, Stack


@contextlib.asynccontextmanager
async def _lifespan(_app):
    task = asyncio.create_task(_watch())
    yield
    task.cancel()


app = FastAPI(title='Nav Studio', version=__version__, lifespan=_lifespan)
S = dict(env=None, domain=None, slots=[], scene=None)


class Slot:
    """One live session: a Nav2 stack + simulator and the bridge that talks to it."""

    def __init__(self, idx, env, domain):
        self.idx, self.domain = idx, domain
        self.stack = Stack(dict(env, ROS_DOMAIN_ID=str(domain)), f'slot{idx}')
        self.bridge = None    # created on first start (an idle bridge would still join the DDS domain)
        self.config = None
        self.launch = None    # last stack.start() arguments, for the automatic retry of a stalled bring-up
        self.retried = False
        self._lock = threading.Lock()

    def node(self):
        with self._lock:
            if self.bridge is None:
                from .bridge import BridgeThread
                self.bridge = BridgeThread(self.domain)
        return self.bridge.node

    @property
    def ready(self):
        return self.stack.status == 'ready' and self.bridge is not None

    def info(self):
        return dict(slot=self.idx, domain=self.domain, status=self.stack.status, message=self.stack.message,
                    config=self.config)


# ------------------------------------------------------------------ models
class Pose(BaseModel):
    pose: list
    slots: list[int] | None = None    # None: every running slot
    reset: bool = False               # goal only: put the robots back on the start pose and reset the scene first


class Slots(BaseModel):
    slots: list[int] | None = None


class SessionReq(BaseModel):
    slot: int = 0
    map: str
    robot_id: str | None = None
    robot: dict | None = None
    stack: str = 'prod'
    values: dict = {}
    raw_overrides: str = ''
    start: list | None = None


class PreviewReq(BaseModel):
    robot_id: str | None = None
    robot: dict | None = None
    stack: str = 'prod'
    values: dict = {}
    raw_overrides: str = ''


# ------------------------------------------------------------------ helpers
def _robot(robot_id, robot):
    if robot:
        return robotlib.normalize(robot)
    return robotlib.load(robot_id or 'everybot')


def _overrides(R, values, raw, stack_id=None):
    ov = schema.to_overrides(R, values, stack_id)
    if raw and raw.strip():
        extra = yaml.safe_load(raw)
        if not isinstance(extra, dict):
            raise ValueError('고급 오버라이드는 {노드: {경로: 값}} 형태의 YAML 이어야 합니다')
        ov = paramgen.merge_overrides(ov, extra)
    return ov


def _bad(e, code=400):
    raise HTTPException(code, str(e))


def _slot(i):
    if not isinstance(i, int) or not 0 <= i < len(S['slots']):
        _bad(f'슬롯 {i} 이 없습니다', 404)
    return S['slots'][i]


def _ready(slots=None):
    """Running slots among `slots` (None: all); 409 if none is running."""
    idx = range(len(S['slots'])) if slots is None else slots
    out = [S['slots'][i] for i in idx if 0 <= i < len(S['slots']) and S['slots'][i].ready]
    if not out:
        _bad('시뮬레이션이 실행 중이 아닙니다. 먼저 시뮬레이션을 시작하세요.', 409)
    return out


def _scene_file():
    return paths.user('sessions', 'scene.json')


def _apply_scene(slot):
    sc = S['scene']
    if sc is not None and slot.bridge is not None:
        slot.bridge.node.sim(op='world', static_obs=sc.get('static_obs', []), dyn_obs=sc.get('dyn_obs', []), episode='scene')
        slot.bridge.node.clear_costmaps()   # obstacles moved: forget what perception had confirmed


# ------------------------------------------------------------------ info / catalog
@app.get('/api/info')
def info():
    have = paramgen.available_packages()
    return dict(version=__version__, domain=S['domain'], max_slots=MAX_SLOTS, cpus=os.cpu_count(),
                plugins={p: p in have for p in paramgen.CUSTOM_PLUGINS},
                nav2=('nav2_bringup' in have or 'nav2_controller' in have), slots=[s.info() for s in S['slots']])


@app.get('/api/maps')
def list_maps():
    return maps.list_maps()


@app.get('/api/maps/{mid}')
def map_meta(mid: str):
    try:
        return maps.meta(mid)
    except KeyError:
        _bad(f'맵 {mid} 이 없습니다', 404)


@app.get('/api/maps/{mid}/grid.png')
def map_grid(mid: str):
    return Response(maps.grid_png(mid), media_type='image/png', headers={'Cache-Control': 'no-cache'})


@app.get('/api/maps/{mid}/thumb.png')
def map_thumb(mid: str):
    return Response(maps.thumb_png(mid), media_type='image/png', headers={'Cache-Control': 'no-cache'})


@app.get('/api/maps/{mid}/export.zip')
def map_export(mid: str):
    try:
        data = maps.export_zip(mid)
    except KeyError:
        _bad(f'맵 {mid} 이 없습니다', 404)
    return Response(data, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="{mid}.zip"'})


@app.post('/api/maps/{mid}/check_pose')
def map_check_pose(mid: str, body: dict):
    try:
        R = _robot(body.get('robot_id'), body.get('robot'))
        c = maps.footprint_clearance(mid, body['pose'], robotlib.polygon(R, 32))
    except Exception as e:
        _bad(e)
    return dict(clearance=c, ok=c > 0.02)


@app.post('/api/maps')
async def upload_maps(files: list[UploadFile] = File(...), name: str = Form('')):
    """Map zips and/or ROS map_server YAML + image files; see maps.import_files."""
    try:
        got = maps.import_files([(f.filename, await f.read()) for f in files], name.strip() or None)
    except Exception as e:
        _bad(f'맵을 읽지 못했습니다: {e}')
    return dict(maps=[dict(id=i, name=n) for i, n in got])


@app.patch('/api/maps/{mid}')
def rename_map(mid: str, body: dict):
    try:
        return maps.rename(mid, str(body.get('name', '')))
    except KeyError:
        _bad('직접 올린 맵만 이름을 바꿀 수 있습니다', 404)


@app.delete('/api/maps/{mid}')
def delete_map(mid: str):
    try:
        maps.delete(mid)
    except KeyError:
        _bad('직접 올린 맵만 지울 수 있습니다', 404)
    return dict(ok=True)


@app.get('/api/scenarios/{mid}')
def scenarios(mid: str):
    return maps.scenarios(mid)


@app.get('/api/robots')
def robots():
    return robotlib.list_profiles()


@app.get('/api/robots/{rid}')
def robot_get(rid: str):
    try:
        p = robotlib.load(rid)
    except KeyError:
        _bad(f'로봇 {rid} 이 없습니다', 404)
    return _robot_payload(p)


def _robot_payload(p):
    ins, circ = robotlib.inscribed_circumscribed(p)
    return dict(profile=p, derived=dict(inscribed=round(ins, 3), circumscribed=round(circ, 3),
                                        min_turning_radius=round(robotlib.min_turning_radius(p), 3),
                                        polygon=robotlib.polygon(p)))


@app.post('/api/robots/validate')
def robot_validate(body: dict):
    try:
        return _robot_payload(robotlib.normalize(body))
    except Exception as e:
        _bad(e)


_coverage_cache = {}
_coverage_lock = threading.Lock()


@app.get('/api/coverage/probes')
def coverage_probes():
    from . import coverage
    return [dict(id=k, **v) for k, v in coverage.PROBES.items()]


@app.post('/api/robots/coverage')
def robot_coverage(body: dict):
    """Where a probe object would be detected around the robot: {robot, probe: {preset | kind, size, z0, z1, depth},
    params?: perception overrides}. Takes about a second; the last results are kept."""
    from . import coverage
    if not isinstance(body.get('robot'), dict):
        _bad('robot 이 필요합니다')
    key = json.dumps(body, sort_keys=True)
    with _coverage_lock:
        hit = _coverage_cache.get(key)
    if hit is not None:
        return hit
    try:
        out = coverage.compute(body['robot'], body.get('probe'), params=body.get('params'))
    except Exception as e:
        _bad(e)
    with _coverage_lock:
        _coverage_cache[key] = out
        while len(_coverage_cache) > 16:
            _coverage_cache.pop(next(iter(_coverage_cache)))
    return out


@app.put('/api/robots/{rid}')
def robot_save(rid: str, body: dict):
    try:
        return _robot_payload(robotlib.save(rid, body))
    except Exception as e:
        _bad(e)


@app.delete('/api/robots/{rid}')
def robot_delete(rid: str):
    try:
        robotlib.delete(rid)
    except KeyError:
        _bad('사용자 로봇만 지울 수 있습니다', 404)
    return dict(ok=True)


@app.get('/api/stacks')
def stacks():
    return paramgen.list_stacks()


# ------------------------------------------------------------------ sensors: type plugins and the model library
@app.get('/api/sensor-types')
def sensor_types():
    from . import sensortypes
    return dict(types=sensortypes.schemas(), errors=sensortypes.errors, dir=sensortypes.user_dir())


@app.post('/api/sensor-types/reload')
def sensor_types_reload():
    from . import sensortypes
    sensortypes.reload()
    return sensor_types()


@app.post('/api/sensor-types/template')
def sensor_types_template(body: dict = None):
    from . import sensortypes
    return dict(path=sensortypes.write_template((body or {}).get('name') or 'my_sensor'))


@app.get('/api/sensors')
def sensor_models():
    return sensorlib.list_models()


@app.post('/api/sensors')
def sensor_create(body: dict):
    try:
        return sensorlib.save_model(body)
    except Exception as e:
        _bad(e)


@app.put('/api/sensors/{mid}')
def sensor_save(mid: str, body: dict):
    try:
        return sensorlib.save_model(body, mid)
    except PermissionError as e:
        _bad(e, 403)
    except Exception as e:
        _bad(e)


@app.delete('/api/sensors/{mid}')
def sensor_delete(mid: str):
    try:
        sensorlib.delete_model(mid)
    except KeyError:
        _bad('직접 만든 센서만 지울 수 있습니다', 404)
    return dict(ok=True)


@app.post('/api/sensors/mount')
def sensor_mount(body: dict):
    """A new mount of a library model: {model, name, x, y, ...} -> normalized mount (pose from the model's hint)."""
    try:
        model = sensorlib.get_model(body['model'])
        pose = {k: body[k] for k in sensorlib.POSE if k in body}
        return sensorlib.mount_from_model(model, body.get('name') or model['type'], **pose)
    except KeyError:
        _bad('센서 모델이 없습니다', 404)
    except Exception as e:
        _bad(e)


# ------------------------------------------------------------------ config sets (stack + parameter changes)
@app.get('/api/presets')
def presets():
    return configsets.list_sets()


@app.post('/api/presets')
def preset_create(body: dict):
    try:
        return configsets.save(body)
    except Exception as e:
        _bad(e)


@app.put('/api/presets/{sid}')
def preset_save(sid: str, body: dict):
    try:
        return configsets.save(body, sid)
    except PermissionError as e:
        _bad(e, 403)
    except Exception as e:
        _bad(e)


@app.delete('/api/presets/{sid}')
def preset_delete(sid: str):
    try:
        configsets.delete(sid)
    except KeyError:
        _bad('직접 저장한 설정 세트만 지울 수 있습니다', 404)
    return dict(ok=True)


@app.post('/api/params/schema')
def params_schema(req: PreviewReq):
    try:
        return schema.resolve(req.stack, _robot(req.robot_id, req.robot), req.values)
    except Exception as e:
        _bad(e)


@app.post('/api/params/preview')
def params_preview(req: PreviewReq):
    try:
        R = _robot(req.robot_id, req.robot)
        ov = _overrides(R, req.values, req.raw_overrides, req.stack)
        doc, warn = paramgen.generate(req.stack, R, ov)
        base, _ = paramgen.generate('prod', robotlib.load('everybot'))
    except Exception as e:
        _bad(e)
    txt = yaml.safe_dump(doc, sort_keys=False, default_flow_style=None, allow_unicode=True)
    btxt = yaml.safe_dump(base, sort_keys=False, default_flow_style=None, allow_unicode=True)
    diff = ''.join(difflib.unified_diff(btxt.splitlines(True), txt.splitlines(True), '운영 기본값', '현재 설정', n=2))
    return dict(yaml=txt, diff=diff, overrides=ov, warnings=warn)


# ------------------------------------------------------------------ live sessions
_launch_lock = asyncio.Lock()
LAUNCH_SPACING = 2.0   # s between bring-ups: several Nav2 stacks starting in the same instant lose DDS service replies


@app.post('/api/session/start')
async def session_start(req: SessionReq):
    slot = _slot(req.slot)
    try:
        R = _robot(req.robot_id, req.robot)
        ov = _overrides(R, req.values, req.raw_overrides, req.stack)
        start = req.start or maps.meta(req.map)['start']
    except Exception as e:
        _bad(e)
    loop = asyncio.get_running_loop()
    node = await loop.run_in_executor(None, slot.node)
    node.cancel()
    node.reset_view_state()
    slot.stack.status, slot.stack.message = 'starting', '시작 대기 중'
    slot.launch, slot.retried = (req.map, R, req.stack, ov, start), False
    async with _launch_lock:
        try:
            warn = await loop.run_in_executor(None, slot.stack.start, *slot.launch)
        except Exception as e:
            slot.stack.status, slot.stack.message = 'error', f'시작하지 못했습니다: {e}'
            _bad(f'시작하지 못했습니다: {e}')
        await asyncio.sleep(LAUNCH_SPACING)
    slot.config = dict(map=req.map, robot_id=req.robot_id, robot=R, stack=req.stack, values=req.values,
                       raw_overrides=req.raw_overrides, start=list(start))
    if S['scene'] is None or S['scene'].get('map') != req.map:
        S['scene'] = dict(map=req.map, static_obs=[], dyn_obs=[], start=list(start), goal=None)
    else:
        S['scene']['start'] = list(start)
    return dict(ok=True, slot=slot.idx, warnings=warn)


@app.post('/api/session/stop')
async def session_stop(body: Slots = Slots()):
    loop = asyncio.get_running_loop()
    targets = [_slot(i) for i in body.slots] if body.slots is not None else S['slots']
    for s in targets:
        if s.bridge is not None:
            s.bridge.node.cancel()
        s.config = None
    await asyncio.gather(*(loop.run_in_executor(None, s.stack.stop) for s in targets))
    return dict(ok=True)


@app.get('/api/session/log')
def session_log(slot: int = 0):
    return PlainTextResponse('\n'.join(_slot(slot).stack.log))


@app.get('/api/session/params.yaml')
def session_params(slot: int = 0):
    st = _slot(slot).stack
    if not st.session:
        _bad('실행 중인 세션이 없습니다', 404)
    return FileResponse(st.session['params_file'], media_type='text/yaml', filename=f'nav2_params_slot{slot}.yaml')


@app.get('/api/scene')
def scene_get():
    return S['scene'] or {}


@app.post('/api/scene')
def scene_set(body: dict):
    S['scene'] = dict(S['scene'] or {}, **body)
    for s in S['slots']:
        if s.ready:
            _apply_scene(s)
    os.makedirs(os.path.dirname(_scene_file()), exist_ok=True)
    json.dump(S['scene'], open(_scene_file(), 'w'))
    return S['scene']


@app.post('/api/nav/goal')
async def nav_goal(p: Pose):
    targets = _ready(p.slots)
    if p.reset:
        # same start, same pedestrians, same moment: a fair side-by-side run
        sc = S['scene'] or {}
        if not sc.get('start'):
            _bad('출발점이 없습니다', 409)
        for s in targets:
            s.bridge.node.cancel()
            s.bridge.node.sim(op='reset', pose=sc['start'], static_obs=sc.get('static_obs', []),
                              dyn_obs=sc.get('dyn_obs', []), episode='reset')
            s.bridge.node.clear_costmaps()
        await asyncio.sleep(0.8)   # let the sims apply the reset and the costmaps clear
    errors = []
    for s in targets:
        try:
            s.bridge.node.send_goal(p.pose)
        except Exception as e:
            errors.append(f'슬롯 {chr(65 + s.idx)}: {e}')
    if errors and len(errors) == len(targets):
        _bad('; '.join(errors), 409)
    if S['scene'] is not None:
        S['scene']['goal'] = list(p.pose)
    return dict(ok=True, slots=[s.idx for s in targets], errors=errors)


@app.post('/api/nav/cancel')
def nav_cancel(body: Slots = Slots()):
    for s in S['slots'] if body.slots is None else [_slot(i) for i in body.slots]:
        if s.bridge is not None:
            s.bridge.node.cancel()
    return dict(ok=True)


@app.post('/api/sim/teleport')
def sim_teleport(p: Pose):
    for s in _ready(p.slots):
        s.bridge.node.cancel()
        s.bridge.node.sim(op='teleport', pose=p.pose, episode='teleport')
        s.bridge.node.clear_costmaps()
    if S['scene'] is not None:
        S['scene']['start'] = list(p.pose)
    return dict(ok=True)


@app.post('/api/sim/clear_costmaps')
def sim_clear(body: Slots = Slots()):
    for s in _ready(body.slots):
        s.bridge.node.clear_costmaps()
    return dict(ok=True)


# ------------------------------------------------------------------ benchmark / tuning runs
from .bench import runner as runs  # noqa: E402


@app.post('/api/bench/start')
def bench_start(spec: dict):
    if not spec.get('configs'):
        _bad('비교할 설정을 하나 이상 고르세요')
    if not (spec.get('episodes') or {}).get('maps'):
        _bad('맵을 하나 이상 고르세요')
    r = runs.BenchRun(spec, S['env'])
    runs.RUNS[r.id] = r
    r.start()
    return dict(id=r.id)


@app.post('/api/tune/start')
def tune_start(spec: dict):
    if not spec.get('params'):
        _bad('튜닝할 파라미터를 하나 이상 고르세요')
    if not (spec.get('episodes') or {}).get('maps'):
        _bad('맵을 하나 이상 고르세요')
    r = runs.TuneRun(spec, S['env'])
    runs.RUNS[r.id] = r
    r.start()
    return dict(id=r.id)


@app.get('/api/runs')
def runs_list(kind: str | None = None):
    return runs.list_runs(kind)


def _run(rid):
    try:
        return runs.get(rid, S['env'])
    except KeyError:
        _bad('작업을 찾을 수 없습니다', 404)


@app.get('/api/runs/{rid}')
def run_get(rid: str, weights: str | None = None):
    r = _run(rid)
    w = json.loads(weights) if weights else (r.spec.get('weights') if r.kind == 'tune' else None)
    out = dict(id=r.id, kind=r.kind, spec=r.spec, status=r.status, message=r.message, started=r.started,
               finished=r.finished, progress=r.progress(), warnings=r.warnings, report=r.report(w))
    if r.kind == 'bench':
        feas = runs._load(os.path.join(r.dir, 'feasibility.json'), {})
        eps = []
        for k in range(len(r.spec['configs'])):
            for rec in runs.read_results(os.path.join(r.dir, f'cfg_{k}')):
                eps.append(dict(cfg=k, id=rec['id'], map=rec['map'], category=rec['category'], status=rec['status'],
                                collisions=rec.get('collisions'), duration=rec.get('duration'), path_len=rec.get('path_len'),
                                ref_len=rec.get('ref_len'), min_clear=rec.get('min_clear'), recoveries=rec.get('recoveries'), falls=rec.get('falls'),
                                gap=feas.get(rec['id'], {}).get('gap')))
        out['episodes'] = eps
    return out


@app.post('/api/runs/{rid}/cancel')
def run_cancel(rid: str):
    r = _run(rid)
    r.cancel()
    return dict(ok=True)


@app.delete('/api/runs/{rid}')
def run_delete(rid: str):
    try:
        runs.delete(rid)
    except Exception as e:
        _bad(e)
    return dict(ok=True)


@app.get('/api/runs/{rid}/episode')
def run_episode(rid: str, cfg: str, eid: str):
    r = _run(rid)
    d = os.path.join(r.dir, cfg if not cfg.isdigit() else f'cfg_{cfg}')
    ep = next((e for e in runs._load(os.path.join(r.dir, 'episodes.json'), []) if e['id'] == eid), None)
    rec = next((x for x in runs.read_results(d) if x['id'] == eid), None)
    tr = runs._load(os.path.join(d, 'traj', eid.replace('/', '__') + '.json'), None)
    robot = runs._load_yaml(os.path.join(d, 'robot.yaml'))
    if ep is None:
        _bad('에피소드를 찾을 수 없습니다', 404)
    return dict(episode=ep, record=rec, traj=tr, robot=robot)


# ------------------------------------------------------------------ live stream
def _z(b64):
    raw = base64.b64decode(b64)
    return base64.b64encode(zlib.compress(raw, 6)).decode()


@app.websocket('/api/ws')
async def ws(sock: WebSocket):
    await sock.accept()
    sent = [dict(seq={}, log=0, cm_t={'global': 0.0, 'local': 0.0}, reset=None) for _ in S['slots']]
    try:
        await sock.send_json(dict(type='hello', version=__version__, max_slots=MAX_SLOTS,
                                  slots=[s.info() for s in S['slots']], scene=S['scene']))
        while True:
            ticks, after = [], []
            for s, st in zip(S['slots'], sent):
                if s.bridge is None:
                    ticks.append(dict(slot=s.idx, stack=dict(status=s.stack.status, message=s.stack.message), sim=None, nav=None))
                    continue
                snap = s.bridge.node.snapshot()
                seq = snap['seq']
                if seq.get('reset') != st['reset']:
                    st['reset'] = seq.get('reset')
                    st['seq'] = {}
                    await sock.send_json(dict(type='reset', slot=s.idx))
                ticks.append(dict(slot=s.idx, stack=dict(status=s.stack.status, message=s.stack.message),
                                  sim=snap['sim'], nav=snap['nav']))
                for which in ('global', 'local'):
                    k = 'plan_' + which
                    if seq.get(k) and seq.get(k) != st['seq'].get(k) and snap['plans'][which] is not None:
                        st['seq'][k] = seq[k]
                        after.append(dict(type='plan', slot=s.idx, which=which, pts=snap['plans'][which]))
                    k = 'costmap_' + which
                    now = time.monotonic()
                    period = 2.0 if which == 'global' else 0.3
                    if seq.get(k) and seq.get(k) != st['seq'].get(k) and now - st['cm_t'][which] >= period \
                            and snap['costmaps'][which] is not None:
                        st['seq'][k] = seq[k]
                        st['cm_t'][which] = now
                        cm = dict(snap['costmaps'][which])
                        cm['z'] = _z(cm.pop('data'))
                        after.append(dict(type='costmap', slot=s.idx, **cm))
                k = 'perception'
                if seq.get(k) and seq.get(k) != st['seq'].get(k) and snap['perception'] is not None:
                    st['seq'][k] = seq[k]
                    after.append(dict(type='perception', slot=s.idx, **snap['perception']))
                k = 'sensors'
                if seq.get(k) and seq.get(k) != st['seq'].get(k) and snap['sensors'] is not None:
                    st['seq'][k] = seq[k]
                    after.append(dict(type='sensors', slot=s.idx, sensors=snap['sensors']))
                new = [l for l in snap['logs'] if l['seq'] > st['log']]
                if new:
                    st['log'] = new[-1]['seq']
                    after.append(dict(type='log', slot=s.idx, items=new[-50:]))
            await sock.send_json(dict(type='tick', slots=ticks))
            for m in after:
                await sock.send_json(m)
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        return
    except Exception as e:  # never let one bad frame kill the stream silently
        import traceback
        traceback.print_exc()
        try:
            await sock.close(code=1011, reason=str(e)[:100])
        except Exception:
            pass


async def _watch_slot(s):
    """Promote a slot to 'ready' when Nav2's action server is up and the simulator is publishing."""
    st = s.stack
    if st.status != 'starting' or s.bridge is None or st.proc is None:
        return
    br = s.bridge
    if br.node.nav_ready() and br.node.nav_active():
        snap = br.node.snapshot()
        if snap['sim'] is not None and time.time() - st.started_at > 2.0:
            await asyncio.sleep(0.5)  # let the costmaps receive their first scans
            st.mark_ready()
            _apply_scene(s)
            br.node.clear_costmaps()
    elif time.time() - st.started_at > 30 and not s.retried and s.launch:
        # a lifecycle transition reply lost under load leaves Nav2 half-active: start this slot once more
        s.retried = True
        s.bridge.node.reset_view_state()
        async with _launch_lock:
            await asyncio.get_running_loop().run_in_executor(None, st.start, *s.launch)
            st.message = 'Nav2 다시 시작 중 (첫 시도가 멈춤)'
            await asyncio.sleep(LAUNCH_SPACING)
    elif any('Failed to bring up all requested nodes' in l for l in list(st.log)[-200:]):
        cause = [l.split(']: ', 1)[-1] for l in st.log if 'Original error' in l or 'Failed to create' in l or 'Exception' in l]
        st.status = 'error'
        st.message = 'Nav2 노드를 띄우지 못했습니다' + (f': {cause[-1]}' if cause else ' (세션 로그 확인)')
    elif time.time() - st.started_at > 90:
        st.status, st.message = 'error', 'Nav2 가 90초 안에 준비되지 않았습니다 (세션 로그 확인)'


async def _watch():
    while True:
        for s in S['slots']:
            try:
                await _watch_slot(s)
            except Exception:
                pass
        await asyncio.sleep(0.3)


@app.get('/')
def index():
    return FileResponse(paths.web('index.html'))


app.mount('/static', StaticFiles(directory=paths.web()), name='static')


def create(env, domain):
    paths.ensure_user_dirs()
    from .stack import kill_stale
    if kill_stale():
        print('이전 실행에서 남은 시뮬레이션을 정리했습니다.', flush=True)
    S['env'], S['domain'] = env, domain
    S['slots'] = [Slot(i, env, domain + i) for i in range(MAX_SLOTS)]
    f = _scene_file()
    if os.path.exists(f):
        try:
            S['scene'] = json.load(open(f))
        except Exception:
            pass
    return app


def shutdown():
    for s in S['slots']:
        s.stack.stop()
    for s in S['slots']:
        if s.bridge is not None:
            s.bridge.shutdown()
