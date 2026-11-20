# 多体系对比

## 曲线：compare

```yaml
figures:
  - name: msd-compare
    layout: {ncols: 1}
    panels:
      - compare:
          pack: msd
          product: msd-raw
          select: {group: water}
          compute: {msd_type: xyz}
          sources:
            - {source: A, label: TMA-5}
            - {source: B, label: TMA-7.5}
```

- 只允许 `kind: curve` 的产品；
- 平台检查同一 pack/product、产品 compare 能力和每来源参数；轴/单位兼容性目前只做基础保护，不保证所有科学语义自动判断；
- 每个来源的 `PanelSource.label` 用作曲线标签；
- compare 最终产出一个 Panel；
- 同一 source 可以出现多次，用 per-source `compute`/`select` 做参数对比，`label` 必须不同。

```yaml
sources:
  - {source: A, label: xyz, compute: {msd_type: xyz}}
  - {source: A, label: xy,  compute: {msd_type: xy}}
```

## 2D 密度：并排

field 不能叠加。使用两个普通 Panel：

```yaml
  - name: density-compare
    layout: {ncols: 2}
    panels:
      - {source: A, pack: density, product: density-2d, select: {group: water}, compute: {delta: 1.0}, plot: {plane: xy, title: A}}
      - {source: B, pack: density, product: density-2d, select: {group: water}, compute: {delta: 1.0}, plot: {plane: xy, title: B}}
```

`figures[]` 只出一张 PNG；两个 Panel 在同一张图里并排。

## 不可 compare 的产品

- `density-2d`（field）；
- `hbond-type`（bars）。
平台会明确报错，而不是产出一张没有意义的叠图。
