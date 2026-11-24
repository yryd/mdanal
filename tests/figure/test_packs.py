from __future__ import annotations

from mdanal.figure.catalog import discover_packs, pack_payload


def test_builtin_packs_and_products():
    packs = discover_packs()
    assert set(packs) == {"contact", "density", "hbond", "msd", "rdf", "velocity"}
    assert set(packs["contact"].products) == {"contact-count", "contact-coordination"}
    assert set(packs["density"].products) == {"density-2d", "density-line"}
    assert set(packs["hbond"].products) == {"hbond-count", "hbond-type", "hbond-lifetime-continuous", "hbond-lifetime-intermittent"}
    assert set(packs["msd"].products) == {"msd-raw", "msd-fit", "msd-rdc"}


def test_every_product_is_single_panel_and_declares_requires():
    for name, pack in discover_packs().items():
        assert pack.slots, name
        for product in pack.products.values():
            assert product.id in pack.products
            assert product.requires, f"{name}/{product.id} 没有 requires"
            assert product.kind in ("curve", "field", "bars")
            if product.kind != "curve":
                assert product.compare is None


def test_pack_payload_is_json_friendly():
    payload = pack_payload(discover_packs()["density"])
    assert payload["name"] == "density"
    assert {"density-2d", "density-line"} == {row["id"] for row in payload["products"]}
    assert payload["slots"] == ["group"]
