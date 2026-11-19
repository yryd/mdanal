# msd

## 分析目的

计算一个统计单元（原子或残基/分子质心）的时间平均均方位移，并可从同一份 MSD 派生线性拟合、扩散系数 D 与运行扩散系数 RDC。

## 输入与前提

- 槽位：`group`。
- 默认 `grouping: residues`，按所选原子所属残基做质量加权质心；只选分子的一部分时，结果是该部分的质心，不等于完整分子。
- `grouping: atoms` 时计算所选原子的原子 MSD。
- 轨迹需要连续坐标；`dt_ns` 由 dump 间隔和 `timestep_fs` 决定。

## 科学定义

```text
MSD(τ) = < |R(t+τ) - R(t)|² >
D_RDC(τ) = MSD(τ) / (2 d τ)
D_fit = slope / (2 d)
```

`d` 由 `msd_type` 决定：`xyz=3`、`xy/xz/yz=2`、单轴=1。  
RDC 与 D_fit 在有限窗口、存在截距时不必相等；不强制过原点。

## 参数

- `msd_type`：维度组合。
- `grouping`：`residues`（默认）或 `atoms`。
- `fft`：是否用 FFT 自相关。FFT 前按统计单元减固定参考位置，避免大坐标抵消。

## 输出

- `msd`：`dt_ns`、`msd_A2`。
- `msd_fit`（请求 fit 时）：`dt_ns`、`fit_msd_A2`。
- `msd_fit_summary`：D、D 的拟合标准误、斜率、截距、窗口、点数。
- `msd_rdc`（请求 rdc 时）：`dt_ns`、`rdc_A2_per_ps`。

## Figures

- `raw`：只有 MSD，文件名 `msd.png`；默认输出。
- `fit`：MSD + 拟合线 + 拟合起止线 + D，文件名 `msd-fit.png`。
- `rdc`：RDC + D 水平线 + 拟合窗口阴影，文件名 `msd-rdc.png`。

## 配置

```yaml
- name: msd
  sel: [water]
  derive:
    fit:
      window_ns: [1.0, 3.0]
      intercept: free
    rdc: {}
  figures:
    raw: {}
    fit: {}
    rdc: {}
```

## 注意

- `fit_window_ns` 改变数值结果，属于派生参数；不能用 `plot.xlim` 偷偷改变拟合窗口。
- RDC 在 τ=0 为 NaN；不填成零。
- `D_stderr` 只是回归斜率换算出的标准误，不是含时间相关的完整不确定度。
- 自动平台检测首版只作为诊断；不静默采用后段窗口。
- 大批量、少分子或短轨迹的 MSD 可能非单调；应检查拟合窗口与统计量。
