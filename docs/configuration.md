# 输入与配置

这一页回答三个问题：**改哪个文件、字段是什么意思、改完要不要重新算。**

## 1. 输入/输出地图

| 文件或入口 | 谁提供 | 用途 | 用户平时是否编辑 |
|---|---|---|---|
| LAMMPS data 与 dump | 仿真 | 原子、轨迹、盒子、速度等 | 不为调图修改 |
| `system.yaml` | 你 | 轨迹、时间、选择、分析和初次呈现 | 换计算对象/参数时改 |
| `plot.yaml` | 你（文件名自定） | `replot` 的呈现覆盖 | 反复调图时改 |
| `compare.yaml` | 你（文件名自定） | 选择多个结果并对齐叠图 | 多体系对比时改 |
| `derive.yaml` | 你（文件名自定） | 从已有表重算 fit/RDC | 改拟合窗口时 |
| `tables/*.csv` | 程序 | 稳定机器列名的数据 | 可读；手改后原快照哈希会失效 |
| `plot.json` | 程序 | 重绘所需上下文 | 不手改 |
| `manifest.csv` / `provenance.json` | 程序 | 分析目录、参数、警告、输入校验和 | 阅读/排错 |
| `replot.json` | 程序 | 本次重绘设置与产物记录 | 阅读，不当配置 |
| `derive.json` | 程序 | 离线派生源、配置与产物记录 | 阅读，不当配置 |
| `analyses/<name>/` | 分析作者 | 插件包（实现 + note） | 写插件时编辑 |

数据流：

```text
data + dump + system.yaml ──run──> CSV + plot.json + 初次 PNG
                                   │
                         plot.yaml + replot ──> 新图目录

多个 run 结果 + compare.yaml ──compare──> 对比图 + 对齐表
已有表 + derive.yaml ──derive──> 新派生表/图（不读轨迹）
CSV / 自己的数组 + Python/chart ──> 自由绘图
```

## 2. 三种 YAML 的分工

| | `system.yaml` | `plot.yaml`（replot） | `compare.yaml` | `derive.yaml` |
|---|---|---|---|---|
| 作用 | 计算输入 | 已有结果的呈现覆盖 | 多个结果的对齐叠图 | 已有表重算派生 |
| `analyses` 形态 | 列表 | 按输出目录名索引的映射 | 没有 `analyses`，用 `items` | 按输出目录名索引的映射 |
| 能否改计算 | 能 | **不能** | **不能** | 只改派生，不重算轨迹 |
| 主要字段 | topology/trajectory/frames/groups/analyses | defaults/analyses | items/figure/out | analyses.<dir>.derive/figures |
| 典型命令 | `run` / `check` | `replot` | `compare` | `derive` |

四个最容易混的点：

1. `system.yaml` 的 `analyses` 是列表；`plot.yaml` 的 `analyses` 是按**输出目录名**索引的映射。`name: density` + `tag: xy` 的输出目录是 `density-xy`。
2. 分析参数（`nbins`、`dim`、`delta` 等）写在分析条目本层；呈现参数放在 `plot`；用户标注 `annotate` 与 `plot` 并列。没有 `params:` 包裹层。
3. `system.yaml` 内路径相对配置文件目录；`compare.yaml` 的 `item.root` 和 `out` 相对 compare 配置目录；命令行相对当前工作目录。
4. `derive.yaml` 只读已有 `plot.json` + CSV，不读轨迹；它改变派生数值，不是纯呈现覆盖。

## 3. `system.yaml` 字段

完整示例见 [`example/system.yaml`](../example/system.yaml)；最小示例见 [`example/quickstart/system.yaml`](../example/quickstart/system.yaml)。

### 顶层

| 字段 | 必填 | 含义 | 默认/注意 |
|---|---|---|---|
| `name` | 否 | 体系名，只用于日志/溯源 | 省略取目录名 |
| `topology` | 否 | LAMMPS data 文件 | 省略时在目录内找唯一 `*.lmp`/`*.data` |
| `trajectory` | 否 | 单个 dump 或 dump 列表（多段合并） | 省略时找唯一 `*.lammpstrj`；列表按顺序拼接 |
| `timestep_fs` | 否 | 每步时间（fs） | 默认 1.0 |
| `dump_every` | 否 | 每多少步一帧 | 默认 1；帧间隔 = `dump_every × timestep_fs` |
| `frames` | 否 | `[起, 止]`，左闭右开 | 省略用全部帧 |
| `view.origin` | 否 | 视图坐标零点 | `[x,y,z]` 或 `box_corner`；影响 `prop` 选择 |
| `naming` | 否 | 给残基/原子补名字 | `hbond_type` 需要；见 [分析说明](analyses.md#hbond_type) |
| `groups` | 否 | 名字 → MDAnalysis 选择串 | `sel` 可以用组名或直接写选择串 |
| `analyses` | 是 | 分析列表 | 见下 |
| `figures` | 否 | 跨分析组合图列表 | 引用 `analyses` 的输出目录和 recipe |

### `analyses` 每一条

| 字段 | 必填 | 含义 |
|---|---|---|
| `name` | 是 | 插件文件名/分析名 |
| `sel` | 是 | 选择列表，长度必须等于该分析的 `SLOTS` 数 |
| `tag` | 否 | 同一种分析写多条时区分输出目录；目录为 `name-tag` |
| `section` | 否 | 在体系 `frames` 内再切 `[起, 止]`，相对偏移，左闭右开 |
| `plot` | 否 | 具体字段见 [绘图与重绘](plotting.md#plot-字段) |
| `figures` | 否 | 该分析的图 recipe 映射；键必须是插件 `FIGURES` 声明过的 ID |
| `derive` | 否 | 从基础表派生的科学结果；键必须是插件 `DERIVE` 声明过的 ID；未知键直接报错 |
| `annotate` | 否 | 用户标注列表，与 `plot` 并列 |
| 分析参数 | 否 | 如 `nbins`、`dim`、`delta`、`tau_max_ps`，直接写在本层；用 `mdanal list <name>` 查契约 |

**`sel` 是必填的**。参数有默认值不等于不需要选择组；`sel` 数量不对会在 `build_plan` 阶段报错。

### 顶层 `figures`

跨分析组合图放在 `system.yaml` 顶层，和 `analyses` 并列：

```yaml
figures:
  - name: msd-3comp-fit
    layout: {ncols: 3}
    plot: {title: {zh: TMA-5 三组分 MSD, en: TMA-5 three-component MSD}}
    panels:
      - {analysis: msd-water, recipe: fit, plot: {title: 水}}
      - {analysis: msd-pip, recipe: fit, plot: {title: PIP}}
      - {analysis: msd-tma, recipe: fit, plot: {title: TMA}}
```

- `analysis` 是输出目录名（`msd-water`），不是插件名（`msd`）；
- `recipe` 必须是该 analysis 模块 `FIGURES` 中已有的名字；
- `layout.ncols` 控制一行几张 Panel；
- 图级 `plot` 只接受 `title`、`palette`、`rc`；Panel 级 `plot` 只接受 `title`、`xlabel`、`ylabel`、`window`、`xlim`、`ylim`；
- 需要 `fit` 时，每个被引用的 analysis 必须自己配置 `derive.fit`；跨分析图不会偷偷派生；
- 不写顶层 `figures` 时，单分析行为完全不变。

<a id="坐标视图与每帧几何"></a>

### 坐标视图与每帧几何

程序读取每帧 `BOX BOUNDS` 的盒原点、盒矩阵和 `pp/ff` 边界标记：

- `in_box`：相对**当前帧盒原点**的局部笛卡尔坐标，只沿周期方向折回；
- `continuous`：实验室绝对笛卡尔坐标；`x/xs` 包裹坐标在固定盒矩阵下逐帧展开，`xu/xsu` 直接使用已给出的连续位置。

这解决三类常见错误：

- 缩放坐标遇到非零盒原点；
- 盒原点逐帧移动时 MSD 混入参考系运动；
- 非周期方向被当成周期方向做最小镜像。

`view.origin` 仍是旧兼容入口：它参与选择坐标和初次显示；选择在首帧按该帧原点求值，之后固定原子身份。`replot` 不能改 `origin`。`--aligned` 副本仍是“表值加视图平移”，正表保留自身坐标语义。

首版支持条件：

| 分析 | 盒形状 | 边界 |
|---|---|---|
| density / lineardensity / velocity | 正交 | x/y 周期；z 可为 `ppf/pps` 非周期 |
| rdf | 正交（变盒逐帧） | 声明三向周期；非周期正交方向按直接距离计算并标定性；三斜+非周期拒绝 |
| hbond / hbond_type / hbond_lifetime | 任意盒（由 MDAnalysis 距离实现） | 三向周期；非周期输入会明确标为 `unsupported_geometry` |
| msd | 连续视图按输入路径限制 | 包裹坐标只支持固定盒矩阵；已给 `xu/xsu` 按输入定义 |

不满足声明时 `run`/`check` 会打印“非物理/仅供定性参考”警告并继续执行，不会阻止运行；警告会写入 provenance。不要靠改 YAML 假装周期；需要定量结果时仍应使用满足条件的数据。每帧几何和窗口摘要写入 `provenance.json` 的 `geometry`。

### 时间

```text
帧间隔 = dump_every × timestep_fs
第 i 帧时间 = i × 帧间隔
```

多段轨迹的 TIMESTEP 可以重置；程序按**合并后的全局帧号**计时，不跟随 LAMMPS 的 TIMESTEP 跳变。同一段内若 TIMESTEP 步差与 `dump_every` 不一致（抽帧不均/丢帧/配错 `dump_every`），`check`/`run` 会给出明确提示；合法接缝重置不误报。

## 4. 输出结构

### `run`

```text
OUT/
├── manifest.csv
├── provenance.json
├── msd/
│   ├── plot.json
│   ├── tables/msd.csv
│   └── figures/msd.png
└── density-xz/
    ├── plot.json
    ├── tables/density_xz.csv
    └── figures/density_xz.png
```

- `plot.json` 保存表路径/哈希、参数、帧窗口、视角平移、双语标签、用户标注、呈现默认值和实际生成的图选择（默认 MSD `raw` 也会记录）；
- `--aligned` 会另写 `tables/*.aligned.csv`，正表仍是盒局部坐标；
- `provenance.json` 记录输入校验和、视图、参数、警告和库版本；`manifest.csv` 是每条分析的目录、选择、原子数和参数。

### `replot`

```text
FIGURES/
├── replot.json
└── msd/figures/msd.svg
```

不复制表；`replot.json` 记录源结果、快照/表哈希、实际 palette、语言、格式和文件清单。

### `compare`

```text
COMPARE/
├── lineardensity.png
├── tables/lineardensity_z.csv
└── provenance.json
```

同一 analysis/table 被多个 Panel 引用时，第二张起写成 `...__panel2.csv`，不会互相覆盖；`provenance.json` 记录每个 Panel 实际引用的表。

### `derive`

```text
DERIVED/
├── derive.json
└── msd/
    ├── plot.json
    ├── tables/msd.csv + msd_fit.csv + msd_fit_summary.csv + msd_rdc.csv
    └── figures/msd.png / msd-fit.png / msd-rdc.png
```

## 5. 命令与选项

| 命令 | 主要选项 | 输出处理 |
|---|---|---|
| `list` / `list <name>` / `list --system DIR` |  | 只打印 |
| `check --system DIR` |  | 加载体系、解析选择、检查依赖，不计算 |
| `check-analysis [names]` | `--system DIR`、`--keep DIR` | 静态检查；带 `--system` 会实跑中英各一遍 |
| `run --system DIR --out DIR` | `--lang`、`--dpi`、`--annotate`、`--force`、`--no-memory`、`--aligned` | `--force` 只清空含 `provenance.json` 的旧 run 输出；输入（YAML/拓扑/轨迹）位于输出目录内时直接拒绝 |
| `replot --from DIR --out DIR` | `--analysis`、`--config`、`--lang`、`--dpi`、`--format`、`--annotate/--no-annotate`、`--force` | 非空输出默认拒绝；`--force` 只更新带 `replot.json` 的旧重绘目录 |
| `compare --config FILE [--out DIR]` | `--lang`、`--force` | 非空输出默认拒绝；`--force` 允许覆盖，但拒绝与输入目录重叠 |
| `derive --from DIR --out DIR --config FILE` | `--analysis`、`--lang`、`--dpi`、`--format`、`--force` | 非空输出默认拒绝；`--force` 只更新带 `derive.json` 的旧派生目录；不读轨迹 |

`--force` 在各命令里的含义不同，不能互相套用。

## 6. 选择、帧窗口和常见错误

- `frames` 左闭右开；`section` 也是左闭右开，并且是相对 `frames` 的偏移。
- 选择在**体系窗口首帧**求值一次，之后不逐帧重选；需要动态选择时要自己写新分析。
- `and`/`or` 从左到右，没有优先级；混用必须加括号。
- `type` 只接受空格分隔的枚举；`resid`、`bynum` 支持范围。`type 3-13` 不会报错但可能选中 0 个原子。
- `hbond_type` 需要 `naming`，否则无法把类型映射成元素/分子标签。

下一步：[绘图与重绘](plotting.md) 或 [分析说明](analyses.md)。
