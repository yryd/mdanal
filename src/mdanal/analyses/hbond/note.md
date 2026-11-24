# hbond

## 图包目的

一个 `hbond` 图包，四个产品共享同一次 HBA 计算：

- `hbond-count`：每帧氢键数与汇总/占有率；
- `hbond-type`：按供体/受体类型统计，需要 `naming`；
- `hbond-lifetime-continuous`：连续型寿命曲线；
- `hbond-lifetime-intermittent`：间歇型寿命曲线。

## 输入与前提

槽位 donor / hydrogen / acceptor；默认 `d_a_cutoff=3.5 Å`、`d_h_a_angle_cutoff=150°`。当前只支持全周期盒；非周期输入按 HBA 周期路径计算，结果不能当作非周期氢键。

## 输出

- `hbond_count`、`hbond_summary`、`hbond_occupancy`；
- `hbond_type`；
- `hbond_lifetime`、`hbond_lifetime_summary`。

## 注意

一次 compute 只构造一次 HBA analysis；四个产品共享缓存。`hbond-type` 需要 source 配置 `naming`。`hbond-count`、两个 lifetime 单曲线产品都可 compare；`hbond-type` 是 bars，不可 compare。两个 lifetime 产品不提供 `stack`。
