# hbond

## 图包目的

一个 `hbond` 图包，四个产品共享同一次 HBA 计算：

- `hbond-count`：每帧氢键数与汇总/占有率；
- `hbond-type`：按供体/受体类型统计，需要 `naming`；
- `hbond-lifetime-continuous`：连续型寿命曲线；
- `hbond-lifetime-intermittent`：间歇型寿命曲线。

## 输入与前提

槽位 donor / hydrogen / acceptor；默认 `d_a_cutoff=3.5 Å`、`d_h_a_angle_cutoff=150°`。当前只支持全周期盒；非周期输入按 HBA 周期路径计算，结果不能当作非周期氢键。

## 寿命定义

- `continuous`：事件在整个 lag 内持续存在，不允许中断；
- `intermittent`：允许短时间断裂，`intermittency` 的单位是帧；
- 1 帧容忍在 0.1 ps 和 5 ps 的 dump 下物理意义不同，跨来源比较时要先看采样间隔；
- `tau_1e_ps` 是曲线首次降到 1/e 的线性插值时间，不是对曲线积分，也不是指数拟合参数；
- `not_reached` 表示窗口内没有降到 1/e；`no_events` 表示没有可估计的氢键事件；采样不足时尾部为空样本，不能把空值理解为“寿命很长”。
- `tau_max_ps` 超过 `(窗口帧数 - 1) × frame_dt_ps` 时，尾部没有完整时间原点；程序会告警，不会把空值填零。

## 输出

- `hbond_count`、`hbond_summary`、`hbond_occupancy`；
- `hbond_type`；
- `hbond_lifetime`、`hbond_lifetime_summary`。

## 注意

一次 compute 只构造一次 HBA analysis；四个产品共享缓存。`hbond-type` 需要 source 配置 `naming`。`hbond-count`、两个 lifetime 单曲线产品都可 compare；`hbond-type` 是 bars，不可 compare。两个 lifetime 产品不提供 `stack`。
