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
- MDAnalysis 2.10+、NumPy、pandas、Matplotlib、PyYAML、SciencePlots、tidynamics（MSD 的 FFT 路径）

## 安装

```bash
pip install -r requirements.txt
pip install -e .        # 可选，安装后提供 mdanal 命令
```

不安装也可直接运行：`python main.py <命令>`。

## 用法

```bash
mdanal list                                    # 列出可用分析
mdanal list density                            # 查看某个分析的输入契约（参数/单位/默认值）
mdanal list --system DIR                       # 列出体系的分组与将要执行的分析
mdanal check --system DIR                      # 校验配置与依赖，不计算
mdanal run --system DIR --out OUT              # 执行分析
mdanal replot --from OUT --out FIGURES        # 从已有结果重绘，不读轨迹
mdanal check-analysis                          # 检查已安装分析的声明是否完整
mdanal check-analysis --system DIR             # 再按该体系实跑中英各一遍并检查出图
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

## 从已有结果重绘

`run` 会在每条分析目录下保存 `plot.json`（绘图快照，含表哈希、参数、标签、窗口、标注与呈现默认值）。
`replot` 只读快照和 CSV，不加载轨迹、不重新计算：

```bash
mdanal replot --from OUT --out FIGURES
mdanal replot --from OUT --out FIGURES_EN --analysis msd --analysis rdf --lang en --format svg
mdanal replot --from OUT --out FIGURES_CUSTOM --config plot.yaml
```

- `--from` 是 `run` 的结果根目录；`--out` 必须是独立目录，不能与源目录重叠；
- 非空输出默认拒绝，只有带 `replot.json` 的旧重绘目录才可用 `--force` 更新；
- 表哈希不一致、快照缺失/版本不支持、插件无法导入时明确失败；插件源码变化只警告；
- `plot.yaml` 支持 `defaults` 和按分析目录的 `plot`/`annotate` 覆盖，优先级为
  快照默认 < 配置 defaults < 单分析配置 < CLI；
- 初始 `run` 出图也读刚写出的 CSV，和 `replot` 共用同一渲染路径。

最小 `plot.yaml`：

```yaml
schema_version: 1
defaults:
  lang: zh
  dpi: 300
  format: png
  plot:
    rc:
      font.size: 9
analyses:
  msd:
    plot:
      xlim: [0, 80]
      title: {zh: 均方位移, en: Mean squared displacement}
    annotate:
      - {kind: vline, axis: horizontal, at: 10,
         text: {zh: 参考时间, en: Reference time}}
```

完整可运行示例见 `example/plot.yaml`。

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
mdanal compare --config compare.yaml [--out DIR] [--lang zh|en] [--force]
```

- 只叠一维曲线（`lineardensity`、`velocity`、`rdf`、`msd`、`hbond`、`hbond_lifetime`）；
  二维密度图没法叠在一张等值图上，各自出图；
- 横轴是盒坐标的分析参与对齐：`left`（盒下角 → 0）、`center`（盒心 → 0，默认）、
  或直接写数值当锚点；每个体系可用 `anchor` 单独覆盖；
- 缺省横轴范围取各体系该轴平移后的并集；`t_offset` 只用于时间轴（列名以 `_ps` 结尾且非盒坐标轴），
  用在空间轴上会直接报错；
- 多列结果（如氢键寿命的连续/间歇）按体系分色、按列分线型，图例写成「体系 · 列名」；
- 轴标签取该分析 `COLUMN_LABELS` 里的中英文案，可用 `figure.xlabel/ylabel` 覆盖；`--lang` 切换语言；
- 输出目录不能等于或位于任一输入结果目录内；已存在的非空输出默认拒绝，需 `--force`；
- 输出：一张 PNG、合并后的对齐表 `tables/<表名>.csv`、`provenance.json`（每个体系的平移量与所用语言）。

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
  origin: [0, 0, 23.47]     # 可选：视图坐标的零点（图件窗口属于分析级，见下）

groups:
  water_o: "type 17"
  water_h: "type 18"
  walls:   "resid 1 or resid 90"

analyses:
  - name: density
    tag: xz
    sel: [water_o]
    sum_axis: y
    plot:
      window: {x: [17.0, 30.0]}   # 可选：只裁这张图的坐标轴
  - name: hbond
    sel: [water_o, water_h, water_o]
    section: [50, 100]            # 可选：在体系帧窗口内再切一段（相对偏移）
```

| 字段 | 说明 |
|---|---|
| `name` | 体系名，用于日志与溯源；省略时取目录名 |
| `topology` / `trajectory` | 拓扑与轨迹文件；`trajectory` 可写列表（多段合并）；省略时在文件所在目录内唯一查找 |
| `timestep_fs` | 时间步长（fs） |
| `dump_every` | 输出间隔（步） |
| `frames` | 帧窗口，左闭右开；省略时使用全部帧 |
| `view` | 视图坐标零点；省略时坐标与 `data.lmp` 一致 |
| `naming` | 给残基与原子补名字与元素；省略时只能用类型编号选择 |
| `groups` | 具名原子选择，供 `sel` 引用 |
| `analyses` | 要执行的分析列表 |

`analyses` 每条只有 `name` 必填；`sel` 的长度须等于该分析声明的槽位数；其余键覆盖该分析模块 `PARAMS` 里的默认参数（用 `mdanal list <name>` 查看）。`tag` 用于区分同一种分析的多次输出。

两个额外键：

- `section: [起, 止]`：在体系帧窗口内再切一段（相对偏移），只影响该分析；分组仍在体系窗口首帧解析一次。
- `plot:`：图件选项，支持 `window`、`size`（英寸）、`xlim`/`ylim`、`title`/`xlabel`/`ylabel`（字符串或 `{zh, en}`）与 `rc`；只改呈现，不改数据表。

### 图内标注（可选）

每条分析可以带 `annotate`，标注**属于这一条分析**。`axis` 写 `horizontal`/`vertical` 时
使用这张图的横轴/纵轴数据坐标（时间、r 等）；写 `x`/`y`/`z` 时保留旧的物理盒轴语义，
只有该物理轴正好是本图横轴时才画，否则 `warn` 并跳过：

```yaml
  - name: lineardensity
    sel: [water_o]
    dim: z
    annotate:
      - {kind: vline, axis: z, at: 22.0, text: 界面}
      - {kind: span,  axis: z, at: [17.0, 29.0], text: 缝内}
      - {kind: hline, at: 0.5, text: 参考}
      - {kind: vline, axis: horizontal, at: 10, text: {zh: 参考时间, en: Reference}}
      - {kind: span,  axis: vertical, at: [0, 2], text: 置信带}
      - {kind: text,  at: [5.0, 0.8], text: bulk}
```

`text` 支持字符串或 `{zh, en}`；`vline+vertical` 等矛盾组合会报错；纵向区间文字用纵轴 transform。

| kind | axis | at | 说明 |
|---|---|---|---|
| `vline` | `horizontal` / `x` / `y` / `z` | 数值 | 竖线；`horizontal` 用图横轴数据坐标 |
| `hline` | 省略或 `vertical` | 数值 | 横线；用图纵轴数据坐标 |
| `span` | `horizontal` / `vertical` / `x` / `y` / `z` | `[起, 止]` | 阴影区间 |
| `text` | 省略 | `[横轴, 纵轴]` | 文字，数据坐标 |

**标注是用户自己写的，不是程序自动识别的界面。** 程序不会根据密度剖面自动判断“界面在哪里”；
`vline` 的 `at` 和 `span` 的 `at` 都由你给出。`--annotate` 是另一件事：它只在图角上加帧窗口/参数说明，
和 `annotate` 列表互不影响。

**标注样式边界（v1）：** 标注颜色、字号、线宽目前是固定的——竖线/横线用灰色 `0.45`、字号 6、线宽 0.8；
区间用主色 `#4165c0`、透明度 0.12。`plot.rc` 的 `font.size` 不会覆盖这些显式样式。要统一改标注样式，
编辑 `src/mdanal/plot/annotations.py`；要逐条改颜色/字号，暂时需要自己读 CSV 用 Matplotlib 画
（见 `example/plot_from_data.py`）。标题、轴标签、普通文字字号可以用 `plot.rc` 或 `plot.title/xlabel/ylabel`。

### 坐标与视图

数据表用**盒坐标**（`0 … L`，与呈现无关）；选择串与图件用**视图坐标**（盒坐标加视图偏移）。

- 默认与 `data.lmp` 一致；写 `view.origin: [x, y, z]` 后以该点为零点，写 `view.origin: box_corner` 后以盒下角为零点（坐标范围 `0 … L`）。
- 改 `origin` 后，`prop` 选择串里的坐标区间要同步改；**数据表不变**，改图不必重跑分析。
- 需要平移后的数值时加 `--aligned`，程序会另写一份 `*.aligned.csv`；正表仍是盒坐标。
- 图件窗口写在每条分析的 `plot.window` 里（如 `plot: {window: {z: [17.0, 30.0]}}`），只裁坐标轴、不改数据表；体系级不再有窗口。
- `density` 与 `lineardensity` 只在**固定盒子**窗口上做多帧平均；检测到盒子变化时
  只使用窗口首帧并在 `provenance.json` 的 warnings 里提示。要显式只算一帧，用
  `section: [i, i+1]`；要平均，请把窗口裁到盒子不变的一段。
- 轨迹为包裹坐标时，连续位移由连续视图包装器逐帧按最小镜像展开；每帧位移应小于半个盒长，
  否则结果可能失真。回退或跳到未处理的帧会从第 0 帧重放，section/重复分析/多段都一致。
  优先输出 `xu/yu/zu`；只有包裹坐标也能用，但采样必须足够密。
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

`mdanal list` 显示各分析的选择数与默认参数；`mdanal list <name>` 打印完整契约（类型、单位、默认值、取值范围与说明）。

氢键口径：

- `per_donor_atom` = 平均氢键数 / 供体原子数；`per_donor_residue` = 平均氢键数 / 供体残基数；
  不再输出含义含糊的"每分子平均"；
- `tau_1e_ps` 是存活曲线 C(τ) 首次降到 1/e 的交叉时间（线性插值），不是指数拟合寿命；
- `hbond_lifetime` 按 **H–受体对** 识别同一个氢键，`hbond_occupancy` 按 **供体–氢–受体三元组**；
  两者身份定义不同，比较时需注意。

### 输出单位

各列单位以调用到的库的文档为准；代码里每处取数都标了单位。

| 输出 | 单位 | 来源 |
|---|---|---|
| 坐标列（`x (Å)`、`r (Å)`、`滞后 (ps)` 等） | Å / ps | MDAnalysis |
| 质量密度 | g·cm⁻³ | 由 amu/Å³ 换算（1 amu = 1/N_A g） |
| `charge_density_e_A3` | e·Å⁻³ | 自实现直方图（电荷 / bin 体积） |
| `number_density_A3` | Å⁻³ | 自实现三维直方图（坐标按盒折回） |
| `g_r` | 无量纲 | `InterRDF` |
| `msd_A2` / `dt_ps` | Å² / ps | `EinsteinMSD` |
| `hbond_count` / `count` / `frames_present` | 个 | `HydrogenBondAnalysis` |
| `tau_1e_ps` / `lag_ps` | ps | 库给出以帧为单位的 τ，乘帧间隔得到 ps；τ 为 1/e 交叉 |
| `v*_A_per_ps` / `error_A_per_ps` | Å·ps⁻¹ | 按盒坐标逐帧分箱，误差列是逐帧均值的标准误 |

`density` 需要盒内坐标，`msd` 需要连续坐标，其余分析对两者都不敏感；程序按需选视图，`system.yaml` 无需声明。
坐标约定由加载层显式指定：同时存在 `x` 与 `xu` 时，盒内分析读 `x`、连续位移读 `xu`；
`xs`/`xsu` 也能识别。时间轴统一为"全局帧号 × 帧间隔"，不跟随 LAMMPS 的 TIMESTEP 重置。`velocity` 直接按原盒坐标分箱（不把参考组平移到盒心），速度是实验室系速度；参考组只记入
`provenance.json`。盒子变化时按首帧参考盒坐标平均并给出警告。

### 表头（机器名）

表头是稳定的机器名（ASCII、不随 `--lang` 变），`--lang` 只影响图内文字。`*_angstrom` 是盒坐标列，
`--aligned` 副本会对它们施加视图平移。

| 分析 | 列 | 含义 | 单位 |
|---|---|---|---|
| `density` | `x_angstrom` / `y_angstrom` | 投影平面坐标 | Å |
| | `number_density_A3` | 沿求和轴平均的数密度 | Å⁻³ |
| `lineardensity` | `{x,y,z}_angstrom` | 轴坐标 | Å |
| | `mass_density_g_cm3` | 质量密度 | g cm⁻³ |
| | `charge_density_e_A3` | 电荷密度 | e Å⁻³ |
| `rdf` | `r_angstrom` / `g_r` | 距离 / 径向分布函数 | Å / — |
| `hbond` | `frame` / `time_ps` / `hbond_count` | 帧号 / 时间 / 氢键数 | — / ps / 个 |
| | `donor` / `hydrogen` / `acceptor` / `frames_present` / `occupancy` | 占有率表 | — / 个 / — |
| | `n_frames` / `mean_hbonds` / `std_hbonds` / `per_donor_atom` / `per_donor_residue` | 汇总（按供体原子/残基归一化） | — |
| `hbond_type` | `donor` / `acceptor` / `count` / `per_frame` / `share` | 类型统计 | — |
| `hbond_lifetime` | `lag_ps` / `continuous` / `intermittent` | 滞后与存活概率 | ps / — |
| | `criterion` / `tau_1e_ps` / `tolerance_frames` / `note` | 寿命汇总（1/e 交叉时间） | — / ps / 帧 |
| `msd` | `dt_ps` / `msd_A2` | 滞后 / 均方位移 | ps / Å² |
| `velocity` | `{x,y,z}_angstrom` | 剖面坐标 | Å |
| | `v{x,y,z}_A_per_ps` / `error_A_per_ps` | 速度 / 标准误 | Å ps⁻¹ |

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

分析是插件：**一个文件就是一个分析**，放进 `src/mdanal/analyses/` 即被发现，不需要改注册表。
文件名就是分析名。

```python
"""示例：两组原子间的距离统计。"""

from ..plot import annotations, chart

SLOTS = ("a", "b")                      # 必填：选择槽位，顺序与 sel 对应
PARAMS = {}                              # 必填：可为空映射；无参数分析不要虚构参数
# 有参数时：
# PARAMS = {
#     "cutoff": {"type": float, "default": 12.0, "unit": "Å", "min": 0.0},
#     "nbins": {"type": int, "default": 50, "min": 2},
# }
LABELS = {                              # 必填：图内文字，中英各一份
    "zh": {"title": "距离分布", "x": "$r$ (Å)", "y": "计数"},
    "en": {"title": "Distance distribution", "x": "$r$ (Å)", "y": "count"},
}

COORDINATES = "any"                     # 可选：in_box / continuous / any
REQUIRES = ()                           # 可选：("velocities",)
PACKAGE = None                          # 可选：{"name": "package-name", "min_version": "1.0"}
COMPARE = None                          # 可选：{"table": ..., "x": ..., "y": [...], "box_axis": bool}
MUTATES_POSITIONS = False               # 可选：分析会就地改坐标


def run(ctx):
    """返回 {表名: pandas.DataFrame}。"""


def figures(ctx, tables):
    """可选：返回 [(图名, matplotlib Figure)]；核心负责保存。

    ctx 是 PlotContext：只有表、快照信息与呈现设置，没有 universe/原子组。
    """


def meta(ctx, tables):
    """可选：返回 dict，写进 provenance。"""
```

`run(ctx)` / `meta(ctx, tables)` 的 `ctx` 是 RunContext，提供 `groups`、`universe`、`view`、
`start/stop`、`selection_frame`、`params`、`window(axis)`、`warn()` 等；`figures(plot_ctx, tables)`
的 `ctx` 是 PlotContext，只提供 `params`、`meta`、`extras`、`start/stop`、`frame_dt_ps`、`shift`、
`lang`、`annotations`、`label()`、`size()`、`window(axis)`、`annotation()`、`warn()`，**没有** Universe。
图件窗口用 `ctx.window(axis)`；切片后的帧窗口由 `ctx.start/stop` 给出。可复制的空参数模板见
`example/analysis_template.py`。

**分析之间不互相 import，也不共享辅助函数**；需要复用就各自写一份。`mdanal list <name>`
可检查契约，`mdanal check-analysis <name>` 会做静态校验，加 `--system DIR` 时还会实跑一遍。

## 目录结构

```
src/mdanal/
├── cli.py            命令行入口
├── errors.py         共用异常
├── config/           配置与发现（system、registry、naming、check、defaults/labels.yaml）
├── run/              执行（context、runner、writers）
├── plot/             绘图（context、snapshot、render、replot、settings、chart、annotations）
├── compare/          多体系对比
└── analyses/         分析插件：一个文件一个分析
```

## 测试

测试分三层，默认只跑前两层（`testpaths` 已配置）：

```bash
python -m pytest                 # 框架（假分析）+ 内置插件烟测
python -m pytest tests/analyses  # 科学断言（密度守恒、氢键计数、RDF、MSD、速度剖面）
```

- `tests/framework/`：用 `tests/fake_analysis.py` 跑通配置、注册、执行、落盘与绘图层，
  不依赖任何真实分析；
- `tests/smoke/`：内置插件的健康检查——可发现、可导入、声明有效、中英端到端出图，
  只验证"插件还活着"，不断言数值；
- `tests/analyses/`：真实分析的科学断言，标了 `analysis` marker，默认不跑。

测试跑在 `tests/fixtures/tiny`——真实 LAMMPS 输出的 20 帧截取（24 个 TMA、504 原子），
不需要外部算例，也不需要设置环境变量。

## 限制

- 一次只处理一个体系
- `rdf` 只输出 g(r)，不计算配位数
- `hbond` 只输出每帧计数与整个帧窗口的占有率，不保留逐帧明细
- `msd` 只输出曲线，不拟合扩散系数
