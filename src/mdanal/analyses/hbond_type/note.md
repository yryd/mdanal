# hbond_type

## 分析目的

统计供体类型到受体类型的氢键次数、每帧速率和占比。

## 输入与前提

三个槽位与 hbond 相同；需要 `naming` 提供残基名和元素，用于 donor/acceptor 类型标签。几何前提同 hbond。

## 输出

`hbond_type`：donor、acceptor、count、per_frame、share。count 是窗口内总次数，per_frame 是除以帧数，share 是当前类型占全部氢键的比例。

## 注意

类型由分子名和元素组成；命名规则覆盖文件名字时会记录警告。full HBA 结果与 hbond/hbond_lifetime 共享。
