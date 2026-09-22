#!/usr/bin/env bash
# Exercise the REST API exactly as the landing page will: with the ANON key.
# Proves (a) public reads work through RLS, (b) anonymous writes are rejected.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
[ -f .env.local ] && set -a && . ./.env.local && set +a

: "${SUPABASE_URL:?set SUPABASE_URL in .env.local}"
: "${SUPABASE_ANON_KEY:?set SUPABASE_ANON_KEY in .env.local}"

AUTH=(-H "apikey: ${SUPABASE_ANON_KEY}" -H "Authorization: Bearer ${SUPABASE_ANON_KEY}")
fails=0

get() { # description, path, expected HTTP status
  local body status
  body=$(curl -s -w '\n%{http_code}' "${AUTH[@]}" "${SUPABASE_URL}/rest/v1/$2")
  status=$(tail -n1 <<<"$body")
  body=$(sed '$d' <<<"$body")
  if [ "$status" = "$3" ]; then
    printf 'PASS  %-38s [%s]  %s\n' "$1" "$status" "$(cut -c1-90 <<<"$body")"
  else
    printf 'FAIL  %-38s [expected %s, got %s]  %s\n' "$1" "$3" "$status" "$(cut -c1-90 <<<"$body")"
    fails=$((fails + 1))
  fi
}

echo "== Public reads (anon key) =="
get "KPIs"              "v_kpis"                                                        200
get "por marca"         "v_por_marca?order=modelos.desc&limit=3"                        200
get "nivel de margen"   "v_por_nivel_margen"                                            200
get "nivel de stock"    "v_por_nivel_stock"                                             200
get "tipo de producto"  "v_por_tipo_producto"                                           200
get "bandas de precio"  "v_bandas_precio"                                               200
get "curva de tallas"   "v_curva_tallas?limit=3"                                        200
get "temporada"         "v_por_temporada?limit=3"                                       200
get "matriz ABCD"       "v_abcd_matriz?limit=3"                                         200
get "top descuentos"    "models?select=modelo,nombre_modelo,precio,precio_rebaja,descuento_pct,url&en_rebaja=is.true&order=descuento_pct.desc&limit=3" 200
get "modelo + tallas"   "models?select=modelo,nombre_modelo,precio,skus(talla_es,ean)&modelo=eq.1001142170" 200
get "filtro por marca"  "v_modelos_detalle?brand_code=eq.NIKE&limit=2"                200

echo
echo "== Writes must be rejected (anon key) =="
# Status codes alone are a weak signal: under RLS a DELETE that matches no rows
# is still "successful" and PostgREST answers 204. So we check the status AND,
# below, that the data is genuinely untouched.
w() {
  local status
  status=$(curl -s -o /dev/null -w '%{http_code}' -X "$2" "${AUTH[@]}" \
    -H 'Content-Type: application/json' ${3:+-d "$3"} "${SUPABASE_URL}/rest/v1/$1")
  case "$status" in
    400|401|403|404|405) printf 'PASS  %-6s %-30s rejected [%s]\n' "$2" "${1%%\?*}" "$status" ;;
    *) printf 'FAIL  %-6s %-30s NOT rejected [%s]\n' "$2" "${1%%\?*}" "$status"; fails=$((fails + 1)) ;;
  esac
}
w "brands" POST   '{"code":"TEST","name":"test"}'
w "models" POST   '{"modelo":1,"brand_code":"NIKE"}'
w "skus?material=eq.5757282"   DELETE
w "models?modelo=eq.1001142170" PATCH '{"precio":1}'
w "brands" DELETE

echo
echo "== Data must be unchanged after those attempts =="
num() { sed -n "s/.*\"$1\":\([0-9][0-9]*\).*/\1/p" <<<"$2" | head -n1; }
kpis=$(curl -s "${AUTH[@]}" "${SUPABASE_URL}/rest/v1/v_kpis")
for pair in "total_modelos:1483" "total_skus:24109" "total_marcas:28"; do
  k=${pair%%:*}; want=${pair##*:}; got=$(num "$k" "$kpis")
  if [ "$got" = "$want" ]; then printf 'PASS  %-14s %s\n' "$k" "$got"
  else printf 'FAIL  %-14s expected %s, got %s\n' "$k" "$want" "${got:-none}"; fails=$((fails + 1)); fi
done

# The two rows the DELETE and PATCH above targeted.
row=$(curl -s "${AUTH[@]}" "${SUPABASE_URL}/rest/v1/skus?select=material&material=eq.5757282")
case "$row" in *5757282*) echo "PASS  targeted sku still present" ;;
  *) echo "FAIL  targeted sku missing -- DELETE went through"; fails=$((fails + 1)) ;; esac

row=$(curl -s "${AUTH[@]}" "${SUPABASE_URL}/rest/v1/models?select=precio&modelo=eq.1001142170")
case "$row" in *140*) echo "PASS  targeted precio still 140.00" ;;
  *) echo "FAIL  precio changed ($row) -- PATCH went through"; fails=$((fails + 1)) ;; esac

echo
[ "$fails" -eq 0 ] && echo "All API checks passed." || { echo "$fails check(s) FAILED."; exit 1; }
