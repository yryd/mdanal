# 首次使用

目标：不读源码，先跑通一张图，再换语言/格式，最后知道自己的数据要改哪些字段。

## 1. 安装

要求 Python 3.10+、MDAnalysis 2.10+、NumPy、pandas、Matplotlib、PyYAML、SciencePlots、tidynamics。

```bash
pip install -r requirements.txt
pip install -e .        # 可选；不安装就运行 python main.py
```

中文图需要 `Noto Serif CJK SC`。缺失时 `run` 会报“缺少字体”。检查：

```bash
python -c "from mdanal.plot.chart import missing_fonts; print(missing_fonts())"
```

字体安装见 [排错：字体](troubleshooting.md#字体)。

## 2. 用仓库数据跑第一张图

`example/quickstart/system.yaml` 只启用一个 MSD，并引用仓库自带的 tiny 数据：

```bash
python main.py check --system example/quickstart
python main.py run   --system example/quickstart --out /tmp/mdanal-demo --force
```

第二条命令会打印：

```text
[01] msd                表 1 张，图 1 张
输出：/tmp/mdanal-demo
```

打开 `/tmp/mdanal-demo/msd/figures/msd.png`。图来自真实运行，但 tiny 的 MSD 短且噪声大，只用于演示流程，不要当作物理结论。

### 输出结构

```text
/tmp/mdanal-demo/
├── manifest.csv
├── provenance.json
└── msd/
    ├── plot.json          # 重绘所需的快照，不要手改
    ├── tables/msd.csv
    └── figures/msd.png
```

表的前几行：

```text
dt_ps,msd_A2
0,-5.98e-12
5,5.83
10,4.98
15,4.41
```

`dt_ps` 是滞后时间（ps），`msd_A2` 是均方位移（Å²）。第一行接近 0 的负数来自浮点舍入。

### `check` 和 `run` 的区别

`check` 会加载体系、解析选择、检查依赖和输出路径，但**不执行分析计算**；它仍然会读轨迹和盒子，不是纯 YAML 语法检查。

## 3. 不重算，改语言和格式

```bash
python main.py replot --from /tmp/mdanal-demo --out /tmp/mdanal-demo-en \
  --lang en --format svg --config example/recipes/plot-en.yaml
```

结果：

```text
/tmp/mdanal-demo-en/
├── replot.json
└── msd/figures/msd.svg
```

SVG 示例：[quickstart-msd-en.svg](assets/quickstart-msd-en.svg)。

`replot` 只读 `plot.json` 和 CSV，不加载轨迹。中文/英文、PNG/SVG/PDF、标题、范围、颜色和标注都属于这一层。

## 4. 换成自己的数据

复制 `example/quickstart/system.yaml` 到自己的算例目录，至少改这些字段：

```yaml
topology: ../path/to/data.lmp
trajectory: ../path/to/run.lammpstrj
timestep_fs: 1.0        # 自己的 LAMMPS 时间步（fs）
dump_every: 5000        # 每多少步写一帧
frames: [0, 100]        # 左闭右开
groups:
  tma: "all"            # 名字自取，选择串来自自己的体系
analyses:
  - name: msd
    sel: [tma]
```

- **时间**：`帧间隔 = dump_every × timestep_fs`。例如 `1 fs × 5000 = 5 ps/帧`；帧号、LAMMPS 步号和时间不是一回事。
- **选择**：`type`/`resid` 编号来自你的 LAMMPS 数据；示例里的编号不能照搬。可以先 `python main.py list --system DIR` 看分组和选择数。
- **窗口**：`frames` 是左闭右开；每条分析还可以用 `section: [起, 止]` 在窗口内再切一段。
- **参数**：`nbins`、`dim`、`delta` 等写在分析条目这一层，不要加 `params:` 包裹层；呈现设置放在 `plot`。

改完先跑：

```bash
python main.py check --system /path/to/your/system.yaml
```

看到选择数、帧窗口和依赖都符合预期，再 `run`。

<a id="tiny-示例的边界"></a>

## 5. tiny 示例的边界

本手册的示例图由 tiny 生成。它会在 `provenance.json` 里留下真实警告：

- `density`/`lineardensity`：盒子在变，只使用首帧；
- `hbond_lifetime`：5 ps 的帧间隔太大，寿命结果不可信；
- `msd`：只有 20 帧，曲线噪声大。

这些警告是正确行为，不是“示例跑坏了”。要得到可靠数值，换合适的采样数据，或只把图当作流程演示。

下一步：[输入与配置](configuration.md) 或 [绘图与重绘](plotting.md)。
