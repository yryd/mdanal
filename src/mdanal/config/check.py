"""契约检查：静态校验声明，可选在临时目录里实跑（中英各一遍）。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Sequence

from ..errors import MdanalError, ValidationError
from ..run.runner import RunOptions, execute, prepare
from .registry import Discovery, build_plan
from .system import read_system


def check_analysis(
    discovery: Discovery,
    *,
    system: str | Path | None = None,
    keep: str | Path | None = None,
    names: Sequence[str] = (),
) -> list[str]:
    """返回问题列表；空列表表示通过。"""
    wanted = tuple(names)
    problems: list[str] = []

    for failure in discovery.failures:
        if wanted and failure.name not in wanted:
            continue
        message = f"{failure.path}: {failure.category}：{failure.detail}"
        if failure.declaration is not None:
            message += f"（声明本身可解析：{len(failure.declaration.slots)} 个槽位）"
        problems.append(message)

    known = set(discovery.definitions) | {failure.name for failure in discovery.failures}
    for name in wanted:
        if name not in known:
            problems.append(f"没有名为 {name!r} 的分析")

    if system is None:
        return problems

    try:
        cfg = read_system(system)
        plan = build_plan(cfg, discovery.definitions, discovery.failures)
        if wanted:
            plan = [item for item in plan if item.name in wanted]
            if not plan:
                problems.append("该体系里没有要检查的分析")
                return problems
    except ValidationError as exc:
        problems.append(str(exc))
        return problems

    with tempfile.TemporaryDirectory(prefix="mdanal-check-") as tmp:
        root = Path(keep).expanduser() if keep else Path(tmp)
        for lang in ("zh", "en"):
            try:
                prepared = prepare(cfg, plan)
                out = root / lang
                execute(prepared, out, RunOptions(lang=lang, force=True), {})
            except (ValidationError, MdanalError) as exc:
                problems.append(f"[{lang}] {exc}")
                continue
            provenance = json.loads(
                (out / "provenance.json").read_text(encoding="utf-8")
            )
            for analysis in provenance["analyses"]:
                if not analysis["tables"]:
                    problems.append(f"[{lang}] {analysis['directory']} 没有产出表")
                for figure in analysis["figures"]:
                    path = out / analysis["directory"] / "figures" / figure
                    if not path.is_file():
                        problems.append(f"[{lang}] 缺少图 {path}")
    return problems
