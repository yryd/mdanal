"""连续视图：无键包裹坐标的顺序/回退/跳帧展开。"""

from __future__ import annotations

import numpy as np
import pytest

from mdanal.config.continuous import ContinuousView


def _universe(frames):
    import MDAnalysis as mda
    from MDAnalysis.coordinates.memory import MemoryReader

    coords = np.asarray(frames, dtype=float).reshape(len(frames), 1, 3)
    universe = mda.Universe.empty(1, trajectory=True)
    universe.load_new(
        coords,
        dimensions=np.tile([10.0, 10.0, 10.0, 90, 90, 90], (len(frames), 1)),
        format=MemoryReader,
    )
    return universe


def test_continuous_view_handles_forward_backward_and_gaps():
    universe = _universe([[9.0, 0.5, 0.5], [1.0, 0.5, 0.5], [3.0, 0.5, 0.5]])
    view = ContinuousView(universe)
    for frame, expected in (
        (0, 9.0),
        (1, 11.0),
        (2, 13.0),
        (1, 11.0),
        (0, 9.0),
        (2, 13.0),
    ):
        universe.trajectory[frame]
        view(universe.trajectory.ts)
        assert universe.trajectory.ts.positions[0, 0] == pytest.approx(expected)


def test_continuous_view_repeated_frame_is_idempotent():
    universe = _universe([[9.0, 0.5, 0.5], [1.0, 0.5, 0.5]])
    view = ContinuousView(universe)
    universe.trajectory[0]
    view(universe.trajectory.ts)
    universe.trajectory[1]
    view(universe.trajectory.ts)
    first = universe.trajectory.ts.positions.copy()
    view(universe.trajectory.ts)
    assert np.allclose(universe.trajectory.ts.positions, first)
