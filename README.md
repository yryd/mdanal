# mdanal

通用 MD 分析层：读体系目录下的 `system.yaml`，调用 MDAnalysis 与已注册插件完成分析，输出数据表与图件。

程序内不实现分析算法——每个物理量都对应一次库调用。设计说明见 `process/plan/mdanal-spec.md`。

---

## 1 它做什么、不做什么

**做**：一个体系、一次运行、若干种分析；自动处理包裹、时间单位、速度单位、分子编号；每张表与图落在独立子目录，附清单与溯源。

**不做**：跨体系批量；库里没有的量（应力、界面几何、三维速度场、温度剖面）；交互式图；逐帧氢键明细。

---

## 2 安装

```bash
conda activate go_analysis
pip install -r requirements.txt          # 或 requirements-dev.txt（含 pytest）
pip install -e .                         # 可选：装好后任意目录可用 mdanal 命令
```

| 包 | 用途 |
|---|---|
| MDAnalysis ≥ 2.8 | 轨迹读取与全部分析 |
| numpy / pandas / matplotlib | 计算与绘图 |
| PyYAML | 读取配置 |
| scienceplots | 绘图样式（`science` + `retro`） |
| maicos ≥ 0.12 | **仅 velocity 分析需要**，不装也能跑其余五个 |

中文字体使用系统自带的 `Noto Serif CJK SC`。

---

## 3 五分钟上手

```bash
# 1. 复制模板到算例目录
cp example/system.yaml /path/to/your/run/

# 2. 改三处：trajectory 文件名、frames 窗口、groups 选择串
#    （topology/trajectory 留空也行，会在同目录唯一查找）

# 3. 先校验，再运行
python main.py check --system /path/to/your/run
python main.py run   --system /path/to/your/run --out /path/to/your/run/results/mdanal

# 4. 看结果
ls /path/to/your/run/results/mdanal
```

`check` 会加载轨迹、解析每条分析的原子选择并打印原子数，但不做任何计算；`run` 才会真正计算。

---

## 4 三份配置怎么分工

| 文件 | 位置 | 管什么 |
|---|---|---|
| `defaults.yaml` | 程序内 `src/mdanal/` | 语言、dpi、画布尺寸、默认是否标注 |
| `analyses.yaml` | 程序内 `src/mdanal/` | 每个分析的槽位、默认参数、依赖、图内文案 |
| `system.yaml` | 算例目录（**必需**） | 体系文件、时间、帧窗口、分组、跑哪些分析 |

**覆盖边界**（务必记牢）：

```
defaults.yaml          语言 / dpi / 画布 / 标注
      ↓ 不能被 system.yaml 覆盖
analyses.yaml          slots / requires / package / labels + params 默认值
      ↓ 只有 params 能被覆盖
system.yaml            体系 / 帧 / 分组 / 分析清单 + 条目参数
      ↓ 呈现设置可被覆盖
命令行                 --lang / --dpi / --annotate / --force
```

| 想改的东西 | 改哪里 |
|---|---|
| 分析参数（`nbins`、`sum_axis`、`delta`、`bin_width`…） | `system.yaml` 的分析条目，或改 `analyses.yaml` 的默认值 |
| 槽位数、要速度、依赖哪个包、图的默认文案 | 只能改 `analyses.yaml` |
| 语言、dpi、画布、默认是否标注 | 改 `defaults.yaml`（全局）或命令行（本次） |
| 体系文件、时间、帧窗口、分组、跑哪些分析 | 只能写 `system.yaml` |

写错参数名会报错并列出允许的键，不会出现“改了却没生效”。

---

## 5 `system.yaml` 字段

```yaml
name: gom_F0p2            # 可选，日志与溯源用；省略取目录名
topology: data.lmp         # 可选，省略则同目录唯一查找 *.lmp / *.data
trajectory: run.lammpstrj  # 可选，省略则同目录唯一查找 *.lammpstrj
timestep_fs: 1.0           # LAMMPS 时间步长（fs）
dump_every: 10000          # dump 间隔（步）；相邻帧相差 dump_every × timestep_fs
frames: [400, 500]         # 帧窗口，左闭右开；省略则全部帧

groups:                    # 具名分组：名字 → MDAnalysis 选择串
  water_o: "type 17"
  water_h: "type 18"
  walls:   "resid 1 or resid 90"

analyses:                  # 按顺序执行，一个分析一条
  - name: density
    tag: xz                # 可选，输出子目录名 = name-tag
    sel: [water_o]         # 长度必须等于该分析的槽位数
    sum_axis: y            # 其余键覆盖 analyses.yaml 的默认参数
```

要点：

- **`system.yaml` 是必需文件**，找不到直接退出，不做任何推断。
- 所有相对路径都相对于 `system.yaml` 所在目录。
- 同一分析可写多条（例如两种密度投影），用 `tag` 区分输出目录；两个条目算出同一目录名会在计算前报错。
- `sel` 里可以写分组名，也可以直接写选择串。

### 选择串的两个坑

```yaml
"type 17 18"     # ✅ 两类原子
"type 3-13"      # ❌ 不报错，但选中 0 个原子（type 不支持范围）
"resid 1-90"     # ✅ resid 支持范围
```

程序会校验解析结果非空，为空时直接报错——这是必须的，因为库本身不会报。

---

## 6 内置分析

| 分析 | 槽位（`sel` 顺序） | 默认参数 | 产出 | 依赖 |
|---|---|---|---|---|
| `density` | `group` | `delta=1.0`、`sum_axis=y` | `density_<两轴>.csv/png` | — |
| `lineardensity` | `group` | `binsize=0.5`、`dim=z` | `lineardensity_x/y/z.csv` + 图 | — |
| `rdf` | `a`、`b` | `range=[0.5,6.0]`、`nbins=60` | `rdf.csv/png` | — |
| `hbond` | `donor`、`hydrogen`、`acceptor` | `d_a_cutoff=3.5`、`d_h_a_angle_cutoff=150` | 计数 / 汇总 / 占有率 + 图 | — |
| `msd` | `group` | `msd_type=xyz`、`fft=true` | `msd.csv/png` | — |
| `velocity` | `group`、`ref` | `dim=2`、`vdim=0`、`bin_width=1.0`、`grouping=molecules` | `velocity.csv/png` | maicos |

几句说明：

- **density**：三维数密度沿 `sum_axis` 求和后投影到另外两轴，单位 Å⁻³，含义是沿求和方向的平均。两种投影写两条分析即可。可用 `Σρ·Δa·Δb·L_axis = 原子数` 核对（`L_axis` 取 `provenance.json` 里的 `meta.grid_extent`）。
- **lineardensity**：沿单轴的质量密度与电荷密度，一次输出三个轴的表，图只画 `dim` 指定的那个轴。
- **rdf**：只输出 `r` 与 `g(r)`。受限体系里密度沿一维不均匀，3D 体相归一化的 g(r) 没有唯一的配位数定义，故不换算配位数。
- **hbond**：三个槽位必须给**重原子**与**氢**。给整个水分子当供体会把氢也算成供体，氢键数虚高约 3 倍；库自带的自动找氢按质量/电荷筛选，会把板上羟基的氢一起选进来，因此必须显式给。
- **velocity**：第二槽位为参考组，决定剖面原点（取参考组质心，不是几何中心）；没有样本的 bin 在图上级断开，不插值。
- **msd**：只输出曲线，扩散系数需另行拟合。

---

## 7 输出

```
<out>/
├── density-xz/
│   ├── tables/density_xz.csv
│   └── figures/density_xz.png
├── rdf/
│   ├── tables/rdf.csv
│   └── figures/rdf.png
├── manifest.csv          本次运行的分析清单与落位
└── provenance.json       输入校验和、帧窗口、参数、meta、库版本
```

- **输出目录已存在时拒绝运行**，需加 `--force`。
- 表格列名固定中文，不随 `--lang` 变化。
- 坐标列会加回 dump 的盒原点，因此 `z` 与 `data.lmp` 一致（不是 MDAnalysis 内部的 `[0, L)`）。
- `manifest.csv` 的 `directory` 列可与实际目录一一对应，便于下游脚本取数。
- 同一输入重复运行，表格与图片逐字节一致。

---

## 8 常用命令

```bash
python main.py list                        # 全部分析、槽位、默认参数
python main.py list --system <目录>         # 该体系的分组与将要跑的分析（不读轨迹）
python main.py check --system <目录>        # 只校验：文件、分组、槽位数、参数名、依赖
python main.py run --system <目录> --out <输出目录>
python main.py help
```

| 选项 | 说明 |
|---|---|
| `--lang zh\|en` | 图内文字语言，默认 `zh` |
| `--dpi N` | 图片分辨率，默认 300 |
| `--annotate` | 在图内标注帧窗口与参数 |
| `--force` | 允许覆盖已存在的输出目录 |

示例：

```bash
# 一次跑完 system.yaml 里列出的全部分析
python main.py run --system run --out out/run1

# 只想跑其中几条：另存一份 system.yaml，只保留需要的条目
python main.py run --system run/system-density.yaml --out out/dens

# 英文图、600 dpi、带标注
python main.py run --system run --out out/en --lang en --dpi 600 --annotate

# 想换帧窗口：改 system.yaml 的 frames（或复制一份改完再跑）
```

安装后把 `python main.py` 换成 `mdanal` 即可。

退出码：`0` 成功、`2` 用法错误、`3` 校验失败、`4` 运行期异常。

---

## 9 常见错误

| 报错 | 原因 | 处理 |
|---|---|---|
| 找不到 system.yaml | 目录里没有配置 | 复制 `example/system.yaml` 过去 |
| 选择 … 解析为空 | 选择串写错，常见 `type 3-13` | 改成 `type 3 4 5 …` 枚举，或换 `resid` 范围 |
| sel 有 N 个，需要 M 个 | 槽位数不符 | 看 `python main.py list` 的槽位列 |
| 含未知字段 | 参数名拼错或该分析没有此参数 | 按提示的允许键改 |
| 输出子目录被重复使用 | 同一分析多条且无 `tag` | 给其中一条加唯一 `tag` |
| 输出目录已存在 | 防止覆盖 | 加 `--force` 或换目录 |
| 需要第三方包 maicos，未安装 | 没装 velocity 的依赖 | `pip install maicos` |
| 帧窗口超出轨迹范围 | `frames` 超过实际帧数 | `check` 会打印实际帧数 |

---

## 10 新增一个分析

两处改动，不改共享代码：

**1. 在 `src/mdanal/analyses.yaml` 加一段**

```yaml
interaction:
  module: analyses.interaction      # 指向 src/mdanal/analyses/interaction.py
  slots: [a, b]                     # 决定 sel 的个数与顺序
  params:
    cutoff: 12.0
  requires: []                      # 需要速度则填 [velocities]
  package: null                     # 或 {name: xxx, min_version: "1.0"}
  labels:
    zh: {x: 时间 (ps), y: 能量 (kJ/mol), title: 相互作用能}
    en: {x: time (ps), y: energy (kJ/mol), title: Interaction energy}
```

**2. 在 `src/mdanal/analyses/interaction.py` 实现**

```python
def run(ctx):
    """返回 {表名: pandas.DataFrame}"""
    ...

def figures(ctx, tables):
    """返回 [(图名, matplotlib Figure)]，可选"""
    ...

def meta(ctx, tables):
    """可选：写进 provenance 的附加信息"""
    return {}
```

`ctx` 提供：`groups`（槽位名 → 原子组，含 `.atoms` 与 `.selection`）、`start`/`stop`、`params`、`label(key)`、`size("single"|"wide"|"map")`、`universe`、`system`（含 `origin`、`frame_dt_ps`）。

绘图约束：分析模块内不出现 `savefig`、`rcParams`、`dpi`、字体名；只用 `ctx.label()` 取文案，图由框架统一保存。

---

## 11 测试

```bash
python -m pytest tests -q
```

测试依赖真实体系，默认取 `process/runs/003-systems/zgom/flow_F0p2`，可用 `MDANAL_SYSTEM` 指向其他算例；目录不存在时整组跳过。

---

## 12 已知限制

- 一次只处理一个体系。
- `rdf` 不换算配位数。
- `velocity` 纵轴原点取参考组质心。
- 氢键只输出计数与整窗占有率，不保留逐帧明细；需要时按帧窗口分段多次运行。
- MSD 只输出曲线。
- 图件为静态 PNG，无可交互缩放。
- 密度图按整个截面平均，储水区往往比缝内更亮，读图时注意这是沿求和方向平均的结果。
