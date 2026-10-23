# mdanal

通用 MD 分析层：读体系目录下的 `system.yaml`，调用 MDAnalysis 与已注册插件完成分析，输出数据表与图件。程序内不实现分析算法。

设计说明见 `process/plan/mdanal-spec.md`。

## 目录

```
mdanal/
├── main.py              入口：python main.py <命令>
├── pyproject.toml       安装配置（提供 mdanal 命令）
├── requirements.txt     运行依赖（下限）
├── requirements-dev.txt 运行依赖 + pytest
├── example/system.yaml  完整的配置模板
├── src/mdanal/          源码（包）
│   ├── cli.py           命令行
│   ├── system.py        体系加载、选择解析
│   ├── registry.py      analyses.yaml 与计划校验
│   ├── runner.py        编排与落盘
│   ├── writers.py       CSV、密度投影、manifest、provenance
│   ├── plotutil.py      样式、画布、色标、标注、保存
│   ├── analyses/        六个分析模块
│   └── *.yaml           默认配置、分析定义、标签
└── tests/               集成测试
```

## 依赖

```bash
conda activate go_analysis
pip install -r requirements.txt        # 或 requirements-dev.txt
```

| 包 | 用途 |
|---|---|
| MDAnalysis ≥ 2.8 | 轨迹读取与全部分析 |
| numpy / pandas / matplotlib | 计算与绘图 |
| PyYAML | 读取 yaml |
| scienceplots | 绘图样式（`science` + `retro`） |
| maicos ≥ 0.12 | 仅 velocity 分析需要 |

中文字体使用系统自带的 `Noto Serif CJK SC`。

## 运行

在程序目录内，无需安装：

```bash
python main.py list                                    # 可用分析与槽位
python main.py list --system <体系目录>                 # 该体系的分组与计划
python main.py check --system <体系目录>                # 只校验，不计算
python main.py run --system <体系目录> --out <输出目录>  # 执行
```

安装后可在任意目录用 `mdanal` 命令：

```bash
pip install -e .
mdanal run --system <体系目录> --out <输出目录>
```

常用选项：

| 选项 | 说明 |
|---|---|
| `--lang zh\|en` | 图内文字语言，默认 `zh` |
| `--dpi N` | 图片分辨率，默认 300 |
| `--annotate` | 在图内标注帧窗口与参数 |
| `--force` | 允许覆盖已存在的输出目录 |

## 输入：`system.yaml`

体系目录下必须有该文件。完整模板见 `example/system.yaml`，复制到算例目录后改文件名与分组即可。

```yaml
name: gom_F0p2
topology: data.lmp
trajectory: run_flow.lammpstrj
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

- `topology` / `trajectory` 可省略，省略时在同目录内唯一查找。
- `sel` 的长度必须等于该分析的槽位数（见 `python main.py list`）。
- 同一种分析可写多条，用 `tag` 区分输出子目录。

## 输出

```
<out>/
├── density-xz/tables/density_xz.csv
├── density-xz/figures/density_xz.png
├── rdf/...
├── manifest.csv        本次运行的分析清单与落位
└── provenance.json     输入校验和、帧窗口、参数、meta、库版本
```

输出目录已存在时会被拒绝，需加 `--force`。

## 新增一个分析

两处改动，不改共享代码：

1. 在 `src/mdanal/analyses.yaml` 加一段定义（`slots`、`params`、`requires`、`package`、`labels`）；
2. 在 `src/mdanal/analyses/` 下加同名模块：

```python
def run(ctx):
    """返回 {表名: pandas.DataFrame}"""

def figures(ctx, tables):
    """返回 [(图名, matplotlib Figure)]，可选"""
```

`ctx` 提供 `groups`（槽位 → 原子组）、`start/stop`、`params`、`label()`、`size()`、`universe`。

## 测试

```bash
python -m pytest tests -q
```

测试依赖真实体系目录，默认取 `process/runs/003-systems/zgom/flow_F0p2`，可用 `MDANAL_SYSTEM` 指向其他体系；目录不存在时整组跳过。

## 已知限制

- 一次只处理一个体系。
- `rdf` 只给 g(r)，不换算配位数（受限体系中无唯一定义）。
- `velocity` 的纵轴原点取参考组质心。
- 氢键只输出计数与整窗占有率，不保留逐帧明细。
- MSD 只输出曲线，扩散系数需另行拟合。
