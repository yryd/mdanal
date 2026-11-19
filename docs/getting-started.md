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

`replot` 不读轨迹、不重算表；改 `plot` 的标题/范围/颜色/尺寸后重新 `render` 会复用已有表。

## 只校验

```bash
python main.py check --config example/figures.yaml
```

它会在计算前检查图包、产品、槽位、参数、derive 和 compare 能力。
