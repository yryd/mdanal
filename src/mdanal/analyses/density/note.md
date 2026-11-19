# density

## 图包目的

一个 `density` 图包，两个产品：

- `density-2d`：三维数密度 → 二维投影，`plot.plane` 选择 `xy/xz/yz`；
- `density-line`：沿一个轴的质量/电荷线密度，`plot.axis` 选择 `x/y/z`。

## 输入与前提

槽位 `group`；`delta` 为 3D 网格目标边长，`binsize` 为线密度直方图宽度。固定正交盒；变盒时只用首帧并警告。

## 一次计算

`density` 的 compute 一次产出：

- `density_xy`、`density_xz`、`density_yz`（三个投影）；
- `lineardensity_x/y/z`（三条线密度）。

切换 `plot.plane`/`plot.axis` 不重算 3D 网格。

## 输出

- 投影表：两个盒坐标轴 + `number_density_A3`；
- 线密度表：轴坐标 + `mass_density_g_cm3` + `charge_density_e_A3`。

## 注意

`density-2d` 是 field，不可 compare；多体系对比用多个 Panel 并排。`cmap/colors/vmin/vmax` 是分析参数，不是 `plot.palette`。
