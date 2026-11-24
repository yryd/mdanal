# 输入与配置

输入是一份 `figures.yaml`。顶层只有：

```yaml
schema_version: 1
name: ...
render: {lang: zh, dpi: 300, annotate: false}
sources: {...}
figures: [...]
```

## sources

每个 source 是一个可独立取数的体系：

```yaml
sources:
  A:
    topology: runs/A/data.lmp
    trajectory: runs/A/traj.lammpstrj
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 1040]
    groups:
      water: "type 11 12"
    naming: {from_data: runs/A/data.lmp}   # hbond-type 需要
```

字段：

| 字段 | 说明 |
|---|---|
| `topology` / `trajectory` | 必填；路径相对配置文件 |
| `timestep_fs` | LAMMPS 时间步长（fs），默认 1.0 |
| `dump_every` | 每隔多少个时间步 dump，默认 1 |
| `frames` | `[起, 止)` 帧窗口，默认全部 |
| `groups` | 名字 → MDAnalysis 选择串 |
| `naming` | 分子名/元素；`hbond-type` 必需 |
| `view` | 可选；`origin` 是盒坐标原点（Å），只改变视图坐标/平移，不改变轨迹数值 |

## figures

```yaml
figures:
  - name: msd-fit
    layout: {ncols: 3}
    title: "TMA-5 MSD"
    panels:
      - source: A
        pack: msd
        product: msd-fit
        select: {group: water}
        compute: {msd_type: xyz, grouping: residues}
        derive: {fit: {window_ns: [1.0, 4.0]}}
        section: [0, 1000]
        plot: {title: 水, xlim: [0, 5], size: [4, 3]}
```

| 字段 | 说明 |
|---|---|
| `figures[]` | **一张最终图**；每项有自己的 `layout`，输出一张 PNG |
| `panels[]` | 这张图里的 Panel；一项必须恰好一个 Panel |
| `source` | 输入体系名 |
| `pack` | 图包名 |
| `product` | 图产品 ID；见 `mdanal packs` |
| `select` | 槽位 → group/选择串；键必须正好是图包的 `slots` |
| `compute` | 算法参数；键必须在图包 `PARAMS` 内 |
| `derive` | 派生参数；产品需要的键必须提供 |
| `section` | 相对 source `frames` 的 `[起, 止)` |
| `plot` | 标题、范围、窗口、颜色、尺寸、`plane/axis`、`cbar_width/cbar_frame/legend_loc` 等呈现/查看参数；stack 可加 `stack_total` |

### 一张图 vs 多张图

```yaml
figures:
  - name: one-image
    layout: {ncols: 2}
    panels: [...]
  - name: another-image
    layout: {ncols: 1}
    panels: [...]
```

这是两张 PNG；不是一张图有两个 layout。

### density 的 plane

`density-2d` 是**一个产品**，`plot.plane: xy/xz/yz` 选择投影：

```yaml
- source: A
  pack: density
  product: density-2d
  select: {group: water}
  compute: {delta: 1.0}
  plot: {plane: xy}
```

3D 网格只计算一次，三个投影表一起保存；换 `plane` 不重算。

### compare

```yaml
panels:
  - compare:
      pack: msd
      product: msd-raw
      select: {group: water}
      sources:
        - {source: A, label: TMA-5}
        - {source: B, label: TMA-7.5}
```

只允许曲线产品；2D density 不能 compare，写成两个普通 `panels[]` 并排。

### stack

```yaml
panels:
  - stack:
      pack: contact
      product: contact-count
      sources:
        - {source: A, label: "TMA⁻–TMA⁻", select: {first: TMA_anion, second: TMA_anion}}
        - {source: A, label: "TMA⁻–TMA⁰", select: {first: TMA_anion, second: TMA_neutral}}
      plot: {stack_total: true}
```

`stack` 和 `compare` 一样输入多个单曲线 source；区别是累积堆叠。顺序就是 `sources` 顺序；所有曲线必须共享同一 x，不做插值。

### contact 分块平均

```yaml
compute:
  mode: com
  cutoff: 10.0
  block_ps: 250.0
```

`block_ps: 0` 逐帧；`> 0` 分块平均。首尾点强制落在窗口起止时间，值取第一块/最后一块均值。

## 输出

```text
OUT/
├── figures/<name>.png
├── figures/<name>.json     # 重绘快照
├── data/<source>/<pack>/<compute-key>/tables/*.csv
├── data/<source>/<pack>/<compute-key>/context.json
└── project.json
```
