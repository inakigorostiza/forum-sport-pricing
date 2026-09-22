#!/usr/bin/env python3
"""Turn the "bbdd" tab of Dataset_FS_pricing_dinámico.xlsx into load-ready JSON.

The sheet has one row per SKU with the model-level attributes repeated across
every size of a model. This script splits it into brands / models / skus and
applies the cleaning rules, then asserts the result against counts taken from
the "valores dimensiones" pivot tab in the same workbook.

Runs with no credentials and touches no network: the transform can be reviewed
on its own. Output goes to data/*.json for scripts/load_supabase.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "dataset" / "Dataset_FS_pricing_dinámico.xlsx"
OUT = ROOT / "data"

# Sentinels the source uses instead of leaving a cell empty.
SIN_DATOS_COBERTURA = "SIN DATOS COBERTURA"
SIN_DATOS_ABCD = "SIN DATOS CLASIFICACIÓN"

# Column positions in the "bbdd" tab, in sheet order.
(
    C_MODELO_UNICO, C_MODELO, C_MARCA, C_DESCMARCA, C_NOMBREMODELO, C_COLOR,
    C_REF_COLOR_PROV, C_REF_PROV, C_GR, C_TEMPORADA, C_ANO, C_TIPO,
    C_MATERIAL, C_TALLA, C_TALLA_ES, C_EAN, C_EXCLUSIVO, C_OUTLET,
    C_CAT_EXT, C_CUSTOM_LABEL, C_ABCD_TIENDA, C_ABCD_DIGITAL, C_PRECIO,
    C_REBAJA, C_NETO, C_NIVEL_MARGEN, C_MARGEN, C_COBERTURA, C_NIVEL_STOCK,
    C_ONLINE,
) = range(30)

# Ground truth from the "valores dimensiones" pivot tab. Because those pivots
# were built independently of this script, they catch a silently wrong split.
EXPECTED = {
    "brands": 28,
    "models": 1483,
    "skus": 24109,
    "tipo_producto": {
        "zapatilla running hombre": 984,
        "zapatillas trail hombre": 499,
    },
    "nivel_margen": {"muy bajo": 287, "bajo": 261, "medio": 601, "alto": 334},
    "nivel_stock": {
        "muy alto": 58, "alto": 63, "medio": 66, "bajo": 269, "muy bajo": 1027,
    },
    "outlet_true": 112,
    "cat_extendido_true": 478,
    "exclusivo_online_true": 682,
    "temporada": {"AN": 48, "OI": 1040, "PV": 395},
    "abcd_tienda": {"AA": 6, "A": 14, "B": 43, "C": 234, "D": 892, None: 294},
}


def text(value) -> str | None:
    """Trim, and treat a blank cell as absent."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def main() -> int:
    if not XLSX.exists():
        sys.exit(f"Dataset not found: {XLSX}")

    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    rows = wb["bbdd"].iter_rows(values_only=True)
    next(rows)  # header

    brands: dict[str, str] = {}
    models: dict[int, dict] = {}
    skus: list[dict] = []
    neto_mismatches = 0

    for row in rows:
        if not any(c is not None and c != "" for c in row):
            continue

        modelo = int(row[C_MODELO])

        code = text(row[C_MARCA])
        brands.setdefault(code, text(row[C_DESCMARCA]) or code)

        if modelo not in models:
            cobertura = row[C_COBERTURA]
            models[modelo] = {
                "modelo": modelo,
                "brand_code": code,
                "nombre_modelo": text(row[C_NOMBREMODELO]),
                "color": text(row[C_COLOR]),
                "ref_color_prov": (
                    int(row[C_REF_COLOR_PROV])
                    if row[C_REF_COLOR_PROV] is not None else None
                ),
                "ref_prov": text(row[C_REF_PROV]),
                "gr": text(row[C_GR]),
                "temporada": text(row[C_TEMPORADA]),
                "ano_temporada": int(row[C_ANO]),
                "tipo_producto": text(row[C_TIPO]),
                "exclusivo_online": text(row[C_EXCLUSIVO]) is not None,
                "outlet": text(row[C_OUTLET]) == "SI",
                "cat_extendido": int(row[C_CAT_EXT]) == 1,
                "custom_label": text(row[C_CUSTOM_LABEL]),
                "abcd_tienda": (
                    None if text(row[C_ABCD_TIENDA]) == SIN_DATOS_ABCD
                    else text(row[C_ABCD_TIENDA])
                ),
                "abcd_digital": (
                    None if text(row[C_ABCD_DIGITAL]) == SIN_DATOS_ABCD
                    else text(row[C_ABCD_DIGITAL])
                ),
                "precio": float(row[C_PRECIO]),
                "precio_rebaja": float(row[C_REBAJA]),
                "margen": float(row[C_MARGEN]),
                "nivel_margen": text(row[C_NIVEL_MARGEN]),
                # A string here is the SIN DATOS COBERTURA sentinel.
                "cobertura_stock": (
                    None if isinstance(cobertura, str) else int(cobertura)
                ),
                "nivel_stock": text(row[C_NIVEL_STOCK]),
                "online": text(row[C_ONLINE]) == "online",
            }

        # neto is a generated column in Postgres; confirm the source agrees
        # rather than importing it.
        expected_neto = float(row[C_REBAJA]) * (1 - float(row[C_MARGEN]))
        if abs(expected_neto - float(row[C_NETO])) > 1e-6:
            neto_mismatches += 1

        skus.append({
            "material": int(row[C_MATERIAL]),
            "modelo": modelo,
            "talla": float(row[C_TALLA]),
            "talla_es": int(row[C_TALLA_ES]),
            "ean": int(row[C_EAN]),
        })

    check(brands, models, skus, neto_mismatches)

    OUT.mkdir(exist_ok=True)
    write(OUT / "brands.json",
          [{"code": c, "name": n} for c, n in sorted(brands.items())])
    write(OUT / "models.json", list(models.values()))
    write(OUT / "skus.json", skus)
    return 0


def check(brands, models, skus, neto_mismatches) -> None:
    """Assert the split against the workbook's own pivot tables."""
    def tally(key):
        out = {}
        for m in models.values():
            out[m[key]] = out.get(m[key], 0) + 1
        return out

    failures = []

    def expect(label, got, want):
        if got != want:
            failures.append(f"  {label}: got {got!r}, expected {want!r}")

    expect("brands", len(brands), EXPECTED["brands"])
    expect("models", len(models), EXPECTED["models"])
    expect("skus", len(skus), EXPECTED["skus"])
    expect("tipo_producto", tally("tipo_producto"), EXPECTED["tipo_producto"])
    expect("nivel_margen", tally("nivel_margen"), EXPECTED["nivel_margen"])
    expect("nivel_stock", tally("nivel_stock"), EXPECTED["nivel_stock"])
    expect("temporada", tally("temporada"), EXPECTED["temporada"])
    expect("abcd_tienda", tally("abcd_tienda"), EXPECTED["abcd_tienda"])
    expect("outlet=SI", sum(m["outlet"] for m in models.values()),
           EXPECTED["outlet_true"])
    expect("cat_extendido=1", sum(m["cat_extendido"] for m in models.values()),
           EXPECTED["cat_extendido_true"])
    expect("exclusivo_online", sum(m["exclusivo_online"] for m in models.values()),
           EXPECTED["exclusivo_online_true"])
    expect("neto formula mismatches", neto_mismatches, 0)

    # Structural integrity, independent of the pivots.
    expect("unique materials", len({s["material"] for s in skus}), len(skus))
    expect("unique eans", len({s["ean"] for s in skus}), len(skus))
    expect("orphan skus",
           len({s["modelo"] for s in skus} - set(models)), 0)
    expect("rebaja > precio",
           sum(1 for m in models.values()
               if m["precio_rebaja"] > m["precio"]), 0)

    if failures:
        sys.exit("Validation FAILED:\n" + "\n".join(failures))

    print(f"Validated against the workbook pivots: "
          f"{len(brands)} brands, {len(models)} models, {len(skus)} skus.")


def write(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    print(f"  wrote {len(records):>6,} records -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
