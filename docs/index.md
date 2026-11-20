# mdanal 手册

mdanal 是 figure-first 的 LAMMPS 轨迹绘图工具：用户声明要哪些图，平台反推计算、构建 Panel、排版成 Figure。

## 从哪里开始

| 我想… | 看 |
|---|---|
| 跑通第一张图 | [首次使用](getting-started.md) |
| 写 `figures.yaml` | [输入与配置](configuration.md) |
| 改图、重绘 | [绘图与重绘](plotting.md) |
| 多体系叠加/并排 | [对比](compare.md) |
| 新增图包 | [插件手册](plugins.md) |
| 排错 | [排错](troubleshooting.md) |
| 看科学口径 | [分析说明](analyses.md) |

## 一句话架构

```text
sources → figures[] → PanelRef → FigurePack/Product → Panel → Figure
```

- `figures[]` 的每一项是一张最终图，有自己的 `layout.ncols`；
- 一个产品恰好一个 Panel；
- compare 只对曲线产品开放，最终产出一个 Panel；
- 2D 密度用多个 Panel 并排；
