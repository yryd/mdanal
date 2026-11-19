# velocity

## 分析目的

按盒坐标分箱计算实验室系速度剖面。

## 输入与前提

group 和 ref 两个槽位；ref 只记录质心元数据，不改变速度参考系。需要速度列；`dim` 为剖面法向轴，`vdim` 为速度分量，`bin_width` 为分箱宽度，`grouping` 为 atoms/residues/segments/molecules；`sym` 对反向 bin 做对称化。

## 输出

`velocity`：`{axis}_angstrom`、`v{vdim}_A_per_ps`、`error_A_per_ps`。

## 注意

误差是逐帧样本的简单 SEM，未校正时间相关性；三斜盒/非支持几何结果仅供定性参考。
