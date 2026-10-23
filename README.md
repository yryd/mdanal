# mdanal

分子动力学轨迹的命令行分析工具。读取体系目录下的 `system.yaml`，调用 MDAnalysis 完成指定的分析，输出数据表与图件。

## 特性

- 六种内置分析：密度投影、线密度、径向分布、氢键、均方位移、流速剖面
- 一次运行处理一个体系，可同时执行多条分析
- 每个分析独立输出目录，互不覆盖
- 输出可复现：相同输入得到逐字节一致的结果
- 图为静态 PNG，分辨率可调

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

源码运行时把 `mdanal` 换成 `python main.py`。

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
| `topology` / `trajectory` | 拓扑与轨迹文件；省略时在文件所在目录内唯一查找 |
| `timestep_fs` | 时间步长（fs） |
| `dump_every` | 输出间隔（步） |
| `frames` | 帧窗口，左闭右开；省略时使用全部帧 |
| `view` | 视图坐标零点与图件显示窗口；省略时坐标与 `data.lmp` 一致 |
| `naming` | 给残基与原子补名字与元素；省略时只能用类型编号选择 |
| `groups` | 具名原子选择，供 `sel` 引用 |
| `analyses` | 要执行的分析列表 |

`analyses` 每条只有 `name` 必填；`sel` 的长度须等于该分析的选择数；其余键覆盖 `analyses.yaml` 中的默认参数。`tag` 用于区分同一种分析的多次输出。

### 坐标与视图

选择串、数据表、图件使用同一套坐标。

- 默认与 `data.lmp` 一致；写 `view.origin: [x, y, z]` 后以该点为零点，写 `view.origin: box_corner` 后以盒下角为零点（坐标范围 `0 … L`）。
- 改 `origin` 后，`prop` 选择串里的坐标区间要同步改。
- `view.window` 只裁剪图件的坐标轴范围，不改数据表；某个轴没写就不裁。
- 轨迹为包裹坐标时，`msd` 会用 `NoJump` 重建连续性并给出提示。
- 程序内部按盒坐标（`0 … L`）计算，视图偏移只影响选择串的求值与输出表图的坐标。

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

完整示例见 `example/system.yaml`。

## 内置分析

| 分析 | `sel` 顺序 | 主要参数 | 输出 |
|---|---|---|---|
| `density` | group | `delta`、`sum_axis` | 密度投影表与图 |
| `lineardensity` | group | `binsize`、`dim` | 三个轴的线密度表，指定轴的图 |
| `rdf` | a, b | `range`、`nbins` | g(r) 表与图 |
| `hbond` | donor, hydrogen, acceptor | `d_a_cutoff`、`d_h_a_angle_cutoff` | 每帧计数、汇总、占有率，计数图 |
| `msd` | group | `msd_type`、`fft` | MSD 表与图 |
| `velocity` | group, ref | `dim`、`vdim`（写 `x`/`y`/`z`）、`bin_width`、`grouping` | 速度剖面表与图 |

`mdanal list` 显示各分析的选择数与默认参数。

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
MDANAL_SYSTEM=/path/to/system python -m pytest tests -q
```

`MDANAL_SYSTEM` 指向包含 `system.yaml` 与轨迹的目录；未设置时测试跳过。

## 限制

- 一次只处理一个体系
- `rdf` 只输出 g(r)，不计算配位数
- `hbond` 只输出每帧计数与整个帧窗口的占有率，不保留逐帧明细
- `msd` 只输出曲线，不拟合扩散系数
