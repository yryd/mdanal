# 首次使用

## 安装

```bash
pip install -r requirements.txt
pip install -e .          # 可选；不装则用 python main.py
```

## 用仓库 tiny 数据跑通

```bash
python main.py check  --config example/figures.yaml
python main.py render --config example/figures.yaml --out /tmp/mdanal-demo --force
```

输出：

```text
/tmp/mdanal-demo/
├── figures/
│   ├── msd-tiny.png
│   ├── msd-tiny.json
│   ├── density-tiny.png
│   └── density-tiny.json
└── data/tiny/...
```

`figures/*.json` 是重绘入口；`data/` 是表与计算上下文。用户不需要给分析起目录名。

## 改成自己的轨迹

编辑 `example/figures.yaml` 的 `sources`：

```yaml
sources:
  A:
    topology: runs/A/data.lmp
    trajectory: runs/A/traj.lammpstrj
    timestep_fs: 1.0
    dump_every: 5000
    frames: [0, 1000]
    groups:
      water: "type 11 12"
      tma: "type 1 2 3 4 5 6"
```

然后在 `figures[].panels[]` 里引用 `source: A`、`pack`、`product`。

## 只改图

```bash
python main.py replot --from /tmp/mdanal-demo --out /tmp/mdanal-demo-replot
```

`replot` 不读轨迹、不重算表；它只按快照重绘。当前不同 `render` 之间不共享基础表：再次 `render` 会重新计算（同一 `render` 内才复用）。

## 只校验

```bash
python main.py check --config example/figures.yaml
```

它会在计算前检查图包、产品、槽位、参数、derive 和 compare 能力。
