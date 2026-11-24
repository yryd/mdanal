# contact

产物是两个**单曲线**产品：

- `contact-count`：每帧分子对接触数；
- `contact-coordination`：按 `first` 组每个分子的平均接触数。

## 口径

- `first` / `second` 是 source 的 group；
- 每个 residue 视为一个分子；
- 只接受完整分子；部分分子直接报错；
- `mode: com`：分子质心距离 ≤ `cutoff` 算接触；
- 自接触只取上三角，不重复计数；
- 不同组配位数 = `N / N_first`；
- 自接触配位数 = `2N / N_first`。

## 分块平均

`compute.block_ps`：

- `0`：逐帧；
- `> 0`：按块平均；
- 首尾点强制落在窗口起止时间，值取第一块/最后一块均值；
- 块宽按帧间隔取整，实际块宽记录在表中。

## 边界

- 第一版只有 `mode: com`；
- 不做 Q；
- 不做 stack；stack 是平台合成；
- 不做接触寿命；
- TMA⁻/TMA⁰ 由 source 的 groups 定义，不由本包识别。
