# mdanal

从 LAMMPS 轨迹直接得到科研图：用户声明“我要哪些图”，平台反推需要哪些计算；一个图包提供若干**图产品**，每个产品恰好产出一个 Panel。

![示例 MSD 图](docs/assets/quickstart-msd-en.png)

## 30 秒开始

```bash
pip install -r requirements.txt
pip install -e .                 # 可选；不装就运行 python main.py

python main.py check  --config example/figures.yaml
python main.py render --config example/figures.yaml --out /tmp/mdanal-demo --force
# 打开 /tmp/mdanal-demo/figures/ 下的 PNG

python main.py replot --from /tmp/mdanal-demo --out /tmp/mdanal-demo-replot
```

`example/figures.yaml` 用仓库自带的 tiny 数据，只用于跑通流程。

中文图需要系统安装 `Noto Serif CJK SC`；缺字体时 `render` 会直接报错，见 [排错](docs/troubleshooting.md#字体)。

## 核心模型

```text
sources（轨迹输入）
    ↓
figures[]（每项一张最终图，有自己的 ncols）
    ↓  每项若干 Panel
PanelRef（source + pack + product + select/compute/derive + plot）
    ↓
FigurePack（图包：compute + PRODUCTS）
    ↓
Panel（单个图，数据 + 画法）
```

- **Panel 是单个图**；一张 Figure 可以有多个 Panel，由 `layout.ncols` 排版。
- **产品**是命名图种；`density-2d` 是一个产品，`xy/xz/yz` 是它的 `plot.plane` 参数，不是三个产品。
- **compare** 只把同一曲线产品的多个来源合成一个 Panel；2D 密度用多个 Panel 并排。
- 表仍是缓存/重绘/compare 的边界，但不是用户入口。

## 输入示例

```yaml
schema_version: 1
name: tma-figures
render: {lang: zh, dpi: 300}

sources:
  A:
    topology: runs/A/data.lmp
    trajectory: runs/A/traj.lammpstrj
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 1040]
    groups:
      water: "type 11 12"

figures:
  - name: msd-A
    layout: {ncols: 2}
    panels:
      - source: A
        pack: msd
        product: msd-fit
        select: {group: water}
        compute: {msd_type: xyz}
        derive: {fit: {window_ns: [1.0, 4.0]}}

      - source: A
        pack: density
        product: density-2d
        select: {group: water}
        compute: {delta: 1.0}
        plot: {plane: xy}
```

完整字段见 [输入与配置](docs/configuration.md)。

## 命令

```text
mdanal render    --config figures.yaml --out OUT [--force]
mdanal check     --config figures.yaml
mdanal replot    --from OUT --out FIG [--figure NAME]
mdanal packs     [--json]
mdanal check-pack NAME
```

- `render` 读轨迹、计算、写 `OUT/data/` 与 `OUT/figures/`；
- `check` 只做静态校验：图包/产品/槽位/参数/derive 是否齐全；
- `replot` 只读 `OUT/figures/*.json` + 表，不读轨迹；
- `packs --json` 是给 AI/脚本看的图包能力清单。

## 内置图包

| 包 | 产品 | 说明 |
|---|---|---|
| `density` | `density-2d`, `density-line` | 3D 数密度投影 + 质量/电荷线密度 |
| `hbond` | `hbond-count`, `hbond-type`, `hbond-lifetime` | 一次 HBA，三个产品 |
| `msd` | `msd-raw`, `msd-fit`, `msd-rdc` | 原始 MSD、拟合、RDC |
| `rdf` | `rdf` | 径向分布 |
| `velocity` | `velocity` | 速度剖面 |

每个包有 `note.md`（科学说明）和 `pack.json`（机器能力）。加图包见 [插件手册](docs/plugins.md)。

## 目录

```text
src/mdanal/analyses/<pack>/   # 图包
src/mdanal/figure/            # 配置、planner、组合、重绘
src/mdanal/plot/              # Panel/Figure/chart 基础设施
example/figures.yaml          # 可运行示例
docs/                         # 手册
```

## 重要边界

- 一次 `render` 可以包含多个 source；同一 `(source, pack, select, compute, derive, section)` 只计算一次。
- `density` 3D 网格一次计算，三个投影都保存；切换 `plot.plane` 不重算。
- 变盒时 density/line 只使用首帧并警告；MSD 连续视图要求相邻帧位移小于半盒。
- `hbond` 的 type 产品需要 source 配置 `naming`。

## AI 入口

`llms.txt` 是给 AI 的最小上下文；机器可读能力用 `mdanal packs --json`。

## 开发

```bash
python -m pytest
python -m pytest tests/analyses tests/figure
```
