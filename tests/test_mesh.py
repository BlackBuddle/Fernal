from types import SimpleNamespace

import numpy as np
import pytest

from fernal import mesh


def seg(i, parent, depth, start, end, radius=2.0, birth=0.0, hours=10.0):
    return SimpleNamespace(
        id=i, parent=parent, depth=depth,
        start=np.array(start, np.float32), end=np.array(end, np.float32),
        radius=radius, birth_age=birth, grow_hours=hours,
    )


def make_skel():
    segments = [
        seg(0, -1, 0, (0, 0, 0), (0, 100, 0), radius=6.0, birth=0.0, hours=24.0),
        seg(1, 0, 1, (0, 100, 0), (30, 150, 0), radius=4.2, birth=15.0, hours=20.0),
        seg(2, 1, 2, (30, 150, 0), (30, 180, 20), radius=2.9, birth=100.0, hours=16.0),
    ]
    return SimpleNamespace(
        segments=segments,
        leaf_pos=np.array([[30, 150, 0], [10, 120, 5], [30, 175, 15]], np.float32),
        leaf_dir=np.array([[0, 1, 0], [1, 0, 0], [0, 0, 1]], np.float32),
        leaf_birth=np.array([20.0, 30.0, 105.0], np.float32),
        leaf_scale=np.array([1.0, 1.2, 0.8], np.float32),
        fruit_pos=np.array([[30, 147, 0], [10, 117, 5]], np.float32),
        fruit_birth=np.array([25.0, 120.0], np.float32),
    )


def check_arrays(arrays):
    pos, nrm, uv0, uv1, idx = arrays
    n = len(pos)
    assert pos.shape == (n, 3) and nrm.shape == (n, 3)
    assert uv0.shape == (n, 2) and uv1.shape == (n, 2)
    assert pos.dtype == nrm.dtype == uv0.dtype == uv1.dtype == np.float32
    assert idx.dtype == np.uint32 and idx.ndim == 1 and len(idx) % 3 == 0


def facing(arrays):
    """Dot product of each triangle's geometric normal with the mean of its vertex normals."""
    pos, nrm, _, _, idx = arrays
    tri = idx.reshape(-1, 3)
    a, b, c = (pos[tri[:, i]].astype(np.float64) for i in range(3))
    geo = np.cross(b - a, c - a)
    vn = sum(nrm[tri[:, i]].astype(np.float64) for i in range(3))
    return np.einsum("ij,ij->i", geo, vn)


def test_growth_smoothstep_bounds():
    assert mesh.growth(0.0, 0.0, 10.0) == 0.0
    assert mesh.growth(-5.0, 0.0, 10.0) == 0.0
    assert mesh.growth(5.0, 0.0, 10.0) == pytest.approx(0.5)
    assert mesh.growth(10.0, 0.0, 10.0) == 1.0
    assert mesh.growth(99.0, 0.0, 10.0) == 1.0
    assert mesh.growth(2.5, 0.0, 10.0) == pytest.approx(0.15625)  # 3t^2 - 2t^3 at t = 0.25
    assert isinstance(mesh.growth(5.0, 0.0, 10.0), float)
    birth = np.array([0.0, 5.0, 20.0], np.float32)
    hours = np.array([10.0, 10.0, 10.0], np.float32)
    g = mesh.growth(10.0, birth, hours)
    assert g.shape == (3,)
    assert g == pytest.approx([1.0, 0.5, 0.0])
    ts = np.linspace(-5.0, 15.0, 81)
    gs = mesh.growth(ts, 0.0, 10.0)
    assert np.all(np.diff(gs) >= 0.0) and gs.min() == 0.0 and gs.max() == 1.0


def test_branch_arrays_vertex_count():
    skel = make_skel()
    arrays = mesh.branch_arrays(skel, 20.0)  # segments 0 and 1 are visible
    check_arrays(arrays)
    pos, _, _, _, idx = arrays
    assert len(pos) == 2 * 12
    assert len(idx) == 2 * 36
    one = mesh.branch_arrays(skel, 5.0)  # only the trunk
    assert len(one[0]) == 12 and len(one[4]) == 36


def test_unborn_segments_excluded():
    skel = make_skel()
    for empty_age in (-1.0, 0.0):  # growth is exactly 0 at the birth age
        assert all(len(a) == 0 for a in mesh.branch_arrays(skel, empty_age))
    pos = mesh.branch_arrays(skel, 20.0)[0]
    assert pos[:, 1].max() < 130.0  # segment 2 (birth 100) would reach y = 180
    assert len(mesh.branch_arrays(skel, 500.0)[0]) == 3 * 12
    empty = SimpleNamespace(segments=[])
    assert len(mesh.branch_arrays(empty, 10.0)[0]) == 0


def test_branch_tip_growth_radius_and_sway():
    skel = make_skel()
    pos, nrm, uv0, uv1, _ = mesh.branch_arrays(skel, 500.0)  # fully grown
    base, tip = pos[:6], pos[6:12]
    assert np.allclose(base.mean(axis=0), [0, 0, 0], atol=1e-4)
    assert np.allclose(tip.mean(axis=0), [0, 100, 0], atol=1e-4)
    assert np.allclose(np.linalg.norm(base - base.mean(axis=0), axis=1), 6.0, atol=1e-4)
    assert np.allclose(np.linalg.norm(tip - tip.mean(axis=0), axis=1), 6.0 * 0.7, atol=1e-4)
    assert np.allclose(np.linalg.norm(nrm, axis=1), 1.0, atol=1e-5)
    assert uv0[6:12, 1] == pytest.approx(100.0 / 20.0)
    for i, s in enumerate(skel.segments):
        block = uv1[12 * i:12 * (i + 1)]
        assert np.allclose(block[:, 0], (s.id * 0.618) % 1.0, atol=1e-6)
        assert np.allclose(block[:, 1], s.depth / 2.0, atol=1e-6)  # deepest segment has depth 2
    half = mesh.branch_arrays(skel, 12.0)  # trunk growth = 0.5
    assert half[0][6:12, 1] == pytest.approx(50.0, abs=1e-3)
    assert np.linalg.norm(half[0][:6] - half[0][:6].mean(axis=0), axis=1) == pytest.approx(3.0, abs=1e-4)


def test_tube_winding_faces_outward():
    arrays = mesh.branch_arrays(make_skel(), 500.0)
    assert np.all(facing(arrays) > 0.0)
    vertical = SimpleNamespace(segments=[seg(0, -1, 0, (0, 0, 0), (0, 0, 0), birth=0.0, hours=1.0)])
    check_arrays(mesh.branch_arrays(vertical, 1.0))  # zero-length segment must not produce NaN
    assert np.isfinite(mesh.branch_arrays(vertical, 1.0)[0]).all()


def test_leaf_quad_size_scales_with_growth():
    skel = make_skel()
    one = SimpleNamespace(
        leaf_pos=skel.leaf_pos[1:2], leaf_dir=skel.leaf_dir[1:2],
        leaf_birth=np.array([10.0], np.float32), leaf_scale=np.array([1.2], np.float32),
    )

    def edge(age, size):
        pos = mesh.leaf_arrays(one, age, size)[0]
        assert len(pos) == 4
        return np.linalg.norm(pos[1] - pos[0]), np.linalg.norm(pos[3] - pos[0])

    full_age = 10.0 + mesh.LEAF_GROW_HOURS
    assert edge(full_age, 1.0) == pytest.approx((8.0 * 1.2,) * 2, rel=1e-4)
    assert edge(full_age, 1.5) == pytest.approx((8.0 * 1.5 * 1.2,) * 2, rel=1e-4)
    assert edge(10.0 + 0.5 * mesh.LEAF_GROW_HOURS, 1.0) == pytest.approx((8.0 * 1.2 * 0.5,) * 2, rel=1e-4)
    assert len(mesh.leaf_arrays(one, 10.0, 1.0)[0]) == 0  # not born yet

    arrays = mesh.leaf_arrays(one, full_age, 1.0)
    check_arrays(arrays)
    pos, nrm, uv0, uv1, idx = arrays
    assert np.allclose(nrm, [1, 0, 0])  # leaf_dir is the quad normal
    assert np.allclose((pos[1:] - pos[0]) @ np.array([1.0, 0, 0]), 0.0, atol=1e-5)  # quad lies in the plane
    assert np.allclose(pos.mean(axis=0), one.leaf_pos[0], atol=1e-5)
    assert uv0.tolist() == [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert np.all(uv1[:, 1] == 1.0) and np.all((uv1[:, 0] >= 0) & (uv1[:, 0] < 1))
    assert np.all(facing(arrays) > 0.0)


def test_leaf_phase_is_stable_across_ages():
    skel = make_skel()
    early = mesh.leaf_arrays(skel, 25.0, 1.0)  # leaf 0 only
    late = mesh.leaf_arrays(skel, 500.0, 1.0)  # all three
    assert len(early[0]) == 4 and len(late[0]) == 12
    assert early[3][:, 0] == pytest.approx(late[3][:4, 0])
    again = mesh.leaf_arrays(skel, 500.0, 1.0)
    assert np.array_equal(again[3], late[3])


def test_fruit_arrays_sphere():
    skel = make_skel()
    arrays = mesh.fruit_arrays(skel, 500.0, radius=3.0)
    check_arrays(arrays)
    pos, nrm, _, _, idx = arrays
    assert len(pos) == 2 * 42 and len(idx) == 2 * 80 * 3
    first = pos[:42] - skel.fruit_pos[0]
    assert np.allclose(np.linalg.norm(first, axis=1), 3.0, atol=1e-4)
    assert np.allclose(np.linalg.norm(nrm, axis=1), 1.0, atol=1e-5)
    assert np.all(facing(arrays) > 0.0)
    young = mesh.fruit_arrays(skel, 26.0, radius=4.0)  # fruit 0 is half grown, fruit 1 unborn
    assert len(young[0]) == 42
    r = np.linalg.norm(young[0] - skel.fruit_pos[0], axis=1)
    assert r == pytest.approx(4.0 * mesh.growth(26.0, 25.0, mesh.FRUIT_GROW_HOURS), rel=1e-4)


def test_indices_in_range():
    skel = make_skel()
    for age in (0.0, 12.0, 26.0, 60.0, 500.0):
        for arrays in (
            mesh.branch_arrays(skel, age),
            mesh.leaf_arrays(skel, age, 1.0),
            mesh.fruit_arrays(skel, age),
        ):
            check_arrays(arrays)
            pos, idx = arrays[0], arrays[4]
            assert np.isfinite(pos).all()
            if len(idx):
                assert idx.min() >= 0 and idx.max() < len(pos)
            else:
                assert len(pos) == 0
    empty = SimpleNamespace(
        leaf_pos=np.zeros((0, 3), np.float32), leaf_dir=np.zeros((0, 3), np.float32),
        leaf_birth=np.zeros(0, np.float32), leaf_scale=np.zeros(0, np.float32),
        fruit_pos=np.zeros((0, 3), np.float32), fruit_birth=np.zeros(0, np.float32),
    )
    assert len(mesh.leaf_arrays(empty, 10.0, 1.0)[0]) == 0
    assert len(mesh.fruit_arrays(empty, 10.0)[0]) == 0


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def test_plant_geometry_import(qapp):
    from PySide6.QtQuick3D import QQuick3DGeometry

    assert issubclass(mesh.PlantGeometry, QQuick3DGeometry)
    arrays = mesh.branch_arrays(make_skel(), 500.0)
    geo = mesh.PlantGeometry()
    geo.set_arrays(arrays)
    pos = arrays[0]
    assert geo.stride() == 40
    assert geo.attributeCount() == 5
    assert geo.primitiveType() == QQuick3DGeometry.PrimitiveType.Triangles
    assert geo.indexData().size() == len(arrays[4]) * 4
    lo, hi = geo.boundsMin(), geo.boundsMax()
    assert (lo.x(), lo.y(), lo.z()) == pytest.approx(tuple(pos.min(axis=0)), abs=1e-4)
    assert (hi.x(), hi.y(), hi.z()) == pytest.approx(tuple(pos.max(axis=0)), abs=1e-4)
    offsets = [geo.attribute(i).offset for i in range(4)]
    assert offsets == [0, 12, 24, 32]
    geo.set_arrays(mesh.branch_arrays(SimpleNamespace(segments=[]), 1.0))  # empty upload is allowed
    assert geo.indexData().size() == 0
