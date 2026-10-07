"""Vectorized mesh builders and the QQuick3DGeometry bridge.

The builders read a skeleton (any object exposing the Skeleton/Segment fields of
``fernal.tree``) and return ``Arrays``:

    (positions (N,3) f32, normals (N,3) f32, uv0 (N,2) f32, uv1 (N,2) f32, indices (M,) u32)

``uv1 = (sway_phase, sway_weight)`` is baked for the wind shader. Units are
centimeters, Y is up, triangles are counter-clockwise when seen from outside.
"""

import functools

import numpy as np
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry

STRIDE = 40  # position(3) normal(3) uv0(2) uv1(2) as float32
SIDES = 6  # vertices per tube ring
TIP_RADIUS = 0.7  # tube radius at the tip, relative to the base
V_TILE_CM = 20.0  # bark texture repeats every 20 cm along a branch
LEAF_SIZE_CM = 8.0  # edge length of a fully grown leaf with size 1 and leaf_scale 1
LEAF_GROW_HOURS = 2.0  # plant hours a leaf needs to unfurl after its birth
FRUIT_GROW_HOURS = 2.0  # plant hours a fruit needs to swell after its birth
_LEAF_SEED = 7001
_FRUIT_SEED = 7002
_UP = np.array([0.0, 1.0, 0.0])
_RIGHT = np.array([1.0, 0.0, 0.0])

# Index pattern of one tube: ring 0 = vertices 0..5, ring 1 = vertices 6..11.
_k = np.arange(SIDES)
_k1 = (_k + 1) % SIDES
_TUBE_INDICES = np.stack([_k, _k1, SIDES + _k1, _k, SIDES + _k1, SIDES + _k], axis=1).ravel()
_QUAD_INDICES = np.array([0, 1, 2, 0, 2, 3])
_QUAD_CORNERS = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
_QUAD_UV = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])


def growth(age, birth, hours):
    """smoothstep(clamp((age - birth) / hours, 0, 1)); scalars give a float, arrays an array."""
    t = np.clip((np.asarray(age, dtype=np.float64) - birth) / hours, 0.0, 1.0)
    g = t * t * (3.0 - 2.0 * t)
    return float(g) if g.ndim == 0 else g


def _empty():
    return (
        np.zeros((0, 3), np.float32),
        np.zeros((0, 3), np.float32),
        np.zeros((0, 2), np.float32),
        np.zeros((0, 2), np.float32),
        np.zeros(0, np.uint32),
    )


def _pack(pos, nrm, uv0, uv1, idx):
    return (
        np.ascontiguousarray(pos.reshape(-1, 3), np.float32),
        np.ascontiguousarray(nrm.reshape(-1, 3), np.float32),
        np.ascontiguousarray(uv0.reshape(-1, 2), np.float32),
        np.ascontiguousarray(uv1.reshape(-1, 2), np.float32),
        np.ascontiguousarray(idx.reshape(-1), np.uint32),
    )


def _unit(v):
    """Normalize rows; zero-length rows become +Y."""
    n = np.linalg.norm(v, axis=1)
    ok = n > 1e-9
    return np.where(ok[:, None], v / np.where(ok, n, 1.0)[:, None], _UP)


def _frame(n):
    """Two unit vectors (t, b) with t x b == n for each unit row of n."""
    ref = np.where((np.abs(n[:, 1]) < 0.99)[:, None], _UP, _RIGHT)
    t = _unit(np.cross(ref, n))
    return t, np.cross(n, t)


def _tip_radius(parent, radius, g):
    """Tip radius per segment: TIP_RADIUS * base, blending toward the thickest child's base radius
    as that child grows, so chained segments join without a step."""
    tip = radius * TIP_RADIUS
    kids = np.flatnonzero(parent >= 0)
    if len(kids) == 0:
        return tip
    order = kids[np.argsort(radius[kids], kind="stable")]  # thickest child is assigned last and wins
    kid_r = np.zeros(len(radius))
    kid_g = np.zeros(len(radius))
    has = np.zeros(len(radius), bool)
    kid_r[parent[order]] = radius[order]
    kid_g[parent[order]] = g[order]
    has[parent[order]] = True
    blend = np.where(has, tip + (np.minimum(kid_r, radius) - tip) * kid_g, tip)
    return np.maximum(blend, 0.05 * radius)


def branch_arrays(skel, age: float):
    """A 6-sided tube per segment with growth > 0; length and radius scale with growth."""
    segs = skel.segments
    if not segs:
        return _empty()
    info = np.array([(s.id, s.depth, s.radius, s.birth_age, s.grow_hours) for s in segs], np.float64)
    ids, depth, radius, birth, hours = info.T
    parent = np.array([s.parent for s in segs], np.int64)
    max_depth = max(1.0, depth.max())
    g = growth(age, birth, hours)
    tip_r = _tip_radius(parent, radius, g)
    vis = g > 0.0
    count = int(vis.sum())
    if count == 0:
        return _empty()

    start = np.array([s.start for s in segs], np.float64)[vis]
    delta = np.array([s.end for s in segs], np.float64)[vis] - start
    ids, depth, radius, g, tip_r = ids[vis], depth[vis], radius[vis], g[vis], tip_r[vis]
    length = np.linalg.norm(delta, axis=1)
    d = _unit(delta)
    u, v = _frame(d)  # u x v == d, so increasing angle runs counter-clockwise seen from the tip
    ang = np.arange(SIDES) * (2.0 * np.pi / SIDES)
    ring = np.cos(ang)[None, :, None] * u[:, None, :] + np.sin(ang)[None, :, None] * v[:, None, :]

    pos = np.empty((count, 2, SIDES, 3))
    pos[:, 0] = start[:, None, :] + (radius * g)[:, None, None] * ring
    pos[:, 1] = (start + delta * g[:, None])[:, None, :] + (tip_r * g)[:, None, None] * ring

    # The surface leans toward the tip by the taper slope; both rings share the normal.
    slope = (radius - tip_r) / np.maximum(length, 1e-9)
    side = ring + d[:, None, :] * slope[:, None, None]
    side /= np.linalg.norm(side, axis=2, keepdims=True)
    nrm = np.broadcast_to(side[:, None], pos.shape)

    uv0 = np.zeros((count, 2, SIDES, 2))
    uv0[..., 0] = np.arange(SIDES) / SIDES
    uv0[:, 1, :, 1] = (g * length / V_TILE_CM)[:, None]
    uv1 = np.empty((count, 2, SIDES, 2))
    uv1[..., 0] = ((ids * 0.618) % 1.0)[:, None, None]
    uv1[..., 1] = (depth / max_depth * g)[:, None, None]

    idx = 2 * SIDES * np.arange(count)[:, None] + _TUBE_INDICES[None, :]
    return _pack(pos, nrm, uv0, uv1, idx)


def leaf_arrays(skel, age: float, size: float):
    """One quad per born leaf, 8 cm * size * leaf_scale * growth, normal = leaf_dir."""
    leaf_pos = np.asarray(skel.leaf_pos, np.float64).reshape(-1, 3)
    total = len(leaf_pos)
    if total == 0:
        return _empty()
    # Draw for every leaf so a leaf keeps its phase and spin as others are born.
    rng = np.random.default_rng(_LEAF_SEED)
    phase = rng.random(total)
    spin = rng.random(total) * (2.0 * np.pi)
    g = growth(age, np.asarray(skel.leaf_birth, np.float64), LEAF_GROW_HOURS)
    vis = g > 0.0
    count = int(vis.sum())
    if count == 0:
        return _empty()

    n = _unit(np.asarray(skel.leaf_dir, np.float64).reshape(-1, 3)[vis])
    half = 0.5 * LEAF_SIZE_CM * size * np.asarray(skel.leaf_scale, np.float64)[vis] * g[vis]
    t, b = _frame(n)
    cs, sn = np.cos(spin[vis])[:, None], np.sin(spin[vis])[:, None]
    tr, br = cs * t + sn * b, cs * b - sn * t  # spin about n keeps tr x br == n
    corner = _QUAD_CORNERS[None, :, :, None]  # (1,4,2,1)
    offs = corner[:, :, 0] * tr[:, None, :] + corner[:, :, 1] * br[:, None, :]
    pos = leaf_pos[vis][:, None, :] + half[:, None, None] * offs

    nrm = np.broadcast_to(n[:, None, :], pos.shape)
    uv0 = np.broadcast_to(_QUAD_UV, (count, 4, 2))
    uv1 = np.empty((count, 4, 2))
    uv1[..., 0] = phase[vis][:, None]
    uv1[..., 1] = 1.0

    idx = 4 * np.arange(count)[:, None] + _QUAD_INDICES[None, :]
    return _pack(pos, nrm, uv0, uv1, idx)


@functools.lru_cache(maxsize=None)
def _icosphere():
    """Unit icosahedron with one subdivision: 42 vertices, 80 outward-facing triangles."""
    p = (1.0 + 5.0**0.5) / 2.0
    verts = [(-1, p, 0), (1, p, 0), (-1, -p, 0), (1, -p, 0), (0, -1, p), (0, 1, p),
             (0, -1, -p), (0, 1, -p), (p, 0, -1), (p, 0, 1), (-p, 0, -1), (-p, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
             (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
             (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
             (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts = [np.array(v, np.float64) / np.linalg.norm(v) for v in verts]
    mids = {}

    def mid(a, b):
        key = (min(a, b), max(a, b))
        if key not in mids:
            m = verts[a] + verts[b]
            verts.append(m / np.linalg.norm(m))
            mids[key] = len(verts) - 1
        return mids[key]

    tris = []
    for a, b, c in faces:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        tris += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    verts = np.array(verts)
    tris = np.array(tris)
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    inward = np.einsum("ij,ij->i", np.cross(b - a, c - a), a + b + c) < 0.0
    tris[inward] = tris[inward][:, ::-1]
    uv = np.stack([0.5 + np.arctan2(verts[:, 2], verts[:, 0]) / (2.0 * np.pi),
                   0.5 - np.arcsin(verts[:, 1]) / np.pi], axis=1)
    for arr in (verts, tris, uv):
        arr.setflags(write=False)
    return verts, tris, uv


def fruit_arrays(skel, age: float, radius: float = 4.0):
    """A low-poly sphere per born fruit, scaled by growth."""
    fruit_pos = np.asarray(skel.fruit_pos, np.float64).reshape(-1, 3)
    total = len(fruit_pos)
    if total == 0:
        return _empty()
    phase = np.random.default_rng(_FRUIT_SEED).random(total)
    g = growth(age, np.asarray(skel.fruit_birth, np.float64), FRUIT_GROW_HOURS)
    vis = g > 0.0
    count = int(vis.sum())
    if count == 0:
        return _empty()

    verts, tris, uv = _icosphere()
    nv = len(verts)
    pos = fruit_pos[vis][:, None, :] + verts[None] * (radius * g[vis])[:, None, None]
    nrm = np.broadcast_to(verts, pos.shape)
    uv0 = np.broadcast_to(uv, (count, nv, 2))
    uv1 = np.empty((count, nv, 2))  # fruits hang from leaves, so they share the leaf sway
    uv1[..., 0] = phase[vis][:, None]
    uv1[..., 1] = 1.0
    idx = nv * np.arange(count)[:, None] + tris.ravel()[None, :]
    return _pack(pos, nrm, uv0, uv1, idx)


class PlantGeometry(QQuick3DGeometry):
    """Geometry that uploads interleaved float32 vertices (stride 40) and u32 indices."""

    def set_arrays(self, arrays) -> None:
        pos, nrm, uv0, uv1, idx = arrays
        verts = np.concatenate([pos, nrm, uv0, uv1], axis=1).astype(np.float32, copy=False)
        Sem = QQuick3DGeometry.Attribute.Semantic
        Comp = QQuick3DGeometry.Attribute.ComponentType
        self.clear()
        self.setVertexData(QByteArray(verts.tobytes()))
        self.setIndexData(QByteArray(np.ascontiguousarray(idx, np.uint32).tobytes()))
        self.setStride(STRIDE)
        self.addAttribute(Sem.PositionSemantic, 0, Comp.F32Type)
        self.addAttribute(Sem.NormalSemantic, 12, Comp.F32Type)
        self.addAttribute(Sem.TexCoord0Semantic, 24, Comp.F32Type)
        self.addAttribute(Sem.TexCoord1Semantic, 32, Comp.F32Type)
        self.addAttribute(Sem.IndexSemantic, 0, Comp.U32Type)
        lo, hi = (pos.min(axis=0), pos.max(axis=0)) if len(pos) else (np.zeros(3), np.zeros(3))
        self.setBounds(QVector3D(*map(float, lo)), QVector3D(*map(float, hi)))
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        self.update()
