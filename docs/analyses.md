# 分析说明

八种内置分析的科学含义、选择顺序、主要参数和限制。参数默认值和完整契约用 `mdanal list <name>` 查看。

## 总表

| 分析 | `sel` 顺序 | 主要参数 | 主要输出 |
|---|---|---|---|
| [`density`](#density) | group | `delta`、`sum_axis` | 二维数密度投影 |
| [`lineardensity`](#lineardensity) | group | `binsize`、`dim` | 三个轴的线密度表 |
| [`rdf`](#rdf) | a, b | `range`、`nbins` | g(r) |
| [`hbond`](#hbond) | donor, hydrogen, acceptor | `d_a_cutoff`、`d_h_a_angle_cutoff` | 计数、汇总、占有率 |
| [`hbond_type`](#hbond_type) | donor, hydrogen, acceptor | 同上、`figure_axis` | 类型计数/每帧/份额 |
| [`hbond_lifetime`](#hbond_lifetime) | donor, hydrogen, acceptor | 同上、`tau_max_ps`、`intermittency`、`window_step` | 存活曲线、1/e 交叉 |
| [`msd`](#msd) | group | `msd_type`、`fft` | MSD 曲线 |
| [`velocity`](#velocity) | group, ref | `dim`、`vdim`、`bin_width`、`grouping`、`sym` | 速度剖面 |

统一约定：表头稳定 ASCII，单位在列名/文档中；`--lang` 只改图内文字，不改列名或数值。

<a id="density"></a>

## density

- 输入：一个原子组；
- 参数：`delta`（网格宽 Å）、`sum_axis`（x/y/z）；
- 输出：`{a}_angstrom`、`{b}_angstrom`、`number_density_A3`（Å⁻³）；
- 含义：三维网格上的数密度沿 `sum_axis` 求和后，除以该方向格数，得到沿轴平均的数密度；不是柱密度；
- 限制：只支持正交盒；x/y 必须周期，z 可非周期（`ppf/pps`），非周期 z 不 wrap。网格按首帧盒子建立；盒子变化时只使用首帧并警告。三斜盒或非周期 x/y 会被拒绝。

<a id="lineardensity"></a>

## lineardensity

- 输入：一个原子组；
- 参数：`binsize`（Å）、`dim`（x/y/z）；
- 输出：`lineardensity_x/y/z` 三张表，列为 `{axis}_angstrom`、`mass_density_g_cm3`、`charge_density_e_A3`；
- 含义：沿各轴的质量密度和电荷密度；电荷单位是 e/Å³；
- 限制：只支持正交盒；x/y 必须周期，z 可非周期（`ppf/pps`），非周期 z 不 wrap。固定盒；盒子变化时只使用首帧并警告；每个轴用自己的盒长和 `floor(L/binsize)` 个 bin。

<a id="rdf"></a>

## rdf

- 输入：a、b 两个原子组；
- 参数：`range`（Å）、`nbins`；
- 输出：`r_angstrom`、`g_r`；
- 含义：两组原子间的径向分布函数，`g_r` 无量纲；
- 限制：当前 RDF 插件要求正交全周期盒（见插件声明）；`range` 上限按**整个实际窗口**的最短盒长检查，不是当前读取器偶然帧；不计算配位数；tiny 的尖峰包含分子内相关。

<a id="hbond"></a>

## hbond

- 输入：供体重原子、氢、受体重原子；当前库路径要求全周期盒，非周期输入会被拒绝。
- 参数：`d_a_cutoff`（供体-受体距离上限 Å）、`d_h_a_angle_cutoff`（D-H-A 角下限，度）；
- 输出：
  - `hbond_count`：`frame`、`time_ps`、`hbond_count`；
  - `hbond_summary`：`n_frames`、`mean_hbonds`、`std_hbonds`、`per_donor_atom`、`per_donor_residue`；
  - `hbond_occupancy`：`donor`、`hydrogen`、`acceptor`、`frames_present`、`occupancy`（按三元组统计，`occupancy = frames_present / n_frames`）；
- 归一化：`per_donor_atom` 除供体原子数，`per_donor_residue` 除供体残基数；不再有含糊的“每分子”；
- 氢键身份：占有率的“同一个氢键”按供体-氢-受体三元组；`hbond_lifetime` 按 H-受体对，两者不同。

<a id="hbond_type"></a>

## hbond_type

- 输入：供体重原子、氢、受体重原子；需要先配置 `naming`；当前库路径要求全周期盒。
- 参数：同 hbond，另 `figure_axis`（`rate` 每帧平均 / `total` 总次数）；
- 输出：`donor`、`acceptor`、`count`、`per_frame`、`share`；
- 限制：没有 `naming` 时类型标签无法映射到元素/分子；空表时合法跳图并给出原因。

<a id="hbond_lifetime"></a>

## hbond_lifetime

- 输入：供体重原子、氢、受体重原子；当前库路径要求全周期盒。
- 参数：同 hbond，另 `tau_max_ps`、`intermittency`、`window_step`；
- 输出：
  - `hbond_lifetime`：`lag_ps`、`continuous`、`intermittent`；
  - `hbond_lifetime_summary`：`criterion`、`tau_1e_ps`、`tolerance_frames`、`note`；
- 含义：`tau_1e_ps` 是存活曲线首次降到 1/e 的线性插值时间，不是指数拟合寿命；`note` 说明是否达到 1/e；
- 身份：库按 H-受体对识别同一个氢键；
- 限制：采样必须足够密；tiny 的 5 ps/帧太粗，程序会提示寿命不可信。

<a id="msd"></a>

## msd

- 输入：一个原子组；
- 参数：`msd_type`（xyz/xy/x 等）、`fft`（是否用 FFT，默认需要 tidynamics）；
- 输出：`dt_ps`、`msd_A2`；
- 含义：均方位移；时间轴按全局帧号 × 帧间隔，不跟随 TIMESTEP 重置；
- 限制：只输出曲线，不拟合扩散系数；`continuous` 对 `x/xs` 包裹坐标只支持固定盒矩阵并逐帧展开，`xu/xsu` 按输入定义；采样需足够密。

<a id="velocity"></a>

## velocity

- 输入：计算组、参考组；
- 参数：`dim`、`vdim`、`bin_width`、`grouping`（atoms/residues/segments/molecules）、`sym`；
- 输出：`{axis}_angstrom`、`v{vdim}_A_per_ps`、`error_A_per_ps`；
- 含义：按原盒坐标逐帧分箱的实验室系速度；当前要求正交盒且 x/y 周期，z 可非周期（`ppf/pps`）；参考组只记录质心到 meta，不改变速度或坐标参考系；
- 统计：每个统计单元每帧的观测作为一个样本；`profile = mean(v_i)`，`error = sqrt(sample_variance / N)`，N<2 时缺失；
- `sym`：对相反 bin 的 profile/error 做现有算术平均，不是样本翻倍；
- 限制：误差未校正时间相关性，不声称适合论文级置信区间；空 bin 为 NaN，图上断线。

## 列与单位

| 分析 | 列 | 单位 |
|---|---|---|
| density | `number_density_A3` | Å⁻³ |
| lineardensity | `mass_density_g_cm3` / `charge_density_e_A3` | g·cm⁻³ / e·Å⁻³ |
| rdf | `r_angstrom` / `g_r` | Å / — |
| hbond | `time_ps` / `hbond_count` / `occupancy` | ps / 个 / — |
| hbond_type | `count` / `per_frame` / `share` | 个 / 个·帧⁻¹ / — |
| hbond_lifetime | `lag_ps` / `tau_1e_ps` | ps |
| msd | `dt_ps` / `msd_A2` | ps / Å² |
| velocity | `v*_A_per_ps` / `error_A_per_ps` | Å·ps⁻¹ |

`x_angstrom/y_angstrom/z_angstrom` 是盒局部位置列；`r_angstrom` 是距离，不是盒坐标，不能加盒原点平移；`dt_ps`/`lag_ps` 是时间。`--aligned` 只对位置列施加视图平移，`replot` 使用原表，不用 aligned 副本。

下一步：[多体系对比](compare.md) 或 [排错](troubleshooting.md)。
