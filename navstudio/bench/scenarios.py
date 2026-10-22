"""Episode generation for any map and robot size: start/goal pairs, unmapped obstacles, pedestrians.

Feasibility: an episode is 'blocked' when the widest free corridor between start and goal (with the unmapped
obstacles in place) is narrower than the robot can pass. Blocked episodes are reported separately and excluded
from success rates.
"""
import heapq
import math

import numpy as np
from scipy import ndimage

from .. import maps


class World:
    def __init__(self, mid, rr):
        m = maps.load(mid)
        self.mid, self.res, self.origin, self.H, self.W = mid, m['res'], m['origin'], m['H'], m['W']
        self.solid = m['occ'] | m['unk']
        yy, xx = np.mgrid[0:self.H, 0:self.W]
        self.cx = self.origin[0] + (xx + 0.5) * self.res
        self.cy = self.origin[1] + (yy + 0.5) * self.res
        self.rr = rr
        self.update([])

    def raster(self, o):
        if o['type'] == 'circle':
            return (self.cx - o['x']) ** 2 + (self.cy - o['y']) ** 2 <= o['r'] ** 2
        return (self.cx >= o['x0']) & (self.cx <= o['x1']) & (self.cy >= o['y0']) & (self.cy <= o['y1'])

    def update(self, obs):
        s = self.solid.copy()
        for o in obs:
            s |= self.raster(o)
        self.dist = ndimage.distance_transform_edt(~s) * self.res
        trav = self.dist > self.rr + 0.02
        self.lab, n = ndimage.label(trav, structure=np.ones((3, 3)))
        if n:
            sizes = ndimage.sum(trav, self.lab, range(1, n + 1))
            self.main = int(np.argmax(sizes)) + 1
        else:
            self.main = 0
        return self

    def idx(self, x, y):
        return int((y - self.origin[1]) / self.res), int((x - self.origin[0]) / self.res)

    def xy(self, iy, ix):
        return self.origin[0] + (ix + 0.5) * self.res, self.origin[1] + (iy + 0.5) * self.res

    def inside(self, x, y):
        iy, ix = self.idx(x, y)
        return 0 <= iy < self.H and 0 <= ix < self.W

    def connected(self, a, b):
        ia, ib = self.idx(*a), self.idx(*b)
        return self.lab[ia] != 0 and self.lab[ia] == self.lab[ib]

    def astar(self, a, b):
        trav = self.dist > self.rr + 0.02
        extra = np.clip(0.5 - self.dist, 0, None) * 4.0
        s, g = self.idx(*a), self.idx(*b)
        if not (trav[s] and trav[g]):
            return None
        moves = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
        hfun = lambda c: math.hypot(c[0] - g[0], c[1] - g[1])
        best, parent, pq = {s: 0.0}, {s: None}, [(hfun(s), 0.0, s)]
        while pq:
            _, d, c = heapq.heappop(pq)
            if c == g:
                break
            if d > best.get(c, 1e18):
                continue
            for dy, dx, w in moves:
                n = (c[0] + dy, c[1] + dx)
                if not (0 <= n[0] < self.H and 0 <= n[1] < self.W) or not trav[n]:
                    continue
                nd = d + w * (1.0 + extra[n])
                if nd < best.get(n, 1e18):
                    best[n], parent[n] = nd, c
                    heapq.heappush(pq, (nd + hfun(n), nd, n))
        if g not in parent:
            return None
        out, c = [], g
        while c is not None:
            out.append(self.xy(*c))
            c = parent[c]
        return out[::-1]

    def bottleneck(self, a, b):
        """Width (m) of the widest corridor connecting a and b (2 x max-min clearance)."""
        lo, hi = 0.0, 1.5
        ia, ib = self.idx(*a), self.idx(*b)
        for _ in range(12):
            mid = (lo + hi) / 2
            lab, _ = ndimage.label(self.dist > mid, structure=np.ones((3, 3)))
            if lab[ia] and lab[ia] == lab[ib]:
                lo = mid
            else:
                hi = mid
        return round(2 * lo, 3)


def path_len(p):
    return float(sum(math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]) for i in range(len(p) - 1)))


def point_at(p, frac):
    L = path_len(p) * frac
    for i in range(len(p) - 1):
        seg = math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
        if L <= seg:
            a = L / seg if seg else 0
            return (p[i][0] + a * (p[i + 1][0] - p[i][0]), p[i][1] + a * (p[i + 1][1] - p[i][1]),
                    math.atan2(p[i + 1][1] - p[i][1], p[i + 1][0] - p[i][0]))
        L -= seg
    return p[-1][0], p[-1][1], 0.0


def _obstacle(rng, x, y, th):
    kind = rng.choice(['box', 'chair', 'pole'], p=[0.45, 0.4, 0.15])
    nx, ny = -math.sin(th), math.cos(th)
    off = rng.uniform(-0.35, 0.35)
    cx, cy = x + nx * off, y + ny * off
    if kind == 'box':
        hw, hh = rng.uniform(0.15, 0.35), rng.uniform(0.15, 0.35)
        return [dict(type='rect', x0=cx - hw, y0=cy - hh, x1=cx + hw, y1=cy + hh)], 'box'
    if kind == 'pole':
        return [dict(type='circle', x=cx, y=cy, r=float(rng.uniform(0.05, 0.12)))], 'pole'
    s, a = rng.uniform(0.2, 0.25), rng.uniform(0, math.pi / 2)
    return [dict(type='circle', x=cx + s * math.sqrt(2) * math.cos(a + k * math.pi / 2 + math.pi / 4),
                 y=cy + s * math.sqrt(2) * math.sin(a + k * math.pi / 2 + math.pi / 4), r=0.025) for k in range(4)], 'chair'


def generate(mid, counts, seed=1, robot_radius=0.175, dmin=3.0, dmax=22.0, start_clear=None):
    """counts: {'nominal': n, 'unmapped': n, 'dynamic': n}. robot_radius: circumscribed radius (+padding)."""
    rng = np.random.default_rng(seed)
    rr = robot_radius
    sc = start_clear or rr + 0.15
    w = World(mid, rr)
    eps, tries = [], 0
    for cat in ('nominal', 'unmapped', 'dynamic'):
        k = 0
        while k < counts.get(cat, 0) and tries < 6000:
            tries += 1
            w.update([])
            cand = np.argwhere((w.dist > sc) & (w.lab == w.main))
            if not len(cand):
                break
            s = (*w.xy(*cand[rng.integers(len(cand))]), float(rng.uniform(-math.pi, math.pi)))
            g = (*w.xy(*cand[rng.integers(len(cand))]), float(rng.uniform(-math.pi, math.pi)))
            if not dmin <= math.hypot(g[0] - s[0], g[1] - s[1]) <= dmax:
                continue
            p = w.astar(s[:2], g[:2])
            if p is None:
                continue
            ep = dict(id=f'{mid}/{cat}/{k:03d}', map=mid, category=cat, start=list(s), goal=list(g), ref_len=path_len(p),
                      static_obs=[], dyn_obs=[], tags=[])
            if cat == 'unmapped':
                obs, tags = [], []
                for frac in sorted(rng.uniform(0.25, 0.8, size=int(rng.integers(1, 4)))):
                    x, y, th = point_at(p, frac)
                    if any(math.hypot(x - q[0], y - q[1]) < 0.7 + rr for q in (s, g)):
                        continue
                    o, t = _obstacle(rng, x, y, th)
                    obs += o
                    tags.append(t)
                if not obs:
                    continue
                w.update(obs)
                if not w.connected(s[:2], g[:2]):
                    continue
                p2 = w.astar(s[:2], g[:2])
                if p2 is None:
                    continue
                ep['ref_len'], ep['static_obs'], ep['tags'] = path_len(p2), obs, tags
            if cat == 'dynamic':
                for j in range(int(rng.integers(1, 3))):
                    x, y, th = point_at(p, rng.uniform(0.3, 0.7))
                    mode = rng.choice(['cross', 'headon'], p=[0.7, 0.3])
                    if mode == 'cross':
                        nx, ny = -math.sin(th), math.cos(th)
                        wps = [[x - nx * 1.5, y - ny * 1.5], [x + nx * 1.5, y + ny * 1.5]]
                    else:
                        x0, y0, _ = point_at(p, max(0.15, (j + 1) * 0.25))
                        wps = [[x, y], [x0, y0]]
                    ep['dyn_obs'].append(dict(wps=[[round(a, 3), round(b, 3)] for a, b in wps],
                                              speed=float(rng.uniform(0.3, 0.9)), r=0.22, phase=float(rng.uniform(0, 1))))
                    ep['tags'].append(str(mode))
            eps.append(ep)
            k += 1
    return eps


def feasibility(eps, min_gap):
    """Mark episodes whose start-goal corridor is narrower than min_gap (m)."""
    worlds = {}
    out = {}
    for e in eps:
        w = worlds.get(e['map'])
        if w is None:
            w = worlds[e['map']] = World(e['map'], 0.0)
        w.update(e['static_obs'])
        if not (w.inside(*e['start'][:2]) and w.inside(*e['goal'][:2])):
            out[e['id']] = dict(gap=0.0, blocked=True)
            continue
        gap = w.bottleneck(e['start'][:2], e['goal'][:2])
        out[e['id']] = dict(gap=gap, blocked=gap < min_gap)
    return out
