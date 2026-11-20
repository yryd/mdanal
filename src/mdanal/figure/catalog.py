"""发现 FigurePack：扫描 analyses/<name>/ 并从模块读取 PRODUCTS。"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..config.paths import ANALYSES_DIR, ANALYSES_PACKAGE
from ..errors import ValidationError
from .model import FigurePack, PanelProduct


def _pack_path(name: str) -> Path:
    path = ANALYSES_DIR / name
    if path.is_dir() and (path / "__init__.py").is_file():
        return path / "__init__.py"
    raise ValidationError(f"找不到图包 {name}（需要 analyses/{name}/__init__.py）")


def _validate_products(module: Any, name: str, path: Path) -> dict[str, PanelProduct]:
    raw = getattr(module, "PRODUCTS", None)
    if not isinstance(raw, Mapping) or not raw:
        raise ValidationError(
            f"图包 {name} 必须声明非空 PRODUCTS", where=str(path)
        )
    products: dict[str, PanelProduct] = {}
    for key, product in raw.items():
        if not isinstance(key, str) or not key:
            raise ValidationError(f"PRODUCTS 的键必须是非空字符串", where=str(path))
        if not isinstance(product, PanelProduct):
            raise ValidationError(
                f"PRODUCTS[{key!r}] 必须是 PanelProduct", where=str(path)
            )
        if product.id != key:
            raise ValidationError(
                f"PRODUCTS[{key!r}].id 必须与键一致，收到 {product.id!r}",
                where=str(path),
            )
        if not isinstance(product.requires, tuple):
            raise ValidationError(
                f"PRODUCTS[{key!r}].requires 必须是 tuple", where=str(path)
            )
        if not callable(product.build):
            raise ValidationError(
                f"PRODUCTS[{key!r}].build 必须可调用", where=str(path)
            )
        if product.kind not in ("curve", "field", "bars"):
            raise ValidationError(
                f"PRODUCTS[{key!r}].kind 必须是 curve/field/bars",
                where=str(path),
            )
        if product.compare is not None and product.kind != "curve":
            raise ValidationError(
                f"PRODUCTS[{key!r}] 不是曲线产品，不能声明 compare",
                where=str(path),
            )
        products[key] = product
    defaults = [key for key, product in products.items() if product.default]
    if len(defaults) > 1:
        raise ValidationError(
            f"图包 {name} 只能有一个默认产品，收到 {defaults}", where=str(path)
        )
    return products


def _read_manifest(path: Path) -> dict[str, Any] | None:
    manifest = path.parent / "pack.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"pack.json 无法读取：{manifest}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"pack.json 必须是映射：{manifest}")
    return payload


def _check_manifest(
    name: str, path: Path, products: Mapping[str, PanelProduct], payload: dict[str, Any]
) -> None:
    if payload.get("pack") != name:
        raise ValidationError(
            f"pack.json 的 pack={payload.get('pack')!r} 与目录名 {name!r} 不一致",
            where=str(path.parent / "pack.json"),
        )
    rows = payload.get("products")
    if not isinstance(rows, list):
        raise ValidationError("pack.json.products 必须是列表")
    declared = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValidationError("pack.json 产品必须含字符串 id")
        declared[row["id"]] = row
    missing = sorted(set(products) - set(declared))
    extra = sorted(set(declared) - set(products))
    if missing or extra:
        raise ValidationError(
            f"pack.json 与 PRODUCTS 不一致：缺 {missing}，多 {extra}",
            where=str(path.parent / "pack.json"),
        )
    for key, product in products.items():
        row = declared[key]
        if row.get("kind") != product.kind:
            raise ValidationError(
                f"pack.json 产品 {key!r} 的 kind 与代码不一致",
                where=str(path.parent / "pack.json"),
            )
        if tuple(row.get("requires") or ()) != tuple(product.requires):
            raise ValidationError(
                f"pack.json 产品 {key!r} 的 requires 与代码不一致",
                where=str(path.parent / "pack.json"),
            )
        if bool(row.get("compare", False)) != (product.compare is not None):
            raise ValidationError(
                f"pack.json 产品 {key!r} 的 compare 与代码不一致",
                where=str(path.parent / "pack.json"),
            )
        if bool(row.get("default", False)) != bool(product.default):
            raise ValidationError(
                f"pack.json 产品 {key!r} 的 default 与代码不一致",
                where=str(path.parent / "pack.json"),
            )
        if tuple(row.get("requires_derive") or ()) != tuple(product.requires_derive):
            raise ValidationError(
                f"pack.json 产品 {key!r} 的 requires_derive 与代码不一致",
                where=str(path.parent / "pack.json"),
            )


def load_pack(name: str) -> FigurePack:
    path = _pack_path(name)
    try:
        module = importlib.import_module(f"{ANALYSES_PACKAGE}.{name}")
    except ImportError as exc:
        raise ValidationError(f"图包 {name} 无法导入：{exc}", where=str(path)) from exc
    products = _validate_products(module, name, path)
    compute = getattr(module, "compute", None)
    if not callable(compute):
        raise ValidationError(f"图包 {name} 必须声明 compute(ctx)", where=str(path))
    slots = getattr(module, "SLOTS", None)
    if not isinstance(slots, (tuple, list)) or not slots:
        raise ValidationError(f"图包 {name} 必须声明非空 SLOTS", where=str(path))
    params = getattr(module, "PARAMS", {})
    labels = getattr(module, "LABELS", {})
    derive = getattr(module, "derive", None)
    validate_derive = getattr(module, "validate_derive", None)
    pack = FigurePack(
        name=name,
        module=f"{ANALYSES_PACKAGE}.{name}",
        slots=tuple(str(slot) for slot in slots),
        params=dict(params),
        labels=dict(labels),
        products=products,
        compute=compute,
        derive=derive if callable(derive) else None,
        validate_derive=validate_derive if callable(validate_derive) else None,
        coordinates=str(getattr(module, "COORDINATES", "any")),
        geometry=dict(getattr(module, "GEOMETRY", {}) or {}),
        note=str(getattr(module, "NOTE", "") or ""),
    )
    payload = _read_manifest(path)
    if payload is None:
        raise ValidationError(
            f"图包 {name} 缺少 pack.json；它是必需机器契约",
            where=str(path.parent / "pack.json"),
        )
    _check_manifest(name, path, products, payload)
    return pack


def discover_packs() -> dict[str, FigurePack]:
    packs: dict[str, FigurePack] = {}
    for path in sorted(ANALYSES_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        if not (path / "__init__.py").is_file():
            continue
        packs[path.name] = load_pack(path.name)
    if not packs:
        raise ValidationError(f"在 {ANALYSES_DIR} 下没有发现任何图包")
    return packs


def pack_payload(pack: FigurePack) -> dict[str, Any]:
    return {
        "name": pack.name,
        "module": pack.module,
        "coordinates": pack.coordinates,
        "geometry": dict(pack.geometry),
        "slots": list(pack.slots),
        "params": {
            key: {
                "type": getattr(value.get("type"), "__name__", str(value.get("type"))),
                "default": value.get("default"),
                "unit": value.get("unit"),
                "choices": list(value.get("choices") or ()),
                "help": value.get("help", ""),
            }
            for key, value in pack.params.items()
        },
        "products": [
            {
                "id": product.id,
                "kind": product.kind,
                "requires": list(product.requires),
                "requires_derive": list(product.requires_derive),
                "default": product.default,
                "compare": product.compare is not None,
                "help": product.help,
            }
            for product in pack.products.values()
        ],
    }
