# mdanal

通用 MD 分析层：读体系目录下的 `system.yaml`，调用 MDAnalysis 与已注册插件完成分析，输出数据表与图件。程序内不实现分析算法。

设计说明见 `process/plan/mdanal-spec.md`。

## 依赖

运行环境为 conda env `go_analysis`：

| 包 | 用途 |
|---|---|
| MDAnalysis ≥ 2.8 | 轨迹读取、全部分析 |
| numpy / pandas / matplotlib | 计算与绘图 |
| PyYAML | 读取 yaml |
| scienceplots | 绘图样式（`science` + `retro`） |
| maicos ≥ 0.12 | 流速剖面 |
| pytest | 测试 |

中文字体使用系统自带的 `Noto Serif CJK SC`。

## 快速开始

在 `process/code` 目录下执行：

```bash
# 查看可用的分析及其槽位、默认参数
python -m mdanal list

# 查看某个体系的分组与将要运行的分析（不读轨迹）
python -m mdanal list --system ../runs/003-systems/zgom/flow_F0p2

# 只校验：文件、分组、槽位数、参数名、依赖
python -m mdanal check --system ../runs/003-systems/zgom/flow_F0p2

# 执行
python -m mdanal run --system ../runs/003-systems/zgom/flow_F0p2 --out /tmp/out

# 英文图、600 dpi、在图内标注帧窗口
python -m mdanal run --system ../runs/003-systems/zgom/flow_F0p2 --out /tmp/out-en \
       --lang en --dpi 600 --annotate
```

## 输入：`system.yaml`

体系目录下必须有该文件。拓扑与轨迹可省略，省略时在同目录内唯一查找。

```yaml
name: gom_F0p2
timestep_fs: 1.0
dump_every: 10000
frames: [400, 500]
groups:
  water_o: "type 17"
  water_h: "type 18"
  walls:   "resid 1 or resid 90"
analyses:
  - {name: density, tag: xz, sel: [water_o], sum_axis: y}
  - {name: rdf,     sel: [water_o, walls]}
```

`sel` 的长度必须等于该分析的槽位数（见 `list`）；多条分析写在同一列表里，输出按 `name` 或 `name-tag` 分目录。

## 输出

```
<out>/
├── density-xz/tables/density_xz.csv
├── density-xz/figures/density_xz.png
├── rdf/...
├── manifest.csv        本次运行的分析清单与落位
└── provenance.json     输入校验和、帧窗口、参数、`meta`、库版本
```

输出目录已存在时会被拒绝，需加 `--force`。

## 新增一个分析

两处改动，无需修改共享代码：

1. 在 `analyses.yaml` 中加一段定义（`slots`、`params`、`requires`、`package`、`labels`）；
2. 在 `analyses/` 下加同名模块，实现：

```python
def run(ctx, tables_unused=None):
    """返回 {表名: pandas.DataFrame}"""

def figures(ctx, tables):
    """返回 [(图名, matplotlib Figure)]，可选"""
```

`ctx` 提供 `groups`（槽位 → 原子组）、`start/stop`、`params`、`label()`、`size()` 与 `universe`。

## 测试

```bash
cd process/code
python -m pytest mdanal/tests -q
```

测试依赖真实体系目录，默认取 `process/runs/003-systems/zgom/flow_F0p2`，可用环境变量 `MDANAL_SYSTEM` 指向其他体系；目录不存在时整组跳过。

## 已知限制

- 一次只处理一个体系。
- `rdf` 只给 g(r)，不换算配位数（受限体系中无唯一定义）。
- `velocity` 的纵轴原点取参考组质心。
- 氢键只输出计数与整窗占有率，不保留逐帧明细。
- MSD 只输出曲线，扩散系数需另行拟合。
