"""Benchmark and tuning runs: configuration -> parallel workers (own ROS domains) -> statistics.

Run directory (~/.navstudio/runs/<id>/):
  run.json           spec + status
  episodes.json      episodes used by every configuration
  feasibility.json   corridor width per episode
  cfg_<k>/           params.yaml robot.yaml sim.yaml, results *.jsonl.part<lane>, traj/
"""
import copy
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time

import yaml

from .. import paths, paramgen, robot as robotlib, schema
from . import scenarios as scenlib, stats

BENCH_DOMAIN, TUNE_DOMAIN = 150, 170
RUNS = {}


def _now_id(prefix):
    return prefix + time.strftime('%Y%m%d-%H%M%S')


def resolve_config(c):
    R = robotlib.normalize(c['robot']) if c.get('robot') else robotlib.load(c.get('robot_id') or 'everybot')
    ov = schema.to_overrides(R, c.get('values') or {})
    raw = (c.get('raw') or '').strip()
    if raw:
        ov = paramgen.merge_overrides(ov, yaml.safe_load(raw))
    return R, ov


def write_config(d, c):
    os.makedirs(d, exist_ok=True)
    R, ov = resolve_config(c)
    doc, warn = paramgen.generate(c.get('stack', 'prod'), R, ov)
    paramgen.write(doc, os.path.join(d, 'params.yaml'))
    with open(os.path.join(d, 'robot.yaml'), 'w') as f:
        yaml.safe_dump(R, f, sort_keys=False, allow_unicode=True)
    with open(os.path.join(d, 'sim.yaml'), 'w') as f:
        yaml.safe_dump({'sim2d': {'ros__parameters': {'use_sim_time': False, 'seed': 1}}}, f)
    json.dump(c, open(os.path.join(d, 'config.json'), 'w'), ensure_ascii=False, indent=1)
    return R, warn


def min_gap(R):
    ins, _ = robotlib.inscribed_circumscribed(R)
    return round(2 * (ins + R['footprint_padding']) + 0.12, 3)


def build_episodes(spec, robots):
    """spec: {source: bundled|generate, maps, categories, per_map, seed}"""
    cats = spec.get('categories') or ['nominal', 'unmapped', 'dynamic']
    per = int(spec.get('per_map', 6))
    eps = []
    if spec.get('source', 'bundled') == 'bundled':
        for mid in spec['maps']:
            f = paths.data('scenarios', mid + '.json')
            pool = json.load(open(f)) if os.path.exists(f) else []
            by = {c: [e for e in pool if e['category'] == c] for c in cats}
            picked, i = [], 0
            while len(picked) < per and any(by.values()):
                c = cats[i % len(cats)]
                if by[c]:
                    picked.append(by[c].pop(0))
                i += 1
            eps += picked
    else:
        circ = max(robotlib.inscribed_circumscribed(R)[1] + R['footprint_padding'] for R in robots)
        n = math.ceil(per / len(cats))
        for mid in spec['maps']:
            eps += scenlib.generate(mid, {c: n for c in cats}, seed=int(spec.get('seed', 1)), robot_radius=circ)
    return eps


class Lanes:
    """Runs worker jobs on N lanes, each with its own ROS_DOMAIN_ID."""

    def __init__(self, env, domain_base, n):
        self.env, self.base, self.n = env, domain_base, n
        self.procs = {}
        self.cancelled = False

    def run(self, jobs):
        q = queue.Queue()
        for j in jobs:
            q.put(j)

        def lane(i):
            env = dict(self.env, ROS_DOMAIN_ID=str(self.base + i))
            while not self.cancelled:
                try:
                    j = q.get_nowait()
                except queue.Empty:
                    return
                cmd = [sys.executable, '-m', 'navstudio.bench.worker', '--cfg-dir', j['cfg_dir'], '--map', j['map'],
                       '--episodes', j['episodes'], '--ids', ','.join(j['ids']), '--out', f"{j['out']}.part{self.base + i}"]
                with open(f"{j['out']}.part{self.base + i}.worker.log", 'a') as lf:
                    p = subprocess.Popen(cmd, env=env, stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
                    self.procs[i] = p
                    p.wait()
                    self.procs.pop(i, None)
        ths = [threading.Thread(target=lane, args=(i,), daemon=True) for i in range(self.n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()

    def cancel(self):
        self.cancelled = True
        for p in list(self.procs.values()):
            try:
                os.killpg(p.pid, signal.SIGINT)
            except ProcessLookupError:
                pass


def read_results(cfg_dir):
    recs = {}
    if not os.path.isdir(cfg_dir):
        return []
    for fn in sorted(os.listdir(cfg_dir)):
        if '.jsonl.part' in fn and not fn.endswith('.log'):
            for line in open(os.path.join(cfg_dir, fn)):
                try:
                    r = json.loads(line)
                    recs[r['id']] = r
                except Exception:
                    pass
    return sorted(recs.values(), key=lambda r: r['id'])


class BenchRun:
    kind = 'bench'

    def __init__(self, spec, env, rid=None):
        self.id = rid or _now_id('b')
        self.dir = paths.user('runs', self.id)
        self.spec, self.env = spec, env
        self.status, self.message = 'preparing', '에피소드 준비 중'
        self.lanes = None
        self.started = time.time()
        self.finished = None
        self.total = 0
        self.warnings = []

    def save(self):
        os.makedirs(self.dir, exist_ok=True)
        json.dump(dict(id=self.id, kind=self.kind, spec=self.spec, status=self.status, message=self.message,
                       started=self.started, finished=self.finished, total=self.total, warnings=self.warnings),
                  open(os.path.join(self.dir, 'run.json'), 'w'), ensure_ascii=False, indent=1)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            cfgs = self.spec['configs']
            robots = []
            for k, c in enumerate(cfgs):
                R, warn = write_config(os.path.join(self.dir, f'cfg_{k}'), c)
                robots.append(R)
                self.warnings += [f"[{c.get('name', k)}] {w}" for w in warn]
            eps = build_episodes(self.spec['episodes'], robots)
            if not eps:
                raise RuntimeError('조건에 맞는 에피소드가 없습니다')
            json.dump(eps, open(os.path.join(self.dir, 'episodes.json'), 'w'))
            self.message = '통과 가능 여부 계산 중'
            json.dump(scenlib.feasibility(eps, 0.0), open(os.path.join(self.dir, 'feasibility.json'), 'w'))
            self.total = len(eps) * len(cfgs)
            chunk = int(self.spec.get('chunk', 5))
            jobs = []
            by_map = {}
            for e in eps:
                by_map.setdefault(e['map'], []).append(e['id'])
            for mid, ids in by_map.items():
                for s in range(0, len(ids), chunk):
                    for k in range(len(cfgs)):   # interleave configurations
                        jobs.append(dict(cfg_dir=os.path.join(self.dir, f'cfg_{k}'), map=mid, ids=ids[s:s + chunk],
                                         episodes=os.path.join(self.dir, 'episodes.json'),
                                         out=os.path.join(self.dir, f'cfg_{k}', f'{mid}.jsonl')))
            self.status, self.message = 'running', '실행 중'
            self.save()
            self.lanes = Lanes(self.env, BENCH_DOMAIN, int(self.spec.get('workers', 4)))
            self.lanes.run(jobs)
            self.status = 'canceled' if self.lanes.cancelled else 'done'
            self.message = '취소됨' if self.lanes.cancelled else '완료'
        except Exception as e:
            self.status, self.message = 'error', str(e)
        self.finished = time.time()
        self.save()

    def cancel(self):
        if self.lanes:
            self.lanes.cancel()
        self.status, self.message = 'canceled', '취소 중'

    def progress(self):
        done = sum(len(read_results(os.path.join(self.dir, f'cfg_{k}'))) for k in range(len(self.spec['configs'])))
        return dict(done=done, total=self.total)

    def report(self, weights=None):
        feas = _load(os.path.join(self.dir, 'feasibility.json'), {})
        cfgs = self.spec['configs']
        out, recs_all = [], []
        for k, c in enumerate(cfgs):
            d = os.path.join(self.dir, f'cfg_{k}')
            recs = read_results(d)
            R = _load_yaml(os.path.join(d, 'robot.yaml'))
            gap = min_gap(R) if R else 0.5
            for r in recs:
                g = feas.get(r['id'], {}).get('gap')
                r['gap'] = g
                r['blocked'] = g is not None and g < gap
            usable = [r for r in recs if not r['blocked']]
            out.append(dict(index=k, name=c.get('name', f'설정 {k + 1}'), summary=stats.summarize(usable, weights),
                            blocked=sum(1 for r in recs if r['blocked']), min_gap=gap))
            recs_all.append(usable)
        if len(recs_all) > 1:
            for k in range(1, len(recs_all)):
                out[k]['paired'] = stats.paired(recs_all[0], recs_all[k])
        return out


def _load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def _load_yaml(p):
    try:
        return yaml.safe_load(open(p))
    except Exception:
        return None


class TuneRun(BenchRun):
    kind = 'tune'

    def __init__(self, spec, env, rid=None):
        super().__init__(spec, env, rid or _now_id('t'))
        self.trials = []
        self.study = None

    def _run(self):
        try:
            import optuna
        except ImportError:
            self.status, self.message = 'error', 'optuna 가 설치되어 있지 않습니다 (pip install optuna)'
            self.save()
            return
        try:
            os.makedirs(self.dir, exist_ok=True)
            base = self.spec['base']
            R, warn = write_config(os.path.join(self.dir, 'base'), base)
            self.warnings += warn
            eps = build_episodes(self.spec['episodes'], [R])
            if not eps:
                raise RuntimeError('조건에 맞는 에피소드가 없습니다')
            json.dump(eps, open(os.path.join(self.dir, 'episodes.json'), 'w'))
            self.message = '통과 가능 여부 계산 중'
            feas = scenlib.feasibility(eps, min_gap(R))
            json.dump(feas, open(os.path.join(self.dir, 'feasibility.json'), 'w'))
            usable = [e for e in eps if not feas[e['id']]['blocked']]
            json.dump(usable, open(os.path.join(self.dir, 'episodes_usable.json'), 'w'))
            n_trials, parallel = int(self.spec.get('trials', 20)), int(self.spec.get('parallel', 1))
            workers = int(self.spec.get('workers', 3))
            self.total = n_trials
            by_map = {}
            for e in usable:
                by_map.setdefault(e['map'], []).append(e['id'])
            space = self.spec['params']
            by_id = {p['id']: p for p in schema.load()['params']}
            free_slots = list(range(parallel))
            lock = threading.Lock()
            self.active = {}

            def objective(trial):
                vals = dict(base.get('values') or {})
                for p in space:
                    meta = by_id.get(p['id'], {})
                    if meta.get('type') == 'int':
                        v = trial.suggest_int(p['id'], int(p['low']), int(p['high']))
                    else:
                        v = trial.suggest_float(p['id'], float(p['low']), float(p['high']), log=bool(p.get('log')))
                        step = meta.get('step')
                        if step:
                            v = round(round(v / step) * step, 6)
                    vals[p['id']] = v
                with lock:
                    slot = free_slots.pop()
                d = os.path.join(self.dir, f'trial_{trial.number:03d}')
                try:
                    write_config(d, dict(base, values=vals, name=f'trial {trial.number}'))
                    jobs = [dict(cfg_dir=d, map=mid, ids=ids[s:s + 4], episodes=os.path.join(self.dir, 'episodes_usable.json'),
                                 out=os.path.join(d, f'{mid}.jsonl')) for mid, ids in by_map.items() for s in range(0, len(ids), 4)]
                    lanes = Lanes(self.env, TUNE_DOMAIN + slot * workers, workers)
                    self.active[slot] = lanes
                    lanes.run(jobs)
                    self.active.pop(slot, None)
                    if lanes.cancelled:
                        raise optuna.TrialPruned()
                    s = stats.summarize(read_results(d), self.spec.get('weights'))
                    for k in ('n', 'success', 'collision_rate', 'avg_speed', 'min_clear_p10', 'recoveries', 'ang_jerk_rms', 'time_mean'):
                        trial.set_user_attr(k, s.get(k))
                    trial.set_user_attr('values', vals)
                    return s['score'] if s.get('score') is not None else -1e9
                finally:
                    with lock:
                        free_slots.append(slot)

            storage = f"sqlite:///{os.path.join(self.dir, 'optuna.db')}"
            self.study = optuna.create_study(study_name=self.id, storage=storage, direction='maximize', load_if_exists=True,
                                             sampler=optuna.samplers.TPESampler(seed=int(self.spec.get('seed', 42)),
                                                                                n_startup_trials=min(8, max(3, n_trials // 3)), multivariate=True))
            if self.spec.get('enqueue_base', True):
                init = {}
                for p in space:
                    v = (base.get('values') or {}).get(p['id'], p.get('default'))
                    if v is not None and float(p['low']) <= float(v) <= float(p['high']):
                        init[p['id']] = v
                if len(init) == len(space):
                    self.study.enqueue_trial(init)
            self.status, self.message = 'running', '실행 중'
            self.save()
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            self.study.optimize(objective, n_trials=n_trials, n_jobs=parallel, catch=(Exception,))
            self.status = 'canceled' if self.status == 'canceled' else 'done'
            self.message = '취소됨' if self.status == 'canceled' else '완료'
        except Exception as e:
            self.status, self.message = 'error', str(e)
        self.finished = time.time()
        self.save()

    def cancel(self):
        self.status, self.message = 'canceled', '취소 중'
        if self.study is not None:
            self.study.stop()
        for lanes in list(getattr(self, 'active', {}).values()):
            lanes.cancel()

    def progress(self):
        t = self.trial_list()
        return dict(done=sum(1 for x in t if x['state'] in ('COMPLETE', 'PRUNED', 'FAIL')), total=self.total)

    def trial_list(self):
        try:
            import optuna
            st = self.study or optuna.load_study(study_name=self.id, storage=f"sqlite:///{os.path.join(self.dir, 'optuna.db')}")
        except Exception:
            return []
        out = []
        for t in st.get_trials(deepcopy=False):
            out.append(dict(number=t.number, state=t.state.name, value=t.value, params=t.params,
                            attrs={k: v for k, v in t.user_attrs.items() if k != 'values'}, values=t.user_attrs.get('values'),
                            duration=(t.datetime_complete - t.datetime_start).total_seconds() if t.datetime_complete and t.datetime_start else None))
        return out

    def report(self, weights=None):
        return dict(trials=self.trial_list())


def list_runs(kind=None):
    d = paths.user('runs')
    out = []
    if os.path.isdir(d):
        for rid in sorted(os.listdir(d), reverse=True):
            meta = _load(os.path.join(d, rid, 'run.json'), None)
            if meta and (kind is None or meta.get('kind') == kind):
                live = RUNS.get(rid)
                if live:
                    meta.update(status=live.status, message=live.message)
                out.append({k: meta.get(k) for k in ('id', 'kind', 'status', 'message', 'started', 'finished', 'total')} |
                           dict(name=meta['spec'].get('name', rid)))
    return out


def get(rid, env):
    if rid in RUNS:
        return RUNS[rid]
    meta = _load(paths.user('runs', rid, 'run.json'), None)
    if not meta:
        raise KeyError(rid)
    r = (TuneRun if meta['kind'] == 'tune' else BenchRun)(meta['spec'], env, rid)
    r.status, r.message, r.started, r.finished, r.total = meta['status'], meta['message'], meta['started'], meta['finished'], meta['total']
    if r.status in ('running', 'preparing'):
        r.status, r.message = 'canceled', '서버 재시작으로 중단됨'
    return r


def delete(rid):
    if rid in RUNS and RUNS[rid].status in ('running', 'preparing'):
        raise RuntimeError('실행 중인 작업은 먼저 취소하세요')
    RUNS.pop(rid, None)
    shutil.rmtree(paths.user('runs', rid), ignore_errors=True)
