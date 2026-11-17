# mdanal 手册

这是面向使用者的手册。README 只负责入口；本页按“你现在要做什么”组织阅读路线。

## 先约定三件事

1. 命令默认在仓库根目录执行；`python main.py` 和安装后的 `mdanal` 等价。
2. YAML 数据路径相对**配置文件所在目录**；命令行相对路径相对当前工作目录。
3. 文档正文中文，字段名保持英文；CSV 列名不随语言改变。

## 阅读路线

| 你的情况 | 建议顺序 |
|---|---|
| 第一次用，先跑通 | [首次使用](getting-started.md) → [输入与配置](configuration.md) → [绘图与重绘](plotting.md) |
| 有轨迹，想换自己的体系 | [输入与配置](configuration.md) → [分析说明](analyses.md) → [排错](troubleshooting.md) |
| 已经会跑，想调图 | [绘图与重绘](plotting.md) → [颜色](colors.md) → [图库](gallery.md) |
| 想把多个体系叠起来 | [多体系对比](compare.md) |
| 想写插件/接第三方库 | [插件手册](plugins.md) |
| 某条命令报错 | [排错](troubleshooting.md) |

## 页面地图

- [首次使用](getting-started.md)：MSD 起步、输出结构、第一次重绘、换自己的数据。
- [输入与配置](configuration.md)：`system.yaml`、`plot.yaml`、`compare.yaml` 的分工，路径、帧窗口、选择、输出树。
- [绘图与重绘](plotting.md)：哪些改动不用重算、`plot` 字段、标注、语言/格式、重绘优先级。
- [颜色](colors.md)：SciencePlots 色板、`palette`、固定主色/对照色、密度色标、生效范围。
- [图库](gallery.md)：八种分析图与五类改图案例。
- [分析说明](analyses.md)：八种分析的科学含义、输入、列名和限制。
- [多体系对比](compare.md)：空间对齐与时间偏移两个独立例子。
- [插件手册](plugins.md)：声明、`RunContext`/`PlotContext`、模板、第三方适配。
- [排错](troubleshooting.md)：字体、输出冲突、哈希、盒子变化、寿命采样、palette 不生效等。

## 文档里的示例数据

示例使用 `tests/fixtures/tiny`：真实 LAMMPS 输出的 20 帧截取（24 个 TMA、504 原子）。它适合验证流程，不代表可靠物理结论：

- `density`/`lineardensity` 遇到盒子变化只用首帧；
- 氢键寿命的帧间隔 5 ps，远大于水的氢键寿命量级，程序会提示寿命不可信；
- MSD 曲线短且噪声大，只用于演示出图和重绘。

生成文档图的脚本是 `scripts/build_docs_assets.py`；它只写 `docs/assets/`，不复制大轨迹。


## 本轮文档状态

- 重写 `README.md`，新增本手册 10 页、`example/quickstart` 与 `example/recipes`；
- 图库、色卡、改图示例、插件模板图由 `scripts/build_docs_assets.py` 从 tiny 数据生成；
- 已验证 quickstart 的 run/replot、`check-analysis --system tests/fixtures/tiny`、临时插件的 list/check/run/replot；
- 坐标轮已完成：每帧盒原点/盒矩阵/PBC、`x/xs/xu/xsu` 归一化、移动原点 MSD、非周期与三斜拒绝、RDF 半盒窗口检查；旧结果仍按旧快照重绘；
- 尚未实施：density 的真实体积归一化、RDF 自配对、hbond 颜色统一、密度色标范围、逐条标注样式，见 [排错与限制](troubleshooting.md#限制)。
