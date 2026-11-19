# 绘图与重绘

目标：判断一个改动是**只改图**还是**必须重算**，并知道字段写在哪一层。

## 1. 先判断：要不要重算

| 想改什么 | 入口 | 是否重算 | 限制 |
|---|---|---|---|
| 中文/英文 | run/replot 的 `--lang`；replot `defaults.lang` | 已有快照时不用 | 不自动翻译你自己写的字符串 |
| 画布尺寸 | `plot.size` | 不用 | 英寸；紧边框保存，像素不保证正好等于英寸×DPI |
| 标题、轴标签、显示范围 | `plot.title/xlabel/ylabel/xlim/ylim` | 不用 | 范围只裁显示，不改 CSV |
| 曲线颜色 | `plot.palette` / compare `figure.palette` | 不用 | 只影响未显式设色的曲线 |
| 字号等默认样式 | `plot.rc` | 不用 | 显式写死的字号/线宽优先 |
| 竖线、横线、阴影、文字 | `annotate` | 不用 | 用实际图轴数据坐标；当前四个字段 |
| 标注单独颜色/字号/线宽 | 当前 YAML 不支持 | — | 用 Python 读表画，见 [Python](#python) |
| 密度色标/色标范围 | 当前 YAML 不支持 | — | `palette` 不是密度 colormap |
| 单条曲线线型/标记/复杂排版 | 插件 figure recipe 或 Python | 可复用已保存表 | 现有插件常显式指定线型 |
| 一次分析出多张图 | `figures: {raw, fit, rdc}` | 不重算基础表 | 需插件声明 `FIGURES`；MSD 已支持 |
| 改拟合窗口/D/RDC | `derive:` | **要派生，不重算轨迹** | 只对声明 derive 的插件；首版 MSD |
| 只重绘某张图 | `replot --figure NAME` | 不重算 | 需快照包含 figures |
| PNG/SVG/PDF | `replot --format` | 不用 | `run` 和 `compare` 没有同样的格式选项 |
| 选择组、帧窗口、分箱、截断、参数 | `system.yaml` | **要** | 不能塞进 `plot.yaml` |
| 单位换算（Å→nm 等） | 当前没有通用 YAML 换算 | 可读表用 Python 换算 | 必须同时换算数据、范围和标注 |
| `view.origin` | `system.yaml` | 可能影响选择，需重算 | replot 不能覆盖保存的 shift |

## 2. `replot` 配置

```bash
python main.py replot --from OUT --out FIGURES [--config plot.yaml]
```

`plot.yaml`：

```yaml
schema_version: 1
defaults:
  lang: zh
  dpi: 300
  format: png
  show_run_info: false
  plot:
    palette: bright
    rc:
      font.size: 9
analyses:
  msd:
    plot:
      xlim: [0, 80]
      ylim: [0, 20]
      title: {zh: 均方位移, en: Mean squared displacement}
    annotate:
      - {kind: vline, axis: horizontal, at: 10,
         text: {zh: 参考时间, en: Reference}}
  density-xz:
    plot:
      size: [4.2, 3.0]
      window: {x: [5, 25]}
```

- 顶层只接受 `schema_version`、`defaults`、`analyses`；未知字段报错；
- `analyses` 的键是**输出目录名**，不是插件名（`density-xz`，不是 `density`）；
- `defaults` 接受 `lang/dpi/format/show_run_info/plot/annotate`；单分析项只接受 `plot/annotate`；
- 配置里不存在的分析目录会报错；目录存在但没被 `--analysis` 选中时不处理。

### 覆盖优先级

从低到高：

1. 输出中保存的绘图默认值；
2. 配置 `defaults`；
3. 配置中对应 `analyses` 项；
4. 明确给出的 CLI 选项。

映射字段 `plot.window`、`plot.rc` 递归合并；列表和标量整体替换。没给的 CLI 选项不会覆盖快照。

<a id="plot-字段"></a>

## 3. `plot` 字段

| 字段 | 类型 | 作用 |
|---|---|---|
| `window` | `{x/y/z: [下界, 上界]}` | 插件现有的物理轴/图轴窗口；先于 `xlim/ylim` |
| `size` | `[宽, 高]` 英寸 | 显式画布；优先于插件自动图幅（density 不再自动调高度） |
| `layout.ncols` | 正整数 | 平台 Figure 一行放几个 Panel；density 多面板和其他插件共用 |
| `xlim` / `ylim` | `[下界, 上界]` | 最终显示范围；不改数据表 |
| `title` / `xlabel` / `ylabel` | 字符串或 `{zh, en}` | 标题/轴标签；空字符串可清空 |
| `palette` | 色板名或颜色列表 | 曲线颜色循环；见 [颜色](colors.md) |
| `rc` | Matplotlib rc 映射 | 局部生效；显式写死的样式优先 |

`plot.rc` 是高级入口：它能改字号、轴样式等，但不会覆盖插件里显式写的 `color=`、`lw=`，也不改标注的固定样式。`rc` 不允许改 `backend`。
<a id="多图输出"></a>

### 多图输出

插件若声明 `FIGURES`，可在分析下选择 recipe：

```yaml
- name: msd
  sel: [water]
  derive:
    fit: {window_ns: [1.0, 3.0], intercept: free}
    rdc: {}
  figures:
    raw: {}
    fit: {}
    rdc: {}
```

`figures` 的键是稳定的 recipe ID，不是文件名；每个 recipe 的 `plot` 覆盖只影响该图。不写 `figures` 时保持当前默认输出（MSD 只出 raw）。`derive` 改变的是数值结果，`plot.xlim` 只改显示范围，不能改拟合窗口。



<a id="标注"></a>

## 4. 标注

```yaml
  - name: lineardensity
    sel: [water_o]
    dim: z
    annotate:
      - {kind: vline, axis: horizontal, at: 20, text: {zh: 参考位置, en: Reference}}
      - {kind: span,  axis: horizontal, at: [22, 27], text: {zh: 观察区间, en: Window}}
      - {kind: hline, at: 0.5, text: {zh: 半密度, en: Half density}}
      - {kind: text,  at: [5, 0.35], text: {zh: 体相, en: Bulk}}
```

| kind | axis | at | 含义 |
|---|---|---|---|
| `vline` | `horizontal` / `x/y/z` | 数值 | 竖线；`horizontal` 用图横轴数据坐标 |
| `hline` | 省略或 `vertical` | 数值 | 横线；用图纵轴数据坐标 |
| `span` | `horizontal/vertical/x/y/z` | `[起, 止]` | 阴影区间 |
| `text` | 省略 | `[横轴, 纵轴]` | 文字，数据坐标 |

- `horizontal/vertical` 是**图轴的数据坐标**，单位跟图轴一致；`x/y/z` 是旧物理盒轴匹配规则，只有正好是该图横轴时才画，否则 `warn` 并跳过。
- `text` 支持字符串或 `{zh, en}`；`vline+vertical` 等矛盾组合报错。
- 标注是**你自己写的**，程序不会自动识别界面；`at` 的单位由图轴决定，不自动 ps→ns。
- `--annotate` / `show_run_info` 只控制自动的帧窗口/参数说明；YAML `annotate` 是用户标注。未提供列表继承，`[]` 清空，列表替换不追加。
- 当前标注颜色/字号/线宽固定：竖线/横线灰色 0.45、字号 6、线宽 0.8；阴影主色 `#4165c0`、alpha 0.12。`plot.rc` 不会覆盖这些显式样式。

RDF 的距离区间更具体：

```yaml
analyses:
  rdf:
    annotate:
      - {kind: span, axis: horizontal, at: [3, 5],
         text: {zh: 观察区间, en: Inspection window}}
```

这里的 `axis: horizontal` 是 `r_angstrom`；不是 0–1 比例，也不会改变计算用的 `range`。示例效果见 [图库](gallery.md#标注)。

## 5. 语言、格式、输出保护

```bash
python main.py replot --from OUT --out FIGURES_EN --lang en --format svg
python main.py replot --from OUT --out FIGURES --analysis msd --analysis rdf
```

- `--format` 只属于 `replot`：`png`、`svg`、`pdf`；
- `run` 当前只出 PNG；`compare` 当前只出 PNG；
- `--out` 不能与源结果目录相同或互相包含；非空输出默认拒绝；只有带 `replot.json` 的旧重绘目录才可用 `--force` 更新；
- 表哈希不一致、快照缺失/版本不支持、插件无法导入时明确失败；插件源码变化只警告；
- `rdf` 的 `range`/`nbins`、`density` 的 `delta` 等是计算参数，必须改 `system.yaml` 重算；`xlim` 不会扩展计算范围；
- 重绘不复制或改写科学数据表。

<a id="python"></a>

## 6. Python

如果 YAML 表达不了，直接读 CSV 用 Matplotlib：

```python
import pandas as pd
import matplotlib.pyplot as plt

table = pd.read_csv("OUT/msd/tables/msd.csv")
fig, ax = plt.subplots(figsize=(3.5, 2.6))
ax.plot(table["dt_ns"], table["msd_A2"], color="#4165c0")
ax.set_xlabel("lag (ns)")
ax.set_ylabel("MSD (Å²)")
fig.savefig("my-msd.png", dpi=300, bbox_inches="tight")
```

也可以 `from mdanal import chart` 用项目统一样式；见 [example/plot_from_data.py](../example/plot_from_data.py)。

下一步：[颜色](colors.md)、[图库](gallery.md) 或 [多体系对比](compare.md)。
