"""Seeded skeleton generation for the Fernal plant.

The tree is grown as a set of *axes*: a leader trunk, limbs on the trunk,
branches on the limbs and twigs on the branches. Each axis is a chain of short
straight segments with small random bends, and side axes (laterals) leave from
the nodes between chain segments, so ``Segment.start`` of every child is its
parent's ``end``. ``Params.max_depth`` is read as the maximum branching order
(``max_depth - 3``: 6 gives trunk, limbs, branches, twigs); ``Segment.depth``
stays the number of segments from the trunk base.

Every segment draws its randomness from ``default_rng([seed, segment_id])`` with
a fixed draw budget, so moving a slider morphs the same tree instead of
reshuffling it, and leaf or fruit settings never move a branch. Radii follow the
pipe model (cross-section proportional to the twigs carried). Pure numpy; the
environment object is duck-typed.
"""
import math
from dataclasses import dataclass

import numpy as np

_MAX_LATERALS = 3   # laterals a single node can carry
_LAT_COLS = 6       # angle, azimuth, length, curve, birth, bend
_MAX_LEAVES = 16    # leaves a single segment can carry
_LEAF_COLS = 9      # t, phi, 3 jitter values, scale, fruit roll, birth, offset
_FRUIT_DROP = 3.0   # cm below the leaf
_FRUIT_SHARE = 0.12  # of fruit_ratio: leaves are many, so only a few carry fruit
_DRAWS = 3 + 1 + _MAX_LATERALS * _LAT_COLS + 1 + _MAX_LEAVES * _LEAF_COLS  # per segment
_GOLDEN = math.pi * (3.0 - math.sqrt(5.0))  # phyllotaxis angle, ~137.5 deg
_UP = np.array([0.0, 1.0, 0.0])

# Per branching order: 0 trunk, 1 limb, 2 branch, 3 twig, 4 twiglet.
_SEG_CM = (19.0, 16.0, 11.0, 7.0, 5.0)        # target segment length
_MAX_SEGS = (10, 8, 6, 4, 2)                   # segments per axis (trunk: bole + crown leader)
_ZONE = (0.28, 0.12, 0.12, 0.10, 1.0)          # where laterals start along the axis
_LAT_PER_NODE = (0.50, 0.36, 0.34, 0.32, 0.0)  # mean laterals per node per unit branch_factor
_CHILD_LEN = (0.0, 0.72, 0.62, 0.45, 0.0)      # lateral length / parent axis length (orders >= 1)
_BEND = (0.07, 0.10, 0.13, 0.16, 0.18)         # random bend per segment
# Growth speed in cm per plant hour. The leader climbs slowly for most of the plant's
# life while the limbs reach out at a similar pace, so a young tree is a smaller,
# narrower version of the mature crown rather than its lower half.
_SPEED = (2.75, 2.45, 2.9, 3.0, 2.6)
_BOLE_HOURS = 5.0                              # the bare bole shoots up first
_LAG = (0.0, 0.8, 0.8, 0.5, 0.5)               # hours a lateral bud waits at its node
_TROPISM = (0.06, 0.10, 0.09, 0.07, 0.07)     # per-segment pull toward the light per unit strength
_MIN_LEN = 4.0                                 # cm, shorter laterals are not grown
# Leaves: relative density by rank (0 = finest twigs), on the leader above this axis fraction.
_LEAF_WEIGHT = (1.0, 0.8, 0.45, 0.25)
_LEADER_LEAF_WEIGHT = 0.8
_LEADER_LEAF_FROM = 0.3
_LEAF_RATE = 2.2    # leaves per cm of twig at full density, before the per-segment rolls
_LEAF_BUDGET = 4800  # leaves at most; rich, dense trees are thinned evenly (vertex budget)


@dataclass
class Params:
    branch_factor: float = 2.4      # mean children per segment, 1.5..3.5
    length_ratio: float = 0.72      # child/parent length, 0.6..0.85
    spread_deg: float = 35.0        # 20..60
    droop: float = 0.0              # 0..1 downward bend
    leaf_density: float = 0.7       # 0..1
    leaf_size: float = 1.0          # 0.5..1.5 multiplier
    tropism: tuple = (0.0, 1.0, 0.0)
    tropism_strength: float = 0.2   # 0..1
    max_depth: int = 6              # 4..7
    trunk_length: float = 100.0     # cm
    fruit_ratio: float = 0.0        # 0..1 fraction of leaves that carry a fruit
    max_segments: int = 1500


@dataclass
class Segment:
    id: int
    parent: int                     # -1 for the trunk
    depth: int
    start: np.ndarray               # (3,) float32, fully grown
    end: np.ndarray                 # (3,) float32
    radius: float                   # cm at the base
    birth_age: float                # plant hours
    grow_hours: float


@dataclass
class Skeleton:
    segments: list                  # list[Segment], index == id
    leaf_pos: np.ndarray            # (L,3) f32
    leaf_dir: np.ndarray            # (L,3) f32 unit normal of the leaf quad
    leaf_birth: np.ndarray          # (L,) f32
    leaf_scale: np.ndarray          # (L,) f32 in 0.7..1.3
    fruit_pos: np.ndarray           # (F,3) f32
    fruit_birth: np.ndarray         # (F,) f32


def _clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def params_from(env, vitality: float, sun_dir: tuple, theme: str) -> Params:
    """Map environment values to growth parameters (spec section 4 table)."""
    water = _clamp(env.water, 0.0, 1.0)
    nutrients = _clamp(env.nutrients, 0.0, 1.0)
    humidity = _clamp(env.humidity, 0.0, 1.0)
    light = _clamp(env.light, 0.0, 1.0)
    affection = _clamp(env.affection, 0.0, 1.0)
    vit = _clamp(vitality, 0.0, 1.0)

    sun = np.asarray(sun_dir, dtype=np.float64)
    norm = float(np.linalg.norm(sun))
    if norm > 1e-9 and math.isfinite(norm):
        tropism = tuple(float(c) for c in sun / norm)
    else:
        tropism = (0.0, 1.0, 0.0)

    return Params(
        branch_factor=1.5 + 2.0 * nutrients,
        length_ratio=0.6 + 0.25 * water,
        droop=_clamp((0.2 - water) / 0.2, 0.0, 1.0),
        leaf_density=_clamp(humidity * vit, 0.0, 1.0),
        leaf_size=0.5 + water,
        tropism=tropism,
        tropism_strength=_clamp(0.1 + 0.5 * light, 0.0, 1.0),
        fruit_ratio=0.3 * affection if theme == "fruit" else 0.0,
    )


def _unit(x, fallback):
    n = math.sqrt(float(x[0] * x[0] + x[1] * x[1] + x[2] * x[2]))
    return x / n if n > 1e-9 else fallback


def _basis(d):
    """Two unit vectors u, v so that (d, u, v) is a right-handed frame."""
    dx, dy, dz = d.tolist()
    # Cross d with the world axis it is least aligned with.
    hx, hy, hz = (1.0, 0.0, 0.0) if abs(dy) > 0.9 else (0.0, 1.0, 0.0)
    ux, uy, uz = dy * hz - dz * hy, dz * hx - dx * hz, dx * hy - dy * hx
    n = math.sqrt(ux * ux + uy * uy + uz * uz)
    ux, uy, uz = ux / n, uy / n, uz / n
    vx, vy, vz = dy * uz - dz * uy, dz * ux - dx * uz, dx * uy - dy * ux
    return np.array([ux, uy, uz]), np.array([vx, vy, vz])


def _crown_shape(r):
    """Relative limb length at crown position r (0 = crown base, 1 = top): an ovoid."""
    return 0.32 + 0.68 * math.exp(-((r - 0.3) / 0.48) ** 2)


@dataclass
class _Axis:
    order: int
    n: int              # segments in the chain
    seg_len: float      # cm per segment
    length: float       # total cm
    rise: float         # per-segment upward curl
    sag: float          # per-segment gravity at the tip
    azimuth: float      # phyllotaxis phase of its laterals
    zone: float         # axis fraction where laterals start


def _node_t(ax, k):
    """Axis fraction at the end of its k-th segment (the trunk's bole spans ``zone``)."""
    if ax.order == 0:
        return ax.zone + (1.0 - ax.zone) * k / (ax.n - 1)
    return (k + 1) / ax.n


def generate(seed: int, params: Params) -> Skeleton:
    """Grow the skeleton breadth-first; same seed and params give same arrays."""
    p = params
    seed = int(seed) & 0xFFFFFFFFFFFFFFFF
    max_order = min(4, max(1, int(p.max_depth) - 3))
    cap = max(1, int(p.max_segments))
    trop = np.asarray(p.tropism, dtype=np.float64) * _clamp(p.tropism_strength, 0.0, 1.0)
    droop = _clamp(p.droop, 0.0, 1.0)
    lr = _clamp(p.length_ratio, 0.3, 1.0)
    spread = _clamp(p.spread_deg, 5.0, 80.0)
    bf = max(0.0, float(p.branch_factor))

    # The leader's own randomness comes from the trunk base segment's stream,
    # after the draws that segment spends in the loop below.
    lead = np.random.default_rng([seed, 0]).random(_DRAWS + 4)[_DRAWS:]
    lead_len = p.trunk_length * (2.15 + 0.3 * lead[0]) * (0.75 + 0.35 * lr)
    n0 = _MAX_SEGS[0]
    zone0 = _ZONE[0] + 0.06 * (lead[2] - 0.5)
    # The bole is one segment up to the crown base; the leader above it is a chain.
    axes = [_Axis(0, n0, lead_len * (1.0 - zone0) / (n0 - 1), lead_len, 0.10, 0.0,
                  2.0 * math.pi * lead[1], zone0)]
    d0 = _unit(_UP + 0.04 * np.array([math.cos(6.28 * lead[3]), 0.0, math.sin(6.28 * lead[3])]), _UP)

    seg_len0 = lead_len * zone0
    segments = [Segment(0, -1, 0, np.zeros(3, np.float32), (d0 * seg_len0).astype(np.float32),
                        0.0, 0.0, _BOLE_HOURS)]
    dirs = [d0]
    axis_of = [0]
    index_of = [0]          # position of the segment within its axis
    leaf_rolls = []         # per segment: (count roll, leaf block)

    i = 0
    while i < len(segments):
        seg, d = segments[i], dirs[i]
        ax = axes[axis_of[i]]
        k = index_of[i]
        rng = np.random.default_rng([seed, i])
        # Fixed draw budget: bend, lateral count, laterals, leaves.
        bend = rng.random(3)
        count_u = rng.random()
        lat = rng.random((_MAX_LATERALS, _LAT_COLS))
        leaf_rolls.append((rng.random(), rng.random((_MAX_LEAVES, _LEAF_COLS))))
        u, v = _basis(d)
        start = seg.end.astype(np.float64)
        t_node = _node_t(ax, k)
        node_birth = seg.birth_age + seg.grow_hours * 0.9

        # Continue the axis.
        if k + 1 < ax.n and len(segments) < cap:
            ang = 2.0 * math.pi * bend[0]
            w = u * math.cos(ang) + v * math.sin(ang)
            vert = ax.rise * (1.0 - t_node) - ax.sag * t_node ** 1.5
            nd = d + _BEND[ax.order] * (0.4 + bend[1]) * w + vert * _UP + _TROPISM[ax.order] * trop
            nd = _unit(nd, d)
            length = ax.seg_len * (0.9 + 0.2 * bend[2])
            segments.append(Segment(len(segments), i, seg.depth + 1, seg.end.copy(),
                                    (start + nd * length).astype(np.float32), 0.0,
                                    seg.birth_age + seg.grow_hours * 0.85,
                                    length / _SPEED[ax.order]))
            dirs.append(nd)
            axis_of.append(axis_of[i])
            index_of.append(k + 1)

        # Laterals at the node.
        if ax.order < max_order and t_node >= ax.zone:
            lam = _LAT_PER_NODE[ax.order] * bf
            if k + 1 == ax.n:
                lam *= 0.8 if ax.order else 1.4   # a fuller crown top, lighter ends elsewhere
            n_lat = min(_MAX_LATERALS, int(lam + count_u))
            co = ax.order + 1
            r_crown = (t_node - ax.zone) / max(1e-6, 1.0 - ax.zone)
            for j in range(n_lat):
                if len(segments) >= cap:
                    break
                a_th, a_az, a_len, a_curve, a_birth, a_bend = lat[j]
                if ax.order == 0:
                    clen = lead_len * 0.62 * (lr / 0.72) * _crown_shape(r_crown) * (0.8 + 0.4 * a_len)
                    theta = spread * (1.2 + 0.6 * a_th) * (1.0 - 0.35 * r_crown)
                else:
                    clen = ax.length * _CHILD_LEN[co] * (lr / 0.72) * (1.0 - 0.5 * t_node) * (0.75 + 0.5 * a_len)
                    theta = spread * (1.0 + 0.6 * a_th)
                if clen < _MIN_LEN:
                    continue
                theta = math.radians(min(70.0, theta + 25.0 * droop))
                az = ax.azimuth + k * _GOLDEN + j * (2.0 * math.pi / n_lat) + 0.6 * (a_az - 0.5)
                w = u * math.cos(az) + v * math.sin(az)
                if ax.order and w[1] < 0.0:
                    w = _unit(w * np.array([1.0, -0.35, 1.0]), w)   # keep side shoots off the underside
                nd = _unit(d * math.cos(theta) + w * math.sin(theta) + _TROPISM[co] * trop, d)
                n = min(_MAX_SEGS[co], max(1, round(clen / _SEG_CM[co])))
                seg_len = clen / n
                heavy = clen / 100.0
                rise = (0.05 + 0.07 * a_curve) * (1.0 - 0.6 * droop)
                sag = (0.03 + 0.17 * heavy * (1.0 - 0.7 * r_crown if ax.order == 0 else 1.0)) + 0.5 * droop
                axes.append(_Axis(co, n, seg_len, clen, rise, sag, 2.0 * math.pi * a_az,
                                  _ZONE[co] if co < 4 else 1.0))
                length = seg_len * (0.9 + 0.2 * a_bend)
                segments.append(Segment(len(segments), i, seg.depth + 1, seg.end.copy(),
                                        (start + nd * length).astype(np.float32), 0.0,
                                        node_birth + _LAG[co] * (0.6 + 0.8 * a_birth),
                                        length / _SPEED[co]))
                dirs.append(nd)
                axis_of.append(len(axes) - 1)
                index_of.append(0)
        i += 1

    _assign_radii(segments, axes, axis_of, index_of, p.trunk_length * 0.06)
    leaves = _leaves(segments, dirs, axes, axis_of, index_of, leaf_rolls, p, max_order)
    leaf_pos, leaf_dir, leaf_birth, leaf_scale, carries_fruit = leaves
    fruit_pos = leaf_pos[carries_fruit] - np.array([0.0, _FRUIT_DROP, 0.0], np.float32)
    fruit_birth = leaf_birth[carries_fruit]
    return Skeleton(segments, leaf_pos, leaf_dir, leaf_birth, leaf_scale,
                    fruit_pos, fruit_birth)


def _assign_radii(segments, axes, axis_of, index_of, base_radius):
    """Pipe model: a segment's cross-section is proportional to the tips it carries."""
    n = len(segments)
    carried = np.zeros(n)
    has_child = np.zeros(n, bool)
    for s in segments[1:]:
        has_child[s.parent] = True
    carried[~has_child] = 1.0
    for s in reversed(segments[1:]):
        carried[s.parent] += carried[s.id]
    pipe = (carried / carried[0]) ** 0.42
    for s in segments:
        ax = axes[axis_of[s.id]]
        along = 1.0 - 0.22 * index_of[s.id] / ax.n
        r = max(0.25, base_radius * pipe[s.id] * along)
        s.radius = float(r if s.parent < 0 else min(r, segments[s.parent].radius))
        s.birth_age, s.grow_hours = float(s.birth_age), float(s.grow_hours)


def _leaves(segments, dirs, axes, axis_of, index_of, leaf_rolls, p, max_order):
    """Leaf anchors on every side axis and on the upper leader, densest on the finest twigs.

    Leaves follow their segment within a few hours, so a sapling already carries a few on
    its first shoots. Early leaves are kept small (shade leaves deep in the mature crown);
    later ones span the full 0.7..1.3 scale.
    """
    ends = np.array([s.end for s in segments], np.float64)
    outer = [s.id for s in segments if axes[axis_of[s.id]].order >= 1]
    center = ends[outer].mean(axis=0) if outer else ends.mean(axis=0)
    center[1] = ends[outer, 1].mean() if outer else center[1]
    density = _clamp(p.leaf_density, 0.0, 1.0)
    offset = 4.2 * _clamp(p.leaf_size, 0.3, 2.0)
    late = max(1.0, max(s.birth_age + s.grow_hours for s in segments))

    plan = []
    for s in segments:
        ax = axes[axis_of[s.id]]
        if s.id == 0:
            continue                          # the bare bole
        n_u = leaf_rolls[s.id][0]
        t_axis = _node_t(ax, index_of[s.id])
        if ax.order == 0:
            if t_axis < _LEADER_LEAF_FROM:
                continue
            weight = _LEADER_LEAF_WEIGHT
        else:
            weight = _LEAF_WEIGHT[min(3, max_order - ax.order)]
        if n_u < 0.08:
            continue                          # a bare stretch lets the branches show
        seg_len = float(np.linalg.norm(s.end - s.start))
        expected = _LEAF_RATE * density * weight * seg_len * (0.55 + 0.9 * t_axis) * (0.45 + 1.1 * n_u)
        plan.append((s, expected / 3.0))
    total = sum(min(_MAX_LEAVES, e) for _, e in plan)
    thin = min(1.0, _LEAF_BUDGET / total) if total > 0 else 1.0

    parts = []
    for s, expected in plan:
        n_u, block = leaf_rolls[s.id]
        dither = (n_u * 7.31) % 1.0             # spreads rounding so sparse trees keep some leaves
        n = min(_MAX_LEAVES, int(expected * thin + dither))
        if n == 0:
            continue
        b = block[:n]
        d = dirs[s.id]
        u, v = _basis(d)
        start = s.start.astype(np.float64)
        on_twig = start + (s.end.astype(np.float64) - start) * b[:, 0:1]
        phi = 2.0 * math.pi * b[:, 1:2]
        perp = u * np.cos(phi) + v * np.sin(phi)
        pos = on_twig + perp * (offset * (0.7 + 0.6 * b[:, 8:9]))
        out = pos - center
        out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-6)
        ldir = 0.55 * perp + 0.5 * out + 0.3 * _UP + 0.45 * (b[:, 2:5] * 2.0 - 1.0)
        ldir /= np.maximum(np.linalg.norm(ldir, axis=1, keepdims=True), 1e-6)
        birth = s.birth_age + s.grow_hours * (0.6 + 0.4 * b[:, 0]) + 0.3 + 1.5 * b[:, 7]
        # Leaves born early stay small; the spread opens up as the plant matures.
        span = 0.25 + 0.75 * np.clip((birth - 0.1 * late) / (0.55 * late), 0.0, 1.0)
        scale = 0.7 + 0.6 * b[:, 5] * span
        parts.append((pos, ldir, birth, scale, b[:, 6]))

    if not parts:
        z3, z = np.zeros((0, 3), np.float32), np.zeros(0, np.float32)
        return z3, z3.copy(), z, z.copy(), np.zeros(0, bool)
    cat = [np.concatenate([x[c] for x in parts]) for c in range(5)]
    return (cat[0].astype(np.float32), cat[1].astype(np.float32), cat[2].astype(np.float32),
            cat[3].astype(np.float32), cat[4] < p.fruit_ratio * _FRUIT_SHARE)
