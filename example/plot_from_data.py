"""公共绘图层示例：不读轨迹、不需要 system.yaml，直接用自己的数据出图。

    python example/plot_from_data.py [输出.png]
"""

import sys
from pathlib import Path

# 从干净检出直接运行：优先使用仓库内的 src/，避免被其他 mdanal 安装遮蔽
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mdanal import chart  # noqa: E402

x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
y = [0.0, 0.84, 1.00, 0.35, 0.06, 0.0]

fig, ax = chart.figure("single")
chart.line(ax, x, y, color=chart.COLORS["primary"])
chart.refline(ax, 1.0)
chart.note(ax, "from arrays")
ax.set_xlabel("z (Å)")
ax.set_ylabel("g(r)")

out = sys.argv[1] if len(sys.argv) > 1 else "plot_from_data.png"
print(chart.save(fig, out, dpi=150))
