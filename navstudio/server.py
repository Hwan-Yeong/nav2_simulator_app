"""Nav Studio web server: REST API + WebSocket stream + static UI."""
import asyncio
import base64
import copy
import difflib
import json
import os
import time
import zlib

import yaml
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, maps, paramgen, paths, robot as robotlib, schema
from .stack import Stack

app = FastAPI(title='Nav Studio', version=__version__)
S = dict(stack=None, bridge=None, env=None, domain=None, scene=None, config=None, bench=None)


# ------------------------------------------------------------------ models
class Pose(BaseModel):
    pose: list


class SessionReq(BaseModel):
    map: str
    robot_id: str | None = None
    robot: dict | None = None
    stack: str = 'prod'
    values: dict = {}
    raw_overrides: str = ''
    start: list | None = None


class WorldReq(BaseModel):
    static_obs: list = []
    dyn_obs: list = []


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


def _overrides(R, values, raw):
    ov = schema.to_overrides(R, values)
    if raw and raw.strip():
        extra = yaml.safe_load(raw)
        if not isinstance(extra, dict):
            raise ValueError('고급 오버라이드는 {노드: {경로: 값}} 형태의 YAML 이어야 합니다')
        ov = paramgen.merge_overrides(ov, extra)
    return ov


def _bad(e, code=400):
    raise HTTPException(code, str(e))


def _scene_file():
    return paths.user('sessions', 'current', 'scene.json')


def _apply_scene_to_sim():
    sc, br = S['scene'], S['bridge']
    if sc is None or br is None:
        return
    br.node.sim(op='world', static_obs=sc.get('static_obs', []), dyn_obs=sc.get('dyn_obs', []), episode='scene')


# ------------------------------------------------------------------ info / catalog
@app.get('/api/info')
def info():
    have = paramgen.available_packages()
    st = S['stack']
    return dict(version=__version__, domain=S['domain'], plugins={p: p in have for p in paramgen.CUSTOM_PLUGINS},
                nav2=('nav2_bringup' in have or 'nav2_controller' in have),
                stack=dict(status=st.status, message=st.message) if st else None, config=S['config'])


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
    return Response(maps.grid_png(mid), media_type='image/png', headers={'Cache-Control': 'max-age=3600'})


@app.get('/api/maps/{mid}/thumb.png')
def map_thumb(mid: str):
    return Response(maps.thumb_png(mid), media_type='image/png', headers={'Cache-Control': 'max-age=3600'})


@app.post('/api/maps/{mid}/check_pose')
def map_check_pose(mid: str, body: dict):
    try:
        R = _robot(body.get('robot_id'), body.get('robot'))
        c = maps.footprint_clearance(mid, body['pose'], robotlib.polygon(R, 32))
    except Exception as e:
        _bad(e)
    return dict(clearance=c, ok=c > 0.02)


@app.post('/api/maps')
async def upload_map(name: str = Form(...), yaml_file: UploadFile = File(...), image: UploadFile = File(...)):
    try:
        mid = maps.save_upload(name, await yaml_file.read(), await image.read(), image.filename)
    except Exception as e:
        _bad(f'맵을 읽지 못했습니다: {e}')
    return dict(id=mid)


@app.delete('/api/maps/{mid}')
def delete_map(mid: str):
    try:
        maps.delete(mid)
    except KeyError:
        _bad('사용자 맵만 지울 수 있습니다', 404)
    return dict(ok=True)


@app.get('/api/scenarios/{mid}')
def scenarios(mid: str):
    f = paths.data('scenarios', mid + '.json')
    if not os.path.exists(f):
        return []
    return json.load(open(f))


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


@app.get('/api/presets')
def presets():
    out = []
    for d in (paths.data('presets'), paths.user('presets')):
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.yaml'):
                    p = yaml.safe_load(open(os.path.join(d, fn)))
                    p['id'] = fn[:-5]
                    out.append(p)
    return out


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
        ov = _overrides(R, req.values, req.raw_overrides)
        doc, warn = paramgen.generate(req.stack, R, ov)
        base, _ = paramgen.generate('prod', robotlib.load('everybot'))
    except Exception as e:
        _bad(e)
    txt = yaml.safe_dump(doc, sort_keys=False, default_flow_style=None, allow_unicode=True)
    btxt = yaml.safe_dump(base, sort_keys=False, default_flow_style=None, allow_unicode=True)
    diff = ''.join(difflib.unified_diff(btxt.splitlines(True), txt.splitlines(True), '운영 기본값', '현재 설정', n=2))
    return dict(yaml=txt, diff=diff, overrides=ov, warnings=warn)


# ------------------------------------------------------------------ session
@app.post('/api/session/start')
async def session_start(req: SessionReq):
    try:
        R = _robot(req.robot_id, req.robot)
        ov = _overrides(R, req.values, req.raw_overrides)
        start = req.start or maps.meta(req.map)['start']
    except Exception as e:
        _bad(e)
    S['bridge'].node.cancel()
    S['bridge'].node.reset_view_state()
    loop = asyncio.get_running_loop()
    try:
        warn = await loop.run_in_executor(None, S['stack'].start, req.map, R, req.stack, ov, start)
    except Exception as e:
        _bad(f'시작하지 못했습니다: {e}')
    S['config'] = dict(map=req.map, robot_id=req.robot_id, robot=R, stack=req.stack, values=req.values,
                       raw_overrides=req.raw_overrides, start=list(start))
    if S['scene'] is None or S['scene'].get('map') != req.map:
        S['scene'] = dict(map=req.map, static_obs=[], dyn_obs=[], start=list(start), goal=None)
    else:
        S['scene']['start'] = list(start)
    return dict(ok=True, warnings=warn)


@app.post('/api/session/stop')
async def session_stop():
    S['bridge'].node.cancel()
    await asyncio.get_running_loop().run_in_executor(None, S['stack'].stop)
    return dict(ok=True)


@app.get('/api/session/log')
def session_log():
    return PlainTextResponse('\n'.join(S['stack'].log))


@app.get('/api/session/params.yaml')
def session_params():
    st = S['stack']
    if not st.session:
        _bad('실행 중인 세션이 없습니다', 404)
    return FileResponse(st.session['params_file'], media_type='text/yaml', filename='nav2_params.yaml')


@app.get('/api/scene')
def scene_get():
    return S['scene'] or {}


@app.post('/api/scene')
def scene_set(body: dict):
    S['scene'] = dict(S['scene'] or {}, **body)
    _apply_scene_to_sim()
    os.makedirs(os.path.dirname(_scene_file()), exist_ok=True)
    json.dump(S['scene'], open(_scene_file(), 'w'))
    return S['scene']


def _require_ready():
    if S['stack'].status != 'ready':
        _bad('시뮬레이션이 실행 중이 아닙니다. 먼저 시뮬레이션을 시작하세요.', 409)


@app.post('/api/nav/goal')
def nav_goal(p: Pose):
    _require_ready()
    try:
        S['bridge'].node.send_goal(p.pose)
    except Exception as e:
        _bad(e, 409)
    if S['scene'] is not None:
        S['scene']['goal'] = list(p.pose)
    return dict(ok=True)


@app.post('/api/nav/cancel')
def nav_cancel():
    S['bridge'].node.cancel()
    return dict(ok=True)


@app.post('/api/sim/teleport')
def sim_teleport(p: Pose):
    _require_ready()
    S['bridge'].node.cancel()
    S['bridge'].node.sim(op='teleport', pose=p.pose, episode='teleport')
    S['bridge'].node.clear_costmaps()
    if S['scene'] is not None:
        S['scene']['start'] = list(p.pose)
    return dict(ok=True)


@app.post('/api/sim/clear_costmaps')
def sim_clear():
    S['bridge'].node.clear_costmaps()
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
                                ref_len=rec.get('ref_len'), min_clear=rec.get('min_clear'), recoveries=rec.get('recoveries'),
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
    sent = dict(seq={}, log=0, cm_t={'global': 0.0, 'local': 0.0}, reset=None)
    try:
        await sock.send_json(dict(type='hello', version=__version__, config=S['config'], scene=S['scene']))
        while True:
            snap = S['bridge'].node.snapshot()
            st = S['stack']
            seq = snap['seq']
            if seq.get('reset') != sent['reset']:
                sent['reset'] = seq.get('reset')
                sent['seq'] = {}
                await sock.send_json(dict(type='reset'))
            await sock.send_json(dict(type='tick', stack=dict(status=st.status, message=st.message),
                                      sim=snap['sim'], nav=snap['nav'], config_map=(S['config'] or {}).get('map')))
            for which in ('global', 'local'):
                k = 'plan_' + which
                if seq.get(k) and seq.get(k) != sent['seq'].get(k) and snap['plans'][which] is not None:
                    sent['seq'][k] = seq[k]
                    await sock.send_json(dict(type='plan', which=which, pts=snap['plans'][which]))
                k = 'costmap_' + which
                now = time.monotonic()
                period = 2.0 if which == 'global' else 0.3
                if seq.get(k) and seq.get(k) != sent['seq'].get(k) and now - sent['cm_t'][which] >= period \
                        and snap['costmaps'][which] is not None:
                    sent['seq'][k] = seq[k]
                    sent['cm_t'][which] = now
                    cm = dict(snap['costmaps'][which])
                    cm['z'] = _z(cm.pop('data'))
                    await sock.send_json(dict(type='costmap', **cm))
            new = [l for l in snap['logs'] if l['seq'] > sent['log']]
            if new:
                sent['log'] = new[-1]['seq']
                await sock.send_json(dict(type='log', items=new[-50:]))
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


async def _watch():
    """Promote the stack to 'ready' when Nav2's action server is up and the simulator is publishing."""
    while True:
        st, br = S['stack'], S['bridge']
        try:
            if st.status == 'starting' and br.node.nav_ready():
                snap = br.node.snapshot()
                if snap['sim'] is not None and time.time() - st.started_at > 2.0:
                    await asyncio.sleep(1.5)  # let bt_navigator / costmaps finish activating
                    st.mark_ready()
                    _apply_scene_to_sim()
                    br.node.clear_costmaps()
            elif st.status == 'starting' and any('Failed to bring up all requested nodes' in l for l in list(st.log)[-200:]):
                cause = [l.split(']: ', 1)[-1] for l in st.log if 'Original error' in l or 'Failed to create' in l or 'Exception' in l]
                st.status = 'error'
                st.message = 'Nav2 노드를 띄우지 못했습니다' + (f': {cause[-1]}' if cause else ' (세션 로그 확인)')
            elif st.status == 'starting' and time.time() - st.started_at > 90:
                st.status, st.message = 'error', 'Nav2 가 90초 안에 준비되지 않았습니다 (세션 로그 확인)'
        except Exception:
            pass
        await asyncio.sleep(0.3)


@app.on_event('startup')
async def _startup():
    asyncio.create_task(_watch())


@app.get('/')
def index():
    return FileResponse(paths.web('index.html'))


app.mount('/static', StaticFiles(directory=paths.web()), name='static')


def create(env, domain):
    from .bridge import BridgeThread
    paths.ensure_user_dirs()
    from .stack import kill_stale
    if kill_stale():
        print('이전 실행에서 남은 시뮬레이션을 정리했습니다.', flush=True)
    S['env'], S['domain'] = env, domain
    S['stack'] = Stack(env)
    S['bridge'] = BridgeThread()
    f = _scene_file()
    if os.path.exists(f):
        try:
            S['scene'] = json.load(open(f))
        except Exception:
            pass
    return app


def shutdown():
    if S['stack']:
        S['stack'].stop()
    if S['bridge']:
        S['bridge'].shutdown()
