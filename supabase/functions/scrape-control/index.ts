/* Panel de scraping: lectura de estado, configuración y lanzamiento manual.
 *
 * Por qué existe esta función y no unas políticas RLS sobre `competitors`:
 * la página está en una URL pública sin autenticación. Abrir esas tablas a
 * `anon` publicaría a qué competidores vigila Forum Sport, con qué retardo y
 * con qué user-agent — y, en los casos marcados 'browser', cómo se sortea un
 * bloqueo. Eso no es un dato de precios, es la estrategia de vigilancia.
 *
 * Así que nada se expone a `anon`. Todo pasa por aquí, y aquí hace falta un
 * token de operador que vive en los secretos del proyecto, nunca en el HTML.
 *
 * Secretos necesarios (Supabase → Edge Functions → Secrets):
 *   OPERATOR_TOKEN   cadena larga y aleatoria; la teclea quien opera el panel
 *   GITHUB_TOKEN     PAT de grano fino con permiso `actions: write` en el repo
 *   GITHUB_REPO      "usuario/repositorio"  (por defecto el de este proyecto)
 * SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY los inyecta Supabase solo.
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-operator-token",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });

/* Comparación en tiempo constante. Un `===` sobre un token filtra su longitud
 * y su prefijo a quien mida los tiempos de respuesta; no cuesta nada evitarlo. */
function tokenValido(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

async function sb(path: string, init: RequestInit = {}) {
  const r = await fetch(`${SB_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SB_KEY,
      Authorization: `Bearer ${SB_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(init.headers ?? {}),
    },
  });
  const txt = await r.text();
  if (!r.ok) throw new Error(`${r.status} ${txt.slice(0, 300)}`);
  return txt ? JSON.parse(txt) : null;
}

/* Lo único que el panel puede tocar. Una lista blanca, no una negra: si mañana
 * se añade una columna a `competitors` no queda editable desde internet por
 * olvido. `strategy`, `sitemap_url` y `product_url_re` quedan fuera a propósito
 * — romperlos desde un formulario deja un competidor sin datos y nadie lo
 * relaciona con el clic de hace tres semanas. */
const EDITABLES: Record<string, (v: unknown) => unknown> = {
  enabled: (v) => v === true || v === "true",
  user_agent: (v) => (v === "browser" ? "browser" : "honest"),
  crawl_delay_s: (v) => Math.min(60, Math.max(0.5, Number(v) || 2)),
  sitemap_max_children: (v) =>
    v === null || v === "" ? null : Math.min(500, Math.max(1, Math.round(Number(v) || 12))),
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const esperado = Deno.env.get("OPERATOR_TOKEN");
  if (!esperado) {
    return json({ error: "setup", detail: "OPERATOR_TOKEN is not set on this project yet." }, 503);
  }
  const dado = req.headers.get("x-operator-token") ?? "";
  if (!tokenValido(dado, esperado)) return json({ error: "unauthorized" }, 401);

  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { /* status no necesita cuerpo */ }
  const accion = String(body.action ?? "status");

  try {
    /* ── estado ──────────────────────────────────────────────────────── */
    if (accion === "status") {
      const comps = await sb(
        "competitors?select=slug,name,classification,base_url,enabled,strategy," +
        "user_agent,crawl_delay_s,sitemap_max_children,robots_status&order=name.asc",
      );
      // Las dos últimas ejecuciones de cada competidor: una sola dice si hoy
      // fue bien, dos dicen si está roto o sólo tuvo un mal día.
      const log = await sb(
        "crawl_log?select=competitor_slug,phase,started_at,finished_at,pages_fetched," +
        "offers_found,offers_matched,errors,notes&order=started_at.desc&limit=400",
      );
      const porComp: Record<string, unknown[]> = {};
      for (const l of log) (porComp[l.competitor_slug] ??= []).push(l);
      return json({
        competidores: comps.map((c: Record<string, unknown>) => ({
          ...c,
          historial: (porComp[c.slug as string] ?? []).slice(0, 2),
        })),
        generado: new Date().toISOString(),
      });
    }

    /* ── configuración ───────────────────────────────────────────────── */
    if (accion === "config") {
      const slug = String(body.slug ?? "");
      if (!/^[a-z0-9-]{1,60}$/.test(slug)) return json({ error: "bad slug" }, 400);
      const patch: Record<string, unknown> = {};
      for (const [k, limpia] of Object.entries(EDITABLES)) {
        if (k in (body.cambios as object ?? {})) {
          patch[k] = limpia((body.cambios as Record<string, unknown>)[k]);
        }
      }
      if (!Object.keys(patch).length) return json({ error: "nothing to change" }, 400);
      const fila = await sb(`competitors?slug=eq.${slug}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      return json({ ok: true, competidor: fila?.[0] ?? null, aplicado: patch });
    }

    /* ── lanzar el rastreo ───────────────────────────────────────────── */
    if (accion === "run") {
      const gh = Deno.env.get("GITHUB_TOKEN");
      const repo = Deno.env.get("GITHUB_REPO") ?? "inakigorostiza/forum-sport-pricing";
      if (!gh) {
        return json({ error: "setup", detail: "GITHUB_TOKEN is not set on this project yet." }, 503);
      }
      const slug = body.slug ? String(body.slug) : "";
      if (slug && !/^[a-z0-9-]{1,60}$/.test(slug)) return json({ error: "bad slug" }, 400);
      const phase = body.phase === "discover" ? "discover" : "refresh";
      const limit = body.limit ? String(Math.min(5000, Math.max(1, Number(body.limit) || 0))) : "";

      const r = await fetch(
        `https://api.github.com/repos/${repo}/actions/workflows/scrape.yml/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${gh}`,
            Accept: "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "forum-sport-pricing-panel",
          },
          body: JSON.stringify({ ref: "main", inputs: { competitor: slug, phase, limit } }),
        },
      );
      // GitHub responde 204 sin cuerpo y NO devuelve el id de la ejecución, así
      // que el panel no puede seguirla: enlaza a la lista de ejecuciones.
      if (r.status !== 204) {
        return json({ error: "github", status: r.status, detail: (await r.text()).slice(0, 400) }, 502);
      }
      return json({
        ok: true,
        lanzado: { competidor: slug || "(todos)", phase, limit: limit || null },
        url: `https://github.com/${repo}/actions/workflows/scrape.yml`,
      });
    }

    return json({ error: "unknown action" }, 400);
  } catch (e) {
    return json({ error: "failed", detail: String(e).slice(0, 400) }, 500);
  }
});
