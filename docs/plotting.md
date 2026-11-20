# 绘图与重绘

## Panel 与 Figure

- `Panel`：一个单图，包含数据 + `draw(ax)`；
- `Figure`：若干 Panel + `ncols`；
- 产品构建 Panel，平台只负责排版、主题和保存。

```yaml
figures:
  - name: combined
    layout: {ncols: 2}
    panels:
      - {source: A, pack: density, product: density-2d, ...}
      - {source: A, pack: msd, product: msd-raw, ...}
```

## plot 字段

```yaml
plot:
  title: 水
  xlabel: ...
  ylabel: ...
  xlim: [0, 5]
  ylim: [0, 10]
  window: {x: [0, 5], y: [0, 10]}
  size: [4, 3]
  palette: bright
  rc: {font.size: 9}
  plane: xy       # density-2d 查看参数
  axis: z         # density-line 查看参数
```

- `plot` 不改变已保存的表；
- `density-2d` 的 `plane` 切换使用已保存的投影表，不重算；
- `palette/rc` 在整张 Figure 级别生效；同一图多个 Panel 的 palette 以第一个显式设置为准。

## replot

只换语言/分辨率：

```bash
python main.py replot --from OUT --out NEW --figure msd-tiny --lang en --dpi 300
```

改标题、范围、颜色、尺寸、Panel 布局，用 plot 覆盖配置：

```yaml
# plot.yaml
schema_version: 1
figures:
  msd-tiny:
    title: {zh: 中文标题, en: English title}
    lang: en
    dpi: 300
    annotate: true
    ncols: 1
    style:
      palette: ["#00aa00"]
      rc: {lines.linewidth: 7}
    panels:
      - title: {zh: 水, en: Water}
        xlabel: tau
        xlim: [0.0, 0.02]
```

```bash
python main.py replot --from OUT --out NEW --config plot.yaml
```

- `panels` 按快照中的 Panel 顺序覆盖；
- `panels[].plane` / `axis` 可切换 density 的查看投影；
- CLI `--lang/--dpi` 优先于 plot 配置；
- 只改呈现，不读轨迹、不重算；
- 目标已有同名图片时默认拒绝，加 `--force` 才覆盖。

`replot` 按快照里的表路径和 sha256 读取，表被改动会报错。
当前同一 `render` 内相同 job 只算一次；不同命令之间暂不复用已有表，改 compute/derive 后再次 `render` 会重新计算。跨运行离线派生尚未提供。
