# mdanal

分子动力学轨迹的命令行分析工具。读取体系目录下的 `system.yaml`，调用 MDAnalysis 完成指定的分析，输出数据表与图件。

## 特性

- 八种内置分析：密度投影、线密度、径向分布、氢键数量、氢键类型分布、氢键寿命、均方位移、流速剖面
- 一次运行处理一个体系，可同时执行多条分析
- 每个分析独立输出目录，互不覆盖
- 输出可复现：相同输入得到逐字节一致的结果
- 图为静态 PNG，分辨率可调
- 图内标注：竖线、参考线、区间阴影、文字，写在 `system.yaml` 里
- 公共绘图层 `mdanal.chart`：不读轨迹，直接用自己的数据出图
- 多体系对比：读已有输出叠图，按盒对齐或锚点对齐

## 环境要求

- Python 3.10 及以上
- MDAnalysis 2.8+、NumPy、pandas、Matplotlib、PyYAML、SciencePlots
- MAICoS 0.12+（仅流速剖面需要）

## 安装

```bash
pip install -r requirements.txt
pip install -e .        # 可选，安装后提供 mdanal 命令
```

不安装也可直接运行：`python main.py <命令>`。

## 用法

```bash
mdanal list                                    # 列出可用分析
mdanal list --system DIR                       # 列出体系的分组与将要执行的分析
mdanal check --system DIR                      # 校验配置与依赖，不计算
mdanal run --system DIR --out OUT              # 执行分析
```

| 选项 | 说明 | 默认 |
|---|---|---|
| `--system DIR` | 体系目录，或 `system.yaml` 路径 | 必填 |
| `--out DIR` | 输出目录 | 必填 |
| `--lang zh\|en` | 图内文字语言 | `zh` |
| `--dpi N` | 图片分辨率 | 300 |
| `--annotate` | 在图内标注帧窗口与参数 | 关闭 |
| `--force` | 清空并重写已存在的输出目录（仅限本程序的输出） | 关闭 |
| `--no-memory` | 不把轨迹读入内存，按需读盘 | 关闭（默认按收益自动决定） |

源码运行时把 `mdanal` 换成 `python main.py`。

## 自己画图

`mdanal.chart` 是公共绘图层：程序内出图与你自己出图走同一套样式与语汇，不需要体系目录。

```python
from mdanal import chart

fig, ax = chart.figure("single")          # single / wide / map，或 (宽, 高)
chart.line(ax, x, y, label="5 ns")        # 也可 line/bars/heatmap/refline/vline/span/note
ax.set_xlabel("z (Å)")
chart.save(fig, "profile.png", dpi=300)
```

完整示例见 `example/plot_from_data.py`。


## 多体系对比

把多个体系的同类一维结果叠在一张图上；只读已有输出（表 + 溯源），不重读轨迹。

```yaml
# compare.yaml
items:
  - {root: runs/test5/out, label: 5 ns}
  - {root: runs/test075/out, label: 75%, anchor: {z: 22.0}, t_offset: 5.0}
figure:
  analysis: lineardensity     # 各运行里的分析目录名
  align: center               # left / center / {z: 22.0}
  xlim: [-20, 20]
out: compare
```

```bash
mdanal compare --config compare.yaml [--out DIR]
```

- 只叠一维曲线（`lineardensity`、`velocity`、`rdf`、`msd`、`hbond`、`hbond_lifetime`）；
  二维密度图没法叠在一张等值图上，各自出图；
- 横轴是盒坐标的分析参与对齐：`left`（盒下角 → 0）、`center`（盒心 → 0，默认）、
  或直接写数值当锚点；每个体系可用 `anchor` 单独覆盖；
- 缺省横轴范围取各体系该轴平移后的并集；`t_offset` 用来平移时间轴的零点；
- 输出：一张 PNG、合并后的对齐表 `tables/<表名>.csv`、`provenance.json`（每个体系的平移量）。

## 配置

体系目录下必须有 `system.yaml`，缺失时程序直接退出。

```yaml
name: example
topology: data.lmp
trajectory: run.lammpstrj
timestep_fs: 1.0
dump_every: 10000
frames: [400, 500]

view:
  origin: [0, 0, 23.47]     # 可选：视图坐标的零点
  window:
    z: [17.0, 30.0]         # 可选：图件的坐标轴范围

groups:
  water_o: "type 17"
  water_h: "type 18"
  walls:   "resid 1 or resid 90"

analyses:
  - name: density
    tag: xz
    sel: [water_o]
    sum_axis: y
  - name: hbond
    sel: [water_o, water_h, water_o]
```

| 字段 | 说明 |
|---|---|
| `name` | 体系名，用于日志与溯源；省略时取目录名 |
| `topology` / `trajectory` | 拓扑与轨迹文件；`trajectory` 可写列表（多段合并）；省略时在文件所在目录内唯一查找 |
| `timestep_fs` | 时间步长（fs） |
| `dump_every` | 输出间隔（步） |
| `frames` | 帧窗口，左闭右开；省略时使用全部帧 |
| `view` | 视图坐标零点与图件显示窗口；省略时坐标与 `data.lmp` 一致 |
| `naming` | 给残基与原子补名字与元素；省略时只能用类型编号选择 |
| `groups` | 具名原子选择，供 `sel` 引用 |
| `analyses` | 要执行的分析列表 |

`analyses` 每条只有 `name` 必填；`sel` 的长度须等于该分析的选择数；其余键覆盖 `analyses.yaml` 中的默认参数。`tag` 用于区分同一种分析的多次输出。

### 图内标注（可选）

每条分析可以带 `annotate`，标注**属于这一条分析**，`axis` 必填——`density-xz` 的横轴是 x、
`lineardensity` 的横轴是 z，同一个位置在两处含义不同：

```yaml
  - name: lineardensity
    sel: [water_o]
    dim: z
    annotate:
      - {kind: vline, axis: z, at: 22.0, text: 界面}
      - {kind: span,  axis: z, at: [17.0, 29.0], text: 缝内}
      - {kind: hline, at: 0.5, text: 参考}
      - {kind: text,  at: [5.0, 0.8], text: bulk}
```

`vline` / `span` 只在该图横轴等于所写 `axis` 时生效，其余情况跳过；`hline` / `text` 按图的数值坐标放置。

### 坐标与视图

数据表用**盒坐标**（`0 … L`，与呈现无关）；选择串与图件用**视图坐标**（盒坐标加视图偏移）。

- 默认与 `data.lmp` 一致；写 `view.origin: [x, y, z]` 后以该点为零点，写 `view.origin: box_corner` 后以盒下角为零点（坐标范围 `0 … L`）。
- 改 `origin` 后，`prop` 选择串里的坐标区间要同步改；**数据表不变**，改图不必重跑分析。
- 需要平移后的数值时加 `--aligned`，程序会另写一份 `*.aligned.csv`；正表仍是盒坐标。
- `view.window` 只裁剪图件的坐标轴范围，不改数据表；某个轴没写就不裁。
- 轨迹为包裹坐标时，`msd` 会用 `NoJump` 重建连续性并给出提示。
- 程序内部按盒坐标（`0 … L`）计算，视图偏移只影响选择串的求值与出图。

### 多段轨迹（续跑）

`trajectory` 可以写列表，按顺序拼成一条轨迹：

```yaml
trajectory: [run.lammpstrj, run.step2.lammpstrj]
```

- 帧号与时间轴按合并后的整体计算（`t = 帧序号 × dump_every × timestep_fs`）；
- dump 里的 TIMESTEP 列不参与时间换算——续跑常把它重置为 0；
- 各段的坐标列必须一致（`x y z` 或 `xu yu zu`），不一致直接报错；
- 接缝处的时间倒退、盒下角变化会写进 `provenance.json` 并作为提示打印；
- 段与段之间若重复写了一帧，程序**不会**自动去重，请在生成轨迹时裁掉。

### 命名（可选）

LAMMPS 写出的 `data.lmp` 只带类型编号。给它补上分子名与原子名后，就能用 `resname`、`name` 写选择串：

```yaml
naming:
  from_data: ../balance/data.lmp   # 读初始 data 里 Atoms 段的 "# 原子名 分子名"
  residues:                         # 也可按类型覆盖分子名
    - {name: WAT, types: [17, 18]}
  atoms:                            # 也可按类型覆盖原子名
    "17": OW
```

- 两条来源可同时写：`from_data` 先填，规则后覆盖，覆盖会记一条警告；
- 覆盖之后必须完整（每个残基有分子名、每个原子有原子名），否则报错；
- 元素按质量推断，`C1` 与 `Cl1` 不会混淆；
- 名字不能与选择串关键字冲突（如 `water`），否则报错；
- 只影响名字与标签，`types`／`resids` 不变，结果数值不受影响。

### 按空间区域分组

用 MDAnalysis 原生的 `prop` 按坐标筛选：

```yaml
groups:
  slit_water: "type 17 18 and prop z > 17.58 and prop z < 29.37"
  outer_water: "type 17 18 and not (prop z > 17.58 and prop z < 29.37)"
```

- 坐标为视图坐标，默认与 `data.lmp` 及输出图表一致。
- 支持 `<`、`>`、`<=`、`>=`、`==`、`!=`，可加 `abs`，如 `prop abs z < 5`。
- 选择是静态的：在帧窗口首帧求值一次，之后不再逐帧重选。
- `and` / `or` **从左到右求值、没有优先级**，混用必须加括号：`(A and B) or (C and D)`。

完整示例见 `example/system.yaml`。

## 内置分析

| 分析 | `sel` 顺序 | 主要参数 | 输出 |
|---|---|---|---|
| `density` | group | `delta`、`sum_axis` | 密度投影表与图 |
| `lineardensity` | group | `binsize`、`dim` | 三个轴的线密度表，指定轴的图 |
| `rdf` | a, b | `range`、`nbins` | g(r) 表与图 |
| `hbond` | donor, hydrogen, acceptor | `d_a_cutoff`、`d_h_a_angle_cutoff` | 每帧计数、汇总、占有率，计数图 |
| `hbond_type` | donor, hydrogen, acceptor | 同上、`figure_axis`（`rate`/`total`）；需先配置 `naming` | 按分子-元素分类的类型表，一张条形图 |
| `hbond_lifetime` | donor, hydrogen, acceptor | 同上、`tau_max_ps`、`intermittency`、`window_step` | 存活曲线表、寿命汇总表、双曲线图 |
| `msd` | group | `msd_type`、`fft` | MSD 表与图 |
| `velocity` | group, ref | `dim`、`vdim`（写 `x`/`y`/`z`）、`bin_width`、`grouping` | 速度剖面表与图 |

`mdanal list` 显示各分析的选择数与默认参数。

### 输出单位

各列单位以调用到的库的文档为准；代码里每处取数都标了单位。

| 输出 | 单位 | 来源 |
|---|---|---|
| 坐标列（`x (Å)`、`r (Å)`、`滞后 (ps)` 等） | Å / ps | MDAnalysis、MAICoS |
| 质量密度 | g·cm⁻³ | 由 amu/Å³ 换算（1 amu = 1/N_A g） |
| 电荷密度 | **e·mol·cm⁻³** | MDAnalysis `LinearDensity` 文档口径，**不是 e·Å⁻³** |
| 密度投影的「数密度」 | Å⁻³ | MDAnalysis `DensityAnalysis` 网格 |
| `g(r)` | 无量纲 | `InterRDF` |
| `MSD (Å^2)` / `Δt (ps)` | Å² / ps | `EinsteinMSD` |
| 氢键数 / 次数 / 出现帧数 | 个 | `HydrogenBondAnalysis` |
| 氢键寿命、滞后 | ps | 库给出以帧为单位的 τ，乘帧间隔得到 ps |
| `v (Å/ps)` / 误差 | Å·ps⁻¹ | MAICoS `VelocityPlanar`，误差列是标准误 |

`density` 需要盒内坐标，`msd` 需要连续坐标，其余分析对两者都不敏感；程序按需选视图，`system.yaml` 无需声明。`velocity` 的剖面零点为参考组质心，表中的坐标已加回该质心，与其他分析同框架。

## 输出

```
OUT/
├── density-xz/
│   ├── tables/density_xz.csv
│   └── figures/density_xz.png
├── hbond/
│   ├── tables/hbond_count.csv
│   ├── tables/hbond_summary.csv
│   ├── tables/hbond_occupancy.csv
│   └── figures/hbond_count.png
├── manifest.csv
└── provenance.json
```

`manifest.csv` 列出本次执行的分析、选择、原子数与参数；`provenance.json` 记录输入文件校验和、帧窗口、输入坐标状态、视图设置、选择求值帧、实际参数、每条分析的提示与库版本。

## 新增分析

1. 在 `src/mdanal/analyses.yaml` 中添加定义：

```yaml
interaction:
  slots: [a, b]
  params: {cutoff: 12.0}
  requires: []
  package: null
  labels:
    zh: {x: 时间 (ps), y: 能量 (kJ/mol), title: 相互作用能}
    en: {x: time (ps), y: energy (kJ/mol), title: Interaction energy}
```

2. 在 `src/mdanal/analyses/` 中创建同名模块：

```python
def run(ctx):
    """返回 {表名: pandas.DataFrame}"""

def figures(ctx, tables):
    """返回 [(图名, matplotlib Figure)]，可省略"""
```

`ctx` 提供 `groups`、`start`、`stop`、`params`、`view`、`selection_frame`、`window()`、`warn()`、`label()`、`size()`、`universe`。

## 测试

```bash
python -m pytest tests -q
```

测试跑在 `tests/fixtures/tiny`——真实 LAMMPS 输出的 20 帧截取（24 个 TMA、504 原子），
不需要外部算例，也不需要设置环境变量。

## 限制

- 一次只处理一个体系
- `rdf` 只输出 g(r)，不计算配位数
- `hbond` 只输出每帧计数与整个帧窗口的占有率，不保留逐帧明细
- `msd` 只输出曲线，不拟合扩散系数
