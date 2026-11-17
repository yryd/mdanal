# 分析审计记录

本文件是分析的"算术规格"：每个输出列/图的公式、单位、依据与状态，以及修正前后对照。
方法：列输出 → 对库文档/源码 → 可手算的小体系核对 → 修错 → 改标签 → 留证据。

## 口径决策

| 问题 | 采用 | 说明 |
|---|---|---|
| 密度投影语义 | 沿轴平均密度，Å⁻³ | 除数是该轴格数 `N_k`，不是体积 |
| 电荷密度单位 | `e/Å³` | 电荷 / bin 体积（不再用库的 `e·mol·cm⁻³`） |
| 氢键归一化 | `per_donor_atom` + `per_donor_residue` | 删除含糊的 `per_molecule` |
| 变盒子（NPT） | 检测并警告，只用首帧 | `density`、`lineardensity` 多帧平均只在固定盒窗口成立 |
| 氢键寿命 | 改名 `tau_1e_ps` | 只改名称与文档，不改算法 |
| 速度参考系 | 审计后定 | 优先逐帧参考质心；否则文档写明固定偏移 |

## 环境

- MDAnalysis 2.10.0；numpy 2.4.6；pandas 3.0.5；matplotlib 3.11.1；tidynamics 1.1.2
- 修正前基线：`/tmp/mdanal-audit-base`（13 张表、8 张图），哈希见 `docs/audit-baseline.sha256`

## 标签审计（A1）

| 分析 | 表头 | 图内中英 | COMPARE 列标签 | 结论 |
|---|---|---|---|---|
| density | `{a}_angstrom`、`{b}_angstrom`、`number_density_A3` | 键集合一致 | 无（二维图不参与对比） | 公式修正后复核 |
| lineardensity | `{axis}_angstrom`、`mass_density_g_cm3`、`charge_density_e_A3` | 一致 | 有 | 已改电荷单位 |
| rdf | `r_angstrom`、`g_r` | 一致 | 有 | 待核对归一化 |
| hbond | `frame`、`time_ps`、`hbond_count`；`n_frames`、`mean_hbonds`、`std_hbonds`、`per_donor_atom`、`per_donor_residue`；`donor`、`hydrogen`、`acceptor`、`frames_present`、`occupancy` | 一致 | 有 | 已改归一化列名 |
| hbond_type | `donor`、`acceptor`、`count`、`per_frame`、`share` | 一致 | 无 | 待交叉核对 |
| hbond_lifetime | `lag_ps`、`continuous`、`intermittent`；`criterion`、`tau_1e_ps`、`tolerance_frames`、`note` | 一致 | 有 | 已改 `tau_1e_ps` |
| msd | `dt_ps`、`msd_A2` | 一致 | 有 | 待解析核对 |
| velocity | `{axis}_angstrom`、`v{vdim}_A_per_ps`、`error_A_per_ps` | 一致 | 有 | 误差列确认是标准误 |

结论：8 个分析的 `LABELS` 中英键集合一致；表头与 `COMPARE`/`COLUMN_LABELS` 对齐；
待 A3/A4 的列名变更会同步 README 与 `COLUMN_LABELS`。

## 审计表

### density

| 输出 | 公式（当前） | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{a}_angstrom`, `{b}_angstrom` | 网格格心（盒坐标） | Å | MDAnalysis `Density.edges` | 正确 |
| `number_density_A3` | `Σ_k ρ / N_k` | Å⁻³ | 精确铺满盒长的三维直方图 + 投影平均 | **已修**：delta 为目标分辨率，实际格宽 `L/ceil(L/delta)`；delta=1/2 均守恒 |
| 网格范围 | `ceil(L/delta)` 格，坐标按盒折回 | Å | 自实现 | **已修**：未包裹坐标不再丢原子 |
| 变盒子 | 检测后只用首帧 | — | `_fixed_box_stop` | **已改**：多帧 + 变盒 → 警告并只用首帧 |

修正前：delta=1 积分 499/504；delta=2 积分 62.9/504。修正后两者均为 504（浮点误差 <1e-5）。

### lineardensity

| 输出 | 公式（当前） | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{axis}_angstrom` | 直方图 bin 中心 | Å | 自实现逐帧直方图 | 正确 |
| `mass_density_g_cm3` | `Σ_frames m_hist / n / (N_A·1e-24·V_bin)` | g·cm⁻³ | 质量 amu、V_bin Å³ | 固定盒/整除时正确 |
| `charge_density_e_A3` | `Σ_frames q_hist / n / V_bin` | e·Å⁻³ | 电荷 e + bin 体积 Å³ | **已修**：不再乘 Avogadro |
| `V_bin` | `L_i·L_j·L_k / floor(L_i/binsize)` | Å³ | 逐轴直方图 | **已修**：逐轴自己的 bin 数 |
| 变盒子 | 检测后只用首帧 | — | `_fixed_box_stop` | **已改**：警告并只用首帧 |

修正后单帧结果与独立 `numpy.histogram` 逐点一致（含 g/cm³ 与 e/Å³ 换算）。

### rdf

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `r_angstrom` | `InterRDF` 的 bin 中心 | Å | `results.edges` | **已核对** |
| `g_r` | `InterRDF.results.rdf` | 无量纲 | MDAnalysis 文档 | **已核对**：理想气体 g(r)≈1（实测 1.05）；`exclusion_block=(1,1)` 排除自配对 |

半盒检查已有；新增理想气体解析测试。

### hbond

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `frame` / `time_ps` / `hbond_count` | 每帧 `count_by_time()`；时间 = 帧号×dt | — / ps / 个 | MDAnalysis | 正确（待选择串修复） |
| `frames_present` / `occupancy` | 按 `(donor,hydrogen,acceptor)` 分组计数 / n_frames | 帧 / — | 自实现 | 正确 |
| `n_frames` / `mean_hbonds` / `std_hbonds` | 计数序列统计 | — / 个 | 自实现 | 正确 |
| `per_donor_atom` | `mean / 供体原子数` | — | 自实现 | **已修** |
| `per_donor_residue` | `mean / 供体残基数` | — | 自实现 | **新增** |
| 选择 | 解析后原子组的 `bynum` 索引，`update_selections=False` | — | 自实现 | **已修**：不再按库自己的坐标重选 |

修正前 `per_molecule` 除的是供体原子数（70.1/144=0.487）；修正后分别给原子/残基两列。

### hbond_type

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `count` | `count_by_type()` 按类型汇总 | 个 | MDAnalysis | **已核对**：总和等于 hbond 计数 |
| `per_frame` | `count / n_frames` | 个/帧 | 自实现 | **已核对** |
| `share` | `count / Σcount` | — | 自实现 | **已核对**：求和为 1 |

### hbond_lifetime

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `lag_ps` | `lifetime()` 的 τ（帧）× dt | ps | MDAnalysis | 正确 |
| `continuous` / `intermittent` | 存活曲线 C(τ) | — | MDAnalysis | 正确 |
| `tau_1e_ps` | 首次 C(τ)≤1/e 的线性插值 | ps | 自实现 | **已改名**（原 `lifetime_ps`） |
| 氢键身份 | lifetime 按 H–受体对 | — | MDAnalysis 文档 | 与 occupancy 的三元组不同，README 已写明 |

### msd

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `dt_ps` | 全局帧号 × 帧间隔 | ps | 加载层统一 | **已修**：不再跟随 TIMESTEP 重置 |
| `msd_A2` | `results.timeseries` | Å² | MDAnalysis | **已核对** |

### velocity

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{axis}_angstrom` | 逐帧按原盒坐标分箱后的 bin 中心 | Å | 自实现 | **已修**：不再用 MAICoS 的参考框架坐标 |
| `v{vdim}_A_per_ps` | 逐帧实验室系速度的 bin 平均 | Å·ps⁻¹ | 自实现 | **已核对**：匀速/非均匀场 |
| `error_A_per_ps` | 逐帧样本的标准误（未做相关时间校正） | Å·ps⁻¹ | 自实现 | **已核对**：匀速时为 0 |

盒子变化时按首帧参考盒坐标平均并警告；参考组只记入 meta，不参与分箱或速度相减。
`velocity.meta` 另记录 `averaging=pooled_unit_samples`、`error_method=naive_sample_sem_without_time_correlation_correction`、
`reference_role=metadata_only`，与代码口径一致。

## 修正前后记录

| 分析 | 项目 | 修正前 | 修正后 | 原因 |
|---|---|---|---|---|
| density | delta=1 守恒 | 499/504 | 504.000003 | 未包裹坐标折回 + 投影除格数 |
| density | delta=2 守恒 | 62.9/504 | 504.000000 | 投影除数由体积改为格数 |
| density | 变盒子 | 静默按首帧网格 | 警告 + 只用首帧 | 固定盒前提 |
| lineardensity | 电荷单位 | e·mol·cm⁻³（×0.6022） | e/Å³ | 电荷/体积 |
| lineardensity | bin 体积 | 全局最大盒长 | 逐轴 bin 数 | 非整除/非立方一致 |
| lineardensity | 变盒子 | 静默用首帧体积 | 警告 + 只用首帧 | 固定盒前提 |
| hbond | 选择 | 原始选择串（按库坐标重选） | 解析组的 bynum 索引 | 视图平移一致性 |
| hbond | 归一化 | `per_molecule`（除供体原子数） | `per_donor_atom` + `per_donor_residue` | 含义明确 |
| hbond_lifetime | 列名 | `lifetime_ps` | `tau_1e_ps` | 1/e 交叉不是拟合寿命 |
| velocity | 坐标原点 | 首帧参考组质心 | 平均盒长/2（盒坐标） | `bin_pos` 是相对盒心，不是相对参考组 |
| rdf | 归一化 | 未验证 | 理想气体 g≈1 | 解析核对 |
| msd | 时间轴 | 未验证 | 匀速 MSD=(v·Δt)² | 解析核对 |


## 审计完成状态

| 分析 | 状态 | 测试文件 | 用例数 |
|---|---|---|---|
| density | 已修（Δ³、边缘、变盒警告） | `tests/analyses/test_density.py` | 3 |
| lineardensity | 已修（e/Å³、逐轴 bin、变盒警告） | `tests/analyses/test_lineardensity.py` | 3 |
| rdf | 已核对（理想气体 g≈1） | `tests/analyses/test_rdf.py` | 2 |
| hbond | 已修（选择串、归一化） | `tests/analyses/test_hbond.py` | 4 |
| hbond_type | 已核对（总数/份额） | `tests/analyses/test_hbond_type.py` | 2 |
| hbond_lifetime | 已改名 + 文档（1/e 交叉） | `tests/analyses/test_hbond_lifetime.py` | 2 |
| msd | 已修时间轴 + 已核对（匀速解析） | `tests/analyses/test_msd.py` | 5 |
| velocity | 已改为原盒坐标分箱 | `tests/analyses/test_velocity.py` | 7 |

相对修正前基线的输出变化（9 项）：

```
density-xy/tables/density_xy.csv
density-xy/figures/density_xy.png
lineardensity/tables/lineardensity_{x,y,z}.csv
lineardensity/figures/lineardensity_z.png
hbond/tables/hbond_summary.csv
hbond_lifetime/tables/hbond_lifetime_summary.csv
velocity/tables/velocity.csv
```

其余表与图逐字节不变。审计轮验收：`pytest` 80 条、`pytest tests/analyses` 28 条；绘图/F 轮后全套 141 条通过，色板轮后 145 条，坐标轮后默认 118 + 科学 41；
`check-analysis --system tests/fixtures/tiny` 通过（density/lineardensity 会给出变盒警告）。

剩余限制（本轮不处理）：

- 变盒子时 `density`/`lineardensity` 只用首帧（警告），不做逐帧体积加权；
- 三斜盒直接拒绝；
- `tau_1e_ps` 是 1/e 交叉时间，不做指数拟合与误差估计；
- `hbond_lifetime`（H–受体对）与 `hbond_occupancy`（三元组）的身份定义不同；
- `velocity` 的盒子变化时坐标按平均盒长换算，跨帧比较需注意。


## 框架修复（审计后）

| 问题 | 修复 | 回归 |
|---|---|---|
| 多段续跑 TIMESTEP 归零导致 MSD 时间轴不一致 | 加载层统一 `ts.time = 全局帧号 × 帧间隔`；内存/读盘同源 | `test_frame_times_ignore_timestep_reset`、`test_segmented_reset_steps_keep_frame_time` |
| 双列/缩放坐标的判断与读取器不一致 | 扫描全部约定并按视图显式传 `lammps_coordinate_convention`；连续视图用显式包装器逐帧展开，回退从 0 重放 | `test_scan_matches_reader_coordinate_precedence`、`test_dual_coordinate_columns_use_unwrapped`、`test_wrapped_no_bond_continuous_view` |
| velocity 的参考组居中坐标被误当盒坐标 | 改为逐帧按原盒坐标分箱，实验室系速度；参考组只记 meta | `test_nonuniform_profile_uses_box_coordinates`、`test_moving_reference_does_not_shift_profile` |
| compare 覆盖输入目录的溯源 | 输出与输入目录重叠时先失败；非空输出需 `--force` | `test_compare_refuses_to_write_into_input_directory`、`test_compare_refuses_nonempty_output_without_force` |
| 依赖声明缺 `tidynamics`、MDAnalysis 下限过低 | `MDAnalysis>=2.10`、`tidynamics>=1.1`；velocity 不再需要 maicos | 安装声明 |
