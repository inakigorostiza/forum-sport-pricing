# Crawler info · guía por competidor

Cómo se rastrea cada competidor, por qué de esa forma, y qué hace falta para
repetirlo. Escrito para que otra persona —o el mismo proceso dentro de seis
meses, cuando un sitio haya cambiado— pueda reproducir o reparar el rastreo sin
volver a investigarlo desde cero.

> Estado de los datos y resultados por competidor: ver la tabla al final.
> El detalle de accesibilidad y políticas está en [SCRAPING.md](SCRAPING.md).

---

## El procedimiento, en cinco preguntas

Cada sitio se evalúa con las mismas cinco preguntas, en este orden. Está
automatizado en `scripts/scraper/evaluate.py`, que escribe el resultado en
`data/evaluation.json`.

```bash
python3 scripts/scraper/evaluate.py                    # todos los pendientes
python3 scripts/scraper/evaluate.py --only wala,base   # concretos
```

| # | Pregunta | Cómo se responde | Si falla |
|---|---|---|---|
| 1 | ¿Responde `robots.txt` a un cliente HTTP? | GET con User-Agent de navegador | reintento con patchright; si tampoco, `BLOQUEADO` |
| 2 | ¿Declara sitemap y se puede leer? | líneas `Sitemap:` de robots.txt | `SIN SITEMAP` → habría que descubrir por categorías |
| 3 | ¿Hay URLs que parezcan zapatillas? | filtro por palabras en el slug | `SIN CANDIDATOS` |
| 4 | ¿La ficha lleva datos estructurados? | `extract.py` sobre 6 fichas | `SIN DATOS ESTRUCTURADOS` (suele ser JS) |
| 5 | ¿Algo empareja con nuestro catálogo? | `gtin13` ∈ EANs, o `mpn` base ∈ `ref_prov` | `SIN CLAVE` o `sin coincidencias` |

**El orden importa.** Cada paso es más caro que el anterior, así que un sitio
que falla en el paso 1 nunca llega a costar una descarga de sitemap de 24 MB.

---

## Las dos claves de emparejamiento

Todo el sistema depende de poder decir «este producto suyo es este producto
nuestro». Hay exactamente dos formas, y conviene no confundirlas.

### EAN / GTIN-13 — exacta, a nivel de talla

La preferida. 24.108 de nuestros 24.109 SKU llevan un código GS1 resoluble, y
la mayoría de tiendas publican `gtin13` en su JSON-LD.

**La trampa que lo rompe todo en silencio:** el 50,7 % de nuestros EAN están
guardados como UPC de 12 dígitos y el resto como EAN de 13. Los competidores
publican 13. Un `join` directo perdería la mitad del catálogo sin dar ningún
error. Por eso ambos lados se normalizan a 13 dígitos —`skus.gtin13` es una
columna generada, y `extract.py:gtin13()` hace lo mismo con lo rastreado.

> En el primer rastreo real, **20 de 26 modelos emparejados vinieron por EAN de
> 12 dígitos**. Sin el relleno habrían sido 6.

### Código de artículo — a nivel de modelo

Para marcas que no publican GTIN (adidas, Nike). El código del fabricante
—`GW4139`, `HV8116`— coincide con nuestro `models.ref_prov`.

- **adidas:** el código es el último segmento de la URL
  (`/zapatilla-galaxy-6/GW4139.html`). Permite filtrar *antes* de descargar.
- **Nike:** la URL no lo lleva (slugs opacos). El `mpn` del JSON-LD es
  `estilo-color` (`HV8116-001`); se corta por el guion. Una ficha de Nike lista
  varios colores, así que una descarga puede emparejar varios modelos nuestros.

La vista `v_ofertas_emparejadas` guarda `match_method` en cada oferta, para que
una coincidencia a nivel de modelo no se confunda nunca con una exacta por talla.

---

## Dos formas de descargar

### Plain HTTP — `scraper/fetch.py`

Por defecto. Un request cada vez por host, nunca más rápido que `crawl_delay_s`,
`robots.txt` respetado, User-Agent identificable, y cada error registrado (nunca
silenciado: un fallo tragado es indistinguible de «esta ficha no tenía ofertas»).

### Patchright — `scraper/sites/adidas.py`

Solo donde hace falta. Playwright normal **es detectado**; patchright lanzado
como contexto persistente sin flags de automatización, no.

```bash
pip install patchright && python3 -m patchright install chromium
```

Probado contra adidas: HTTP plano, Chrome headless real y Chrome con el plugin
stealth de puppeteer **los tres reciben 403**; patchright pasa.

---

## Lecciones que costaron tiempo

**Un sitio no se descarta con 5 páginas de muestra.** Di por descartados
Bergfreunde y Top4Running con 0 coincidencias en 5 fichas. A 300 páginas son el
segundo y el quinto competidor con más datos (1.120 y 769 ofertas). **Mínimo
100 páginas antes de concluir nada.** Viladomat sí está descartado: 0 de 300.

**«Sin datos estructurados» era un bug mío.** `_ld_nodes` solo aplanaba
`@graph`, así que un `Product` anidado en `WebPage.mainEntity` era invisible.
Es exactamente como publica Tradeinn —el competidor más grande de la lista— que
pasó de «no tiene datos» a 9 ofertas con 9 GTIN al arreglarlo. Ahora también
desciende por `mainEntity`, `mainEntityOfPage`, `itemListElement` e `item`.

**`robots.txt` legible no significa sitio accesible.** Decathlon publica un
`robots.txt` permisivo con `Crawl-delay` y devuelve 403 en la portada. La
política declarada y lo que el WAF permite son cosas distintas.

**El volumen de la lista de origen no predice nada.** Atmósfera tiene 10.461
registros y da 26 modelos; Bergfreunde tiene 1.808 y da 73.

**Cada tienda da forma distinta a sus URLs de ficha.** Por eso existe
`competitors.product_url_re`: sin él el rastreador descarga páginas de categoría
(Atmósfera) o rechaza todo (`/p/`, `/product/`, barra final).

---

## Cómo añadir un competidor nuevo

1. `python3 scripts/scraper/evaluate.py --only <slug>` y leer el veredicto.
2. Anotar la política en `scripts/seed_competitors.py:POLICY` y re-sembrar.
3. Configurar en la tabla `competitors`: `sitemap_url` (el que declara
   robots.txt, no uno adivinado), `product_url_re`, `crawl_delay_s`, `strategy`.
4. Guardar una ficha en `scraper/fixtures/` y añadir un caso a `test_extract.py`,
   para que el extractor quede cubierto sin red.
5. `--limit 8 --dry-run`, revisar, y solo entonces `enabled = true`.
6. Primer rastreo real con `--limit 300` y medir la tasa de coincidencia.

---

## Coste

| | Páginas | A 2 s |
|---|--:|--:|
| Sitemap completo de Atmósfera | 31.393 | ~1.046 min |
| Subconjunto running/trail | ~2.000 | ~70 min |
| Solo lo que empareja (refresco diario) | ~600 | ~20 min |

De ahí las dos fases: `discover` semanal reduce el sitemap a candidatos y marca
`is_relevant`; `refresh` diario solo vuelve a por esos. GitHub Actions da 2.000
min/mes en repo privado, y la matriz del workflow rastrea competidores en
paralelo —hosts distintos no comparten límite—. **Nunca en paralelo dentro de un
mismo host: ahí el `crawl_delay` es justamente el compromiso.**
