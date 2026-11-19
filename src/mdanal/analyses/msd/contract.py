"""MSD 的静态契约。"""

SLOTS = ("group",)

PARAMS = {
    "msd_type": {
        "type": str,
        "default": "xyz",
        "choices": ("xyz", "xy", "xz", "yz", "x", "y", "z"),
        "help": "MSD 的维度组合",
    },
    "grouping": {
        "type": str,
        "default": "residues",
        "choices": ("residues", "atoms"),
        "help": "residues 按残基/分子质心；atoms 为原子 MSD",
    },
    "fft": {
        "type": bool,
        "default": True,
        "help": "用 FFT 自相关计算 MSD；false 时用直接时间平均",
    },
}

LABELS = {
    "zh": {
        "title": "均方位移",
        "x": r"$\Delta t$ (ns)",
        "y": "MSD (Å$^{2}$)",
        "fit": "线性拟合",
        "d": "D",
        "rdc": "运行扩散系数",
        "rdc_y": r"$D$ (Å$^{2}$ ps$^{-1}$)",
    },
    "en": {
        "title": "Mean squared displacement",
        "x": r"$\Delta t$ (ns)",
        "y": "MSD (Å$^{2}$)",
        "fit": "linear fit",
        "d": "D",
        "rdc": "Running diffusion coefficient",
        "rdc_y": r"$D$ (Å$^{2}$ ps$^{-1}$)",
    },
}

COLUMN_LABELS = {
    "zh": {"dt_ns": r"$\Delta t$ (ns)", "msd_A2": "MSD (Å$^{2}$)"},
    "en": {"dt_ns": r"$\Delta t$ (ns)", "msd_A2": "MSD (Å$^{2}$)"},
}

COORDINATES = "continuous"
