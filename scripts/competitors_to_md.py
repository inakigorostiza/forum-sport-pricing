#!/usr/bin/env python3
"""Generate competitors.md from dataset/Competidores_PricingDinamico.xlsx.

Lists the sellers worth monitoring: the source sheet's four columns, filtered to
those that are actually candidates for price scraping.

Three exclusions, applied in this order and reported at the foot of the file:
  1. comparadores  — they resell nothing, they list the others
  2. marketplaces  — third-party aggregators, not a single retailer's price
  3. unreachable   — the homepage does not serve content to an HTTP client

Reachability was measured, not assumed (see REACHABLE below). URL citation
artifacts such as "[tradeinn.com]" are stripped.
"""

import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / "dataset" / "Competidores_PricingDinamico.xlsx"
OUT = ROOT / "competitors.md"

# Resellers of other people's listings rather than a price of their own.
COMPARADORES = {"Google Shopping"}
MARKETPLACES = {"Amazon", "Zalando", "ASOS"}

# Measured 2026-09-22: GET the homepage with a browser User-Agent and follow
# redirects. Anything not serving content (403 / 418 / connection failure /
# a Cloudflare interstitial) cannot be scraped without bespoke work.
UNREACHABLE = {
    "ASOS": "sin respuesta",
    "11teamsports": "HTTP 403", "Adidas": "HTTP 403", "Alltricks": "HTTP 403",
    "Bike24": "HTTP 403", "Decathlon": "HTTP 403", "Deporvillage": "HTTP 403",
    "Ekosport": "HTTP 403 (Cloudflare)", "El Corte Inglés": "HTTP 403",
    "Helly Hansen": "HTTP 403", "JD Sports": "HTTP 403",
    "Nencini Sport": "HTTP 403", "Salomon": "HTTP 403", "Sprinter": "HTTP 403",
    "The North Face": "HTTP 403", "Zalando": "HTTP 403", "i-Run": "HTTP 403",
    "Under Armour": "HTTP 418",
}


def main() -> int:
    ws = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)["Listado"]
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() for h in next(it) if h]

    kept, dropped = [], []
    for r in it:
        if not r or not r[0]:
            continue
        name = str(r[0]).strip()
        url = re.sub(r"\s*\[[^\]]*\]", "", str(r[3] or "")).strip().rstrip(",").strip()
        row = (name, int(r[1]), str(r[2]).strip(), url)

        if name in COMPARADORES:
            dropped.append((*row, "comparador"))
        elif name in MARKETPLACES:
            dropped.append((*row, "marketplace"))
        elif name in UNREACHABLE:
            dropped.append((*row, f"no accesible · {UNREACHABLE[name]}"))
        else:
            kept.append(row)

    out = ["# Competidores", "",
           f"Fuente: `dataset/{XLSX.name}` (hoja «Listado»).",
           "",
           f"**{len(kept)} de {len(kept) + len(dropped)} vendedores.** Excluidos los "
           "comparadores, los marketplaces y los sitios que no responden a un "
           "cliente HTTP (ver el detalle al final).",
           "",
           "| " + " | ".join(headers) + " |",
           "|---|--:|---|---|"]
    for name, rec, cls, url in kept:
        # Format ONLY the number: a line-wide swap turns the commas inside
        # "Runnerinn, Dressinn, Trekkinn" into full stops.
        out.append(f"| {name} | {f'{rec:,}'.replace(',', '.')} | {cls} | {url} |")

    out += ["", "## Excluidos", "",
            "| Competidor | Motivo |", "|---|---|"]
    for name, _rec, _cls, _url, why in sorted(dropped, key=lambda x: (x[4], x[0])):
        out.append(f"| {name} | {why} |")
    out += ["",
            "Accesibilidad medida el 22-09-2026: petición GET a la portada con "
            "User-Agent de navegador siguiendo redirecciones. Un 403 no significa "
            "que el sitio sea inalcanzable para siempre, sino que no sirve "
            "contenido a un cliente HTTP normal; alcanzarlo requiere navegador "
            "headless y trabajo a medida."]

    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name} — {len(kept)} kept, {len(dropped)} excluded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
