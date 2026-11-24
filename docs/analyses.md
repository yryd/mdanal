# 分析说明

图包索引见 [analyses-index.md](analyses-index.md)。每个包的产品与 `pack.json` 是权威；这里只给科学口径和限制。

| 图包 | 产品 | 槽位 | 主要参数 |
|---|---|---|---|
| `density` | `density-2d`, `density-line` | group | `delta`、`binsize`、`plane`/`axis` |
| `hbond` | `hbond-count`, `hbond-type`, `hbond-lifetime-continuous`, `hbond-lifetime-intermittent` | donor, hydrogen, acceptor | 距离/角度、`tau_max_ps`、`figure_axis` |
| `msd` | `msd-raw`, `msd-fit`, `msd-rdc` | group | `msd_type`、`grouping`、`derive` |
| `rdf` | `rdf` | a, b | `range`、`nbins` |
| `velocity` | `velocity` | group, ref | `dim`、`vdim`、`bin_width`、`grouping`、`sym` |

## density

- `density-2d`：3D 数密度沿一个方向投影；`plot.plane` 选择 `xy/xz/yz`；
- `density-line`：沿 x/y/z 的质量密度与电荷密度；`plot.axis` 选择轴；
- 一次 compute 产出三个投影和三条线密度；固定正交盒，变盒只用首帧并警告；
- `density-2d` 是 field，不可 compare；多体系用多个 Panel 并排。

## hbond

- 一个 HBA analysis 供 hbond 四个产品共享；
- `hbond-type` 需要 source `naming`；
- `hbond-count` 和两个 `hbond-lifetime-*` 单曲线产品可 compare；`hbond-type` 是 bars，不可 compare；
- 当前只支持全周期盒；非周期结果不能当严格物理量。

## msd

- 基础表 `dt_ns`、`msd_A2`；
- `msd-fit` 需要 `derive.fit.window_ns`；`msd-rdc` 需要 `derive.rdc`；
- 拟合窗口是派生参数，不由 `plot.xlim` 偷偷改变；
- `msd-fit`/`msd-rdc` 的 compare 需要同派生配置；当前 `msd-raw` 可 compare。

## rdf

- `rdf`：`r_angstrom`、`g_r`；
- 逐帧按当前盒计算；非周期正交方向直接距离，g(r) 结果定性；
- 三斜+非周期拒绝。

## velocity

- `velocity`：轴坐标、速度、样本标准误；
- 在首帧参考盒中平均；误差未校正时间相关性；
- 固定正交盒。

## 统一边界

- 表头保留原生 ASCII 列名；图内文字随 `render.lang`；
- 密度/线密度变盒只用首帧；MSD 连续视图要求每帧位移小于半盒；氢键寿命要求足够密采样；
- 结果不能替代对轨迹物理合理性的检查。
