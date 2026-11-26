import numpy as np
import pytest

from pano360.gizmo import AXES, axis_rotation, ball_vector, to_angles, trackball
from pano360.preview import rotation


@pytest.mark.parametrize("angles", [(0, 0, 0), (37, -28, 61), (179.9, 89.99, -170),
    (33, 90, 48), (-160, -90, 120), (0, 0, 180), (-180, 0, 0)])
def test_angle_roundtrip(angles):
    matrix = rotation(*angles)
    result = to_angles(matrix)
    assert -180 <= result[0] <= 180 and -90 <= result[1] <= 90 and -180 <= result[2] <= 180
    np.testing.assert_allclose(rotation(*result), matrix, atol=2e-4)


def test_combined_world_axis_rotations():
    matrix = np.eye(3)
    for index in range(120):
        axis = AXES["XYZ"[index % 3]]
        matrix = axis_rotation(axis, 7) @ matrix
        canonical = rotation(*to_angles(matrix))
        np.testing.assert_allclose(canonical, matrix, atol=1e-5)
    np.testing.assert_allclose(matrix.T @ matrix, np.eye(3), atol=1e-10)
    assert np.linalg.det(matrix) == pytest.approx(1)


def test_trackball_drag_and_antipodes():
    for start, end in [(ball_vector(0, 0), ball_vector(.3, -.2)),
                       (ball_vector(-2, 0), ball_vector(2, 0)),
                       (ball_vector(.2, .1), ball_vector(.2, .1))]:
        delta = trackball(start, end)
        np.testing.assert_allclose(delta @ end, start, atol=1e-7)
        np.testing.assert_allclose(delta.T @ delta, np.eye(3), atol=1e-7)
        assert np.linalg.det(delta) == pytest.approx(1)
