# hbond

## 分析目的

按供体、氢、受体三个选择统计每帧氢键数、汇总和氢键对占有率。

## 输入与前提

槽位为 donor / hydrogen / acceptor；默认 `d_a_cutoff=3.5 Å`、`d_h_a_angle_cutoff=150°`。当前只支持全周期盒；非周期输入仍按 HBA 周期路径计算，meta 会记录 `effective_pbc` 和 `geometry_status=unsupported_geometry`，结果不能当作非周期氢键。

## 科学定义

每帧由 MDAnalysis HydrogenBondAnalysis 判定供体-氢-受体是否满足距离和角度；occupancy 按 D–H–A 三元组统计。

## 输出

- `hbond_count`：frame、time_ps、hbond_count。
- `hbond_summary`：n_frames、mean_hbonds、std_hbonds、per_donor_atom、per_donor_residue。
- `hbond_occupancy`：donor、hydrogen、acceptor、frames_present、occupancy。

## 参数与单位

距离 Å，角度度；`occupancy = frames_present / n_frames`；`per_donor_*` 分别除以供体原子数和残基数。

## 注意

同一判据的 hbond / hbond_type / hbond_lifetime 共享同一次 HBA 结果；不同阈值或帧窗口不能共享。
