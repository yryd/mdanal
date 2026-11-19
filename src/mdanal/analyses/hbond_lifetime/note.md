# hbond_lifetime

## 分析目的

从氢键存在/断裂序列计算连续和间歇存活曲线，并用 1/e 交叉给出 `tau_1e_ps`。

## 输入与前提

三个槽位与 hbond 相同；`tau_max_ps`、`intermittency`、`window_step` 控制滞后上限、容忍断帧和取样步长。帧间隔应明显小于水氢键寿命量级；当前会在帧间隔 ≥1 ps 时警告。

## 输出

- `hbond_lifetime`：lag_ps、continuous、intermittent。
- `hbond_lifetime_summary`：criterion、tau_1e_ps、status、tolerance_frames、note。

## 注意

`intermittency` 的单位是帧，不是 ps；采样间隔变化会改变其物理时间。`status` 区分 `reached`、`not_reached`（窗口内没衰减到 1/e）和 `no_events`（没有氢键事件，寿命未定义）；没有事件不等于“尚未衰减”。
