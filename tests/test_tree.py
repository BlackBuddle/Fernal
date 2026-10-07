import itertools
import time
from types import SimpleNamespace

import numpy as np

from fernal.tree import Params, generate, params_from


def make_env(**kw):
    base = dict(water=0.5, nutrients=0.5, temperature=22.0, humidity=0.7,
                light=0.5, affection=0.5)
    base.update(kw)
    return SimpleNamespace(**base)


def tips(skel):
    parents = {s.parent for s in skel.segments}
    return [s for s in skel.segments if s.id not in parents]


def assert_same(a, b):
    assert len(a.segments) == len(b.segments)
    for sa, sb in zip(a.segments, b.segments):
        assert (sa.id, sa.parent, sa.depth) == (sb.id, sb.parent, sb.depth)
        assert np.array_equal(sa.start, sb.start) and np.array_equal(sa.end, sb.end)
        assert (sa.radius, sa.birth_age, sa.grow_hours) == (sb.radius, sb.birth_age, sb.grow_hours)
    for name in ("leaf_pos", "leaf_dir", "leaf_birth", "leaf_scale", "fruit_pos", "fruit_birth"):
        assert np.array_equal(getattr(a, name), getattr(b, name)), name


def test_same_seed_same_skeleton():
    p = Params(fruit_ratio=0.3)
    assert_same(generate(42, p), generate(42, p))


def test_different_seed_differs():
    a, b = generate(1, Params()), generate(2, Params())
    ends_a = np.array([s.end for s in a.segments])
    ends_b = np.array([s.end for s in b.segments])
    assert ends_a.shape != ends_b.shape or not np.array_equal(ends_a, ends_b)
    assert a.leaf_pos.shape != b.leaf_pos.shape or not np.array_equal(a.leaf_pos, b.leaf_pos)


def test_more_nutrients_more_segments():
    for seed in range(5):
        poor = generate(seed, params_from(make_env(nutrients=0.1), 1.0, (0, 1, 0), "plain"))
        rich = generate(seed, params_from(make_env(nutrients=0.9), 1.0, (0, 1, 0), "plain"))
        assert len(rich.segments) > len(poor.segments)


def test_segment_cap_respected():
    skel = generate(7, Params(branch_factor=3.5, max_depth=7, max_segments=200))
    assert len(skel.segments) == 200
    assert [s.id for s in skel.segments] == list(range(200))


def test_params_from_ranges():
    ranges = dict(branch_factor=(1.5, 3.5), length_ratio=(0.6, 0.85), spread_deg=(20, 60),
                  droop=(0, 1), leaf_density=(0, 1), leaf_size=(0.5, 1.5),
                  tropism_strength=(0, 1), max_depth=(4, 7), fruit_ratio=(0, 1))
    extremes = (-50.0, 0.0, 0.19, 0.5, 1.0, 50.0)
    sun_dirs = [(0, 1, 0), (0, 0, 0), (5, -3, 2), (-1, 0, 0)]
    for w, n, h, l, a in itertools.product(extremes, repeat=5):
        env = make_env(water=w, nutrients=n, humidity=h, light=l, affection=a,
                       temperature=-40.0 if w < 0 else 60.0)
        for vit, theme, sun in zip((-3.0, 0.0, 0.5, 9.0), ("fruit", "flower", "plain", "fruit"), sun_dirs):
            p = params_from(env, vit, sun, theme)
            for name, (lo, hi) in ranges.items():
                assert lo <= getattr(p, name) <= hi, (name, getattr(p, name))
            assert isinstance(p.max_depth, int) and p.trunk_length == 100.0
            assert p.max_segments == 1500
            assert len(p.tropism) == 3
            assert abs(np.linalg.norm(p.tropism) - 1.0) < 1e-9


def test_params_from_mapping():
    dry = params_from(make_env(water=0.1), 1.0, (0, 1, 0), "plain")
    ok = params_from(make_env(water=0.5), 1.0, (0, 1, 0), "plain")
    wet = params_from(make_env(water=1.0), 1.0, (0, 1, 0), "plain")
    assert dry.droop > 0.0 and ok.droop == 0.0 and wet.droop == 0.0
    assert dry.length_ratio < ok.length_ratio < wet.length_ratio
    assert dry.leaf_size < ok.leaf_size < wet.leaf_size
    assert params_from(make_env(nutrients=0.9), 1, (0, 1, 0), "plain").branch_factor > \
        params_from(make_env(nutrients=0.1), 1, (0, 1, 0), "plain").branch_factor
    assert params_from(make_env(light=0.9), 1, (0, 1, 0), "plain").tropism_strength > \
        params_from(make_env(light=0.1), 1, (0, 1, 0), "plain").tropism_strength
    lush = params_from(make_env(humidity=0.8), 1.0, (0, 1, 0), "plain")
    weak = params_from(make_env(humidity=0.8), 0.25, (0, 1, 0), "plain")
    assert abs(weak.leaf_density - lush.leaf_density * 0.25) < 1e-9
    p = params_from(make_env(), 1.0, (2, 0, 0), "plain")
    assert p.tropism == (1.0, 0.0, 0.0)
    assert params_from(make_env(affection=1.0), 1, (0, 1, 0), "fruit").fruit_ratio == 0.3 * 1.0
    assert params_from(make_env(affection=1.0), 1, (0, 1, 0), "flower").fruit_ratio == 0.0


def test_tropism_bends_toward_sun():
    # The lean is gentle, so a single crown's own asymmetry can outweigh it;
    # compare the same seed under opposite suns and the average over seeds.
    rights, lefts = [], []
    for seed in (3, 4, 5):
        right = generate(seed, Params(tropism=(1.0, 0.0, 0.0), tropism_strength=0.5))
        left = generate(seed, Params(tropism=(-1.0, 0.0, 0.0), tropism_strength=0.5))
        rights.append(np.mean([s.end[0] for s in tips(right)]))
        lefts.append(np.mean([s.end[0] for s in tips(left)]))
        assert rights[-1] - lefts[-1] > 30.0
    assert np.mean(rights) > 10.0 and np.mean(lefts) < -10.0


def trunk_chain(skel):
    """Ids of the leader: from the base, follow the child that continues straightest."""
    segs = skel.segments
    kids = {}
    for s in segs[1:]:
        kids.setdefault(s.parent, []).append(s)
    chain = [0]
    while chain[-1] in kids:
        cur = segs[chain[-1]]
        d = (cur.end - cur.start) / np.linalg.norm(cur.end - cur.start)
        best = max(kids[chain[-1]], key=lambda c: np.dot((c.end - c.start) / np.linalg.norm(c.end - c.start), d))
        if np.dot((best.end - best.start) / np.linalg.norm(best.end - best.start), d) < 0.9:
            break
        chain.append(best.id)
    return chain


def test_trunk_and_structure():
    p = Params()
    skel = generate(11, p)
    segs = skel.segments
    trunk = segs[0]
    assert (trunk.id, trunk.parent, trunk.depth) == (0, -1, 0)
    assert np.array_equal(trunk.start, [0, 0, 0]) and trunk.end[1] > 0.5 * p.trunk_length
    assert trunk.radius == 6.0 and trunk.birth_age == 0.0 and trunk.grow_hours > 0
    assert len(trunk_chain(skel)) >= 5  # the leader is a chain, not a single pole
    for i, s in enumerate(segs):
        assert s.id == i and s.start.dtype == np.float32 and s.end.dtype == np.float32
        assert s.start.shape == (3,) and s.grow_hours > 0
        if i:
            par = segs[s.parent]
            assert s.parent < i and s.depth == par.depth + 1
            assert np.array_equal(s.start, par.end)
            assert s.radius <= par.radius + 1e-9
            # A child starts once its parent has mostly grown.
            assert s.birth_age >= par.birth_age + par.grow_hours * 0.8
            assert 1 <= sum(1 for c in segs if c.parent == s.parent) <= 4
    assert min(s.radius for s in segs) < 0.1 * trunk.radius  # fine twigs
    n = len(skel.leaf_pos)
    assert n > 0
    assert skel.leaf_pos.shape == skel.leaf_dir.shape == (n, 3)
    assert skel.leaf_birth.shape == skel.leaf_scale.shape == (n,)
    for arr in (skel.leaf_pos, skel.leaf_dir, skel.leaf_birth, skel.leaf_scale):
        assert arr.dtype == np.float32
    assert np.allclose(np.linalg.norm(skel.leaf_dir, axis=1), 1.0, atol=1e-5)
    assert skel.leaf_scale.min() >= 0.7 - 1e-6 and skel.leaf_scale.max() <= 1.3 + 1e-6
    assert len(skel.fruit_pos) == 0 and len(skel.fruit_birth) == 0


def test_leaf_density_and_fruit_keep_geometry():
    base = generate(9, Params(leaf_density=0.9))
    sparse = generate(9, Params(leaf_density=0.3))
    fruity = generate(9, Params(leaf_density=0.9, fruit_ratio=0.3))
    assert len(sparse.leaf_pos) < len(base.leaf_pos)
    for other in (sparse, fruity):
        assert [s.end.tolist() for s in other.segments] == [s.end.tolist() for s in base.segments]
    for name in ("leaf_pos", "leaf_dir", "leaf_birth", "leaf_scale"):
        assert np.array_equal(getattr(fruity, name), getattr(base, name))
    n_leaves, n_fruit = len(fruity.leaf_pos), len(fruity.fruit_pos)
    # Leaves are many, so only fruit_ratio * 0.2 of them carry a fruit.
    assert 0.03 * n_leaves < n_fruit < 0.09 * n_leaves
    below = {tuple(x) for x in fruity.fruit_pos + np.float32([0, 3, 0])}
    assert below <= {tuple(x) for x in fruity.leaf_pos}
    assert len(fruity.fruit_birth) == n_fruit


def test_default_generation_is_fast():
    start = time.perf_counter()
    skel = generate(1, Params(branch_factor=3.5, max_depth=7))
    assert len(skel.segments) == 1500
    assert time.perf_counter() - start < 1.0


def default_params(seed_sun=(0.5, 0.8, 0.3), light=0.5):
    env = make_env(water=0.6, nutrients=0.5, humidity=0.5, light=light)
    return params_from(env, 1.0, seed_sun, "normal")


def height(skel):
    return max(float(s.end[1]) for s in skel.segments)


def test_tree_is_upright():
    for light in (0.5, 1.0):
        p = default_params(light=light)
        for seed in (1, 2, 3):
            skel = generate(seed, p)
            t = np.array([s.end for s in tips(skel)])
            h = height(skel)
            assert abs(t[:, 0].mean()) < 0.25 * h and abs(t[:, 2].mean()) < 0.25 * h


def test_trunk_has_side_branches_along_length():
    for seed in (1, 2, 3):
        skel = generate(seed, default_params())
        chain = trunk_chain(skel)
        on_chain = set(chain)
        trunk_len = sum(float(np.linalg.norm(skel.segments[i].end - skel.segments[i].start)) for i in chain)
        nodes = {round(float(skel.segments[s.parent].end[1]), 3) for s in skel.segments[1:]
                 if s.parent in on_chain and s.id not in on_chain}
        assert len(nodes) >= 3
        assert max(nodes) - min(nodes) > 0.4 * trunk_len
        assert min(nodes) > 0.15 * trunk_len  # a visible bare trunk below the crown


def test_height_and_schedule_in_range():
    for seed in range(6):
        skel = generate(seed, default_params())
        full = max(s.birth_age + s.grow_hours for s in skel.segments)
        assert 200.0 <= height(skel) <= 380.0
        assert 50.0 <= full <= 130.0
        assert skel.leaf_birth.max() <= 130.0 + 2.0
