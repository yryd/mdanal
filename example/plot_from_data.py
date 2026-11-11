"""公共绘图层示例：不读轨迹、不需要 system.yaml，直接用自己的数据出图。

    pip install -e .                                  # 或 PYTHONPATH=src
    python example/plot_from_data.py [输出.png]
"""

import sys

from mdanal import chart

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
