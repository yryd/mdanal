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

```bash
python main.py replot --from OUT --out NEW --figure msd-tiny --lang en --dpi 300
```

`replot` 只读 `OUT/figures/*.json` 和 `OUT/data/`，不读轨迹、不重算表；它按快照里的表路径和 sha256 读取，表被改动会报错。目标已有同名图片时默认拒绝，加 `--force` 才覆盖。
当前同一 `render` 内相同 job 只算一次；不同命令之间暂不复用已有表，改 compute/derive 后再次 `render` 会重新计算。跨运行离线派生尚未提供。
