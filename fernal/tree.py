"""Seeded recursive skeleton generation for the Fernal plant.

The skeleton is a list of straight segments plus leaf and fruit anchor points.
Every segment draws its randomness from ``default_rng([seed, segment_id])`` with
a fixed draw budget, so moving a slider morphs the same tree instead of
reshuffling it. Pure numpy; the environment object is duck-typed.
"""
import math
from dataclasses import dataclass

import numpy as np

_MAX_CHILDREN = 4
_MAX_LEAVES = 9  # round(6 * 1.0 * 1.5), the most a segment can carry
_LEAF_COLS = 7  # t, phi, 3 jitter values, scale, fruit roll
_FRUIT_DROP = 3.0  # cm below the leaf


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


def _leaves_for(seg, d, u, v, p, rng):
    """Leaf anchors for one segment: pos, dir, birth, scale, fruit roll."""
    n_u = rng.uniform(0.5, 1.5)
    block = rng.random((_MAX_LEAVES, _LEAF_COLS))
    n = min(_MAX_LEAVES, max(0, round(6.0 * p.leaf_density * n_u)))
    if n == 0:
        return None
    b = block[:n]
    start = seg.start.astype(np.float64)
    end = seg.end.astype(np.float64)
    t = 0.4 + 0.6 * b[:, 0:1]                       # last 60 % of the segment
    pos = start + (end - start) * t
    phi = 2.0 * math.pi * b[:, 1:2]
    perp = u * np.cos(phi) + v * np.sin(phi)         # perpendicular to the segment
    ldir = perp + 0.5 * (b[:, 2:5] * 2.0 - 1.0)
    ldir /= np.linalg.norm(ldir, axis=1, keepdims=True)
    birth = np.full(n, seg.birth_age + seg.grow_hours * 0.5)
    scale = 0.7 + 0.6 * b[:, 5]
    return pos, ldir, birth, scale, b[:, 6]


def generate(seed: int, params: Params) -> Skeleton:
    """Build the skeleton breadth-first; same seed and params give same arrays."""
    p = params
    seed = int(seed) & 0xFFFFFFFFFFFFFFFF
    max_depth = max(0, int(p.max_depth))
    cap = max(1, int(p.max_segments))
    tropism = np.asarray(p.tropism, dtype=np.float64) * p.tropism_strength
    sag = np.array([0.0, p.droop, 0.0])

    trunk = Segment(0, -1, 0, np.zeros(3, np.float32),
                    np.array([0.0, p.trunk_length, 0.0], np.float32),
                    p.trunk_length * 0.06, 0.0, 24.0)
    segments = [trunk]
    dirs = [np.array([0.0, 1.0, 0.0])]
    lengths = [float(p.trunk_length)]

    leaf_parts = []
    fruit_rolls = []
    i = 0
    while i < len(segments):
        seg, d, length = segments[i], dirs[i], lengths[i]
        rng = np.random.default_rng([seed, i])
        count_jitter = rng.uniform(-0.8, 0.8)
        child_rolls = rng.random((_MAX_CHILDREN, 4))
        u, v = _basis(d)

        if seg.depth < max_depth:
            n_children = min(_MAX_CHILDREN, max(1, round(p.branch_factor + count_jitter)))
            start = seg.end.astype(np.float64)
            for k in range(n_children):
                if len(segments) >= cap:
                    break
                a, psi, len_j, birth_j = child_rolls[k]
                theta = math.radians(p.spread_deg * (0.6 + 0.8 * a))
                ang = 2.0 * math.pi * psi
                # Rotating d by theta about a random perpendicular axis tilts it
                # toward a uniformly random tangent direction w.
                w = u * math.cos(ang) + v * math.sin(ang)
                nd = d * math.cos(theta) + w * math.sin(theta)
                nd = nd + tropism - sag
                norm = float(np.linalg.norm(nd))
                nd = nd / norm if norm > 1e-9 else d
                clen = length * p.length_ratio * (0.85 + 0.3 * len_j)
                segments.append(Segment(
                    len(segments), i, seg.depth + 1, seg.end.copy(),
                    (start + nd * clen).astype(np.float32), seg.radius * 0.7,
                    seg.birth_age + seg.grow_hours * (0.6 + 0.3 * birth_j),
                    seg.grow_hours * 0.8))
                dirs.append(nd)
                lengths.append(clen)

        if seg.depth >= max_depth - 1:
            leaves = _leaves_for(seg, d, u, v, p, rng)
            if leaves is not None:
                leaf_parts.append(leaves[:4])
                fruit_rolls.append(leaves[4])
        i += 1

    if leaf_parts:
        leaf_pos = np.concatenate([x[0] for x in leaf_parts]).astype(np.float32)
        leaf_dir = np.concatenate([x[1] for x in leaf_parts]).astype(np.float32)
        leaf_birth = np.concatenate([x[2] for x in leaf_parts]).astype(np.float32)
        leaf_scale = np.concatenate([x[3] for x in leaf_parts]).astype(np.float32)
        carries_fruit = np.concatenate(fruit_rolls) < p.fruit_ratio
    else:
        leaf_pos = np.zeros((0, 3), np.float32)
        leaf_dir = np.zeros((0, 3), np.float32)
        leaf_birth = np.zeros(0, np.float32)
        leaf_scale = np.zeros(0, np.float32)
        carries_fruit = np.zeros(0, bool)

    fruit_pos = leaf_pos[carries_fruit] - np.array([0.0, _FRUIT_DROP, 0.0], np.float32)
    fruit_birth = leaf_birth[carries_fruit]
    return Skeleton(segments, leaf_pos, leaf_dir, leaf_birth, leaf_scale,
                    fruit_pos, fruit_birth)
