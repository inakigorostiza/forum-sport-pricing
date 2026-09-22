#!/usr/bin/env python3
"""Generate competitors.md from dataset/Competidores_PricingDinamico.xlsx.

A plain transcription of the sheet: same columns, same order. The only change
is stripping citation artifacts such as "[tradeinn.com]" from the URL column.
"""

import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "dataset" / "Competidores_PricingDinamico.xlsx"
OUT = ROOT / "competitors.md"

rows = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)["Listado"]
it = rows.iter_rows(values_only=True)
headers = [str(h).strip() for h in next(it) if h]

out = ["# Competidores", "",
       f"Fuente: `dataset/{XLSX.name}` (hoja «Listado»).", "",
       "| " + " | ".join(headers) + " |",
       "|---|--:|---|---|"]

for r in it:
    if not r or not r[0]:
        continue
    url = re.sub(r"\s*\[[^\]]*\]", "", str(r[3] or "")).strip().rstrip(",").strip()
    # Format only the number — applying the swap to the whole line turns the
    # commas inside "Runnerinn, Dressinn, Trekkinn" into full stops.
    count = f"{int(r[1]):,}".replace(",", ".")
    out.append(f"| {str(r[0]).strip()} | {count} | {str(r[2]).strip()} | {url} |")

OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote {OUT.name} — {len(out) - 6} rows")
