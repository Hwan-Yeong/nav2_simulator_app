"""2.5D ray casting for the simulated range sensors (ToF, ultrasonic, depth camera).

The world is the occupancy-grid map extruded to wall_height, the floor z = 0 with drops (axis-aligned rectangles
whose floor is `depth` lower), boxes (optionally rotated, from z0 to z1) and vertical cylinders (z0..z1; pedestrians
are cylinders too). Rays are intersected analytically with the floor, drops, boxes and cylinders; walls are found by
marching the ray over the grid. Everything is vectorised over rays, so a 64-zone ToF or a 64x48 depth image costs a
few milliseconds.
"""
import numpy as np

INF = np.inf


class Scene3D:
    def __init__(self, occ, res, origin, wall_height=2.0):
        self.occ = occ                      # bool grid, row 0 = min y (map_server image flipped)
        self.res = float(res)
        self.origin = (float(origin[0]), float(origin[1]))
        self.wall_h = float(wall_height)
        self.boxes = np.zeros((0, 7))       # cx, cy, half_w, half_h, yaw, z0, z1
        self.cyls = np.zeros((0, 5))        # cx, cy, r, z0, z1
        self.drops = np.zeros((0, 5))       # x0, y0, x1, y1, depth (> 0)

    # ------------------------------------------------------------ world
    def set_objects(self, boxes=(), cyls=(), drops=()):
        self.boxes = np.asarray(boxes, float).reshape(-1, 7)
        self.cyls = np.asarray(cyls, float).reshape(-1, 5)
        self.drops = np.asarray(drops, float).reshape(-1, 5)

    def floor_z(self, x, y):
        """Floor height at points (0 or -depth inside a drop)."""
        z = np.zeros(np.shape(x))
        for x0, y0, x1, y1, d in self.drops:
            inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
            z = np.where(inside, np.minimum(z, -d), z)
        return z

    # ------------------------------------------------------------ casting
    def cast(self, origin, dirs, rmax, extra_cyls=None):
        """Distance along each unit ray to the first surface (inf: nothing within rmax).

        origin (3,), dirs (n, 3) unit vectors in the map frame. extra_cyls: (m, 5) moving cylinders (pedestrians).
        """
        o = np.asarray(origin, float)
        d = np.asarray(dirs, float).reshape(-1, 3)
        t = np.full(len(d), INF)
        t = np.minimum(t, self._floor(o, d))
        cyl = self.cyls if extra_cyls is None or not len(extra_cyls) else np.vstack([self.cyls, np.asarray(extra_cyls, float).reshape(-1, 5)])
        if len(self.boxes):
            t = np.minimum(t, self._boxes(o, d, self.boxes))
        if len(cyl):
            t = np.minimum(t, self._cylinders(o, d, cyl))
        t = np.minimum(t, self._walls(o, d, np.minimum(t, rmax)))
        return np.where(t <= rmax, t, INF)

    def _floor(self, o, d):
        """Floor plane z = 0; a ray reaching it inside a drop goes on to the drop's floor or its side wall."""
        with np.errstate(divide='ignore', invalid='ignore'):
            t0 = np.where(d[:, 2] < -1e-9, -o[2] / d[:, 2], INF)
        t = t0.copy()
        if not len(self.drops):
            return t
        tf = np.where(np.isfinite(t0), t0, 0.0)
        x0, y0 = o[0] + d[:, 0] * tf, o[1] + d[:, 1] * tf
        for X0, Y0, X1, Y1, depth in self.drops:
            inside = np.isfinite(t0) & (x0 >= X0) & (x0 <= X1) & (y0 >= Y0) & (y0 <= Y1)
            if not inside.any():
                continue
            dd = d[inside]
            with np.errstate(divide='ignore', invalid='ignore'):
                t_low = (-depth - o[2]) / dd[:, 2]
                # where the ray leaves the rectangle in x-y (slab exit)
                tx = np.where(dd[:, 0] > 1e-12, (X1 - o[0]) / dd[:, 0], np.where(dd[:, 0] < -1e-12, (X0 - o[0]) / dd[:, 0], INF))
                ty = np.where(dd[:, 1] > 1e-12, (Y1 - o[1]) / dd[:, 1], np.where(dd[:, 1] < -1e-12, (Y0 - o[1]) / dd[:, 1], INF))
            t_exit = np.minimum(tx, ty)
            t[inside] = np.minimum(t_low, t_exit)       # lower floor, or the far side wall of the drop
        return t

    @staticmethod
    def _boxes(o, d, boxes):
        cx, cy, hw, hh, yaw, z0, z1 = (boxes[:, k][None, :] for k in range(7))
        c, s = np.cos(-yaw), np.sin(-yaw)
        ox, oy = o[0] - cx, o[1] - cy
        lox, loy = c * ox - s * oy, s * ox + c * oy                        # origin in box frame (1, nb)
        ldx = c * d[:, 0:1] - s * d[:, 1:2]                                 # (n, nb)
        ldy = s * d[:, 0:1] + c * d[:, 1:2]
        ldz = np.broadcast_to(d[:, 2:3], ldx.shape)
        tmin = np.full(ldx.shape, -INF)
        tmax = np.full(ldx.shape, INF)
        with np.errstate(divide='ignore', invalid='ignore'):
            for lo, ld, a, b in ((lox, ldx, -hw, hw), (loy, ldy, -hh, hh), (o[2], ldz, z0, z1)):
                par = np.abs(ld) < 1e-12
                t1, t2 = (a - lo) / ld, (b - lo) / ld
                near, far = np.minimum(t1, t2), np.maximum(t1, t2)
                outside = par & ((lo < a) | (lo > b))
                near = np.where(par, -INF, near)
                far = np.where(par, INF, far)
                tmin = np.maximum(tmin, near)
                tmax = np.minimum(tmax, far)
                tmax = np.where(outside, -INF, tmax)
        hit = (tmax >= np.maximum(tmin, 0)) & (tmax > 0)
        t = np.where(hit, np.where(tmin > 0, tmin, 0.0), INF)
        return t.min(axis=1)

    @staticmethod
    def _cylinders(o, d, cyls):
        cx, cy, r, z0, z1 = (cyls[:, k][None, :] for k in range(5))
        ox, oy = o[0] - cx, o[1] - cy
        dx, dy, dz = d[:, 0:1], d[:, 1:2], d[:, 2:3]
        a = dx * dx + dy * dy
        b = 2 * (ox * dx + oy * dy)
        cc = ox * ox + oy * oy - r * r
        disc = b * b - 4 * a * cc
        with np.errstate(divide='ignore', invalid='ignore'):
            sq = np.sqrt(np.where(disc >= 0, disc, 0))
            t_side = np.where((disc >= 0) & (a > 1e-12), (-b - sq) / (2 * a), INF)
            z_side = o[2] + dz * t_side
            side_ok = (t_side > 0) & (z_side >= z0) & (z_side <= z1)
            t = np.where(side_ok, t_side, INF)
            for zc in (z0, z1):                                             # caps (seen from above / below)
                tc = (zc - o[2]) / dz
                px, py = ox + dx * tc, oy + dy * tc
                cap_ok = (tc > 0) & (px * px + py * py <= r * r) & np.isfinite(tc)
                t = np.where(cap_ok & (tc < t), tc, t)
        return t.min(axis=1)

    def _walls(self, o, d, tmax):
        """March each ray over the grid up to tmax; walls stand from the floor to wall_height."""
        lim = float(np.max(np.where(np.isfinite(tmax), tmax, 0.0), initial=0.0))
        if lim <= 0:
            return np.full(len(d), INF)
        steps = np.arange(self.res * 0.5, lim + self.res, self.res * 0.5)
        px = o[0] + d[:, 0:1] * steps[None, :]
        py = o[1] + d[:, 1:2] * steps[None, :]
        pz = o[2] + d[:, 2:3] * steps[None, :]
        ix = ((px - self.origin[0]) / self.res).astype(np.int64)
        iy = ((py - self.origin[1]) / self.res).astype(np.int64)
        H, W = self.occ.shape
        inb = (ix >= 0) & (iy >= 0) & (ix < W) & (iy < H)
        np.clip(ix, 0, W - 1, out=ix)
        np.clip(iy, 0, H - 1, out=iy)
        hit = (self.occ[iy, ix] | ~inb) & (pz <= self.wall_h) & (steps[None, :] <= tmax[:, None])
        first = hit.argmax(axis=1)
        any_hit = hit[np.arange(len(d)), first]
        return np.where(any_hit, steps[first], INF)
