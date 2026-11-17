"""坐标契约回归：非零盒原点、移动原点、非周期边界。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from mdanal import cli
from mdanal.config.geometry import read_geometry
from mdanal.config.system import load_universe, read_system, resolve_group

DATA = """LAMMPS data file

{natoms} atoms
1 atom types

{xlo} {xhi} xlo xhi
{ylo} {yhi} ylo yhi
{zlo} {zhi} zlo zhi

Masses

1 1.0

Atoms # full

{atoms}
"""


def _write_data(path, positions, lo=0.0, hi=10.0):
    atoms = "\n".join(
        f"{index + 1} 1 1 0.0 {x} {y} {z}"
        for index, (x, y, z) in enumerate(positions)
    )
    path.write_text(
        DATA.format(
            natoms=len(positions),
            xlo=lo,
            xhi=hi,
            ylo=lo,
            yhi=hi,
            zlo=lo,
            zhi=hi,
            atoms=atoms,
        ),
        encoding="utf-8",
    )


def _write_dump(path, frames, columns):
    blocks = []
    for index, (bounds, values) in enumerate(frames):
        (xlo, xhi), (ylo, yhi), (zlo, zhi) = bounds
        blocks.append(
            "ITEM: TIMESTEP\n"
            f"{index}\n"
            "ITEM: NUMBER OF ATOMS\n"
            f"{len(values)}\n"
            "ITEM: BOX BOUNDS pp pp pp\n"
            f"{xlo} {xhi}\n{ylo} {yhi}\n{zlo} {zhi}\n"
            f"ITEM: ATOMS id type {columns}\n"
            + "\n".join(
                f"{atom + 1} 1 " + " ".join(str(v) for v in row)
                for atom, row in enumerate(values)
            )
            + "\n"
        )
    path.write_text("".join(blocks), encoding="utf-8")


def _system(tmp_path, data, trajectory, analyses: str, frames="[0, 1]"):
    path = tmp_path / "system.yaml"
    path.write_text(
        f"""name: geometry-probe
topology: {data}
trajectory: {trajectory}
timestep_fs: 1.0
dump_every: 100
frames: {frames}
groups:
  all_atoms: "all"
analyses:
{analyses}
""",
        encoding="utf-8",
    )
    return path


def test_scaled_unscaled_equivalence_with_nonzero_box_origin(tmp_path):
    cases = {
        "x": ("x y z", [7.0, 7.0, 7.0]),
        "xu": ("xu yu zu", [7.0, 7.0, 7.0]),
        "xs": ("xs ys zs", [0.2, 0.2, 0.2]),
        "xsu": ("xsu ysu zsu", [0.2, 0.2, 0.2]),
    }
    data = tmp_path / "data.lmp"
    _write_data(data, [(7.0, 7.0, 7.0)], lo=5.0, hi=15.0)
    for name, (columns, values) in cases.items():
        trajectory = tmp_path / f"{name}.lammpstrj"
        _write_dump(
            trajectory,
            [(((5.0, 15.0), (5.0, 15.0), (5.0, 15.0)), [values])],
            columns,
        )
        config = _system(
            tmp_path, data.name, trajectory.name, "  - {name: msd, sel: [all_atoms]}\n"
        )
        cfg = read_system(config)
        in_box = load_universe(cfg, coordinates="in_box")
        in_box.trajectory[0]
        continuous = load_universe(cfg, coordinates="continuous")
        continuous.trajectory[0]
        assert np.allclose(in_box.atoms.positions[0], [2.0, 2.0, 2.0])
        assert np.allclose(continuous.atoms.positions[0], [7.0, 7.0, 7.0])


def test_selection_uses_frame_origin(tmp_path):
    data = tmp_path / "data.lmp"
    _write_data(data, [(7.0, 7.0, 7.0)], lo=5.0, hi=15.0)
    trajectory = tmp_path / "scaled.lammpstrj"
    _write_dump(
        trajectory,
        [(((5.0, 15.0), (5.0, 15.0), (5.0, 15.0)), [[0.2, 0.2, 0.2]])],
        "xs ys zs",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: msd, sel: [all_atoms]}\n",
    )
    cfg = read_system(config)
    universe = load_universe(cfg, coordinates="in_box")
    universe.trajectory[0]
    # 默认 view.origin=0，选择坐标应为实验室绝对坐标：q=2 + origin=5 = 7。
    selected = resolve_group(cfg, universe, "prop x > 6 and prop x < 8")
    assert selected.n_atoms == 1


def test_moving_box_origin_does_not_create_msd(tmp_path, capsys):
    data = tmp_path / "data.lmp"
    _write_data(data, [(5.0, 5.0, 5.0)], lo=0.0, hi=10.0)
    trajectory = tmp_path / "moving.lammpstrj"
    # _write_dump 的 bounds 参数需要三元组；上面的写法故意保持可读性，重写为实际帧。
    trajectory.write_text(
        "".join(
            f"ITEM: TIMESTEP\n{i}\nITEM: NUMBER OF ATOMS\n1\n"
            f"ITEM: BOX BOUNDS pp pp pp\n{lo} {lo + 10}\n0 10\n0 10\n"
            "ITEM: ATOMS id type xu yu zu\n1 1 5 5 5\n"
            for i, lo in enumerate((0.0, 1.0, 2.0))
        ),
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: msd, sel: [all_atoms], msd_type: x, fft: false}\n",
        frames="[0, 3]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(config), "--out", str(out)]) == 0
    table = pd.read_csv(out / "msd" / "tables" / "msd.csv")
    assert np.allclose(table["msd_A2"].to_numpy(), 0.0, atol=1e-9)


def test_nonperiodic_hbond_is_rejected(tmp_path, capsys):
    data = tmp_path / "data.lmp"
    _write_data(data, [(1.0, 5.0, 5.0), (0.1, 5.0, 5.0), (8.5, 5.0, 5.0)])
    trajectory = tmp_path / "ff.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
3
ITEM: BOX BOUNDS ff ff ff
0 10
0 10
0 10
ITEM: ATOMS id type x y z
1 1 1.0 5.0 5.0
2 1 0.1 5.0 5.0
3 1 8.5 5.0 5.0
""",
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: hbond, sel: [all_atoms, all_atoms, all_atoms]}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(config), "--out", str(out)]) == 3
    assert "三向周期" in capsys.readouterr().err
    assert not (out / "hbond").exists()


def test_velocity_rejects_triclinic_before_run(tmp_path, capsys):
    data = tmp_path / "data.lmp"
    _write_data(data, [(5.0, 5.0, 5.0)])
    trajectory = tmp_path / "tri.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
1
ITEM: BOX BOUNDS xy xz yz pp pp pp
0 10 2
0 10 1
0 10 1.5
ITEM: ATOMS id type x y z vx vy vz
1 1 5 5 5 0 0 0
""",
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: velocity, sel: [all_atoms, all_atoms]}\n",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(config), "--out", str(out)]) == 3
    assert "正交盒" in capsys.readouterr().err


def test_rdf_half_box_uses_whole_window(tmp_path, capsys):
    data = tmp_path / "data.lmp"
    _write_data(data, [(0.0, 5.0, 5.0), (2.0, 5.0, 5.0)])
    trajectory = tmp_path / "shrinking.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0 20
0 20
0 20
ITEM: ATOMS id type x y z
1 1 0 5 5
2 1 2 5 5
ITEM: TIMESTEP
1
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0 6
0 6
0 6
ITEM: ATOMS id type x y z
1 1 0 5 5
2 1 2 5 5
""",
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: rdf, sel: [all_atoms, all_atoms], range: [0.5, 4], nbins: 4}\n",
        frames="[0, 2]",
    )
    out = tmp_path / "out"
    code = cli.main(["run", "--system", str(config), "--out", str(out)])
    assert code in (3, 4)
    assert "半" in capsys.readouterr().err


def test_periodicity_change_is_rejected(tmp_path, capsys):
    data = tmp_path / "data.lmp"
    _write_data(data, [(1.0, 5.0, 5.0), (2.0, 5.0, 5.0)])
    trajectory = tmp_path / "mixed.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0 10
0 10
0 10
ITEM: ATOMS id type x y z
1 1 1 5 5
2 1 2 5 5
ITEM: TIMESTEP
1
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp ff
0 10
0 10
0 10
ITEM: ATOMS id type x y z
1 1 1 5 5
2 1 2 5 5
""",
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: hbond, sel: [all_atoms, all_atoms, all_atoms]}\n",
        frames="[0, 2]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(config), "--out", str(out)]) == 3
    assert "三向周期" in capsys.readouterr().err


def test_negative_box_origin_scaled_coordinate(tmp_path):
    data = tmp_path / "data.lmp"
    _write_data(data, [(-8.0, 7.0, 7.0)], lo=-15.0, hi=-5.0)
    trajectory = tmp_path / "negative.lammpstrj"
    _write_dump(
        trajectory,
        [(((-15.0, -5.0), (-15.0, -5.0), (-15.0, -5.0)), [[0.7, 0.7, 0.7]])],
        "xs ys zs",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: msd, sel: [all_atoms]}\n",
    )
    cfg = read_system(config)
    universe = load_universe(cfg, coordinates="in_box")
    universe.trajectory[0]
    assert np.allclose(universe.atoms.positions[0], [7.0, 7.0, 7.0])


def test_geometry_parser_keeps_triclinic_and_boundary_types(tmp_path):
    trajectory = tmp_path / "tri.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
1
ITEM: BOX BOUNDS xy xz yz pp pp pp
0 10 2
0 10 1
0 10 1.5
ITEM: ATOMS id type x y z
1 1 5 5 5
""",
        encoding="utf-8",
    )
    frame = read_geometry([trajectory]).frames[0]
    assert frame.boundary_types == ("pp", "pp", "pp")
    assert frame.pbc == (True, True, True)
    assert frame.pbc_known is True
    assert frame.orthorhombic is False
    assert frame.origin == (0.0, 0.0, 0.0)


def test_ppf_profile_analyses_do_not_wrap_z(tmp_path):
    data = tmp_path / "data.lmp"
    _write_data(data, [(1.0, 5.0, 2.0), (9.0, 5.0, 8.0)])
    trajectory = tmp_path / "ppf.lammpstrj"
    trajectory.write_text(
        """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp ff
0 10
0 10
0 10
ITEM: ATOMS id type x y z vx vy vz
1 1 1 5 2 1 0 0
2 2 9 5 8 2 0 0
ITEM: TIMESTEP
1
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp ff
0 10
0 10
0 10
ITEM: ATOMS id type x y z vx vy vz
1 1 2 5 2 1 0 0
2 2 1 5 8 2 0 0
""",
        encoding="utf-8",
    )
    config = _system(
        tmp_path,
        data.name,
        trajectory.name,
        "  - {name: lineardensity, sel: [all_atoms], dim: z, binsize: 1}\n"
        "  - {name: density, tag: xz, sel: [all_atoms], sum_axis: y, delta: 1}\n"
        "  - {name: velocity, sel: [all_atoms, all_atoms], dim: z, vdim: z, "
        "grouping: atoms, bin_width: 1}\n",
        frames="[0, 2]",
    )
    out = tmp_path / "out"
    assert cli.main(["run", "--system", str(config), "--out", str(out)]) == 0
    velocity = pd.read_csv(out / "velocity" / "tables" / "velocity.csv", encoding="utf-8-sig")
    assert list(velocity.columns) == ["z_angstrom", "vz_A_per_ps", "error_A_per_ps"]
    assert np.isfinite(velocity["vz_A_per_ps"]).sum() >= 2
