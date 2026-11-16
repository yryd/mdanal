# 文档资产

这些图由 `scripts/build_docs_assets.py` 从 `tests/fixtures/tiny` 和 `example/` 的真实运行生成：

```bash
python scripts/build_docs_assets.py
```

- `gallery/`：八种内置分析的输出图；
- `quickstart-msd-*.png`：快速开始的中英文图；
- `quickstart-msd-en.svg`：replot 的真实 SVG 输出；
- `recipes/`：换语言、换色、裁剪、标注、对比的改图结果；
- `palette-preview.png/.svg`、`palette-curves.png`、`palettes.json`：颜色页色卡与色值；
- `plugin-template/`：插件模板实跑的表头和图。

生成脚本只写本目录，运行结果放临时目录；不提交轨迹和运行日志。色值/顺序以当前 `resolve_palette` 和 `chart.density_cmap` 为准。
