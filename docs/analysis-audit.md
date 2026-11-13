# 分析审计记录

本文件是分析的"算术规格"：每个输出列/图的公式、单位、依据与状态，以及修正前后对照。
方法：列输出 → 对库文档/源码 → 可手算的小体系核对 → 修错 → 改标签 → 留证据。

## 口径决策

| 问题 | 采用 | 说明 |
|---|---|---|
| 密度投影语义 | 沿轴平均密度，Å⁻³ | 除数是该轴格数 `N_k`，不是体积 |
| 电荷密度单位 | `e/Å³` | 由库的 `e·mol·cm⁻³` 乘 `N_A×1e-24 = 0.6022` |
| 氢键归一化 | `per_donor_atom` + `per_donor_residue` | 删除含糊的 `per_molecule` |
| 变盒子（NPT） | 检测并拒绝 | `density`、`lineardensity` 只支持固定盒子 |
| 氢键寿命 | 改名 `tau_1e_ps` | 只改名称与文档，不改算法 |
| 速度参考系 | 审计后定 | 优先逐帧参考质心；否则文档写明固定偏移 |

## 环境

- MDAnalysis 2.10.0；numpy 2.4.6；pandas 3.0.5；matplotlib 3.11.1；maicos 0.12
- 修正前基线：`/tmp/mdanal-audit-base`（13 张表、8 张图），哈希见 `docs/audit-baseline.sha256`

## 标签审计（A1）

| 分析 | 表头 | 图内中英 | COMPARE 列标签 | 结论 |
|---|---|---|---|---|
| density | `{a}_angstrom`、`{b}_angstrom`、`number_density_A3` | 键集合一致 | 无（二维图不参与对比） | 公式修正后复核 |
| lineardensity | `{axis}_angstrom`、`mass_density_g_cm3`、`charge_density_e_mol_cm3` | 一致 | 有 | A3 改电荷单位 |
| rdf | `r_angstrom`、`g_r` | 一致 | 有 | 待核对归一化 |
| hbond | `frame`、`time_ps`、`hbond_count`；`n_frames`、`mean_hbonds`、`std_hbonds`、`per_molecule`；`donor`、`hydrogen`、`acceptor`、`frames_present`、`occupancy` | 一致 | 有 | A4 改归一化列名 |
| hbond_type | `donor`、`acceptor`、`count`、`per_frame`、`share` | 一致 | 无 | 待交叉核对 |
| hbond_lifetime | `lag_ps`、`continuous`、`intermittent`；`criterion`、`lifetime_ps`、`tolerance_frames`、`note` | 一致 | 有 | A4 改 `tau_1e_ps` |
| msd | `dt_ps`、`msd_A2` | 一致 | 有 | 待解析核对 |
| velocity | `{axis}_angstrom`、`v{vdim}_A_per_ps`、`error_A_per_ps` | 一致 | 有 | 误差列确认是标准误 |

结论：8 个分析的 `LABELS` 中英键集合一致；表头与 `COMPARE`/`COLUMN_LABELS` 对齐；
待 A3/A4 的列名变更会同步 README 与 `COLUMN_LABELS`。

## 审计表

### density

| 输出 | 公式（当前） | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{a}_angstrom`, `{b}_angstrom` | 网格格心（盒坐标） | Å | MDAnalysis `Density.edges` | 正确 |
| `number_density_A3` | `Σ_k ρ_grid / (Δa·Δb·L_k)` | Å⁻³ | 库网格已是 Å⁻³ | **错误**：应为 `Σ_k ρ_grid / N_k`；delta≠1 时低 Δ³ |
| 网格范围 | `gridcenter=L/2`, `padding=0` | — | — | **边缘丢原子**：delta=1 实测 499/504 |
| 变盒子 | 网格固定首帧 | — | — | **错误**：后续帧原子出格 |

已知证据：delta=1 积分 499/504；delta=2 积分 62.9/504（低 8 倍）。
计划：改除数为 `N_k`、加 `padding=delta`、逐帧检查盒尺寸并拒绝变盒子。

### lineardensity

| 输出 | 公式（当前） | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{axis}_angstrom` | 直方图 bin 中心 | Å | 自实现逐帧直方图 | 正确 |
| `mass_density_g_cm3` | `Σ_frames m_hist / n / (N_A·1e-24·V_bin)` | g·cm⁻³ | 质量 amu、V_bin Å³ | 固定盒/整除时正确 |
| `charge_density_e_mol_cm3` | 同上，权重为电荷 e | e·mol·cm⁻³ | MDAnalysis 文档口径 | **口径待换**：物理值为 ×0.6022 的 e/Å³ |
| `V_bin` | `volume / bins[axis]`，直方图上界用 `max(L)` | Å³ | 沿用库的全局上界 | **非整除/非立方时不一致** |
| 变盒子 | 首帧固定 `volume/bins` | — | — | **错误** |

计划：电荷换 `e/Å³`；逐轴 `upper=L_axis`、`nbins=floor(L_axis/binsize)`；变盒子拒绝。

### rdf

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `r_angstrom` | `InterRDF` 的 bin 中心 | Å | `results.edges` | 待核对 |
| `g_r` | `InterRDF.results.rdf` | 无量纲 | MDAnalysis 文档 | 待核对（理想气体 g≈1） |

半盒检查已有：`range` 上限超过半盒长时报错。计划：补理想气体解析测试。

### hbond

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `frame` / `time_ps` / `hbond_count` | 每帧 `count_by_time()`；时间 = 帧号×dt | — / ps / 个 | MDAnalysis | 正确（待选择串修复） |
| `frames_present` / `occupancy` | 按 `(donor,hydrogen,acceptor)` 分组计数 / n_frames | 帧 / — | 自实现 | 正确 |
| `n_frames` / `mean_hbonds` / `std_hbonds` | 计数序列统计 | — / 个 | 自实现 | 正确 |
| `per_molecule` | `mean / donor.n_atoms` | — | 自实现 | **错误**：除的是供体原子数 |
| 选择 | 传原始选择串给库 | — | 库构造参数 | **错误**：绕过视图平移 |

计划：改原子组/索引；`per_donor_atom` + `per_donor_residue`；补视图平移测试。

### hbond_type

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `count` | `count_by_type()` 按类型汇总 | 个 | MDAnalysis | 待与 hbond 总数交叉核对 |
| `per_frame` | `count / n_frames` | 个/帧 | 自实现 | 待核对分母 |
| `share` | `count / Σcount` | — | 自实现 | 待核对（求和为 1） |

### hbond_lifetime

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `lag_ps` | `lifetime()` 的 τ（帧）× dt | ps | MDAnalysis | 正确 |
| `continuous` / `intermittent` | 存活曲线 C(τ) | — | MDAnalysis | 正确 |
| `lifetime_ps` | 首次 C(τ)≤1/e 的线性插值 | ps | 自实现 | **命名误导**：应叫 `tau_1e_ps` |
| 氢键身份 | lifetime 按 H–受体对 | — | MDAnalysis 文档 | 与 occupancy 的三元组不同，需写明 |

### msd

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `dt_ps` | `results.delta_t_values` | ps | MDAnalysis | 待解析核对 |
| `msd_A2` | `results.timeseries` | Å² | MDAnalysis | 待解析核对（匀速 MSD=v²t²） |

### velocity

| 输出 | 公式 | 单位 | 依据 | 状态 |
|---|---|---|---|---|
| `{axis}_angstrom` | `bin_pos` + 首帧参考组质心 | Å | MAICoS | **口径待确认**：参考组漂移时是固定偏移 |
| `v{vdim}_A_per_ps` | `results.profile` | Å·ps⁻¹ | MAICoS | 待核对 |
| `error_A_per_ps` | `results.dprofile`（标准误） | Å·ps⁻¹ | MAICoS | 标签需写明标准误 |

## 修正前后记录

（每完成一个分析，在此追加：列/数值、修正前、修正后、原因、对应提交。）
