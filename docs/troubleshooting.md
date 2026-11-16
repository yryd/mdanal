# 排错与限制

先按报错里的路径/字段定位；大多数问题是“改错了层”（把计算输入放进 plot，或把呈现参数放进 system.yaml）。

<a id="字体"></a>

## 字体

报错类似：

```text
缺少字体 ['Noto Serif CJK SC']；图中文字会渲染成方块
```

处理：

1. 安装 `Noto Serif CJK SC`（Debian/Ubuntu 常见包是 `fonts-noto-cjk`）；
2. 确认 Matplotlib 能找到：
   ```bash
   python -c "from mdanal.plot.chart import missing_fonts; print(missing_fonts())"
   ```
3. 如果系统里字体名不同，改 `src/mdanal/plot/chart.py` 的 `CJK_FONT`。

字体只影响图内文字；CSV 和 `plot.json` 不受影响，所以修好字体后可以直接 `replot`，不用重算。

## 输出目录/`--force`

三个命令的 `--force` 不同：

| 命令 | 非空输出 | `--force` |
|---|---|---|
| `run` | 默认拒绝 | 只清空含 `provenance.json` 的旧 run 输出 |
| `replot` | 默认拒绝 | 只更新带 `replot.json` 的旧重绘目录 |
| `compare` | 默认拒绝 | 允许覆盖非空目录，但拒绝与输入目录重叠 |

不要把 `run` 的 `--force` 习惯套到 `replot`/`compare` 上。

## 重绘相关

| 报错/现象 | 原因 | 处理 |
|---|---|---|
| “未保存独立重绘信息” | 旧结果没有 `plot.json` | 重新 `run`；命令不会自动重算 |
| “表 ... 与绘图快照记录的哈希不一致” | 手改了 CSV 或用旧快照配新表 | 用原表，或重新 `run` |
| “插件源码在生成快照后发生变化” | 插件代码改了 | 只是警告；确认标签/列仍兼容，必要时重新 `run` |
| 输出目录重叠 | `--out` 在 `--from` 里/相反 | 换独立目录 |
| 输出非空 | 重复使用目录 | 换目录，或对合法旧重绘目录用 `--force` |
| 语言/格式没变 | 只改了 `system.yaml` | `replot` 读保存的 `plot.json`，改原 `system.yaml` 不影响旧结果；用 `plot.yaml`/CLI 覆盖 |

## 盒子/采样

- **`density`/`lineardensity` 警告“盒子在变化”**：它们只使用首帧并提示。要平均，选盒子不变的一段；要显式单帧，用 `section: [i, i+1]`。
- **`velocity` 警告盒子变化**：剖面在首帧参考盒坐标中平均。
- **氢键寿命提示帧间隔太大**：寿命需要足够密的采样；5 ps/帧不能分辨亚皮秒寿命。不要改 `timestep_fs` 伪造采样密度。
- **MSD 曲线噪声大**：短轨迹/少帧的结果；不是时间轴错误。连续视图要求相邻帧位移小于半盒。
- **三斜盒**：`density`/`lineardensity` 不支持。

## `palette` 不生效

这是当前设计，不是 bug：

| 图 | 是否跟随 `palette` |
|---|---|
| `rdf`/`msd`/`lineardensity`/`velocity` | 是（未显式设色的曲线） |
| `hbond`/`hbond_lifetime`/`hbond_type` | 否，使用固定主色/对照色 |
| `density` | 否，用连续色标 |
| 标注/参考线 | 否，固定灰色/主色 |
| `compare` | 是，用 `figure.palette` |

如果换 `palette` 后只有部分图变，先看 [颜色：生效范围](colors.md#生效范围)。

## 标注

- **竖线/阴影不画**：`axis: x/y/z` 只在正好是该图横轴时生效；时间/r 轴用 `axis: horizontal`。
- **标注位置不对**：`horizontal/vertical` 是数据坐标，不是 0–1 比例；单位跟图轴。
- **`--no-annotate` 后手写标注也没了？** 不会；`--annotate` 只控制自动帧信息，YAML `annotate` 是另一层。
- **想清空标注**：`annotate: []`；不写表示继承。
- **单条标注颜色/字号**：当前 YAML 不支持；用 Python 读表画，或改全局 `annotations.py`。

## 选择/配置

| 报错 | 处理 |
|---|---|
| “sel 有 N 个，需要 M 个” | `sel` 长度必须等于插件的 `SLOTS` 数；用 `mdanal list <name>` 查 |
| “分组/选择 0 原子” | 检查 `type`/`resid` 是否来自自己的数据；`type` 只接受空格枚举，不支持 `3-13` |
| “未知字段 `params`” | 参数直接写在分析条目本层，没有 `params:` 包裹 |
| “plot 含未知字段” | 看 [plot 字段](plotting.md#plot-字段)；compare 的 figure 字段不同 |
| `hbond_type` 标签是类型号 | 配置 `naming`；否则无法映射元素/分子 |
| `check` 没算但读轨迹 | 正常：`check` 会加载体系和选择，只是不跑分析计算 |

## compare

- “该运行里没有分析目录”：`figure.analysis` 要写实际输出目录名（含 tag）；
- “参数不同”：同一张图只能叠相同分析、相同参数；
- “t_offset 只能用于时间轴”：空间轴删掉 `t_offset`，时间轴见 [compare 的时间轴](compare.md#时间轴)；
- 二维密度不能叠，各自看。

<a id="限制"></a>

## 限制

当前没有：

- 密度色标范围/colormap 的公共 YAML 字段；
- 逐条标注颜色/字号/线宽；
- hbond 三家的统一 `palette` 入口；
- MSD 扩散系数拟合、论文级误差估计；
- 一次 `run` 处理多个体系（用 `compare` 叠结果）；
- `compare` 重绘（compare 保持现有入口）。

这些是后续代码任务，不是本轮文档遗漏。下一步：[插件手册](plugins.md) 或回 [手册入口](index.md)。
