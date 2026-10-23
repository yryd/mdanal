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
| `--force` | 允许写入已存在的输出目录 | 关闭 |

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
| `groups` | 具名原子选择，供 `sel` 引用 |
| `analyses` | 要执行的分析列表 |

`analyses` 每条只有 `name` 必填；`sel` 的长度须等于该分析的选择数；其余键覆盖 `analyses.yaml` 中的默认参数。`tag` 用于区分同一种分析的多次输出。

完整示例见 `example/system.yaml`。

## 内置分析

| 分析 | `sel` 顺序 | 主要参数 | 输出 |
|---|---|---|---|
| `density` | group | `delta`、`sum_axis` | 密度投影表与图 |
| `lineardensity` | group | `binsize`、`dim` | 三个轴的线密度表，指定轴的图 |
| `rdf` | a, b | `range`、`nbins` | g(r) 表与图 |
| `hbond` | donor, hydrogen, acceptor | `d_a_cutoff`、`d_h_a_angle_cutoff` | 每帧计数、汇总、占有率，计数图 |
| `msd` | group | `msd_type`、`fft` | MSD 表与图 |
| `velocity` | group, ref | `dim`、`vdim`、`bin_width`、`grouping` | 速度剖面表与图 |

`mdanal list` 显示各分析的选择数与默认参数。

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

`manifest.csv` 列出本次执行的分析、选择、原子数与参数；`provenance.json` 记录输入文件校验和、帧窗口、实际参数与库版本。

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

`ctx` 提供 `groups`、`start`、`stop`、`params`、`label()`、`size()`、`universe`。

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
