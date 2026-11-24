# 插件手册：图包

一个图包是一个文件夹：

```text
src/mdanal/analyses/<pack>/
├── __init__.py
├── pack.json
├── note.md
├── compute.py        # 可选；也可直接写在 __init__
└── products.py       # 可选；也可直接写在 __init__
```

包不是“分析接口”，而是“图产品提供者”。

## 必须导出

```python
SLOTS = ("group",)          # 选择槽位
PARAMS = {                  # 参数默认值与说明
    "delta": {"type": float, "default": 1.0, "min": 0.01, "help": "..."},
}
LABELS = {"zh": {...}, "en": {...}}
COORDINATES = "in_box"      # 或 "continuous"

def compute(ctx) -> dict[str, pandas.DataFrame]: ...

PRODUCTS = {
    "density-2d": PanelProduct(
        id="density-2d",
        kind="field",                 # curve / field / bars
        requires=("density_xy", "density_xz", "density_yz"),
        build=build_density_2d,       # (PlotContext, PanelSource) -> Panel
        default=True,
        compare=None,                 # field 不可 compare
        curve_request=None,           # 可选：单曲线 → 平台 stack
        help="2D density projection",
    ),
}
```

`build` **必须恰好返回一个 Panel**，不能返回列表。
`compare` 仅对 `kind="curve"` 允许，返回一个合并后的 Panel。
`curve_request` 可选，仅用于单曲线产品；平台 `stack` 会按 source 顺序堆叠。

## PanelSource

```python
source.tables      # 表名 -> DataFrame
source.params      # compute 参数
source.start/stop  # 帧窗口
source.frame_dt_ps
source.shift       # 视图平移
source.label       # compare 来源标签
```

`PlotContext` 提供 `label/window/size/annotate/extras/plot`。

## pack.json

`pack.json` 是机器可读契约，必须与 `PRODUCTS` 一致：

```json
{
  "schema_version": 1,
  "pack": "msd",
  "title": {"zh": "均方位移", "en": "MSD"},
  "products": [
    {"id": "msd-raw", "kind": "curve", "requires": ["msd"], "default": true, "compare": true, "curve": false}
  ]
}
```

`mdanal check-pack <name>` 会检查 ID、kind、requires、default、compare、curve 是否与代码一致。

## 最小可运行配置

```yaml
# figures.yaml
sources:
  A:
    topology: tests/fixtures/tiny/data.lmp
    trajectory: tests/fixtures/tiny/run.lammpstrj
    frames: [0, 5]
    groups: {all: "all"}
figures:
  - name: demo
    panels:
      - source: A
        pack: mypack
        product: my-product
        select: {group: all}
```

包内必须提供 `pack.json`、`PRODUCTS`、`SLOTS`、`PARAMS`、`LABELS`；`compute` 返回表，产品 `build` 返回一个 Panel。用 `mdanal check-pack mypack` 和 `mdanal check --config figures.yaml` 验证。

## 新增后

```bash
python main.py packs
python main.py check-pack mypack
```

如果产品不可用，检查 `pack.json` 是否与 `PRODUCTS` 漂移。

## contact

`contact` 提供两个单曲线产品：

- `contact-count`：分子对接触数；
- `contact-coordination`：按 `first` 组每个分子的平均接触数。

槽位：`first`、`second`。所有组必须是完整分子；第一版 `mode` 只支持 `com`。

```yaml
- source: TMA10
  pack: contact
  product: contact-count
  select: {first: TMA_anion, second: PIP}
  compute: {mode: com, cutoff: 10.0, block_ps: 250.0}
```

`block_ps` 分块平均；`time_origin: window`（默认）让横轴从窗口起点 0 开始；首尾点覆盖窗口起止时间。`contact` 只提供单曲线，`compare`/`stack` 都由平台组合。
