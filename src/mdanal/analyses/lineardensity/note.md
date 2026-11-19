# lineardensity

## 分析目的

沿 x/y/z 三个方向计算质量线密度和电荷线密度。

## 输入与前提

一个 group；`binsize` 为直方图宽度。固定正交盒；变盒时只用首帧并警告。非周期方向落在盒外的原子会警告且不进入直方图。

## 输出

每个方向一张表：`{axis}_angstrom`、`mass_density_g_cm3`、`charge_density_e_A3`。

## 注意

一次 run 输出三个方向；质量/电荷是同一批直方图的两种归一化，不是两次轨迹扫描。
