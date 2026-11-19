# 排错

## 字体

中文图需要：

- `Noto Serif CJK SC`

检查：

```bash
python -c "from mdanal.plot.chart import missing_fonts; print(missing_fonts())"
```

`render` 缺字体会直接报错。

## 找不到图包/产品

```bash
python main.py packs
python main.py check-pack density
```

`check` 会列出可用产品。产品不存在通常是 `pack.json` 与 `PRODUCTS` 不一致或拼写错误。

## `hbond-type` 没有表

`hbond-type` 需要 source 配置 `naming`：

```yaml
naming: {from_data: runs/A/data.lmp}
```

没有 naming 时 `check` 会直接报。

## 输出目录已存在

`render` 只覆盖自己写出的目录（存在 `project.json` 标记）。加 `--force`：

```bash
python main.py render --config figures.yaml --out OUT --force
```

不要用 `--force` 指向包含输入轨迹或人工文件的目录。

## compare 报“不是可 compare 的曲线产品”

- 2D 密度/hbond-type 不能叠加；
- 2D 密度改成多个普通 Panel 并排；
- 确认产品 `kind="curve"` 且声明了 `compare`。

## 变盒/非周期

- density/lineardensity 变盒只用首帧并警告；
- hbond 当前只支持全周期盒；
- RDF 非周期正交方向结果仅定性；
- 速度剖面在首帧参考盒中平均。

## 旧配置

旧 `system.yaml`、`run`、`compare`、`derive`、`FIGURES`、`panels()`、`COMPARE` 已移除。请改成 `figures.yaml`。
