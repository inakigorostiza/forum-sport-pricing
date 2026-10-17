/* Creative Studio: turns a model's recommended price into a branded creative.
 *
 * Generating spends real money on Higgsfield, so every action sits behind the
 * same operator token as the scraping panel. The browser never sees the
 * Higgsfield key and never writes the prompt: the prompt is built here, from
 * the catalogue row and the design-system rules, so a claim on a creative can
 * only come from the data ("limited stock" only when stock is low, and so on).
 *
 * Flow:
 *   create   → inserts the row, submits the still to Marketing Studio Flare
 *   status   → polls Higgsfield; reports when the still is ready to brand,
 *              copies a finished video into Storage
 *   source   → proxies the finished still's bytes, so the browser can draw it
 *              on a canvas without a cross-origin taint
 *   finalize → takes the still with the real logo composited by the browser,
 *              stores it, and for video submits the image-to-video job
 *   estimate → cost before spending
 *
 * The logo is composited in the browser on purpose: decoding and re-encoding a
 * 2K image here can exceed the Edge Function CPU limit; the operator's browser
 * does it in milliseconds.
 *
 * Secrets: OPERATOR_TOKEN, HIGGSFIELD_API_KEY_ID, HIGGSFIELD_API_KEY_SECRET.
 * SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected by Supabase.
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-operator-token",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

function tokenValido(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

const SB_URL = Deno.env.get("SUPABASE_URL")!;
const SB_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const HF = "https://api.higgsfield.ai";
const IMG_PATH = "/marketing-studio/image/flare";
const VID_PATH = "/kling-video/v2.6/pro/image-to-video";

async function sb(path: string, init: RequestInit = {}) {
  const r = await fetch(`${SB_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`, "Content-Type": "application/json",
      Prefer: "return=representation", ...(init.headers ?? {}),
    },
  });
  const txt = await r.text();
  if (!r.ok) throw new Error(`${r.status} ${txt.slice(0, 300)}`);
  return txt ? JSON.parse(txt) : null;
}

async function upload(path: string, bytes: Uint8Array, type: string) {
  const r = await fetch(`${SB_URL}/storage/v1/object/creatives/${path}`, {
    method: "POST",
    headers: { apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}`, "Content-Type": type, "x-upsert": "true" },
    body: bytes,
  });
  if (!r.ok) throw new Error(`storage ${r.status} ${(await r.text()).slice(0, 200)}`);
  return `${SB_URL}/storage/v1/object/public/creatives/${path}`;
}

function hfAuth() {
  const id = Deno.env.get("HIGGSFIELD_API_KEY_ID"), secret = Deno.env.get("HIGGSFIELD_API_KEY_SECRET");
  return id && secret ? `Key ${id}:${secret}` : null;
}
async function hf(path: string, body: unknown, idem?: string) {
  const r = await fetch(HF + path, {
    method: "POST",
    headers: {
      Authorization: hfAuth()!, "Content-Type": "application/json",
      ...(idem ? { "Idempotency-Key": idem } : {}),
    },
    body: JSON.stringify(body),
  });
  const txt = await r.text();
  if (!r.ok) throw new Error(`higgsfield ${r.status} ${txt.slice(0, 300)}`);
  return JSON.parse(txt);
}
async function hfStatus(reqId: string) {
  const r = await fetch(`${HF}/requests/${reqId}/status`, { headers: { Authorization: hfAuth()! } });
  const txt = await r.text();
  if (!r.ok) throw new Error(`higgsfield status ${r.status} ${txt.slice(0, 200)}`);
  return JSON.parse(txt);
}

/* ── Channels and formats: the aspect each one needs, and what we ask the
   image model for. Flare has no 4:5, so the Instagram feed is generated at
   3:4 and cropped to 4:5 in the browser before the logo goes on. Kling only
   does 16:9, 9:16 and 1:1, so video formats are limited to those. ─────── */
const FORMATS: Record<string, { aspect: string; gen: string; video: boolean; style: string }> = {
  "instagram:feed":   { aspect: "4:5",  gen: "3:4",  video: false, style: "poster" },
  "instagram:story":  { aspect: "9:16", gen: "9:16", video: true,  style: "story" },
  "instagram:reel":   { aspect: "9:16", gen: "9:16", video: true,  style: "story" },
  "tiktok:video":     { aspect: "9:16", gen: "9:16", video: true,  style: "story" },
  "youtube:video":    { aspect: "16:9", gen: "16:9", video: true,  style: "wide" },
  "youtube:shorts":   { aspect: "9:16", gen: "9:16", video: true,  style: "story" },
  "facebook:feed":    { aspect: "1:1",  gen: "1:1",  video: true,  style: "square" },
  "display:banner":   { aspect: "16:9", gen: "16:9", video: false, style: "wide" },
};
const GOALS = ["awareness", "sale", "clearance", "launch"];

const eur = (n: number) => n.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "€";

type Model = {
  modelo: number; brand_code: string; nombre_modelo: string; tipo_producto: string;
  precio: number; precio_rebaja: number; nivel_stock: string | null; exclusivo_online: boolean;
  outlet: boolean; ano_temporada: number | null; img_full: string;
};

/* The prompt. Every word a shopper will read is fixed here, from the data:
   the model writes no claim of its own, and is told to leave the logo corner
   empty so the real logo can be composited afterwards. */
function buildPrompt(m: Model, rec: number, goal: string, style: string) {
  const now = Number(m.precio_rebaja);
  const cut = rec < now - 0.5;
  const pct = cut ? Math.round((1 - rec / now) * 100) : 0;
  const lowStock = m.nivel_stock === "bajo" || m.nivel_stock === "muy bajo";
  const headline: Record<string, string> = {
    awareness: "CORRE A TU MANERA.",
    sale: cut ? "MISMO RITMO. MENOS PRECIO." : "TU PRÓXIMO PAR.",
    clearance: lowStock ? "ÚLTIMAS UNIDADES." : "OPORTUNIDAD.",
    launch: "YA DISPONIBLE.",
  };
  const badges: string[] = [];
  if (cut) badges.push(`a small square red tag with white text '-${pct}%'`);
  if (lowStock) badges.push("a small black square sticker with white condensed caps 'STOCK LIMITADO'");
  if (m.exclusivo_online) badges.push("a small black square sticker with white condensed caps 'SOLO ONLINE'");
  const price = cut
    ? `the old price '${eur(now)}' smaller and struck through with a thin line, and the new price '${eur(rec)}' very large in a hand-lettered condensed brush script in red #E32219`
    : `the price '${eur(rec)}' very large in a hand-lettered condensed brush script in red #E32219`;
  const layout: Record<string, string> = {
    poster: "Bold graphic retail poster: flat light grey #F2F2F2 background with one thick diagonal band in red #E32219 behind the product, crisp motion streaks.",
    story: "Vertical social story in a fresh collage style: flat light grey #F2F2F2 background, the product cut out with a thick white sticker outline, short red #E32219 speed marks, sticker-style labels.",
    wide: "Wide banner: product on the right two thirds, all text stacked on the left third, flat light grey #F2F2F2 background with a red #E32219 diagonal band.",
    square: "Clean square layout: product centred on flat light grey #F2F2F2 with a red #E32219 band across the lower third.",
  };
  return [
    `Advertising creative for the Spanish sports retailer Forum Sport, aimed at young runners aged 18 to 28.`,
    `Hero: the exact ${m.brand_code} ${m.nombre_modelo} from the reference image. Keep the product's design, colours and brand marks exactly as in the reference; show it large and dynamic.`,
    layout[style],
    `All typography in bold condensed sans-serif capitals (Roboto Condensed style) in near-black #222222 unless stated. Headline: '${headline[goal]}'.`,
    `Price block: ${price}.`,
    badges.length ? `Also: ${badges.join("; ")}.` : "",
    `Very small grey text in the bottom-right corner: 'Imagen generada con IA'.`,
    `Leave the bottom-left corner completely empty and flat: a clean area of about 32% of the width and 13% of the height with no text, no objects and no logo. Do not write the words Forum Sport or any retailer logo anywhere.`,
    `Square corners only, flat design, no emoji, no icons, no rounded buttons. Spanish text must be spelled exactly as given.`,
  ].filter(Boolean).join(" ");
}

const VIDEO_PROMPT =
  "Subtle premium product motion: a slow camera push-in, the shoe lifts slightly and its shadow breathes, " +
  "light streaks pass in the background. All text, prices and the logo stay perfectly still, sharp and legible. No new text.";

async function loadModel(modelo: number): Promise<Model> {
  const rows = await sb(
    `models?select=modelo,brand_code,nombre_modelo,tipo_producto,precio,precio_rebaja,nivel_stock,` +
    `exclusivo_online,outlet,ano_temporada,img_full&modelo=eq.${modelo}&limit=1`,
  );
  if (!rows?.length) throw new Error("model not found");
  return rows[0];
}

/* Validates the request and returns everything both estimate and create need. */
async function prepare(body: Record<string, unknown>) {
  const modelo = Number(body.modelo);
  const kind = body.kind === "video" ? "video" : "image";
  const key = `${body.channel}:${body.format}`;
  const f = FORMATS[key];
  const goal = String(body.goal);
  if (!Number.isFinite(modelo) || !f || !GOALS.includes(goal)) throw new Error("bad request");
  if (kind === "video" && !f.video) throw new Error("this format has no video version");
  const m = await loadModel(modelo);
  const rec = Math.round(Number(body.price_rec) * 100) / 100;
  // The recommended price comes from the browser's engine; keep it sane.
  if (!(rec > 0 && rec <= Number(m.precio) && rec >= Number(m.precio_rebaja) * 0.3)) throw new Error("price out of range");
  const prompt = buildPrompt(m, rec, goal, f.style);
  const imageBody = { prompt, image_urls: [m.img_full], aspect_ratio: f.gen, resolution: "2k", quality: "high" };
  return { modelo, kind, f, goal, m, rec, prompt, imageBody, channel: String(body.channel), format: String(body.format) };
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const esperado = Deno.env.get("OPERATOR_TOKEN");
  if (!esperado) return json({ error: "setup", detail: "OPERATOR_TOKEN is not set." }, 503);
  if (!tokenValido(req.headers.get("x-operator-token") ?? "", esperado)) return json({ error: "unauthorized" }, 401);
  if (!hfAuth()) return json({ error: "higgsfield_setup", detail: "HIGGSFIELD_API_KEY_ID / _SECRET are not set." }, 503);

  let body: Record<string, unknown> = {};
  try { body = await req.json(); } catch { /* */ }
  const action = String(body.action ?? "");

  try {
    if (action === "estimate") {
      const p = await prepare(body);
      const img = await hf(`/estimate${IMG_PATH}`, p.imageBody);
      let vid = null;
      if (p.kind === "video") {
        vid = await hf(`/estimate${VID_PATH}`, { prompt: VIDEO_PROMPT, image_url: p.m.img_full, duration: 5, sound: "off", aspect_ratio: p.f.aspect });
      }
      return json({ image: img, video: vid });
    }

    if (action === "create") {
      const p = await prepare(body);
      const [row] = await sb("creatives", {
        method: "POST",
        body: JSON.stringify({
          modelo: p.modelo, kind: p.kind, channel: p.channel, format: p.format, aspect: p.f.aspect,
          goal: p.goal, prompt: p.prompt, price_now: p.m.precio_rebaja, price_rec: p.rec, status: "queued",
        }),
      });
      try {
        const sub = await hf(IMG_PATH, p.imageBody, `${row.id}-img`);
        await sb(`creatives?id=eq.${row.id}`, {
          method: "PATCH", body: JSON.stringify({ hf_image_req: sub.request_id, status: "still", updated_at: new Date().toISOString() }),
        });
      } catch (e) {
        await sb(`creatives?id=eq.${row.id}`, { method: "PATCH", body: JSON.stringify({ status: "failed", error: String(e).slice(0, 500) }) });
        throw e;
      }
      return json({ id: row.id, aspect: p.f.aspect, gen: p.f.gen });
    }

    const id = String(body.id ?? "");
    if (!/^[0-9a-f-]{36}$/.test(id)) return json({ error: "bad id" }, 400);
    const [row] = await sb(`creatives?id=eq.${id}&select=*`);
    if (!row) return json({ error: "not found" }, 404);

    if (action === "status") {
      if (row.status === "still") {
        const s = await hfStatus(row.hf_image_req);
        if (s.status === "completed") return json({ stage: "brand", aspect: row.aspect, kind: row.kind });
        if (["failed", "nsfw", "canceled"].includes(s.status)) {
          await sb(`creatives?id=eq.${id}`, { method: "PATCH", body: JSON.stringify({ status: "failed", error: `still ${s.status}` }) });
          return json({ stage: "failed", detail: s.status });
        }
        return json({ stage: "still", detail: s.status });
      }
      if (row.status === "motion") {
        const s = await hfStatus(row.hf_video_req);
        if (s.status === "completed" && s.video?.url) {
          const v = await fetch(s.video.url);
          const url = await upload(`${id}.mp4`, new Uint8Array(await v.arrayBuffer()), "video/mp4");
          await sb(`creatives?id=eq.${id}`, { method: "PATCH", body: JSON.stringify({ video_url: url, status: "done", updated_at: new Date().toISOString() }) });
          return json({ stage: "done", image_url: row.image_url, video_url: url });
        }
        if (["failed", "nsfw", "canceled"].includes(s.status)) {
          await sb(`creatives?id=eq.${id}`, { method: "PATCH", body: JSON.stringify({ status: "failed", error: `video ${s.status}` }) });
          return json({ stage: "failed", detail: s.status });
        }
        return json({ stage: "motion", detail: s.status });
      }
      return json({ stage: row.status, image_url: row.image_url, video_url: row.video_url, detail: row.error });
    }

    if (action === "source") {
      const s = await hfStatus(row.hf_image_req);
      const url = s.images?.[0]?.url;
      if (!url) return json({ error: "not ready" }, 409);
      const r = await fetch(url);
      return new Response(r.body, { headers: { ...CORS, "Content-Type": r.headers.get("content-type") ?? "image/png" } });
    }

    if (action === "finalize") {
      if (row.status !== "still") return json({ error: "not waiting for a still" }, 409);
      const b64 = String(body.jpeg ?? "").replace(/^data:image\/\w+;base64,/, "");
      if (b64.length < 1000 || b64.length > 12_000_000) return json({ error: "bad image" }, 400);
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      const imageUrl = await upload(`${id}.jpg`, bytes, "image/jpeg");
      if (row.kind === "image") {
        await sb(`creatives?id=eq.${id}`, { method: "PATCH", body: JSON.stringify({ image_url: imageUrl, status: "done", updated_at: new Date().toISOString() }) });
        return json({ stage: "done", image_url: imageUrl });
      }
      const sub = await hf(VID_PATH, { prompt: VIDEO_PROMPT, image_url: imageUrl, duration: 5, sound: "off", aspect_ratio: row.aspect }, `${id}-vid`);
      await sb(`creatives?id=eq.${id}`, {
        method: "PATCH", body: JSON.stringify({ image_url: imageUrl, hf_video_req: sub.request_id, status: "motion", updated_at: new Date().toISOString() }),
      });
      return json({ stage: "motion", image_url: imageUrl });
    }

    return json({ error: "unknown action" }, 400);
  } catch (e) {
    return json({ error: "failed", detail: String(e).slice(0, 400) }, 500);
  }
});
