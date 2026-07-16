# -*- coding: utf-8 -*-
"""
Porto Flats — Servicio PDF + Mini-anuncio + Panel de Revisión
Flask service para n8n + WhatsApp automation
"""
import base64
import json
import os
import tempfile
import textwrap
from datetime import datetime

import requests as http
import uuid as _uuid
from flask import Flask, request, jsonify, Response, redirect
from build_presupuesto import draw_presupuesto, draw_presupuesto_v2
from build_recibo import draw_recibo

app = Flask(__name__)

# ── Evolution API ────────────────────────────────────────────────────────────
EVO_URL  = os.environ.get("EVOLUTION_API_URL",  "https://pf-evolution-api.bg4ga1.easypanel.host")
EVO_KEY  = os.environ.get("EVOLUTION_API_KEY",  "F08BB21DEC16-4D00-B400-B16F5CC98731")
EVO_INST = os.environ.get("EVOLUTION_INSTANCE", "Porto Flats")
WA_NUM   = os.environ.get("WA_NUMBER", "5511999999999")
N8N_STATUS_WH = os.environ.get("N8N_STATUS_WEBHOOK", "")
MARCELO_NUM   = os.environ.get("MARCELO_NUMBER", "543815408730")


def _evo_headers():
    return {"apikey": EVO_KEY, "Content-Type": "application/json"}

def _evo_send_text(numero, text):
    url = f"{EVO_URL}/message/sendText/{EVO_INST}"
    try:
        r = http.post(url, json={"number": str(numero), "text": text},
                      headers=_evo_headers(), timeout=30)
        print(f"[EVO text] status={r.status_code} num={numero} body={r.text[:200]}")
        return r.status_code < 300
    except Exception as e:
        print(f"[EVO text error] {e}")
        return False

def _evo_send_pdf(numero, pdf_b64, filename, caption=""):
    url = f"{EVO_URL}/message/sendMedia/{EVO_INST}"
    try:
        http.post(url, json={
            "number": str(numero),
            "mediatype": "document",
            "media": pdf_b64,
            "fileName": filename,
            "caption": caption or "\U0001f4c4 Tu presupuesto Porto Flats. ¡Estamos a disposición!"
        }, headers=_evo_headers(), timeout=45)
    except Exception as e:
        print(f"[EVO pdf error] {e}")

# ── Own Short Links (propuestas.portoflats.com) ──────────────────────────────
PROPUESTAS_DOMAIN = os.environ.get("PROPUESTAS_DOMAIN", "https://propuestas.portoflats.com")
SHORT_LINKS_FILE  = os.environ.get("SHORT_LINKS_FILE",  "/tmp/short_links.json")

def _load_links():
    try:
        with open(SHORT_LINKS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_links(links):
    try:
        os.makedirs(os.path.dirname(SHORT_LINKS_FILE), exist_ok=True)
        with open(SHORT_LINKS_FILE, "w") as f:
            json.dump(links, f)
    except Exception as e:
        print(f"[shortlinks save error] {e}")

def _own_shorten(url):
    """Genera un link corto con dominio propio. Reemplaza TinyURL."""
    try:
        code = _uuid.uuid4().hex[:8]
        links = _load_links()
        links[code] = url
        _save_links(links)
        return f"{PROPUESTAS_DOMAIN}/p/{code}"
    except Exception:
        return url  # fallback: URL completa

def _tinyurl(url):
    """Alias para compatibilidad — usa dominio propio."""
    return _own_shorten(url)


# ── Proposal Store (45 días de retención) ────────────────────────────────────
PROPOSALS_FILE = os.environ.get("PROPOSALS_FILE", "/app/proposals.json")

def _load_proposals():
    try:
        with open(PROPOSALS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_proposals_store(store):
    try:
        d = os.path.dirname(PROPOSALS_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(PROPOSALS_FILE, "w") as f:
            json.dump(store, f, ensure_ascii=False)
    except Exception as e:
        print(f"[proposals save error] {e}")

def _purge_proposals(store, days=45):
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    return {k: v for k, v in store.items() if v.get("created_at", "") > cutoff}

def _store_proposal(nombre, wa_dest, email, ci, co, noites, prop_url, form_dict):
    """Guarda propuesta en el store local. Retorna prop_id. Purga automáticamente > 45 días."""
    from datetime import datetime
    store = _load_proposals()
    store = _purge_proposals(store)
    prop_id = _uuid.uuid4().hex[:10]
    store[prop_id] = {
        "id":         prop_id,
        "created_at": datetime.now().isoformat(),
        "nombre":     nombre,
        "wa_dest":    wa_dest,
        "email":      email,
        "ci":         ci,
        "co":         co,
        "noites":     noites,
        "prop_url":   prop_url,
        "form_data":  form_dict,
    }
    _save_proposals_store(store)
    return prop_id


# ── Settings Store ────────────────────────────────────────────────────────────
SETTINGS_FILE = os.environ.get("SETTINGS_FILE", "/app/settings.json")

DEFAULT_SETTINGS = {
    "n_fotos":             8,       # Fotos por opción (1-10)
    "margen_pct":          25,      # Margen % por defecto
    "reserva_anticipo":    50,      # Anticipo % por defecto
    "saldo_plazo":         "15 días antes del check-in",
    "forma_pago_defaults": ["fp_transf"],   # checkboxes pre-marcados
    "msg_intro":           "Te preparamos una propuesta de alojamiento en Porto de Galinhas.",
    "dias_historial":      45,
    "cond_extra_default":  "",      # Nota libre en condiciones (por defecto)
}

def _load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            stored = json.load(f)
        cfg = dict(DEFAULT_SETTINGS)
        cfg.update(stored)
        return cfg
    except Exception:
        return dict(DEFAULT_SETTINGS)

def _save_settings(new_cfg):
    try:
        d = os.path.dirname(SETTINGS_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
        cfg = _load_settings()
        cfg.update(new_cfg)
        with open(SETTINGS_FILE, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[settings save error] {e}")
        return False


# ── /api/settings ─────────────────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({"ok": True, "settings": _load_settings()})

@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json(silent=True) or {}
    # Validaciones básicas
    if "n_fotos" in data:
        data["n_fotos"] = max(1, min(10, int(data["n_fotos"])))
    if "margen_pct" in data:
        data["margen_pct"] = max(0, min(100, int(data["margen_pct"])))
    if "reserva_anticipo" in data:
        data["reserva_anticipo"] = max(0, min(100, int(data["reserva_anticipo"])))
    if "dias_historial" in data:
        data["dias_historial"] = max(7, min(90, int(data["dias_historial"])))
    ok = _save_settings(data)
    return jsonify({"ok": ok, "settings": _load_settings()})


# ── /health ──────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "porto-flats-pdf"})


# ── /api/shorten ─────────────────────────────────────────────────────────────
@app.route("/api/shorten", methods=["POST"])
def api_shorten():
    """Crea un link corto propio. Body: {url: '...'} → {short_url: '...', code: '...'}"""
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url requerida"}), 400
    short = _own_shorten(url)
    code  = short.rsplit("/", 1)[-1]
    return jsonify({"short_url": short, "code": code, "original_url": url})


# ── /p/<code> ────────────────────────────────────────────────────────────────
@app.route("/p/<code>", methods=["GET"])
def redirect_short(code):
    """Redirige al link original a partir del código corto."""
    links = _load_links()
    dest  = links.get(code)
    if not dest:
        return jsonify({"error": "link no encontrado"}), 404
    return redirect(dest, code=302)


# ── /v/<prop_id> — URL limpia con dominio propio ──────────────────────────────
@app.route("/v/<prop_id>", methods=["GET"])
def view_propuesta(prop_id):
    """Sirve la propuesta desde el historial local. URL limpia y persistente (45 días)."""
    store = _load_proposals()
    entry = store.get(prop_id)
    if not entry:
        html_exp = (
            "<!DOCTYPE html><html lang='es'><head><meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Porto Flats</title>"
            "<style>body{font-family:-apple-system,sans-serif;background:#EDE9E3;"
            "display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}"
            ".card{background:#fff;border-radius:18px;padding:32px 24px;max-width:380px;"
            "width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08)}"
            "h2{color:#87A286;font-size:20px;margin-bottom:12px}"
            "p{font-size:14px;color:#666;line-height:1.6}"
            "</style></head><body>"
            "<div class='card'><h2>🌊 Porto Flats</h2>"
            "<p>Esta propuesta ya no está disponible.<br>"
            "Contactanos por WhatsApp para recibir una nueva.</p></div>"
            "</body></html>"
        )
        return Response(html_exp.encode("utf-8"), content_type="text/html; charset=utf-8", status=410)
    return redirect(entry["prop_url"], code=302)


# ── /api/historial ────────────────────────────────────────────────────────────
@app.route("/api/historial", methods=["GET"])
def api_historial():
    """Lista propuestas enviadas en los últimos 45 días (sin form_data completo)."""
    store = _load_proposals()
    store = _purge_proposals(store)
    items = []
    for v in sorted(store.values(), key=lambda x: x.get("created_at", ""), reverse=True):
        items.append({
            "id":         v["id"],
            "created_at": v.get("created_at", ""),
            "nombre":     v.get("nombre", ""),
            "wa_dest":    v.get("wa_dest", ""),
            "email":      v.get("email", ""),
            "ci":         v.get("ci", ""),
            "co":         v.get("co", ""),
            "noites":     v.get("noites", ""),
            "short_url":  PROPUESTAS_DOMAIN + "/v/" + v["id"],
        })
    return jsonify({"ok": True, "total": len(items), "propuestas": items})


# ── /api/propuesta/<prop_id> ──────────────────────────────────────────────────
@app.route("/api/propuesta/<prop_id>", methods=["GET"])
def api_get_propuesta(prop_id):
    """Devuelve propuesta completa (con form_data) para edición."""
    store = _load_proposals()
    entry = store.get(prop_id)
    if not entry:
        return jsonify({"error": "No encontrada o vencida"}), 404
    return jsonify({"ok": True, "propuesta": entry})


# ── /api/eliminar/<prop_id> ───────────────────────────────────────────────────
@app.route("/api/eliminar/<prop_id>", methods=["DELETE", "POST"])
def api_eliminar(prop_id):
    """Elimina una propuesta del historial."""
    store = _load_proposals()
    if prop_id not in store:
        return jsonify({"ok": True})  # idempotente — ya no existe
    del store[prop_id]
    _save_proposals_store(store)
    return jsonify({"ok": True})


# ── /api/reenviar/<prop_id> ───────────────────────────────────────────────────
@app.route("/api/reenviar/<prop_id>", methods=["POST"])
def api_reenviar(prop_id):
    """Reenvía por WhatsApp la misma propuesta usando la URL limpia almacenada."""
    store = _load_proposals()
    entry = store.get(prop_id)
    if not entry:
        return jsonify({"error": "No encontrada o vencida"}), 404
    short_url       = PROPUESTAS_DOMAIN + "/v/" + prop_id
    nombre_completo = entry.get("nombre", "")
    wa_dest         = entry.get("wa_dest", "")
    nombre_corto    = nombre_completo.split()[0].title() if nombre_completo else "!"
    msg = ("\U0001f30a Hola *" + nombre_corto + "*!\n\n"
           "Te reenviamos tu propuesta de alojamiento en Porto de Galinhas.\n\n"
           "\U0001f4cc Ver opciones:\n" + short_url)
    wa_ok = _evo_send_text(wa_dest, msg)
    return jsonify({"ok": wa_ok, "short_url": short_url, "wa_dest": wa_dest})


# ── /propiedad ────────────────────────────────────────────────────────────────
@app.route("/propiedad", methods=["GET"])
def propiedad_page():
    """
    Propuesta completa para el cliente: fotos, detalles, precios, mapa, política.
    Params: t, d, c, b, h, a, p, l, m, o, ci, co, n, nr, pol, f1..f10
    """
    from urllib.parse import quote as urlquote
    t    = request.args.get("t", "Propiedad")
    d    = request.args.get("d", "Porto de Galinhas, PE")
    c    = request.args.get("c", "1")
    b    = request.args.get("b", "1")
    h    = request.args.get("h", "2")
    a    = request.args.get("a", "")
    p    = request.args.get("p", "")
    lim  = request.args.get("l", "")
    m    = request.args.get("m", "")
    orig = request.args.get("o", "")
    ci   = request.args.get("ci", "")
    co   = request.args.get("co", "")
    n    = request.args.get("n", "")
    nr   = request.args.get("nr", "")   # nombre cliente
    pol  = request.args.get("pol", "")  # URL política de cancelación
    wa_num = WA_NUM

    # ── Fotos ────────────────────────────────────────────────────────────────
    fotos_list = [request.args.get(f"f{i}", "") for i in range(1, 11)]
    fotos_list = [f for f in fotos_list if f]
    gallery_html = ""
    if fotos_list:
        imgs = "".join(
            '<img src="' + f + '" class="g-img" loading="lazy" onerror="this.style.display=\'none\'">'
            for f in fotos_list
        )
        gallery_html = '<div class="gallery np">' + imgs + '</div>'

    # ── Amenidades ───────────────────────────────────────────────────────────
    amenidades_list = [x.strip() for x in a.split(",") if x.strip()] if a else []
    amenidades_html = "".join('<span class="tag">' + x + '</span>' for x in amenidades_list)

    # ── Precios ──────────────────────────────────────────────────────────────
    try:
        p_num   = float(str(p).replace(",", "."))   if p   else 0
        lim_num = float(str(lim).replace(",", ".")) if lim else 0
        n_num   = int(n) if n else 0
        total_num = p_num * n_num + lim_num if n_num else 0
    except Exception:
        p_num = lim_num = total_num = 0
        n_num = 0

    if n:
        noches_label = str(n) + " noche" + ("s" if str(n) != "1" else "")
    else:
        noches_label = ""

    price_rows = ""
    if p:
        price_rows += '<div class="pr-row"><span>\U0001f319 Precio por noche</span><span>R$ ' + str(p) + '</span></div>'
    if noches_label:
        price_rows += '<div class="pr-row"><span>\U0001f4c5 Noches</span><span>\xd7 ' + str(n) + '</span></div>'
    if lim:
        price_rows += '<div class="pr-row"><span>\U0001f9f9 Tarifa de limpieza</span><span>R$ ' + str(lim) + '</span></div>'
    if total_num > 0:
        t_fmt = str("{:,}".format(int(total_num))).replace(",", ".")
        price_rows += '<div class="pr-row pr-total"><span>\U0001f4b0 Total estimado</span><span>R$ ' + t_fmt + '</span></div>'
    if price_rows:
        price_section = '<div class="card"><div class="sec-title">Precio estimado</div><div class="pr-table">' + price_rows + '</div></div>'
    else:
        price_section = ""

    # ── Fechas ───────────────────────────────────────────────────────────────
    dates_section = ""
    if ci or co:
        noches_div = ('<div class="date-noches">' + noches_label + '</div>') if noches_label else ""
        dates_section = (
            '<div class="card">'
            '<div class="sec-title">Tus fechas</div>'
            '<div class="dates-box">'
            '<div class="date-item"><span class="date-label">Check-in</span><span class="date-val">' + (ci or "—") + '</span></div>'
            '<div class="date-sep">→</div>'
            '<div class="date-item"><span class="date-label">Check-out</span><span class="date-val">' + (co or "—") + '</span></div>'
            + noches_div +
            '</div>'
            '</div>'
        )

    # ── Google Maps embed ─────────────────────────────────────────────────────
    maps_section = ""
    if m:
        if "google.com/maps" in m and "output=embed" not in m:
            embed_url = m + ("&" if "?" in m else "?") + "output=embed"
        elif "maps.google.com/maps?" in m:
            embed_url = m if "output=embed" in m else m + "&output=embed"
        else:
            embed_url = None

        if embed_url:
            maps_section = (
                '<div class="card np"><div class="sec-title">\U0001f4cd Ubicaci\xf3n</div>'
                '<div class="maps-wrap"><iframe src="' + embed_url + '" width="100%" height="220" '
                'frameborder="0" style="border:0;border-radius:12px;display:block" '
                'allowfullscreen loading="lazy"></iframe></div>'
                '<a href="' + m + '" class="btn btn-maps" target="_blank">\U0001f5fa Ver en Google Maps</a></div>'
            )
        else:
            maps_section = (
                '<div class="card np"><div class="sec-title">\U0001f4cd Ubicaci\xf3n</div>'
                '<a href="' + m + '" class="btn btn-maps" target="_blank">\U0001f5fa Abrir en Google Maps</a></div>'
            )
    else:
        loc_q = urlquote(t + ", Porto de Galinhas, Pernambuco, Brasil")
        maps_section = (
            '<div class="card np"><div class="sec-title">\U0001f4cd Ubicaci\xf3n</div>'
            '<div class="maps-wrap"><iframe src="https://maps.google.com/maps?q=' + loc_q + '&output=embed" '
            'width="100%" height="200" frameborder="0" style="border:0;border-radius:12px;display:block" '
            'allowfullscreen loading="lazy"></iframe></div></div>'
        )

    # ── Política de cancelación ───────────────────────────────────────────────
    if pol:
        pol_section = (
            '<div class="card"><div class="sec-title">Pol\xedtica de cancelaci\xf3n</div>'
            '<a href="' + pol + '" class="btn btn-light" target="_blank">\U0001f4cb Ver pol\xedtica completa</a></div>'
        )
    else:
        pol_section = (
            '<div class="card">'
            '<div class="sec-title">Pol\xedtica de cancelaci\xf3n</div>'
            '<div class="policy">'
            '<div class="pol-item">✅ Reserva confirmada con <strong>anticipo del 50%</strong></div>'
            '<div class="pol-item">\U0001f4c5 Saldo abonado <strong>15 d\xedas antes</strong> del check-in</div>'
            '<div class="pol-item">\U0001f504 Cancelaci\xf3n +30 d\xedas: reembolso del anticipo (menos tasas)</div>'
            '<div class="pol-item">❌ Cancelaci\xf3n -30 d\xedas: sin reembolso</div>'
            '<div class="pol-item">\U0001f4b3 Pago: transferencia bancaria o PIX</div>'
            '</div>'
            '</div>'
        )

    # ── Saludo cliente ────────────────────────────────────────────────────────
    if nr:
        greeting = '<div class="greeting">Preparado especialmente para <strong>' + nr + '</strong> \U0001f30a</div>'
    else:
        greeting = ""

    # ── Amenidades section ───────────────────────────────────────────────────
    if amenidades_list:
        amenidades_section = '<div class="card"><div class="sec-title">Incluye</div><div class="tags">' + amenidades_html + '</div></div>'
    else:
        amenidades_section = ""

    # ── Ver anuncio link ─────────────────────────────────────────────────────
    if orig:
        orig_link = '<a href="' + orig + '" class="btn btn-light" target="_blank">\U0001f517 Ver anuncio completo</a>'
    else:
        orig_link = ""

    cuartos_s = "s" if c != "1" else ""
    banos_s   = "s" if b != "1" else ""

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>""" + t + """ \xb7 Porto Flats</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}
.header{background:#87A286;padding:20px 16px;text-align:center}
.logo{color:#fff;font-size:20px;font-weight:300;letter-spacing:5px;text-transform:uppercase}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}
.greeting{background:#E7D7C9;text-align:center;padding:10px 16px;font-size:14px;color:#5a4a3a}
.card{background:#fff;border-radius:14px;margin:14px;padding:22px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
.badge{display:inline-block;background:#E7D7C9;color:#3D3D3D;border-radius:20px;padding:4px 14px;font-size:12px;margin-bottom:12px}
h1{font-size:24px;font-weight:400;line-height:1.3}
.location{color:#87A286;font-size:13px;margin-top:6px}
.features{display:flex;gap:16px;margin-top:16px;flex-wrap:wrap}
.feat{display:flex;align-items:center;gap:6px;font-size:14px;color:#555}
.feat-icon{font-size:18px}
.sec-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;margin-bottom:12px}
.tags{display:flex;flex-wrap:wrap;gap:8px}
.tag{background:#EDE9E3;border-radius:20px;padding:5px 13px;font-size:13px;color:#555}
.pr-table{background:#EDE9E3;border-radius:10px;padding:4px 14px}
.pr-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;font-size:14px;border-bottom:1px solid rgba(0,0,0,.06)}
.pr-row:last-child{border-bottom:none}
.pr-total{font-weight:700;font-size:16px;color:#87A286;padding-top:12px;margin-top:4px;border-top:2px solid rgba(135,162,134,.3)!important;border-bottom:none!important}
.pr-discount{background:rgba(135,162,134,.08);border-radius:6px;padding:10px 6px!important;margin:4px -6px}
.disc-tag{background:#FF6B35;color:#fff;font-size:10px;font-weight:700;padding:2px 6px;border-radius:5px;margin-left:4px;vertical-align:middle}
.dates-box{background:#EDE9E3;border-radius:10px;padding:16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.date-item{flex:1;min-width:90px}
.date-label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#87A286;margin-bottom:3px}
.date-val{font-size:16px;font-weight:500}
.date-sep{font-size:20px;color:#CDC6C3}
.date-noches{width:100%;text-align:center;font-size:13px;color:#888;margin-top:6px}
.btn{display:block;text-align:center;padding:14px;border-radius:10px;font-size:15px;text-decoration:none;margin-top:10px;font-weight:500;cursor:pointer;border:none;width:100%;font-family:inherit}
.btn-green{background:#87A286;color:#fff}
.btn-pdf{background:#3D3D3D;color:#fff;font-size:14px;padding:12px}
.btn-maps{background:#4a90d9;color:#fff}
.btn-light{background:#EDE9E3;color:#3D3D3D}
.maps-wrap{border-radius:12px;overflow:hidden;margin-bottom:12px}
.policy{padding:4px 0}
.pol-item{font-size:13px;padding:7px 0;color:#555;border-bottom:1px solid #EDE9E3}
.pol-item:last-child{border-bottom:none}
.footer{text-align:center;padding:20px 16px 32px;color:#aaa;font-size:12px;line-height:1.7}
.gallery{display:flex;overflow-x:auto;gap:10px;padding:14px 14px 4px;scrollbar-width:none;-ms-overflow-style:none}
.gallery::-webkit-scrollbar{display:none}
.g-img{height:220px;min-width:300px;max-width:340px;object-fit:cover;border-radius:12px;flex-shrink:0;background:#CDC6C3}
@media print{
  .np{display:none!important}
  body{background:#fff}
  .card{box-shadow:none;border:1px solid #eee;margin:6px;page-break-inside:avoid}
  .header{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .pr-table,.dates-box{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  .greeting{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
</style>
</head>
<body>
<div class="header">
  <div class="logo">Porto Flats</div>
  <div class="logo-sub">Porto de Galinhas \xb7 Pernambuco \xb7 Brasil</div>
</div>
""" + greeting + """
""" + gallery_html + """
<div class="card">
  <div class="badge">\U0001f4cd """ + d + """</div>
  <h1>""" + t + """</h1>
  <div class="location">Porto de Galinhas \xb7 PE \xb7 Brasil</div>
  <div class="features">
    <div class="feat"><span class="feat-icon">\U0001f6cf</span>""" + c + """ cuarto""" + cuartos_s + """</div>
    <div class="feat"><span class="feat-icon">\U0001f6bf</span>""" + b + """ ba\xf1o""" + banos_s + """</div>
    <div class="feat"><span class="feat-icon">\U0001f465</span>Hasta """ + h + """ personas</div>
  </div>
</div>
""" + dates_section + """
""" + price_section + """
""" + amenidades_section + """
""" + maps_section + """
""" + pol_section + """
<div class="card np">
  <div class="sec-title">¿Te interesa? Confirm\xe1 tu reserva</div>
  <a href="https://wa.me/""" + wa_num + """?text=Hola!+Me+interesa+""" + t.replace(' ', '+') + """" class="btn btn-green">\U0001f4ac Consultar por WhatsApp</a>
  """ + orig_link + """
  <button class="btn btn-pdf np" onclick="window.print()" style="margin-top:10px">⬇️ Descargar como PDF</button>
</div>
<div class="footer np">
  Porto Flats \xb7 Alquileres temporarios<br>
  Porto de Galinhas \xb7 Pernambuco \xb7 Brasil<br>
  <small>Esta propuesta fue preparada especialmente para vos</small>
</div>
</body>
</html>"""
    return Response(html.encode('utf-8'), content_type="text/html; charset=utf-8")


# ── /generar-pdf ─────────────────────────────────────────────────────────────
@app.route("/generar-pdf", methods=["POST"])
def generar_pdf():
    """
    Acepta dos formatos:
    v2 (Panel): { numero, fecha, cliente, propiedad, distancia, personas,
                  checkin, hora_checkin, checkout, hora_checkout, noches,
                  caracteristicas[], total_brl, limpieza_brl,
                  cochera, traslado, forma_pago, anticipo_pct,
                  observaciones, url_link }
    v1 (WF02 legacy): { numero, fecha, cliente, propiedad, ubicacion_desc,
                        caracteristicas[], checkin, checkout, noches, personas,
                        items_precio[], total, condiciones[], ubicacion_link }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Body JSON requerido"}), 400

        use_v2 = "total_brl" in data

        if use_v2:
            required = ["numero", "cliente", "propiedad", "checkin", "checkout",
                        "noches", "total_brl"]
            missing = [f for f in required if f not in data]
            if missing:
                return jsonify({"error": "Faltan: " + str(missing)}), 400
            if not data.get("fecha"):
                data["fecha"] = datetime.now().strftime("%d/%m/%Y")
            data.setdefault("hora_checkin",  "14:00 hs")
            data.setdefault("hora_checkout", "12:00 hs")
            data.setdefault("distancia",     "Porto de Galinhas, PE, Brasil")
            data.setdefault("personas",      2)
            data.setdefault("caracteristicas", [])
            data.setdefault("limpieza_brl",  0)
            data.setdefault("cochera",       "No incluye")
            data.setdefault("traslado",      "")
            data.setdefault("forma_pago",    "Transferencia bancaria")
            data.setdefault("anticipo_pct",  50)
            data.setdefault("observaciones", "")
            data.setdefault("url_link",      "")
            builder = draw_presupuesto_v2
        else:
            required = ["numero", "fecha", "cliente", "propiedad",
                        "checkin", "checkout", "noches", "personas", "total"]
            missing = [f for f in required if f not in data]
            if missing:
                return jsonify({"error": "Faltan: " + str(missing)}), 400
            data.setdefault("ubicacion_desc", "Porto de Galinhas, PE, Brasil")
            data.setdefault("caracteristicas", [])
            data.setdefault("items_precio", [])
            data.setdefault("condiciones", [
                "Reserva confirma con anticipo del 50% del valor total.",
                "Saldo se abona 15 d\xedas antes del check-in.",
                "Pago: transferencia bancaria (Brasil) o consultar en pesos ARG."
            ])
            data.setdefault("ubicacion_link", "https://portoflats-my-site-1.wixsite.com/porto-flats")
            data["items_precio"] = [tuple(i) for i in data["items_precio"]]
            builder = draw_presupuesto

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        orig_dir = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        builder(tmp_path, data)
        os.chdir(orig_dir)

        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)

        pdf_b64  = base64.b64encode(pdf_bytes).decode("utf-8")
        filename = "Presupuesto_PortoFlats_" + data["numero"] + ".pdf"

        return jsonify({"ok": True, "filename": filename,
                        "pdf_base64": pdf_b64, "size_bytes": len(pdf_bytes)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /generar-recibo ───────────────────────────────────────────────────────────
@app.route("/generar-recibo", methods=["POST"])
def generar_recibo():
    """
    Body JSON: numero, fecha_pago, cliente, propiedad, monto
    Opcionales: checkin, checkout, noches, concepto, moneda, forma_pago
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Body JSON requerido"}), 400

        required = ["numero", "fecha_pago", "cliente", "propiedad", "monto"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": "Faltan campos: " + str(missing)}), 400

        data.setdefault("moneda",     "BRL")
        data.setdefault("checkin",    "")
        data.setdefault("checkout",   "")
        data.setdefault("noches",     "")
        data.setdefault("concepto",   "Pago")
        data.setdefault("forma_pago", "Transferencia bancaria")

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        orig_dir = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        draw_recibo(tmp_path, data)
        os.chdir(orig_dir)

        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)

        pdf_b64  = base64.b64encode(pdf_bytes).decode("utf-8")
        filename = "Recibo_PortoFlats_" + data["numero"] + ".pdf"

        return jsonify({"ok": True, "filename": filename,
                        "pdf_base64": pdf_b64, "size_bytes": len(pdf_bytes)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /despachar ────────────────────────────────────────────────────────────────
@app.route("/despachar", methods=["POST"])
def despachar():
    """
    Recibe datos editados del Panel, genera PDF y envía WhatsApp al cliente.
    Body JSON: cliente, numero_wa, propiedad, personas, checkin, hora_checkin,
               checkout, hora_checkout, noches, distancia, caracteristicas[],
               total_brl, limpieza_brl, cochera, traslado, forma_pago,
               anticipo_pct, observaciones, fotos[], row_number, rowTimestamp
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Body JSON requerido"}), 400

        required = ["cliente", "numero_wa", "propiedad", "noches",
                    "total_brl", "checkin", "checkout"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": "Faltan: " + str(missing)}), 400

        cliente     = data["cliente"]
        numero_wa   = str(data["numero_wa"])
        propiedad   = data["propiedad"]
        noches      = int(data.get("noches", 1) or 1)
        total_brl   = float(data.get("total_brl", 0) or 0)
        limpieza    = float(data.get("limpieza_brl", 0) or 0)
        checkin     = data["checkin"]
        checkout    = data["checkout"]
        hora_ci     = data.get("hora_checkin",  "14:00 hs")
        hora_co     = data.get("hora_checkout", "12:00 hs")
        distancia   = data.get("distancia",     "Porto de Galinhas, PE")
        personas    = data.get("personas",      2)
        caracteristicas = data.get("caracteristicas", [])
        cochera     = data.get("cochera",       "No incluye")
        traslado    = data.get("traslado",      "")
        forma_pago  = data.get("forma_pago",    "Transferencia bancaria")
        anticipo    = int(data.get("anticipo_pct", 50) or 50)
        obs         = (data.get("observaciones", "") or "").strip()
        fotos       = [f for f in data.get("fotos", []) if f and str(f).strip()]

        num_pres = data.get("numero_pres") or str(int(datetime.now().timestamp() * 1000))[-6:]
        fecha    = datetime.now().strftime("%d/%m/%Y")

        BASE_URL = os.environ.get("SERVICE_URL", "https://pf-pdf-service.bg4ga1.easypanel.host")
        from urllib.parse import quote

        def ep(v):
            return quote(str(v) if v is not None else "", safe="")

        amenidades = ", ".join(caracteristicas)
        diaria_desc = (total_brl - limpieza) / noches if noches else 0
        mini_params = [
            ("t", propiedad), ("d", distancia),
            ("c", str(data.get("cuartos", 1))), ("b", str(data.get("banos", 1))),
            ("h", str(personas)), ("a", amenidades),
            ("p", str(int(diaria_desc))), ("l", str(int(limpieza))),
            ("ci", checkin), ("co", checkout), ("n", str(noches)),
        ]
        mini_url = BASE_URL + "/propiedad?" + "&".join(k + "=" + ep(v) for k, v in mini_params)
        for i, foto_url in enumerate(fotos[:10], 1):
            mini_url += "&f" + str(i) + "=" + ep(foto_url)

        short_url = _tinyurl(mini_url)

        eW    = "\U0001f44b"
        ePF   = "\U0001f3d6"
        eCal  = "\U0001f4c5"
        eMoon = "\U0001f319"
        eCasa = "\U0001f3e1"
        eMoney= "\U0001f4b0"
        eLink = "\U0001f517"
        DIV   = "━" * 16

        nombre_corto = cliente.split()[0].title() if cliente else "cliente"
        feats_txt = "\n".join("- " + f for f in caracteristicas[:8])

        msg  = eW + " Hola " + nombre_corto + "!\n\n"
        msg += "Somos *Porto Flats* " + ePF + "\n"
        msg += "Te enviamos tu presupuesto para Porto de Galinhas!\n\n"
        msg += eCal + " Check-in:  *" + checkin  + "* \xb7 desde las " + hora_ci  + "\n"
        msg += eCal + " Check-out: *" + checkout + "* \xb7 hasta las " + hora_co  + "\n"
        msg += eMoon + " *" + str(noches) + " noches*\n\n"
        msg += DIV + "\n\n"
        msg += eCasa + " *" + propiedad + "*\n"
        if distancia:
            msg += "★ " + distancia + "\n"
        if feats_txt:
            msg += feats_txt + "\n"
        msg += "\n" + eMoney + " *Total: R$ " + str("{:,}".format(int(total_brl))).replace(",", ".") + "*"
        msg += "\nAnticipo para confirmar: " + str(anticipo) + "% del total\n\n"
        msg += DIV + "\n\n"
        msg += eLink + " Ver fotos y detalles:\n" + short_url + "\n\n"
        if obs:
            msg += "ℹ️ " + obs + "\n\n"
        msg += "Cualquier consulta, estamos a disposici\xf3n!\n"
        msg += "*Porto Flats* " + ePF

        pdf_data = {
            "numero":       num_pres,
            "fecha":        fecha,
            "cliente":      cliente.upper(),
            "propiedad":    propiedad,
            "distancia":    distancia,
            "personas":     personas,
            "checkin":      checkin,
            "hora_checkin": hora_ci,
            "checkout":     checkout,
            "hora_checkout": hora_co,
            "noches":       noches,
            "caracteristicas": caracteristicas,
            "total_brl":    total_brl,
            "limpieza_brl": limpieza,
            "cochera":      cochera,
            "traslado":     traslado,
            "forma_pago":   forma_pago,
            "anticipo_pct": anticipo,
            "observaciones": obs,
            "url_link":     short_url,
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        orig_dir = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        draw_presupuesto_v2(tmp_path, pdf_data)
        os.chdir(orig_dir)

        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)
        pdf_b64  = base64.b64encode(pdf_bytes).decode("utf-8")
        filename = "Presupuesto_PortoFlats_" + num_pres + ".pdf"

        _evo_send_text(numero_wa, msg)
        _evo_send_pdf(numero_wa, pdf_b64, filename)

        confirmacion = (
            "✅ Presupuesto enviado a *" + nombre_corto + "* (" + numero_wa + ")\n"
            "Total: R$ " + str("{:,}".format(int(total_brl))).replace(",", ".") +
            " \xb7 " + str(noches) + " noches\n"
            "Propiedad: " + propiedad
        )
        _evo_send_text(MARCELO_NUM, confirmacion)

        if N8N_STATUS_WH:
            try:
                http.post(N8N_STATUS_WH, json={
                    "row_number":   data.get("row_number"),
                    "rowTimestamp": data.get("rowTimestamp"),
                    "estado":       "Enviado al cliente",
                    "num_pres":     num_pres
                }, timeout=15)
            except Exception:
                pass

        return jsonify({
            "ok":       True,
            "num_pres": num_pres,
            "msg_len":  len(msg),
            "pdf_size": len(pdf_bytes)
        })

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


# ── /panel ────────────────────────────────────────────────────────────────────
@app.route("/panel", methods=["GET"])
def panel():
    """
    Panel de Revisión para que Marcelo edite y apruebe antes de enviar.
    Parámetro opcional: ?d=BASE64_JSON con datos pre-cargados desde WF01.
    """
    d_param = request.args.get("d", "")
    pdata = {}
    if d_param:
        try:
            padded = d_param + "=" * (-len(d_param) % 4)
            pdata = json.loads(base64.b64decode(padded).decode("utf-8"))
        except Exception:
            pass

    lead    = pdata.get("lead", {})
    opciones = pdata.get("opciones", [])
    opt_idx  = int(pdata.get("opcion_idx", 0))
    opt      = opciones[opt_idx] if opciones and opt_idx < len(opciones) else {}

    MARGIN_V2 = 0.25

    pre_cliente     = lead.get("nombre", "")
    pre_wa          = "".join(ch for ch in str(lead.get("whatsapp", "")) if ch.isdigit())
    pre_checkin     = lead.get("fecha_entrada", "")
    pre_checkout    = lead.get("fecha_salida",  "")
    pre_noches      = str(lead.get("noites", ""))
    pre_row_number  = str(lead.get("row_number", ""))
    pre_timestamp   = str(lead.get("timestamp", ""))

    pre_propiedad   = opt.get("nome",      "")
    pre_distancia   = opt.get("distancia", "")
    pre_personas    = str(opt.get("hospedes",   "2"))
    pre_cuartos     = str(opt.get("quartos",    "1"))
    pre_banos       = str(opt.get("banheiros",  "1"))
    preco_raw       = float(opt.get("preco_total", 0) or 0)
    limpeza_raw     = float(opt.get("taxa_limpeza", 0) or 0)
    pre_total       = str(int(round(preco_raw * (1 + MARGIN_V2)))) if preco_raw else ""
    pre_limpieza    = str(int(round(limpeza_raw)))                  if limpeza_raw else ""

    feats = []
    if opt.get("quartos"):   feats.append(str(opt["quartos"]) + " cuarto(s)")
    if opt.get("banheiros"): feats.append(str(opt["banheiros"]) + " ba\xf1o(s)")
    if opt.get("hospedes"):  feats.append("Hasta " + str(opt["hospedes"]) + " personas")
    if opt.get("amenidades"):
        feats += [x.strip() for x in str(opt["amenidades"]).split(",") if x.strip()]
    pre_caracteristicas = "\n".join(feats)

    foto_inputs = "".join(
        '<div class="foto-field"><span class="foto-num">' + str(i) + '</span>'
        '<input id="f' + str(i) + '" type="url" placeholder="https://..."></div>'
        for i in range(1, 11)
    )

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Panel de Revisión \xb7 Porto Flats</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}
.header{background:#87A286;padding:18px 16px;text-align:center}
.logo{color:#fff;font-size:18px;font-weight:300;letter-spacing:5px}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}
.card{background:#fff;border-radius:14px;margin:14px;padding:20px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
h2{font-size:13px;font-weight:700;color:#87A286;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
.field{margin-bottom:12px}
label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#87A286;margin-bottom:4px}
input,select,textarea{width:100%;padding:10px 12px;border:1.5px solid #CDC6C3;border-radius:9px;font-size:15px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit}
input:focus,select:focus,textarea:focus{border-color:#87A286}
textarea{resize:vertical;min-height:70px;line-height:1.5}
.row{display:flex;gap:10px}
.row .field{flex:1;min-width:0}
.calc-box{background:#EDE9E3;border-radius:10px;padding:14px;margin-bottom:12px}
.calc-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-size:14px}
.calc-row:last-child{margin-bottom:0}
.calc-label{color:#555}
.calc-val{font-weight:600;color:#3D3D3D}
.strike{text-decoration:line-through;color:#999;font-weight:400}
.calc-val.main{color:#87A286;font-size:16px}
.fotos-toggle{display:flex;align-items:center;gap:8px;cursor:pointer;color:#87A286;font-size:13px;font-weight:600;margin-bottom:0}
.fotos-toggle input[type=checkbox]{width:18px;height:18px;cursor:pointer;accent-color:#87A286}
#fotos-section{display:none;margin-top:12px}
#fotos-section.open{display:block}
.foto-field{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.foto-num{font-size:12px;color:#999;width:20px;flex-shrink:0;text-align:right}
.foto-field input{margin-bottom:0}
.btn-enviar{display:block;width:100%;padding:16px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:17px;font-weight:700;cursor:pointer;margin:8px 0;letter-spacing:.5px}
.btn-enviar:active{background:#6d8b6c}
.btn-enviar:disabled{background:#CDC6C3;cursor:not-allowed}
.msg-box{text-align:center;padding:12px;font-size:14px;border-radius:10px;margin-top:8px;display:none}
.msg-ok{background:#e8f5e9;color:#2e7d32}
.msg-err{background:#ffebee;color:#c62828}
.tip{font-size:11px;color:#999;margin-top:4px}
</style>
</head>
<body>
<div class="header">
  <div class="logo">PORTO FLATS</div>
  <div class="logo-sub">Panel de Revisión</div>
</div>

<!-- CLIENTE -->
<div class="card">
  <h2>\U0001f464 Cliente</h2>
  <div class="field">
    <label>Nombre completo</label>
    <input id="cliente" value="__CLIENTE__" placeholder="MARIA DE LOS ANGELES ROLANDI" required>
  </div>
  <div class="field">
    <label>WhatsApp (con código de país)</label>
    <input id="numero_wa" value="__WA__" placeholder="5491112345678" required>
    <p class="tip">Sin +, sin espacios. Ej: 5491112345678</p>
  </div>
</div>

<!-- PROPIEDAD -->
<div class="card">
  <h2>\U0001f3e1 Propiedad</h2>
  <div class="field">
    <label>Nombre de la propiedad</label>
    <input id="propiedad" value="__PROPIEDAD__" placeholder="Nixxus Premium" required>
  </div>
  <div class="row">
    <div class="field">
      <label>Distancia al mar</label>
      <input id="distancia" value="__DISTANCIA__" placeholder="40m del mar">
    </div>
    <div class="field">
      <label>Personas</label>
      <input id="personas" type="number" min="1" max="20" value="__PERSONAS__">
    </div>
  </div>
  <div class="row">
    <div class="field">
      <label>Cuartos</label>
      <input id="cuartos" type="number" min="0" max="10" value="__CUARTOS__">
    </div>
    <div class="field">
      <label>Ba\xf1os</label>
      <input id="banos" type="number" min="0" max="10" value="__BANOS__">
    </div>
  </div>
  <div class="field">
    <label>Caracter\xedsticas (una por l\xednea)</label>
    <textarea id="caracteristicas" rows="5" placeholder="Estudio&#10;1 ba\xf1o&#10;Aire acondicionado&#10;Wi-Fi&#10;Cocina equipada">__CARACTERISTICAS__</textarea>
  </div>
</div>

<!-- FECHAS -->
<div class="card">
  <h2>\U0001f4c5 Fechas de la reserva</h2>
  <div class="row">
    <div class="field">
      <label>Check-in</label>
      <input id="checkin" value="__CHECKIN__" placeholder="25/04/2025" required>
    </div>
    <div class="field">
      <label>Check-out</label>
      <input id="checkout" value="__CHECKOUT__" placeholder="05/05/2025" required>
    </div>
  </div>
  <div class="row">
    <div class="field">
      <label>Hora check-in</label>
      <input id="hora_checkin" value="14:00 hs" placeholder="14:00 hs">
    </div>
    <div class="field">
      <label>Hora check-out</label>
      <input id="hora_checkout" value="12:00 hs" placeholder="12:00 hs">
    </div>
  </div>
  <div class="field">
    <label>Noches</label>
    <input id="noches" type="number" min="1" value="__NOCHES__" oninput="recalc()" required>
  </div>
</div>

<!-- PRECIOS -->
<div class="card">
  <h2>\U0001f4b0 Precios</h2>
  <div class="row">
    <div class="field">
      <label>Total R$ (editable)</label>
      <input id="total_brl" type="number" min="0" step="10" value="__TOTAL__" oninput="recalc()" placeholder="1800" required>
    </div>
    <div class="field">
      <label>T.B. Limpieza R$</label>
      <input id="limpieza_brl" type="number" min="0" step="10" value="__LIMPIEZA__" oninput="recalc()" placeholder="200">
    </div>
  </div>
  <div class="calc-box">
    <div class="calc-row">
      <span class="calc-label">Diaria regular (tachada en PDF):</span>
      <span class="calc-val strike" id="diaria_reg">R$ —</span>
    </div>
    <div class="calc-row">
      <span class="calc-label">Diaria c/descuento:</span>
      <span class="calc-val" id="diaria_desc">R$ —</span>
    </div>
    <div class="calc-row" style="margin-top:8px;padding-top:8px;border-top:1px solid #CDC6C3">
      <span class="calc-label" style="font-weight:700">TOTAL:</span>
      <span class="calc-val main" id="total_disp">R$ —</span>
    </div>
  </div>
  <div class="field">
    <label>Cochera</label>
    <input id="cochera" value="No incluye" list="cochera-opts">
    <datalist id="cochera-opts">
      <option>No incluye</option><option>Incluye</option><option>Con costo adicional</option>
    </datalist>
  </div>
  <div class="field">
    <label>Traslado (dejar vac\xedo si no aplica)</label>
    <input id="traslado" placeholder="Incluido / R$ 80 ida y vuelta">
  </div>
  <div class="row">
    <div class="field">
      <label>Forma de pago</label>
      <input id="forma_pago" value="Transferencia bancaria" list="pago-opts">
      <datalist id="pago-opts">
        <option>Transferencia bancaria</option>
        <option>PIX</option>
        <option>Efectivo BRL</option>
        <option>Efectivo USD</option>
        <option>Consultar</option>
      </datalist>
    </div>
    <div class="field">
      <label>Anticipo %</label>
      <input id="anticipo_pct" type="number" min="0" max="100" value="50">
    </div>
  </div>
  <div class="field">
    <label>Observaciones (aparece en PDF y mensaje)</label>
    <textarea id="observaciones" placeholder="Incluye ropa de cama. Consultar disponibilidad para mascotas."></textarea>
  </div>
</div>

<!-- FOTOS -->
<div class="card">
  <label class="fotos-toggle">
    <input type="checkbox" id="fotos-chk" onchange="toggleFotos()">
    \U0001f4f8 Agregar fotos (hasta 10 URLs)
  </label>
  <div id="fotos-section">
    __FOTO_INPUTS__
    <p class="tip">Peg\xe1 URLs de Google Drive, Wix Media, Dropbox, etc.</p>
  </div>
</div>

<!-- ENVIAR -->
<div class="card">
  <button class="btn-enviar" id="btn-enviar" onclick="enviar()">
    ✅ Enviar al cliente
  </button>
  <div class="msg-box" id="msg-box"></div>
</div>

<!-- Campos ocultos de contexto -->
<input type="hidden" id="row_number"  value="__ROW_NUMBER__">
<input type="hidden" id="rowTimestamp" value="__TIMESTAMP__">

<script>
function recalc() {
  const total  = parseFloat(document.getElementById('total_brl').value)  || 0;
  const limp   = parseFloat(document.getElementById('limpieza_brl').value) || 0;
  const noches = parseInt(document.getElementById('noches').value)        || 1;
  const dDesc  = noches > 0 ? (total - limp) / noches : 0;
  const dReg   = dDesc * 1.10;
  const fmt = v => 'R$ ' + Math.round(v).toLocaleString('es-AR');
  document.getElementById('diaria_reg').textContent  = fmt(dReg);
  document.getElementById('diaria_desc').textContent = fmt(dDesc);
  document.getElementById('total_disp').textContent  = fmt(total);
}

function toggleFotos() {
  const sec = document.getElementById('fotos-section');
  sec.classList.toggle('open', document.getElementById('fotos-chk').checked);
}

async function enviar() {
  const btn = document.getElementById('btn-enviar');
  const msgBox = document.getElementById('msg-box');
  btn.disabled = true;
  btn.textContent = 'Enviando…';
  msgBox.style.display = 'none';

  const feats = document.getElementById('caracteristicas').value
    .split('\\n').map(s => s.trim()).filter(Boolean);

  const fotos = [];
  for (let i = 1; i <= 10; i++) {
    const el = document.getElementById('f' + i);
    const v = el ? el.value : '';
    if (v.trim()) fotos.push(v.trim());
  }

  const payload = {
    cliente:      document.getElementById('cliente').value.trim(),
    numero_wa:    document.getElementById('numero_wa').value.trim(),
    propiedad:    document.getElementById('propiedad').value.trim(),
    distancia:    document.getElementById('distancia').value.trim(),
    personas:     parseInt(document.getElementById('personas').value) || 2,
    cuartos:      parseInt(document.getElementById('cuartos').value)  || 1,
    banos:        parseInt(document.getElementById('banos').value)    || 1,
    checkin:      document.getElementById('checkin').value.trim(),
    checkout:     document.getElementById('checkout').value.trim(),
    hora_checkin: document.getElementById('hora_checkin').value.trim(),
    hora_checkout:document.getElementById('hora_checkout').value.trim(),
    noches:       parseInt(document.getElementById('noches').value)   || 1,
    caracteristicas: feats,
    total_brl:    parseFloat(document.getElementById('total_brl').value)   || 0,
    limpieza_brl: parseFloat(document.getElementById('limpieza_brl').value)|| 0,
    cochera:      document.getElementById('cochera').value.trim()    || 'No incluye',
    traslado:     document.getElementById('traslado').value.trim(),
    forma_pago:   document.getElementById('forma_pago').value.trim() || 'Transferencia bancaria',
    anticipo_pct: parseInt(document.getElementById('anticipo_pct').value) || 50,
    observaciones:document.getElementById('observaciones').value.trim(),
    fotos:        fotos,
    row_number:   document.getElementById('row_number').value,
    rowTimestamp: document.getElementById('rowTimestamp').value,
  };

  if (!payload.cliente || !payload.numero_wa || !payload.propiedad) {
    showMsg('Falta nombre, WhatsApp o propiedad.', false);
    btn.disabled = false; btn.textContent = '✅ Enviar al cliente'; return;
  }
  if (payload.total_brl <= 0) {
    showMsg('El total debe ser mayor a 0.', false);
    btn.disabled = false; btn.textContent = '✅ Enviar al cliente'; return;
  }

  try {
    const r = await fetch('/despachar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const j = await r.json();
    if (j.ok) {
      showMsg('✅ Enviado! Presupuesto N° ' + j.num_pres + ' — PDF + mensaje enviados al cliente.', true);
      btn.textContent = '✅ Enviado';
    } else {
      showMsg('Error: ' + (j.error || 'desconocido'), false);
      btn.disabled = false; btn.textContent = '✅ Enviar al cliente';
    }
  } catch(e) {
    showMsg('Error de red: ' + e.message, false);
    btn.disabled = false; btn.textContent = '✅ Enviar al cliente';
  }
}

function showMsg(text, ok) {
  const b = document.getElementById('msg-box');
  b.textContent = text;
  b.className = 'msg-box ' + (ok ? 'msg-ok' : 'msg-err');
  b.style.display = 'block';
}

recalc();
</script>
</body>
</html>"""
    html = (html
        .replace("__CLIENTE__", pre_cliente or "")
        .replace("__WA__", pre_wa or "")
        .replace("__PROPIEDAD__", pre_propiedad or "")
        .replace("__DISTANCIA__", pre_distancia or "")
        .replace("__PERSONAS__", pre_personas or "2")
        .replace("__CUARTOS__", pre_cuartos or "1")
        .replace("__BANOS__", pre_banos or "1")
        .replace("__CARACTERISTICAS__", pre_caracteristicas or "")
        .replace("__CHECKIN__", pre_checkin or "")
        .replace("__CHECKOUT__", pre_checkout or "")
        .replace("__NOCHES__", pre_noches or "1")
        .replace("__TOTAL__", pre_total or "")
        .replace("__LIMPIEZA__", pre_limpieza or "0")
        .replace("__FOTO_INPUTS__", foto_inputs)
        .replace("__ROW_NUMBER__", pre_row_number or "")
        .replace("__TIMESTAMP__", pre_timestamp or "")
    )
    return Response(html.encode('utf-8'), content_type="text/html; charset=utf-8")


# ── /recibo-form ──────────────────────────────────────────────────────────────
@app.route("/recibo-form", methods=["GET"])
def recibo_form():
    """Formulario web para generar recibo manualmente."""
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Generar Recibo \xb7 Porto Flats</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}
.header{background:#87A286;padding:18px 16px;text-align:center}
.logo{color:#fff;font-size:18px;font-weight:300;letter-spacing:5px}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}
.card{background:#fff;border-radius:14px;margin:16px;padding:24px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
h2{font-size:16px;font-weight:600;color:#87A286;margin-bottom:16px;text-transform:uppercase;letter-spacing:1px}
.field{margin-bottom:14px}
label{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#87A286;margin-bottom:5px}
input,select{width:100%;padding:10px 12px;border:1px solid #CDC6C3;border-radius:8px;font-size:15px;color:#3D3D3D;background:#fff;outline:none}
input:focus,select:focus{border-color:#87A286}
.row{display:flex;gap:12px}
.row .field{flex:1}
.btn{display:block;width:100%;padding:15px;background:#87A286;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:600;cursor:pointer;text-align:center;margin-top:8px}
.btn:active{background:#6d8b6c}
.msg{text-align:center;padding:10px;font-size:13px;color:#888;margin-top:8px}
</style>
</head>
<body>
<div class="header">
  <div class="logo">PORTO FLATS</div>
  <div class="logo-sub">Generador de Recibo</div>
</div>
<div class="card">
  <h2>Datos del pago</h2>
  <form id="f">
    <div class="row">
      <div class="field">
        <label>N° Recibo</label>
        <input name="numero" placeholder="REC-001" required>
      </div>
      <div class="field">
        <label>Fecha de pago</label>
        <input name="fecha_pago" placeholder="15/06/2026" required>
      </div>
    </div>
    <div class="field">
      <label>Cliente</label>
      <input name="cliente" placeholder="Nombre completo" required>
    </div>
    <div class="field">
      <label>Propiedad</label>
      <input name="propiedad" placeholder="Nixxus Premium" required>
    </div>
    <div class="row">
      <div class="field">
        <label>Check-in</label>
        <input name="checkin" placeholder="25/06/2026">
      </div>
      <div class="field">
        <label>Check-out</label>
        <input name="checkout" placeholder="01/07/2026">
      </div>
      <div class="field">
        <label>Noches</label>
        <input name="noches" type="number" placeholder="6">
      </div>
    </div>
    <div class="field">
      <label>Concepto</label>
      <select name="concepto">
        <option>Anticipo 50%</option>
        <option>Saldo 50%</option>
        <option>Pago total</option>
        <option>Se\xf1al reserva</option>
      </select>
    </div>
    <div class="row">
      <div class="field">
        <label>Monto</label>
        <input name="monto" placeholder="1.200" required>
      </div>
      <div class="field">
        <label>Moneda</label>
        <input name="moneda" list="monedas" placeholder="BRL">
        <datalist id="monedas">
          <option>BRL</option><option>ARS</option><option>USD</option>
        </datalist>
      </div>
    </div>
    <div class="field">
      <label>Forma de pago</label>
      <input name="forma_pago" list="formas_pago" placeholder="Transferencia bancaria">
      <datalist id="formas_pago">
        <option>Transferencia bancaria</option>
        <option>Efectivo BRL</option>
        <option>Efectivo ARS</option>
        <option>Efectivo USD</option>
        <option>PIX</option>
        <option>Tarjeta de credito</option>
      </datalist>
    </div>
    <button type="submit" class="btn" id="btn">Generar Recibo PDF</button>
    <div class="msg" id="msg"></div>
  </form>
</div>
<script>
document.getElementById('f').onsubmit = async function(e) {
  e.preventDefault();
  const btn = document.getElementById('btn');
  const msg = document.getElementById('msg');
  btn.textContent = 'Generando...';
  btn.disabled = true;
  msg.textContent = '';
  const fd = new FormData(this);
  const data = {};
  fd.forEach((v,k) => data[k] = v);
  try {
    const r = await fetch('/generar-recibo', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error);
    const bytes = Uint8Array.from(atob(j.pdf_base64), c => c.charCodeAt(0));
    const blob = new Blob([bytes], {type: 'application/pdf'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = j.filename; a.click();
    URL.revokeObjectURL(url);
    msg.textContent = 'Recibo generado: ' + j.filename;
    msg.style.color = '#87A286';
  } catch(err) {
    msg.textContent = 'Error: ' + err.message;
    msg.style.color = '#c00';
  }
  btn.textContent = 'Generar Recibo PDF';
  btn.disabled = false;
};
</script>
</body>
</html>"""
    return Response(html.encode('utf-8'), content_type="text/html; charset=utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# NUEVO FLUJO: DASHBOARD → EDITAR → PROPUESTA MULTI-OPCIÓN
# ══════════════════════════════════════════════════════════════════════════════
import uuid as _uuid
import time as _time
import pathlib as _pathlib

# ── Constantes Sheets / Uploads ───────────────────────────────────────────────
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1p-wDJOc6axaZMs103Gu1w_9SmZXZ6Vq0Z1eXgU8tFtc")
OPCIONES_SHEET  = os.environ.get("OPCIONES_SHEET",  "Opciones Pendientes")
HISTORIAL_SHEET = os.environ.get("HISTORIAL_SHEET", "Nuevas propuestas historial")
SERVICE_URL    = os.environ.get("SERVICE_URL", "https://pf-pdf-service.bg4ga1.easypanel.host")

_UPL_DIR = _pathlib.Path(os.environ.get("UPLOADS_DIR", "/app/uploads"))
try:
    _UPL_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _UPL_DIR = _pathlib.Path("/tmp/pf-uploads")
    _UPL_DIR.mkdir(parents=True, exist_ok=True)

# ── Google Sheets helpers ─────────────────────────────────────────────────────
def _sheets_client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive.readonly"]
        creds_b64 = os.environ.get("GOOGLE_CREDENTIALS_B64", "")
        if creds_b64:
            pad  = creds_b64 + "=" * (-len(creds_b64) % 4)
            info = json.loads(base64.b64decode(pad))
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            key_path = _pathlib.Path(__file__).parent / "marcelo-ai-n8n-24231b999d6d.json"
            creds = Credentials.from_service_account_file(str(key_path), scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"[Sheets] client error: {e}")
        return None


def _sheets_get_row(row_number):
    """Devuelve dict {header: value} para la fila indicada."""
    try:
        gc = _sheets_client()
        if not gc:
            return None
        ws      = gc.open_by_key(SPREADSHEET_ID).worksheet(OPCIONES_SHEET)
        headers = ws.row_values(1)
        values  = ws.row_values(int(row_number))
        return {h: (values[i] if i < len(values) else "") for i, h in enumerate(headers)}
    except Exception as e:
        print(f"[Sheets] get_row error: {e}")
        return None


def _sheets_update(row_number, col_name, value):
    """Actualiza una celda por nombre de columna."""
    try:
        gc = _sheets_client()
        if not gc:
            return False
        ws      = gc.open_by_key(SPREADSHEET_ID).worksheet(OPCIONES_SHEET)
        headers = ws.row_values(1)
        if col_name not in headers:
            return False
        col_idx = headers.index(col_name) + 1
        ws.update_cell(int(row_number), col_idx, value)
        return True
    except Exception as e:
        print(f"[Sheets] update error: {e}")
        return False


def _sheets_append_row(data_dict):
    """Agrega nueva fila al sheet usando los headers existentes. Retorna row number."""
    try:
        gc = _sheets_client()
        if not gc: return None
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(OPCIONES_SHEET)
        headers = ws.row_values(1)
        # Contar filas ANTES del append para calcular el número correcto
        rows_before = len(ws.get_all_values())
        row_vals = [str(data_dict.get(h, "")) for h in headers]
        ws.append_row(row_vals, value_input_option="RAW")
        return rows_before + 1  # la nueva fila está una después de las existentes
    except Exception as e:
        print(f"[Sheets] append_row error: {e}")
        return None


def _sheets_historial(nombre, whatsapp, email, ci, co, noites, link):
    """Guarda fila simple en pestaña historial. No bloquea si falla."""
    try:
        import datetime as _dt
        gc = _sheets_client()
        if not gc: return
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(HISTORIAL_SHEET)
        fecha = _dt.datetime.now().strftime("%d/%m/%Y %H:%M")
        ws.append_row([fecha, nombre, whatsapp, email, ci, co, noites, link],
                      value_input_option="RAW")
    except Exception as e:
        print(f"[Historial] error: {e}")


# ── /last-row — número de la última fila en Opciones Pendientes ──────────────
@app.route("/last-row")
def last_row():
    """Devuelve el row_number de la última fila en Opciones Pendientes."""
    try:
        gc = _sheets_client()
        if not gc:
            return jsonify({"error": "No Sheets client"}), 500
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(OPCIONES_SHEET)
        all_values = ws.get_all_values()
        # fila 1 = encabezado, última fila de datos = len(all_values)
        return jsonify({"row": len(all_values)})
    except Exception as e:
        print(f"[last-row] error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Fotos: upload / serve / limpieza ─────────────────────────────────────────
def _cleanup_old_photos(max_days=50):
    cutoff = _time.time() - max_days * 86400
    for f in _UPL_DIR.glob("*"):
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except Exception:
                pass


@app.route("/foto/<fname>")
def serve_foto(fname):
    from flask import send_from_directory
    if not all(c.isalnum() or c in "-_." for c in fname):
        return Response("", status=400)
    return send_from_directory(str(_UPL_DIR), fname)


@app.route("/upload-foto", methods=["POST"])
def upload_foto():
    """Recibe foto, la guarda en volumen y devuelve URL publica."""
    _cleanup_old_photos()
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file"}), 400
    ext = _pathlib.Path(f.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}:
        return jsonify({"error": "Tipo no permitido"}), 400
    if ext in {".heic", ".heif"}:
        ext = ".jpg"
    fname = str(_uuid.uuid4())[:8] + ext
    f.save(str(_UPL_DIR / fname))
    return jsonify({"ok": True, "url": SERVICE_URL + "/foto/" + fname})


# ── /debug-row ────────────────────────────────────────────────────────────────
@app.route("/debug-row")
def debug_row():
    row = request.args.get("row", "")
    if not row:
        return Response("Falta ?row=N", status=400, mimetype="text/plain")
    try:
        gc = _sheets_client()
        ws = gc.open_by_key(SPREADSHEET_ID).worksheet(OPCIONES_SHEET)
        headers = ws.row_values(1)
        values  = ws.row_values(int(row))
        rd = {h: (values[i] if i < len(values) else "") for i, h in enumerate(headers)}
        out = "HEADERS: " + repr(headers) + "\n\n"
        for k, v in rd.items():
            out += f"{k!r}: {v!r}\n"
        return Response(out, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return Response(f"Error: {e}", status=500, mimetype="text/plain")


# ── /dashboard ────────────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    """Panel interno: cards con opciones para seleccionar y enviar."""
    row_single = request.args.get("row",  "")
    rows_raw   = request.args.get("rows", "")
    if rows_raw:
        row_list = [r.strip() for r in rows_raw.split(",") if r.strip()]
    elif row_single:
        row_list = [row_single]
    else:
        return Response("Falta ?row=N o ?rows=N1,N2", status=400, mimetype="text/plain")
    rows_data = {}
    for r in row_list:
        rd = _sheets_get_row(r)
        if rd:
            rows_data[r] = rd
    if not rows_data:
        return Response("Error leyendo Sheets.", status=500, mimetype="text/plain")
    lead_rd = rows_data.get(row_list[0], {})
    for r in row_list:
        if rows_data.get(r, {}).get("nombre", ""):
            lead_rd = rows_data[r]
            break
    nombre = lead_rd.get("nombre", "Cliente")
    ci     = lead_rd.get("fecha_entrada", "")
    co     = lead_rd.get("fecha_salida",  "")
    noites = lead_rd.get("noites", "")
    all_opts = []  # [(r_str, local_idx, opt_dict)]
    for r in row_list:
        rd = rows_data.get(r, {})
        try:
            opciones = json.loads(rd.get("opciones_json", "[]") or "[]")
        except Exception:
            opciones = []
        for local_idx, opt in enumerate(opciones):
            all_opts.append((r, local_idx, opt))
    if not all_opts:
        return Response("No hay opciones en estas filas.", status=404, mimetype="text/plain")
    rows_param = ",".join(row_list)

    def _card(global_i, r_str, local_idx, opt):
        nome      = opt.get("nome", opt.get("Title", "Opcion " + str(global_i+1)))
        distancia = opt.get("distancia", "")
        quartos   = opt.get("quartos",   opt.get("cuartos",   ""))
        banheiros = opt.get("banheiros", opt.get("banos",     ""))
        hospedes  = opt.get("hospedes",  opt.get("personas",  ""))
        amenidades = opt.get("amenidades", "")
        url_anuncio = opt.get("url", "")
        # Precio
        try: pv  = float(str(opt.get("preco_total", opt.get("total_brl", 0))).replace(",",".") or 0)
        except: pv = 0
        try: taxa_v = float(str(opt.get("taxa_limpeza", 0)).replace(",",".") or 0)
        except: taxa_v = 0
        try: noche_v = float(str(opt.get("preco_noche","")).replace(",",".") or 0)
        except: noche_v = 0
        try: sug_v = float(str(opt.get("preco_sugerido","")).replace(",",".") or 0)
        except: sug_v = 0
        if sug_v == 0 and pv > 0: sug_v = round(pv * 1.25)
        margen_v = max(0, round(sug_v - pv)) if sug_v and pv else 0
        fotos = []
        for fi in range(1, 11):
            u = opt.get("foto"+str(fi)+"_up","") or opt.get("foto"+str(fi),"") or opt.get("f"+str(fi),"")
            if u: fotos.append(u)
        thumb = ('<img src="'+fotos[0]+'" class="card-thumb" onerror="this.style.display=\'none\'">'
                 if fotos else "")
        fp = []
        if quartos:   fp.append("\U0001f6cf " + str(quartos) + " cuarto" + ("s" if str(quartos)!="1" else ""))
        if banheiros: fp.append("\U0001f6bf " + str(banheiros) + " bano" + ("s" if str(banheiros)!="1" else ""))
        if hospedes:  fp.append("\U0001f465 hasta " + str(hospedes))
        feats_str = " &nbsp;&middot;&nbsp; ".join(fp)
        prows = ""
        if noche_v > 0:  prows += "<div class='prd-row'><span>Precio base/noche</span><span>R$ "+str(int(noche_v))+"</span></div>"
        if taxa_v  > 0:  prows += "<div class='prd-row'><span>Tarifa limpieza</span><span>R$ "+str(int(taxa_v))+"</span></div>"
        if pv      > 0:  prows += "<div class='prd-row'><span>Total estadia (costo)</span><span>R$ "+str(int(pv))+"</span></div>"
        if sug_v   > 0:  prows += "<div class='prd-row prd-sug'><span>Precio sugerido al cliente</span><span>R$ "+str(int(sug_v))+"</span></div>"
        if margen_v > 0: prows += "<div class='prd-row prd-mg'><span>Margen estimado</span><span>R$ "+str(int(margen_v))+"</span></div>"
        price_html = ("<div class='price-detail'>"+prows+"</div>" if prows else "")
        url_html = ("<a href='"+url_anuncio+"' target='_blank' class='url-anuncio'>\U0001f517 Ver anuncio original</a>" if url_anuncio else "")
        chk_value = r_str + ":" + str(local_idx)
        parts = [
            '<div class="opt-card" id="card-'+str(global_i)+'">',
            '<div class="card-top"><label class="chk-wrap">',
            '<input type="checkbox" name="sel" value="'+chk_value+'" onchange="updateBtn()">',
            '<span class="chk-txt">Incluir en propuesta</span></label>',
            '<span class="opt-num">#'+str(global_i+1)+'</span></div>',
            thumb,
            '<div class="card-info"><div class="opt-name">'+nome+'</div>',
            ('<div class="opt-loc">\U0001f4cd '+distancia+'</div>' if distancia else ""),
            ('<div class="opt-feats">'+feats_str+'</div>' if feats_str else ""),
            ('<div class="opt-amenids">'+amenidades+'</div>' if amenidades else ""),
            price_html,
            url_html,
            '</div>',
            '<a href="/editar?row='+r_str+'&amp;idx='+str(local_idx)+'" class="btn-editar">✏️ Editar propuesta</a>',
            '</div>'
        ]
        return "".join(parts)

    cards_html = "\n".join(_card(gi, r, li, o) for gi, (r, li, o) in enumerate(all_opts))
    rp = []
    if nombre: rp.append(nombre)
    if ci and co: rp.append(ci + " → " + co)
    if noites: rp.append(noites + " noches")
    resumen = " \xb7 ".join(rp)

    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh;padding-bottom:90px}
.header{background:#87A286;padding:18px 16px;text-align:center}
.logo{color:#fff;font-size:18px;font-weight:300;letter-spacing:5px}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}
.subhead{background:#fff;padding:11px 16px;font-size:13px;color:#555;border-bottom:1px solid #EDE9E3;display:flex;justify-content:space-between}
.section-title{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;padding:16px 16px 6px}
.opt-card{background:#fff;border-radius:14px;margin:14px;box-shadow:0 2px 14px rgba(0,0,0,.07);overflow:hidden}
.card-top{display:flex;justify-content:space-between;align-items:center;padding:13px 16px 10px}
.chk-wrap{display:flex;align-items:center;gap:8px;cursor:pointer}
.chk-wrap input[type=checkbox]{width:18px;height:18px;cursor:pointer;accent-color:#87A286}
.chk-txt{font-size:14px;color:#555}
.opt-num{font-size:12px;color:#CDC6C3;font-weight:700}
.card-thumb{width:100%;height:200px;object-fit:cover;display:block}
.card-info{padding:13px 16px}
.opt-name{font-size:18px;font-weight:500;margin-bottom:4px}
.opt-loc{font-size:13px;color:#87A286;margin-bottom:5px}
.opt-feats{font-size:13px;color:#555;margin-bottom:5px}
.opt-amenids{font-size:12px;color:#888;margin-bottom:5px;line-height:1.4}
.opt-price{font-size:16px;font-weight:700;color:#87A286;margin-top:6px}
.btn-editar{display:block;margin:0 16px 16px;padding:12px;background:#EDE9E3;color:#3D3D3D;border-radius:10px;text-align:center;text-decoration:none;font-size:14px;font-weight:500}
.footer-bar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #EDE9E3;padding:12px 16px;box-shadow:0 -4px 16px rgba(0,0,0,.08)}
.btn-enviar{display:block;width:100%;padding:14px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer}
.btn-enviar:disabled{background:#CDC6C3;cursor:not-allowed}
.msg-box{text-align:center;padding:9px;font-size:13px;border-radius:8px;margin-top:8px;display:none}
.msg-ok{background:#e8f5e9;color:#2e7d32}.msg-err{background:#ffebee;color:#c62828}
.price-detail{background:#EDE9E3;border-radius:10px;padding:2px 12px;margin:10px 0 4px}
.prd-row{display:flex;justify-content:space-between;padding:7px 0;font-size:12px;color:#555;border-bottom:1px solid rgba(0,0,0,.06)}
.prd-row:last-child{border-bottom:none}
.prd-sug{font-weight:700;color:#87A286;font-size:13px}
.prd-mg{color:#2e7d32}
.url-anuncio{display:block;margin:6px 0 4px;font-size:12px;color:#4a90d9;text-decoration:none;padding:0 2px}
"""
    subhead_html = ("<div class='subhead'><span>"+resumen+"</span><span style='color:#87A286;font-size:12px'>filas "+rows_param+"</span></div>"
                    if resumen else "")
    html = (
        "<!DOCTYPE html>\n<html lang='es'>\n<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>\n"
        "<title>Dashboard \xb7 Porto Flats</title>\n"
        "<style>"+css+"</style>\n</head>\n<body>\n"
        "<div class='header'><div class='logo'>PORTO FLATS</div>"
        "<div class='logo-sub'>Panel de Revisi\xf3n \xb7 Opciones</div></div>\n"
        + subhead_html + "\n"
        "<div class='section-title'>Selecion\xe1 las opciones para enviar al cliente</div>\n"
        + cards_html + "\n"
        "<div class='footer-bar'>"
        "<button class='btn-enviar' id='btn-enviar' disabled onclick='enviar()'>&#128228; Enviar propuesta al cliente</button>"
        "<div class='msg-box' id='msg-box'></div></div>\n"
        "<script>\n"
        "function updateBtn(){document.getElementById('btn-enviar').disabled=document.querySelectorAll('input[name=sel]:checked').length===0;}\n"
        "async function enviar(){\n"
        "  const btn=document.getElementById('btn-enviar');\n"
        "  const msgBox=document.getElementById('msg-box');\n"
        "  const sels=[...document.querySelectorAll('input[name=sel]:checked')];\n"
        "  const selections=sels.map(function(x){var p=x.value.split(':');return{row:p[0],idx:parseInt(p[1])};});\n"
        "  btn.disabled=true;btn.textContent='Enviando…';msgBox.style.display='none';\n"
        "  try{\n"
        "    const r=await fetch('/enviar-propuesta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:'"+rows_param+"',selections})});\n"
        "    const j=await r.json();\n"
        "    if(j.ok){msgBox.textContent='✅ Propuesta enviada! '+(j.url||'');msgBox.className='msg-box msg-ok';msgBox.style.display='block';btn.textContent='✅ Enviado';}\n"
        "    else{msgBox.textContent='Error: '+(j.error||'desconocido');msgBox.className='msg-box msg-err';msgBox.style.display='block';btn.disabled=false;btn.textContent='&#128228; Enviar propuesta al cliente';}\n"
        "  }catch(e){msgBox.textContent='Error de red: '+e.message;msgBox.className='msg-box msg-err';msgBox.style.display='block';btn.disabled=false;btn.textContent='&#128228; Enviar propuesta al cliente';}\n"
        "}\n</script>\n</body>\n</html>"
    )
    return Response(html.encode('utf-8'), content_type="text/html; charset=utf-8")


# ── /editar ───────────────────────────────────────────────────────────────────
@app.route("/editar", methods=["GET", "POST"])
def editar():
    """Formulario para editar una opcion y subir fotos."""
    row     = request.args.get("row", "") or request.form.get("row", "")
    idx_str = request.args.get("idx", "0") or request.form.get("idx", "0")
    try:
        idx = int(idx_str)
    except Exception:
        idx = 0

    if request.method == "POST":
        rd = _sheets_get_row(row)
        if not rd:
            return jsonify({"error": "No se pudo leer Sheets"}), 500
        try:
            opciones = json.loads(rd.get("opciones_json", "[]") or "[]")
        except Exception:
            opciones = []
        while len(opciones) <= idx:
            opciones.append({})
        opt = opciones[idx]
        for field in ["nome", "distancia", "quartos", "banheiros", "hospedes",
                      "amenidades", "preco_total", "taxa_limpeza", "mapa_url", "observaciones",
                      "preco_noche", "n_noites", "margen_pct", "preco_sugerido", "ganancia_r",
                      "forma_pago", "reserva_anticipo", "saldo_plazo", "cond_extra"]:
            val = request.form.get(field)
            if val is not None:
                opt[field] = val
        for fi in range(1, 11):
            url   = request.form.get("foto"+str(fi)+"_up", "")
            clear = request.form.get("foto"+str(fi)+"_clear", "")
            if url:
                opt["foto"+str(fi)+"_up"] = url
            elif clear:
                opt.pop("foto"+str(fi)+"_up", None)
        opciones[idx] = opt
        _sheets_update(row, "opciones_json", json.dumps(opciones, ensure_ascii=False))
        from flask import redirect
        return redirect("/dashboard?row=" + str(row))

    # GET
    rd = _sheets_get_row(row)
    if not rd:
        return Response("Error leyendo Sheets.", status=500, mimetype="text/plain")
    try:
        opciones = json.loads(rd.get("opciones_json", "[]") or "[]")
    except Exception:
        opciones = []
    noites_lead = str(rd.get("noites", "") or "")
    opt        = opciones[idx] if idx < len(opciones) else {}
    # Forzar str en todos los campos para evitar TypeError si algún valor es lista/int
    def _s(v, default=""):
        if v is None: return default
        if isinstance(v, list): return ", ".join(str(x) for x in v) if v else default
        return str(v)
    url_anuncio_ed = _s(opt.get("url", ""))
    nome       = _s(opt.get("nome",        opt.get("Title",        "")))
    distancia  = _s(opt.get("distancia",   ""))
    quartos    = _s(opt.get("quartos",     opt.get("cuartos",   "")))
    banheiros  = _s(opt.get("banheiros",   opt.get("banos",     "")))
    hospedes   = _s(opt.get("hospedes",    opt.get("personas",  "")))
    amenidades = _s(opt.get("amenidades",  ""))
    preco      = _s(opt.get("preco_total", opt.get("total_brl", "")))
    limpeza    = _s(opt.get("taxa_limpeza",opt.get("limpieza_brl","")))
    mapa_url   = _s(opt.get("mapa_url",    ""))
    observ     = _s(opt.get("observaciones",""))
    preco_noche   = _s(opt.get("preco_noche",   ""))
    n_noites_opt  = _s(opt.get("n_noites",      noites_lead))
    margen_pct    = _s(opt.get("margen_pct",    "25"))
    preco_sugerido = _s(opt.get("preco_sugerido",""))
    ganancia_r    = _s(opt.get("ganancia_r",    ""))
    forma_pago     = _s(opt.get("forma_pago",      ""))
    reserva_anticipo = _s(opt.get("reserva_anticipo","50"))
    saldo_plazo    = _s(opt.get("saldo_plazo",     "15 días"))
    cond_extra_ed  = _s(opt.get("cond_extra",      ""))
    # Compute missing values
    try:
        pv_ed = float(preco.replace(",",".") or 0)
        taxa_ed = float(limpeza.replace(",",".") or 0)
        nn_ed = int(float(n_noites_opt or noites_lead or 1))
    except Exception:
        pv_ed = taxa_ed = 0; nn_ed = 1
    try:
        if not preco_noche and pv_ed > 0 and nn_ed > 0:
            preco_noche = str(round((pv_ed - taxa_ed) / nn_ed))
        if not preco_sugerido and pv_ed > 0:
            preco_sugerido = str(round(pv_ed * (1 + int(float(margen_pct or 25))/100)))
        if not ganancia_r and pv_ed > 0 and preco_sugerido:
            ganancia_r = str(round(float(preco_sugerido) - pv_ed))
    except Exception:
        pass

    foto_rows = ""
    for fi in range(1, 11):
        existing = (opt.get("foto"+str(fi)+"_up","")
                    or opt.get("foto"+str(fi),"")
                    or opt.get("f"+str(fi),""))
        si = str(fi)
        if existing:
            short = existing[:55] + ("..." if len(existing) > 55 else "")
            foto_rows += (
                "<div class='foto-row' id='fr-"+si+"'>"
                "<img src='"+existing+"' class='foto-prev' onerror=\"this.style.display='none'\">"
                "<div class='foto-info'><span class='foto-url'>"+short+"</span>"
                "<button type='button' class='btn-rm' onclick='rmFoto("+si+")'>&#10005;</button></div>"
                "<input type='hidden' name='foto"+si+"_up' id='furl_"+si+"' value='"+existing+"'>"
                "<input type='hidden' name='foto"+si+"_clear' id='fclr_"+si+"' value=''></div>"
            )
        else:
            foto_rows += (
                "<div class='foto-row foto-empty' id='fr-"+si+"'>"
                "<span class='foto-num'>"+si+"</span>"
                "<label class='upload-lbl'>"
                "<input type='file' accept='image/*' onchange='uploadFoto(this,"+si+")' style='display:none'>"
                "&#128247; Foto "+si+"</label>"
                "<span class='fstatus' id='fst-"+si+"'></span>"
                "<input type='hidden' name='foto"+si+"_up' id='furl_"+si+"' value=''>"
                "<input type='hidden' name='foto"+si+"_clear' id='fclr_"+si+"' value=''></div>"
            )

    css_ed = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh;padding-bottom:20px}
.header{background:#87A286;padding:16px;text-align:center}
.logo{color:#fff;font-size:17px;font-weight:300;letter-spacing:4px}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:2px}
.card{background:#fff;border-radius:14px;margin:14px;padding:20px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
h2{font-size:12px;font-weight:700;color:#87A286;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
.field{margin-bottom:12px}
label.lbl{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#87A286;margin-bottom:4px}
input[type=text],input[type=number],input[type=url],textarea{width:100%;padding:10px 12px;border:1.5px solid #CDC6C3;border-radius:9px;font-size:15px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit}
input:focus,textarea:focus{border-color:#87A286}
textarea{resize:vertical;min-height:60px}
.row{display:flex;gap:10px}.row .field{flex:1;min-width:0}
.foto-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid #EDE9E3}
.foto-row:last-child{border-bottom:none}
.foto-prev{width:52px;height:52px;object-fit:cover;border-radius:8px;flex-shrink:0}
.foto-info{flex:1;min-width:0;display:flex;align-items:center;gap:8px}
.foto-url{font-size:11px;color:#888;flex:1;word-break:break-all}
.btn-rm{font-size:13px;color:#c62828;background:none;border:none;cursor:pointer;padding:2px 6px}
.foto-num{width:22px;text-align:center;font-size:12px;color:#CDC6C3;font-weight:700;flex-shrink:0}
.upload-lbl{flex:1;background:#EDE9E3;border-radius:8px;padding:9px 13px;font-size:14px;cursor:pointer;color:#555}
.fstatus{font-size:12px;color:#87A286;min-width:28px;text-align:right}
.btn-guardar{display:block;width:100%;padding:15px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;margin-top:4px}
.btn-volver{display:block;text-align:center;padding:11px;color:#87A286;text-decoration:none;font-size:14px;margin:4px 14px}
.tip{font-size:11px;color:#999;margin-top:4px}
.sep{height:1px;background:#EDE9E3;margin:12px 0}
.inp-hl{border-color:#87A286!important;background:#f0f7f0!important;font-weight:700}
.inp-green{color:#2e7d32!important;font-weight:600}
.pago-opts{display:flex;flex-wrap:wrap;gap:10px;margin-top:6px}
.pago-opt{display:flex;align-items:center;gap:6px;font-size:14px;color:#3D3D3D;cursor:pointer;background:#EDE9E3;padding:7px 12px;border-radius:20px}
.pago-opt input{width:16px;height:16px;accent-color:#87A286;cursor:pointer}
.link-anuncio{display:inline-flex;align-items:center;gap:6px;background:#EDE9E3;color:#4a90d9;text-decoration:none;font-size:13px;font-weight:600;padding:9px 14px;border-radius:10px;margin-bottom:14px;word-break:break-all}
.link-anuncio:hover{background:#d9e8d9}
"""
    html_ed = (
        "<!DOCTYPE html>\n<html lang='es'>\n<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>\n"
        "<title>Editar Opci\xf3n \xb7 Porto Flats</title>\n"
        "<style>"+css_ed+"</style>\n</head>\n<body>\n"
        "<div class='header'><div class='logo'>PORTO FLATS</div>"
        "<div class='logo-sub'>Editar Opci\xf3n #"+str(idx+1)+"</div></div>\n"
        "<a href='/dashboard?row="+str(row)+"' class='btn-volver'>← Volver al dashboard</a>\n"
        "<form method='POST' action='/editar?row="+str(row)+"&idx="+str(idx)+"'>\n"
        "<input type='hidden' name='row' value='"+str(row)+"'>\n"
        "<input type='hidden' name='idx' value='"+str(idx)+"'>\n"
        "<div class='card'><h2>\U0001f3e0 Propiedad</h2>\n"
        + (("<a href='"+url_anuncio_ed+"' target='_blank' class='link-anuncio'>\U0001f517 Ver anuncio original (buscar fotos)</a>\n") if url_anuncio_ed else "")
        + "<div class='field'><label class='lbl'>Nombre</label>"
        "<input type='text' name='nome' value='"+nome+"' placeholder='Nixxus Premium'></div>\n"
        "<div class='field'><label class='lbl'>Distancia / Ubicaci\xf3n</label>"
        "<input type='text' name='distancia' value='"+distancia+"' placeholder='40m del mar'></div>\n"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Cuartos</label><input type='number' name='quartos' value='"+str(quartos)+"' min='0' max='20'></div>"
        "<div class='field'><label class='lbl'>Ba\xf1os</label><input type='number' name='banheiros' value='"+str(banheiros)+"' min='0' max='20'></div>"
        "<div class='field'><label class='lbl'>Personas</label><input type='number' name='hospedes' value='"+str(hospedes)+"' min='1' max='30'></div>"
        "</div>\n"
        "<div class='field'><label class='lbl'>Amenidades (separadas por coma)</label>"
        "<textarea name='amenidades' rows='2' placeholder='Wi-Fi, A/C, Piscina'>"+amenidades+"</textarea></div>"
        "</div>\n"
        "<div class='card'><h2>\U0001f4b0 Precio</h2>\n"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Valor por d\xeda R$</label>"
        "<input type='number' id='preco_noche' name='preco_noche' value='"+str(preco_noche)+"' step='1' min='0' placeholder='600' oninput='calcP(\"base\")'></div>"
        "<div class='field'><label class='lbl'>N\xb0 Diarias</label>"
        "<input type='number' id='n_noites' name='n_noites' value='"+str(n_noites_opt or noites_lead or 1)+"' min='1' max='365' oninput='calcP(\"base\")'></div>"
        "</div>"
        "<div class='field'><label class='lbl'>Tasa de limpieza R$</label>"
        "<input type='number' id='taxa_limpeza' name='taxa_limpeza' value='"+str(limpeza)+"' step='1' min='0' placeholder='200' oninput='calcP(\"base\")'></div>"
        "<div class='sep'></div>"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Total sugerido R$ <small style='color:#aaa'>(editable)</small></label>"
        "<input type='number' id='preco_sugerido' name='preco_sugerido' value='"+str(preco_sugerido)+"' step='1' min='0' class='inp-hl' oninput='calcP(\"sug\")'></div>"
        "</div>"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Margen ganancia %</label>"
        "<input type='number' id='margen_pct' name='margen_pct' value='"+str(margen_pct)+"' step='1' min='0' max='500' oninput='calcP(\"pct\")'></div>"
        "<div class='field'><label class='lbl'>Ganancia R$</label>"
        "<input type='number' id='ganancia_r' name='ganancia_r' value='"+str(ganancia_r)+"' step='1' class='inp-green' oninput='calcP(\"gan\")'></div>"
        "</div>"
        "<input type='hidden' id='preco_total_h' name='preco_total' value='"+str(preco)+"'>"
        "</div>\n"
        "<div class='card'><h2>\U0001f4b3 Condiciones de pago</h2>\n"
        "<div class='field'><label class='lbl'>Forma de pago</label>"
        "<div class='pago-opts'>"
        "<label class='pago-opt'><input type='checkbox' name='fp_efectivo' value='1'"+(" checked" if "Efectivo" in forma_pago else "")+"> Efectivo</label>"
        "<label class='pago-opt'><input type='checkbox' name='fp_transf' value='1'"+(" checked" if "Transferencia" in forma_pago else "")+"> Transferencia</label>"
        "<label class='pago-opt'><input type='checkbox' name='fp_pix' value='1'"+(" checked" if "PIX" in forma_pago else " checked")+"> PIX</label>"
        "<label class='pago-opt'><input type='checkbox' name='fp_cripto' value='1'"+(" checked" if "Cripto" in forma_pago else "")+"> Cripto</label>"
        "<label class='pago-opt'><input type='checkbox' name='fp_tarjeta' value='1'"+(" checked" if "Tarjeta" in forma_pago else "")+"> Tarjeta cr\xe9d/d\xe9b</label>"
        "</div></div>"
        "<div class='field' style='margin-top:12px'><label class='lbl'>Reserva confirmada con anticipo del</label>"
        "<div style='display:flex;align-items:center;gap:8px;margin-top:6px'>"
        "<input type='number' name='reserva_anticipo' value='"+str(reserva_anticipo)+"' min='0' max='100' style='width:70px;padding:8px 10px;border:1.5px solid #CDC6C3;border-radius:9px;font-size:15px'>"
        "<span style='font-size:15px;color:#3D3D3D'>%</span></div></div>"
        "<div class='field' style='margin-top:12px'><label class='lbl'>Saldo debe abonarse antes del check-in</label>"
        "<input type='text' name='saldo_plazo' value='"+str(saldo_plazo)+"' placeholder='15 d\xedas' style='margin-top:6px'></div>"
        "<div class='field' style='margin-top:10px'><label class='lbl'>Nota libre en condiciones <small style='color:#aaa;text-transform:none'>(opcional)</small></label>"
        "<textarea name='cond_extra' rows='2' placeholder='Ej: Incluye ropa de cama. Mascotas no permitidas.'>"+cond_extra_ed+"</textarea></div>"
        "</div>\n"
        "<div class='card'><h2>\U0001f4cd Mapa</h2>\n"
        "<div class='field'><label class='lbl'>URL Google Maps</label>"
        "<input type='url' name='mapa_url' value='"+mapa_url+"' placeholder='https://maps.app.goo.gl/...'></div>"
        "</div>\n"
        "<div class='card'><h2>\U0001f4dd Observaciones</h2>\n"
        "<textarea name='observaciones' rows='3' placeholder='Incluye ropa de cama.'>"+observ+"</textarea>"
        "</div>\n"
        "<div class='card'><h2>\U0001f4f8 Fotos (se borran a los 7 d\xedas)</h2>\n"
        + foto_rows +
        "</div>\n"
        "<div class='card'><button type='submit' class='btn-guardar'>\U0001f4be Guardar y volver al dashboard</button></div>\n"
        "</form>\n"
        "<script>\n"
        "function calcP(c){\n"
        "  const nc=parseFloat(document.getElementById('preco_noche').value)||0;\n"
        "  const nn=parseInt(document.getElementById('n_noites').value)||1;\n"
        "  const lp=parseFloat(document.getElementById('taxa_limpeza').value)||0;\n"
        "  const base=nc*nn;\n"
        "  if(c==='pct'){\n"
        "    const pct=parseFloat(document.getElementById('margen_pct').value)||0;\n"
        "    const gan=Math.round(base*pct/100);\n"
        "    document.getElementById('ganancia_r').value=gan;\n"
        "    document.getElementById('preco_sugerido').value=Math.round(base+gan+lp);\n"
        "  }else if(c==='sug'){\n"
        "    const sug=parseFloat(document.getElementById('preco_sugerido').value)||0;\n"
        "    const gan=Math.round(sug-base-lp);\n"
        "    document.getElementById('ganancia_r').value=gan;\n"
        "    if(base>0)document.getElementById('margen_pct').value=Math.round(gan/base*100);\n"
        "  }else if(c==='gan'){\n"
        "    const gan=parseFloat(document.getElementById('ganancia_r').value)||0;\n"
        "    document.getElementById('preco_sugerido').value=Math.round(base+gan+lp);\n"
        "    if(base>0)document.getElementById('margen_pct').value=Math.round(gan/base*100);\n"
        "  }else{\n"
        "    const pct=parseFloat(document.getElementById('margen_pct').value)||25;\n"
        "    const gan=Math.round(base*pct/100);\n"
        "    document.getElementById('ganancia_r').value=gan;\n"
        "    document.getElementById('preco_sugerido').value=Math.round(base+gan+lp);\n"
        "  }\n"
        "  document.getElementById('preco_total_h').value=Math.round(base+lp);\n"
        "}\n"
        "// Build forma_pago before submit\n"
        "document.addEventListener('submit',function(e){\n"
        "  const fps=['fp_efectivo:Efectivo','fp_transf:Transferencia','fp_pix:PIX','fp_cripto:Cripto','fp_tarjeta:Tarjeta'];\n"
        "  const chosen=fps.filter(f=>document.querySelector('[name='+f.split(':')[0]+']:checked')).map(f=>f.split(':')[1]);\n"
        "  let hi=document.getElementById('fp_hidden');\n"
        "  if(!hi){hi=document.createElement('input');hi.type='hidden';hi.name='forma_pago';hi.id='fp_hidden';e.target.appendChild(hi);}\n"
        "  hi.value=chosen.join(' · ');\n"
        "});\n"
        "async function uploadFoto(input,fi){\n"
        "  const st=document.getElementById('fst-'+fi);\n"
        "  const ur=document.getElementById('furl_'+fi);\n"
        "  const file=input.files[0];if(!file)return;\n"
        "  st.textContent='…';\n"
        "  const fd=new FormData();fd.append('file',file);\n"
        "  try{\n"
        "    const r=await fetch('/upload-foto',{method:'POST',body:fd});\n"
        "    const j=await r.json();\n"
        "    if(j.ok){ur.value=j.url;st.textContent='✅';\n"
        "      const row=document.getElementById('fr-'+fi);\n"
        "      const img=document.createElement('img');img.src=j.url;img.className='foto-prev';img.style.marginRight='8px';\n"
        "      row.insertBefore(img,row.firstChild);\n"
        "    }else{st.textContent='❌';}\n"
        "  }catch(e){st.textContent='❌';}\n"
        "}\n"
        "function rmFoto(fi){\n"
        "  const ur=document.getElementById('furl_'+fi);\n"
        "  const cl=document.getElementById('fclr_'+fi);\n"
        "  if(ur)ur.value='';if(cl)cl.value='1';\n"
        "  document.getElementById('fr-'+fi).style.opacity='0.35';\n"
        "}\n"
        "</script>\n</body>\n</html>"
    )
    return Response(html_ed.encode('utf-8'), content_type="text/html; charset=utf-8")


# ── /enviar-propuesta ─────────────────────────────────────────────────────────
@app.route("/enviar-propuesta", methods=["POST"])
def enviar_propuesta():
    """Recibe {rows, selections:[{row,idx}]}, envia WhatsApp al cliente con link /propuesta."""
    import base64 as _b64, zlib as _zlib
    data       = request.get_json(force=True) or {}
    rows_raw   = str(data.get("rows",   ""))
    row_single = str(data.get("row",    ""))
    selections = data.get("selections", [])  # [{row, idx}]
    selected   = data.get("selected",   [])  # legacy [int]
    if rows_raw:
        row_list = [r.strip() for r in rows_raw.split(",") if r.strip()]
    elif row_single:
        row_list = [row_single]
    else:
        return jsonify({"error": "Faltan row o rows"}), 400
    rows_data = {}
    for r in row_list:
        rd = _sheets_get_row(r)
        if rd:
            rows_data[r] = rd
    if not rows_data:
        return jsonify({"error": "Error leyendo Sheets"}), 500
    lead_rd = rows_data.get(row_list[0], {})
    for r in row_list:
        if rows_data.get(r, {}).get("nombre", ""):
            lead_rd = rows_data[r]
            break
    nombre   = lead_rd.get("nombre",       "")
    whatsapp = lead_rd.get("whatsapp",      "")
    ci       = lead_rd.get("fecha_entrada", "")
    co       = lead_rd.get("fecha_salida",  "")
    noites   = lead_rd.get("noites",        "")
    opts_selected = []
    if selections:
        for sel in selections:
            r_str = str(sel.get("row", ""))
            idx   = int(sel.get("idx", 0))
            if r_str in rows_data:
                try:
                    opciones = json.loads(rows_data[r_str].get("opciones_json", "[]") or "[]")
                    if idx < len(opciones):
                        opts_selected.append(opciones[idx])
                except Exception:
                    pass
    elif selected and row_single in rows_data:
        try:
            opciones = json.loads(rows_data[row_single].get("opciones_json", "[]") or "[]")
            for idx in selected:
                if int(idx) < len(opciones):
                    opts_selected.append(opciones[int(idx)])
        except Exception:
            pass
    if not opts_selected:
        return jsonify({"error": "No se encontraron opciones seleccionadas"}), 400
    propuesta_data = {"nombre": nombre, "ci": ci, "co": co, "noites": noites, "opciones": opts_selected}
    raw_json   = json.dumps(propuesta_data, ensure_ascii=False).encode("utf-8")
    compressed = _zlib.compress(raw_json)
    data_b64   = _b64.urlsafe_b64encode(compressed).decode("ascii").rstrip("=")
    propuesta_url = SERVICE_URL + "/propuesta?data=" + data_b64
    short_url     = _tinyurl(propuesta_url)
    nombre_corto  = nombre.split()[0].title() if nombre else "cliente"
    eW = "\U0001f44b"; ePF = "\U0001f3d6"; eCal = "\U0001f4c5"
    eMoon = "\U0001f319"; eLink = "\U0001f517"; DIV = "━" * 16
    msg  = eW + " Hola " + nombre_corto + "!\n\n"
    msg += "Somos *Porto Flats* " + ePF + "\n"
    msg += "Preparamos tu propuesta personalizada para Porto de Galinhas!\n\n"
    if ci:     msg += eCal + " Check-in:  *" + ci + "*\n"
    if co:     msg += eCal + " Check-out: *" + co + "*\n"
    if noites: msg += eMoon + " *" + str(noites) + " noches*\n"
    msg += "\n" + DIV + "\n\n"
    msg += eLink + " Ver opciones con fotos y detalles:\n" + short_url + "\n\n"
    msg += "Entr\xe1 al link, eleg\xed la opci\xf3n que m\xe1s te guste y confirm\xe1nos.\n"
    msg += "Cualquier consulta, estamos a disposici\xf3n!\n*Porto Flats* " + ePF
    _evo_send_text(whatsapp, msg)
    for r in row_list:
        _sheets_update(r, "estado", "Enviado al cliente")
    return jsonify({"ok": True, "url": short_url, "numero": whatsapp})


def _propuesta_pol(opts):
    """Genera la sección de política de cancelación dinámica + modal T&C."""
    first_opt = opts[0][1] if opts else {}
    anticipo  = str(first_opt.get("reserva_anticipo", "50"))
    saldo_pl  = str(first_opt.get("saldo_plazo",      "15 días"))
    forma_pago = str(first_opt.get("forma_pago",      "Transferencia · PIX"))
    if not forma_pago.strip():
        forma_pago = "Transferencia · PIX"
    pol_items = (
        "<div class='pol-item'>✅ Reserva confirmada con <strong>anticipo del "+anticipo+"%</strong></div>"
        "<div class='pol-item'>\U0001f4c5 Saldo debe abonarse <strong>"+saldo_pl+"</strong> antes del check-in</div>"
        "<div class='pol-item'>\U0001f4b3 Forma de pago: "+forma_pago+"</div>"
    )
    modal = (
        "<div id='modal-tc' onclick='if(event.target===this)closeTc()' style='"
        "display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:999;align-items:center;justify-content:center;padding:16px'>"
        "<div style='background:#fff;border-radius:16px;overflow:hidden;max-width:480px;width:100%;height:80vh;display:flex;flex-direction:column'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid #eee;flex-shrink:0'>"
        "<span style='font-weight:700;font-size:16px'>T\xe9rminos y condiciones</span>"
        "<button onclick='closeTc()' style='background:none;border:none;font-size:22px;cursor:pointer;color:#888'>✕</button></div>"
        "<iframe src='https://portoflatsbr.com/#terminoscondiciones' style='flex:1;border:none;width:100%' loading='lazy'></iframe>"
        "<div style='padding:10px;text-align:center;border-top:1px solid #eee;flex-shrink:0'>"
        "<a href='https://portoflatsbr.com/#terminoscondiciones' target='_blank' "
        "style='font-size:12px;color:#87A286;text-decoration:none'>\U0001f517 Abrir en nueva pesta\xf1a</a>"
        "</div></div></div>"
    )
    return modal


# ── /propuesta ────────────────────────────────────────────────────────────────
@app.route("/propuesta")
def propuesta():
    """Landing multi-opcion para el cliente. ?data=BASE64&sel=0 o ?row=N&sel=0,1"""
    import base64 as _b64, zlib as _zlib
    from urllib.parse import quote as urlquote
    sel_raw  = request.args.get("sel", "")
    data_b64 = request.args.get("data", "")
    row      = ""   # siempre definido para la JS al final

    if data_b64:
        # ── Modo manual: datos comprimidos + codificados en el URL, sin Sheets ──
        try:
            padding   = (4 - len(data_b64) % 4) % 4
            raw_bytes = _b64.urlsafe_b64decode(data_b64 + "=" * padding)
            try:
                json_str = _zlib.decompress(raw_bytes).decode("utf-8")
            except Exception:
                json_str = raw_bytes.decode("utf-8")  # fallback sin compresión
            payload  = json.loads(json_str)
            nombre   = payload.get("nombre", "")
            ci       = payload.get("ci", "")
            co       = payload.get("co", "")
            noites   = payload.get("noites", "")
            all_opts = payload.get("opciones", [])
        except Exception as e:
            return Response("Error cargando propuesta: " + str(e), status=400, mimetype="text/plain")
    else:
        # ── Modo Typebot: leer desde Sheets por row ──
        row = request.args.get("row", "")
        if not row:
            return Response("Falta ?data= o ?row=", status=400, mimetype="text/plain")
        rd = _sheets_get_row(row)
        if not rd:
            return Response("No se pudo cargar la propuesta.", status=500, mimetype="text/plain")
        nombre  = rd.get("nombre", "")
        ci      = rd.get("fecha_entrada", "")
        co      = rd.get("fecha_salida",  "")
        noites  = rd.get("noites", "")
        try:
            all_opts = json.loads(rd.get("opciones_json", "[]") or "[]")
        except Exception:
            all_opts = []

    if sel_raw:
        try:
            idxs = [int(x.strip()) for x in sel_raw.split(",") if x.strip().isdigit()]
            opts = [(i, all_opts[i]) for i in idxs if i < len(all_opts)]
        except Exception:
            opts = list(enumerate(all_opts))
    else:
        opts = list(enumerate(all_opts))
    if not opts:
        return Response("No hay opciones para mostrar.", status=404, mimetype="text/plain")

    def _section(disp_num, orig_idx, opt):
        nome      = opt.get("nome",      opt.get("Title", "Opcion " + str(disp_num)))
        distancia = opt.get("distancia", "")
        quartos   = str(opt.get("quartos",   opt.get("cuartos",   "1")))
        banheiros = str(opt.get("banheiros", opt.get("banos",     "1")))
        hospedes  = str(opt.get("hospedes",  opt.get("personas",  "2")))
        amenidades = opt.get("amenidades", "")
        mapa_url   = opt.get("mapa_url",   "")
        observ     = opt.get("observaciones","")
        preco_raw      = opt.get("preco_total",      opt.get("total_brl", 0))
        limpeza_raw    = opt.get("taxa_limpeza",     opt.get("limpieza_brl", 0))
        noche_raw      = opt.get("preco_noche",      "")
        descuento_raw  = opt.get("preco_descuento",  "")
        try:
            preco_v     = float(str(preco_raw).replace(",",".") or 0)
            limpeza_v   = float(str(limpeza_raw).replace(",",".") or 0)
            noche_v     = float(str(noche_raw).replace(",",".") or 0)   if noche_raw    else 0
            descuento_v = float(str(descuento_raw).replace(",",".") or 0) if descuento_raw else 0
        except Exception:
            preco_v = limpeza_v = noche_v = descuento_v = 0
        fotos = []
        for fi in range(1, 11):
            u = opt.get("foto"+str(fi)+"_up","") or opt.get("foto"+str(fi),"") or opt.get("f"+str(fi),"")
            if u: fotos.append(u)
        carousel = ""
        if fotos:
            fotos_js = json.dumps(fotos, ensure_ascii=False)
            imgs = "".join(
                "<img src='"+f+"' class='car-img' loading='lazy' "
                "onerror=\"this.style.display='none'\" "
                "onclick='openLb("+fotos_js+","+str(i)+")'>"
                for i, f in enumerate(fotos)
            )
            carousel = "<div class='carousel'>"+imgs+"</div>"
        cs = "s" if quartos != "1" else ""
        bs = "s" if banheiros != "1" else ""
        feats = ("<div class='feats'>"
                 "<div class='feat'><span class='fi'>\U0001f6cf</span>"+quartos+" cuarto"+cs+"</div>"
                 "<div class='feat'><span class='fi'>\U0001f6bf</span>"+banheiros+" ba\xf1o"+bs+"</div>"
                 "<div class='feat'><span class='fi'>\U0001f465</span>Hasta "+hospedes+" personas</div>"
                 "</div>")
        amenids_html = ""
        if amenidades:
            alist = [x.strip() for x in amenidades.split(",") if x.strip()]
            if alist:
                tags = "".join("<span class='tag'>"+x+"</span>" for x in alist)
                amenids_html = "<div class='card'><div class='sec-title'>Incluye</div><div class='tags'>"+tags+"</div></div>"
        price_html = ""
        if preco_v > 0:
            rows_p = ""
            has_descuento = descuento_v > 0 and noche_v > 0 and descuento_v < noche_v
            if noites:
                try:
                    n = int(noites)
                    if has_descuento:
                        # Precio regular tachado
                        rows_p += ("<div class='pr-row'>"
                                   "<span>\U0001f319 Precio regular/noche</span>"
                                   "<span style='text-decoration:line-through;color:#bbb'>R$ "+str(int(noche_v))+"</span>"
                                   "</div>")
                        # Precio con descuento resaltado
                        pct_desc = round((noche_v - descuento_v) / noche_v * 100)
                        rows_p += ("<div class='pr-row pr-discount'>"
                                   "<span>\U0001f4b8 Precio especial/noche "
                                   "<span class='disc-tag'>-"+str(pct_desc)+"%</span></span>"
                                   "<span style='font-weight:700;color:#87A286'>R$ "+str(int(descuento_v))+"</span>"
                                   "</div>")
                    elif noche_v > 0:
                        rows_p += "<div class='pr-row'><span>\U0001f319 Precio por noche</span><span>R$ "+str(int(noche_v))+"</span></div>"
                    rows_p += "<div class='pr-row'><span>\U0001f4c5 Noches</span><span>\xd7 "+str(n)+"</span></div>"
                except Exception:
                    pass
            if limpeza_v > 0:
                rows_p += "<div class='pr-row'><span>\U0001f9f9 Tasa de limpieza</span><span>R$ "+str(int(limpeza_v))+"</span></div>"
            for _svc in opt.get('servicios_extras', []):
                try:
                    _m = float(str(_svc.get('monto', 0)))
                    if _m > 0:
                        rows_p += "<div class='pr-row'><span>\u2795 "+str(_svc.get('nombre','Servicio'))+"</span><span>R$ "+str(int(_m))+"</span></div>"
                except Exception:
                    pass
            rows_p += "<div class='pr-row pr-total'><span>\U0001f4b0 Total</span><span>R$ "+str(int(preco_v))+"</span></div>"
            price_html = "<div class='card'><div class='sec-title'>Precio estimado</div><div class='pr-table'>"+rows_p+"</div></div>"
        map_html = ""
        import re as _re
        loc_q        = urlquote(nome + ", Porto de Galinhas, Pernambuco, Brasil")
        gmaps_link   = mapa_url if mapa_url else "https://www.google.com/maps/search/?api=1&query=" + loc_q
        link_txt     = ("<a href='"+gmaps_link+"' style='display:block;text-align:center;"
                        "font-size:13px;color:#4a90d9;margin-top:10px;text-decoration:underline' "
                        "target='_blank'>\U0001f5fa Ver en Google Maps</a>")

        def _osm_embed(url):
            """Intenta extraer coords de URL Google Maps y armar embed OSM. Retorna src o None."""
            resolved = url
            # Seguir redirect para links cortos
            if "maps.app.goo.gl" in url or "goo.gl/maps" in url:
                try:
                    _r2 = http.head(url, allow_redirects=True, timeout=8, headers={'User-Agent': 'Mozilla/5.0'})
                    resolved = _r2.url
                except Exception:
                    pass
            # Extraer lat/lng del patrón /@lat,lng o ?q=lat,lng
            m = _re.search(r'/@(-?\d+\.\d+),(-?\d+\.\d+)', resolved)
            if not m:
                m = _re.search(r'[?&](?:q|ll)=(-?\d+\.\d+),(-?\d+\.\d+)', resolved)
            if not m:
                return None
            lat, lng = float(m.group(1)), float(m.group(2))
            d = 0.004
            bbox = f"{lng-d},{lat-d},{lng+d},{lat+d}"
            return f"https://www.openstreetmap.org/export/embed.html?bbox={bbox}&layer=mapnik&marker={lat},{lng}"

        osm_src = _osm_embed(mapa_url) if mapa_url else None
        if not osm_src and mapa_url and "google.com/maps/embed" in mapa_url:
            osm_src = mapa_url  # URL de embed oficial, usarla directo

        if osm_src:
            map_html = ("<div class='card np'><div class='sec-title'>\U0001f4cd Ubicaci\xf3n</div>"
                        "<div class='maps-wrap'><iframe src='"+osm_src+"' width='100%' height='220' frameborder='0' "
                        "style='border:0;border-radius:12px;display:block' allowfullscreen loading='lazy'></iframe></div>"
                        + link_txt + "</div>")
        else:
            map_html = ("<div class='card np'><div class='sec-title'>\U0001f4cd Ubicaci\xf3n</div>"
                        + link_txt + "</div>")
        obs_lines = observ.replace("\r\n", "\n").replace("\r", "\n").split("\n") if observ else []
        obs_html = ("<div class='card'>"
                    + "".join("<p style='font-size:13px;color:#555;line-height:1.6;margin-bottom:4px'>&#8505;&#65039; "+ln.strip()+"</p>" for ln in obs_lines if ln.strip())
                    + "</div>") if obs_lines else ""
        # Condiciones de reserva (por opción)
        anticipo_opt  = str(opt.get("reserva_anticipo", "50"))
        saldo_opt     = str(opt.get("saldo_plazo",      "15 d\xedas"))
        forma_opt     = str(opt.get("forma_pago",       ""))
        cond_extra    = str(opt.get("cond_extra",       ""))
        cond_items = (
            "<div class='pol-item'>✅ Reserva confirmada con <strong>anticipo del "+anticipo_opt+"%</strong></div>"
            "<div class='pol-item'>\U0001f4c5 Saldo debe abonarse <strong>"+saldo_opt+"</strong> antes del check-in</div>"
            + ("<div class='pol-item'>\U0001f4b3 Forma de pago: "+forma_opt+"</div>" if forma_opt else "")
            + ("<div class='pol-item'>\U0001f4dd "+cond_extra+"</div>" if cond_extra else "")
        )
        cond_html = "<div class='card'><div class='sec-title'>Condiciones de reserva</div>"+cond_items+"</div>"
        elegir_html = ("<div class='card np'><div class='sec-title'>\xbfTe gusta esta opci\xf3n?</div>"
                       "<label class='elegir-label' for='chk-"+str(orig_idx)+"'>"
                       "<input type='checkbox' class='opt-chk' id='chk-"+str(orig_idx)+"' name='opts' "
                       "value='"+str(orig_idx)+"' onchange='updateConfirm()'>"
                       "<span class='elegir-txt'>\U0001f446 Elegir opci\xf3n "+str(disp_num)+": "+nome+"</span></label></div>")
        return ("<div class='opt-section'>"
                "<div class='opt-header'><div class='opt-badge'>Opci\xf3n "+str(disp_num)+"</div>"
                "<div class='opt-title'>"+nome+"</div>"
                + ("<div class='opt-dist'>\U0001f4cd "+distancia+"</div>" if distancia else "")
                + "</div>"
                + carousel
                + "<div class='card'><div class='sec-title'>Caracter\xedsticas</div>"+feats+"</div>"
                + amenids_html + price_html + map_html + obs_html + cond_html + elegir_html
                + "</div><div class='divider'></div>")

    sections_html = "".join(_section(dn, oi, o) for dn, (oi, o) in enumerate(opts, 1))

    info_parts = []
    if ci and co: info_parts.append("\U0001f4c5 "+ci+" → "+co)
    if noites:    info_parts.append("\U0001f319 "+noites+" noches")
    if nombre:    info_parts.append("\U0001f464 "+nombre)
    info_bar = " &nbsp;\xb7&nbsp; ".join(info_parts) if info_parts else ""
    nombre_corto = nombre.split()[0].title() if nombre else ""
    greeting = ("<div class='greeting'>Preparado especialmente para <strong>"+nombre_corto+"</strong> \U0001f30a</div>"
                if nombre_corto else "")

    css_p = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh;padding-bottom:110px}
.header{background:#87A286;padding:20px 16px;text-align:center}
.logo{color:#fff;font-size:20px;font-weight:300;letter-spacing:5px;text-transform:uppercase}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}
.greeting{background:#E7D7C9;text-align:center;padding:10px 16px;font-size:14px;color:#5a4a3a}
.info-bar{background:#fff;padding:10px 16px;font-size:12px;color:#888;text-align:center;border-bottom:1px solid #EDE9E3}
.opt-header{background:#87A286;padding:16px;color:#fff}
.opt-badge{font-size:11px;letter-spacing:2px;text-transform:uppercase;opacity:.8;margin-bottom:4px}
.opt-title{font-size:20px;font-weight:400;margin-bottom:2px}
.opt-dist{font-size:13px;opacity:.8}
.divider{height:6px;background:#EDE9E3;border-top:2px solid #CDC6C3;border-bottom:2px solid #CDC6C3}
.card{background:#fff;border-radius:14px;margin:14px;padding:22px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
.sec-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;margin-bottom:12px}
.feats{display:flex;gap:16px;flex-wrap:wrap}
.feat{display:flex;align-items:center;gap:6px;font-size:14px;color:#555}
.fi{font-size:18px}
.tags{display:flex;flex-wrap:wrap;gap:8px}
.tag{background:#EDE9E3;border-radius:20px;padding:5px 13px;font-size:13px;color:#555}
.pr-table{background:#EDE9E3;border-radius:10px;padding:4px 14px}
.pr-row{display:flex;justify-content:space-between;padding:10px 0;font-size:14px;border-bottom:1px solid rgba(0,0,0,.06)}
.pr-row:last-child{border-bottom:none}
.pr-total{font-weight:700;font-size:16px;color:#87A286}
.carousel{display:flex;overflow-x:auto;gap:10px;padding:14px 14px 4px;scrollbar-width:none;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch}
.carousel::-webkit-scrollbar{display:none}
.car-img{height:240px;min-width:320px;max-width:360px;object-fit:cover;border-radius:12px;flex-shrink:0;scroll-snap-align:start;background:#CDC6C3;cursor:zoom-in}
#lb{display:none;position:fixed;inset:0;background:rgba(0,0,0,.93);z-index:9999;align-items:center;justify-content:center;flex-direction:column;padding:16px}
#lb.open{display:flex}
#lb-img{max-width:95vw;max-height:82vh;object-fit:contain;border-radius:10px}
#lb-close{position:absolute;top:14px;right:18px;color:#fff;font-size:34px;cursor:pointer;line-height:1;font-weight:300}
#lb-prev,#lb-next{position:absolute;top:50%;transform:translateY(-50%);color:#fff;font-size:48px;cursor:pointer;padding:10px 14px;user-select:none;opacity:.8}
#lb-prev{left:0}#lb-next{right:0}
#lb-count{color:#aaa;font-size:13px;margin-top:10px}
.maps-wrap{border-radius:12px;overflow:hidden;margin-bottom:12px}
.btn{display:block;text-align:center;padding:14px;border-radius:10px;font-size:15px;text-decoration:none;margin-top:10px;font-weight:500;cursor:pointer;border:none;width:100%;font-family:inherit}
.btn-maps{background:#4a90d9;color:#fff}
.elegir-label{display:flex;align-items:center;gap:12px;cursor:pointer;padding:4px 0}
.elegir-label input[type=checkbox]{width:22px;height:22px;cursor:pointer;accent-color:#87A286;flex-shrink:0}
.elegir-txt{font-size:15px;font-weight:500}
.cta-todas{text-align:center;padding:18px 16px 8px}
.cta-todas label{display:flex;align-items:center;justify-content:center;gap:10px;cursor:pointer;font-size:15px;font-weight:500;color:#3D3D3D}
.cta-todas input[type=checkbox]{width:20px;height:20px;accent-color:#87A286}
.pol-card{background:#fff;border-radius:14px;margin:14px;padding:20px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
.pol-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;margin-bottom:10px}
.pol-item{font-size:13px;padding:6px 0;color:#555;border-bottom:1px solid #EDE9E3}
.pol-item:last-child{border-bottom:none}
.footer-bar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1px solid #EDE9E3;padding:12px 16px;box-shadow:0 -4px 16px rgba(0,0,0,.08)}
.btn-confirm{display:block;width:100%;padding:14px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer}
.btn-confirm:disabled{background:#CDC6C3;cursor:not-allowed}
.accept-txt{font-size:11px;color:#aaa;text-align:center;margin-top:6px;line-height:1.5;padding:0 8px}
.msg-box{text-align:center;padding:8px;font-size:13px;border-radius:8px;margin-top:6px;display:none}
.msg-ok{background:#e8f5e9;color:#2e7d32}.msg-err{background:#ffebee;color:#c62828}
.footer{text-align:center;padding:20px 16px;color:#aaa;font-size:12px;line-height:1.7}
@media print{.np{display:none!important}}
"""
    html_p = (
        "<!DOCTYPE html>\n<html lang='es'>\n<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>\n"
        "<title>Tu Propuesta \xb7 Porto Flats</title>\n"
        "<style>"+css_p+"</style>\n</head>\n<body>\n"
        "<div class='header'><div class='logo'>Porto Flats</div>"
        "<div class='logo-sub'>Porto de Galinhas \xb7 Pernambuco \xb7 Brasil</div></div>\n"
        + greeting
        + ("<div class='info-bar'>"+info_bar+"</div>\n" if info_bar else "")
        + sections_html
        + "<div class='cta-todas np'><label>"
          "<input type='checkbox' id='chk-todas' onchange='toggleTodas()'>"
          "<span>✨ \xa1Me interesan todas las opciones!</span></label></div>\n"
        + _propuesta_pol(opts)
        + "<div class='footer-bar np'>"
          "<button class='btn-confirm' id='btn-confirm' disabled onclick='confirmar()'>"
          "✅ Confirmar selecci\xf3n</button>"
          "<div class='accept-txt'>Al confirmar acept\xe1s nuestros <a onclick='openTc()' style='color:#87A286;text-decoration:underline;cursor:pointer'>t\xe9rminos y condiciones</a>.</div>"
          "<div class='msg-box' id='msg-box'></div></div>\n"
        + "<div style='margin:0 14px 6px;'>"
          "<button onclick='window.print()' class='btn' style='background:#EDE9E3;color:#3D3D3D;font-size:15px;font-weight:600'>"
          "\U0001f4e5 Descargar PDF</button></div>\n"
        + "<div class='footer np'>Porto Flats \xb7 Alquileres temporarios<br>"
          "Porto de Galinhas \xb7 Pernambuco \xb7 Brasil<br>"
          "<small>Esta propuesta fue preparada especialmente para vos</small></div>\n"
        + "<div id='lb' onclick=\"if(event.target===this)lbClose()\">"
          "<span id='lb-close' onclick='lbClose()'>&#x2715;</span>"
          "<span id='lb-prev' onclick='lbPrev()'>&#8249;</span>"
          "<img id='lb-img' src=''>"
          "<span id='lb-count'></span>"
          "<span id='lb-next' onclick='lbNext()'>&#8250;</span>"
          "</div>\n"
        + "<script>\nconst ROW='"+str(row)+"';\nconst DATA_B64='"+data_b64+"';\n"
          "let _lbP=[],_lbI=0;\n"
          "function openLb(pics,idx){_lbP=pics;_lbI=idx;_lbShow();}\n"
          "function _lbShow(){const lb=document.getElementById('lb');lb.classList.add('open');"
          "document.getElementById('lb-img').src=_lbP[_lbI];"
          "document.getElementById('lb-count').textContent=(_lbI+1)+' / '+_lbP.length;}\n"
          "function lbClose(){document.getElementById('lb').classList.remove('open');}\n"
          "function lbPrev(){_lbI=(_lbI-1+_lbP.length)%_lbP.length;_lbShow();}\n"
          "function lbNext(){_lbI=(_lbI+1)%_lbP.length;_lbShow();}\n"
          "document.addEventListener('keydown',function(e){"
          "if(!document.getElementById('lb').classList.contains('open'))return;"
          "if(e.key==='ArrowLeft')lbPrev();"
          "if(e.key==='ArrowRight')lbNext();"
          "if(e.key==='Escape')lbClose();});\n"
          "function openTc(){document.getElementById('modal-tc').style.display='flex';}\n"
          "function closeTc(){document.getElementById('modal-tc').style.display='none';}\n"
          "function updateConfirm(){const any=document.querySelectorAll('.opt-chk:checked,#chk-todas:checked').length>0;document.getElementById('btn-confirm').disabled=!any;}\n"
          "function toggleTodas(){const v=document.getElementById('chk-todas').checked;document.querySelectorAll('.opt-chk').forEach(c=>{c.checked=v;});updateConfirm();}\n"
          "async function confirmar(){\n"
          "  const btn=document.getElementById('btn-confirm');\n"
          "  const msgBox=document.getElementById('msg-box');\n"
          "  const todas=document.getElementById('chk-todas').checked;\n"
          "  const opts=todas?[...document.querySelectorAll('.opt-chk')].map(c=>parseInt(c.value)):[...document.querySelectorAll('.opt-chk:checked')].map(c=>parseInt(c.value));\n"
          "  if(!opts.length)return;\n"
          "  btn.disabled=true;btn.textContent='Confirmando…';msgBox.style.display='none';\n"
          "  const body=ROW?{row:ROW,opciones_elegidas:opts}:{data_b64:DATA_B64,opciones_elegidas:opts};\n"
          "  try{\n"
          "    const r=await fetch('/confirmar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});\n"
          "    const j=await r.json();\n"
          "    if(j.ok){btn.textContent='✅ \xa1Confirmado!';msgBox.textContent='\xa1Muchas gracias! Te contactamos a la brevedad.';msgBox.className='msg-box msg-ok';msgBox.style.display='block';}\n"
          "    else{msgBox.textContent='Error: '+(j.error||'intent\xe1 de nuevo');msgBox.className='msg-box msg-err';msgBox.style.display='block';btn.disabled=false;btn.textContent='✅ Confirmar selecci\xf3n';}\n"
          "  }catch(e){msgBox.textContent='Error de red. Contact\xe1nos por WhatsApp.';msgBox.className='msg-box msg-err';msgBox.style.display='block';btn.disabled=false;btn.textContent='✅ Confirmar selecci\xf3n';}\n"
          "}\n</script>\n</body>\n</html>"
    )
    return Response(html_p.encode('utf-8'), content_type="text/html; charset=utf-8")


# ── /confirmar ────────────────────────────────────────────────────────────────
@app.route("/confirmar", methods=["POST"])
def confirmar():
    """Cliente confirma opciones -> WhatsApp a Marcelo."""
    data          = request.get_json(force=True) or {}
    row           = str(data.get("row", ""))
    db64          = str(data.get("data_b64", ""))
    opciones_eleg = data.get("opciones_elegidas", [])
    if not row and not db64:
        return jsonify({"error": "Falta row"}), 400
    if db64:
        # Modo manual: decodificar payload base64
        import base64 as _b64c, zlib as _zlc
        try:
            padding  = (4 - len(db64) % 4) % 4
            raw      = _b64c.urlsafe_b64decode(db64 + "=" * padding)
            payload  = json.loads(_zlc.decompress(raw).decode("utf-8"))
            nombre   = payload.get("nombre", "")
            all_opts = payload.get("opciones", [])
        except Exception as e:
            return jsonify({"error": "Error decodificando: "+str(e)}), 400
    else:
        rd = _sheets_get_row(row)
        nombre = rd.get("nombre", "") if rd else ""
        try:
            all_opts = json.loads(rd.get("opciones_json", "[]") or "[]") if rd else []
        except Exception:
            all_opts = []
    nombres_eleg = []
    for i in opciones_eleg:
        try:
            opt = all_opts[int(i)]
            nombres_eleg.append(opt.get("nome", opt.get("Title", "opcion " + str(int(i)+1))))
        except Exception:
            nombres_eleg.append("opcion " + str(int(i)+1))
    nombre_corto = nombre.split()[0].title() if nombre else "el cliente"
    if len(nombres_eleg) == 1:
        opts_txt = "*" + nombres_eleg[0] + "*"
    elif len(nombres_eleg) == 2:
        opts_txt = "*" + nombres_eleg[0] + "* y *" + nombres_eleg[1] + "*"
    else:
        opts_txt = ", ".join("*"+n+"*" for n in nombres_eleg[:-1]) + " y *" + nombres_eleg[-1] + "*"
    msg = ("✅ *" + nombre_corto + "* eligi\xf3 su opci\xf3n de Porto de Galinhas!\n\n"
           "Le gust\xf3: " + opts_txt + "\n\n"
           "Fila Sheets #" + row + " \xb7 Contact\xe1lo para confirmar la reserva.")
    _evo_send_text(MARCELO_NUM, msg)
    _sheets_update(row, "estado", "Cliente confirmo")
    return jsonify({"ok": True})


# ── /nuevo-presupuesto ────────────────────────────────────────────────────────
@app.route("/nuevo-presupuesto", methods=["GET", "POST"])
def nuevo_presupuesto():
    """Panel manual: Marcelo crea y envía una propuesta sin Typebot."""
    from flask import redirect
    import datetime

    if request.method == "POST":
        # ── Datos del cliente ──
        nombre    = request.form.get("nombre", "").strip()
        apellido  = request.form.get("apellido", "").strip()
        nombre_completo = (nombre + " " + apellido).strip()
        ci        = request.form.get("fecha_entrada", "")
        co        = request.form.get("fecha_salida",  "")
        personas  = request.form.get("personas", "")
        notas_int = request.form.get("notas_internas", "")
        pais      = request.form.get("pais", "BR")
        wa_num    = request.form.get("whatsapp_num", "").strip().replace(" ","").replace("-","").replace("+","")
        email_cl  = request.form.get("email_cliente", "").strip()
        # Calcular noches (type=date devuelve YYYY-MM-DD)
        noites = ""
        try:
            from datetime import datetime as dt
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    d1 = dt.strptime(ci, fmt); d2 = dt.strptime(co, fmt)
                    noites = str((d2 - d1).days); break
                except Exception: pass
        except Exception: pass
        # Formatear WhatsApp destino
        prefijos = {"AR": "549", "BR": "55", "US": "1"}
        prefix = prefijos.get(pais, "55")
        wa_dest = prefix + wa_num

        # ── Opciones ──
        _post_cfg2   = _load_settings()
        _custom_svcs = _post_cfg2.get('custom_services', [])

        def _build_opt(sfx):
            """Construye dict de opción desde campos del form con sufijo _0 o _1."""
            def fv(k): return request.form.get(k + sfx, "")
            opt = {}
            for f in ["nome","distancia","quartos","banheiros","hospedes","amenidades",
                      "preco_total","taxa_limpeza","mapa_url","observaciones","cond_extra",
                      "preco_noche","preco_descuento","n_noites","margen_pct","ganancia_r",
                      "reserva_anticipo","saldo_plazo","url"]:
                v = fv(f)
                if v: opt[f] = v
            # forma_pago
            fps = ["fp_efectivo","fp_transf","fp_pix","fp_cripto","fp_tarjeta"]
            labels = {"fp_efectivo":"Efectivo","fp_transf":"Transferencia",
                      "fp_pix":"PIX","fp_cripto":"Cripto","fp_tarjeta":"Tarjeta"}
            chosen = [labels[k] for k in fps if request.form.get(k+sfx)]
            if chosen: opt["forma_pago"] = " \xb7 ".join(chosen)
            # servicios extras
            if _custom_svcs:
                _svcs_list = []
                for _si, _sname in enumerate(_custom_svcs):
                    _monto_str = fv('svc_' + str(_si) + '_monto')
                    try: _monto = float(_monto_str or 0)
                    except: _monto = 0
                    if _monto > 0:
                        _svcs_list.append({'nombre': _sname, 'monto': _monto})
                if _svcs_list:
                    opt['servicios_extras'] = _svcs_list
            # fotos
            for fi in range(1, 11):
                u = request.form.get("foto"+str(fi)+"_up"+sfx, "")
                if u: opt["foto"+str(fi)+"_up"] = u
            return opt

        opt0 = _build_opt("_0")
        opt1 = _build_opt("_1")
        opciones = [opt0]
        # Solo incluir opción 2 si el usuario completó campos significativos
        # n_noites no cuenta porque calcNoches() lo auto-llena aunque la opción no esté activa
        if opt1.get("nome") or opt1.get("preco_noche") or opt1.get("preco_total"):
            opciones.append(opt1)

        # ── Generar URL con datos comprimidos + codificados (sin depender de Sheets) ──
        import base64 as _b64, zlib as _zlib
        payload_dict = {
            "nombre":  nombre_completo,
            "ci":      ci,
            "co":      co,
            "noites":  noites,
            "opciones": opciones,
        }
        json_bytes = json.dumps(payload_dict, ensure_ascii=False, separators=(",",":")).encode("utf-8")
        data_b64 = _b64.urlsafe_b64encode(_zlib.compress(json_bytes, 9)).decode().rstrip("=")
        sel_idxs = ",".join(str(i) for i in range(len(opciones)))
        prop_url  = SERVICE_URL + "/propuesta?data=" + data_b64 + "&sel=" + sel_idxs

        # ── Capturar form_data completo para historial editable ──
        form_dict = {
            "nombre": nombre, "apellido": request.form.get("apellido", ""),
            "fecha_entrada": ci, "fecha_salida": co,
            "personas": request.form.get("personas", ""),
            "notas_internas": request.form.get("notas_internas", ""),
            "pais": pais, "whatsapp_num": wa_num, "email_cliente": email_cl,
        }
        for _sfx in ["_0", "_1"]:
            for _f in ["nome","distancia","quartos","banheiros","hospedes","amenidades",
                       "preco_total","taxa_limpeza","mapa_url","observaciones","cond_extra",
                       "preco_noche","preco_descuento","n_noites","margen_pct","ganancia_r",
                       "reserva_anticipo","saldo_plazo","url","forma_pago"]:
                v = request.form.get(_f + _sfx, "")
                if v: form_dict[_f + _sfx] = v
            for _fi in range(1, 11):
                v = request.form.get("foto" + str(_fi) + "_up" + _sfx, "")
                if v: form_dict["foto" + str(_fi) + "_up" + _sfx] = v
            for _k in ["fp_efectivo","fp_transf","fp_pix","fp_cripto","fp_tarjeta"]:
                v = request.form.get(_k + _sfx, "")
                if v: form_dict[_k + _sfx] = "on"
        # guardar servicios extras en form_dict
        for _si2 in range(len(_custom_svcs)):
            for _sfx3 in ['_0', '_1']:
                _fk = 'svc_' + str(_si2) + '_monto' + _sfx3
                _v = request.form.get(_fk, '')
                if _v: form_dict[_fk] = _v

        # ── Guardar en store local (45 días) → URL limpia con dominio propio ──
        short_url = prop_url
        try:
            prop_id   = _store_proposal(nombre_completo, wa_dest, email_cl,
                                        ci, co, noites, prop_url, form_dict)
            short_url = PROPUESTAS_DOMAIN + "/v/" + prop_id
        except Exception as _e:
            print(f"[store_proposal error] {_e}")
            try:
                short_url = _own_shorten(prop_url)   # fallback al shortlink anterior
            except Exception:
                short_url = prop_url

        # ── Guardar en historial Google Sheets (best-effort, no bloquea) ──
        _sheets_historial(nombre_completo, wa_dest, email_cl, ci, co, noites, short_url)

        # ── Enviar WhatsApp al cliente ──
        nombre_corto = nombre.split()[0].title() if nombre else "!"
        _post_cfg  = _load_settings()
        _msg_intro = _post_cfg.get("msg_intro", "Te preparamos una propuesta de alojamiento en Porto de Galinhas.")
        msg = ("\U0001f30a Hola *" + nombre_corto + "*!\n\n"
               + _msg_intro + "\n\n"
               "\U0001f4cc Ver opciones y confirmar:\n" + short_url)
        wa_ok = _evo_send_text(wa_dest, msg)

        # ── Pantalla de confirmación ──
        html_ok = (
            "<!DOCTYPE html><html lang='es'><head>"
            "<meta charset='UTF-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>"
            "<title>Propuesta enviada \xb7 Porto Flats</title>"
            "<style>"
            "*{box-sizing:border-box;margin:0;padding:0}"
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "background:#EDE9E3;color:#3D3D3D;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px}"
            ".card{background:#fff;border-radius:18px;padding:32px 24px;max-width:420px;width:100%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.08)}"
            ".icon{font-size:52px;margin-bottom:16px}"
            "h1{font-size:20px;font-weight:700;color:#87A286;margin-bottom:8px}"
            "p{font-size:14px;color:#666;line-height:1.6;margin-bottom:6px}"
            ".wa-num{font-size:13px;font-weight:600;color:#3D3D3D;background:#EDE9E3;padding:6px 14px;border-radius:20px;display:inline-block;margin:10px 0 18px}"
            ".btn{display:block;padding:14px;border-radius:12px;font-size:15px;font-weight:700;text-decoration:none;margin-bottom:10px;cursor:pointer;border:none;width:100%}"
            ".btn-green{background:#87A286;color:#fff}"
            ".btn-outline{background:#EDE9E3;color:#3D3D3D}"
            "</style></head><body>"
            "<div class='card'>"
            "<div class='icon'>" + ("\U0001f4ac✅" if wa_ok else "⚠️") + "</div>"
            "<h1>" + ("Propuesta enviada!" if wa_ok else "Propuesta guardada (revisar WA)") + "</h1>"
            "<p>Cliente: <strong>" + nombre_completo + "</strong></p>"
            + ("<p>WhatsApp:</p><div class='wa-num'>+" + wa_dest + "</div>" if wa_ok else
               "<p style='color:#c0392b'>El WhatsApp no se pudo enviar. Reenv\xealo manualmente.</p>")
            + "<a href='" + short_url + "' class='btn btn-green' target='_blank'>\U0001f440 Ver propuesta del cliente</a>"
            "<p style='font-size:12px;color:#aaa;margin-top:4px;word-break:break-all'>"+short_url+"</p>"
            "<a href='/nuevo-presupuesto' class='btn btn-outline'>➕ Nueva propuesta</a>"
            "<a href='/nuevo-presupuesto?open=historial' class='btn btn-outline' style='margin-top:6px'>📋 Ver historial</a>"
            "</div></body></html>"
        )
        return Response(html_ok.encode("utf-8"), content_type="text/html; charset=utf-8")

    # ── GET ── Renderizar formulario ──────────────────────────────────────────
    # Soporte para ?edit=ID — pre-cargar datos de una propuesta anterior
    edit_id        = request.args.get("edit", "")
    edit_data_json = "null"
    if edit_id:
        try:
            _edit_store = _load_proposals()
            _edit_entry = _edit_store.get(edit_id)
            if _edit_entry and _edit_entry.get("form_data"):
                edit_data_json = json.dumps(_edit_entry["form_data"], ensure_ascii=False)
        except Exception:
            pass

    cfg      = _load_settings()
    n_fotos  = cfg.get("n_fotos", 8)
    cfg_json = json.dumps(cfg, ensure_ascii=False)

    def _opt_fields(sfx, label, n_fotos=8, custom_services=None):
        """Genera el bloque HTML de campos para una opción."""
        def fi(name, lbl, typ="text", ph="", extra=""):
            return ("<div class='field'><label class='lbl'>"+lbl+"</label>"
                    "<input type='"+typ+"' name='"+name+sfx+"' placeholder='"+ph+"' "+extra+"></div>")
        def frow(*items):
            return "<div class='row'>"+"".join(items)+"</div>"
        fps_html = (
            "<div class='field'><label class='lbl'>Forma de pago</label>"
            "<div class='pago-opts'>"
            + "".join("<label class='pago-opt'><input type='checkbox' name='"+k+sfx+"'>"+v+"</label>"
                      for k,v in [("fp_efectivo","Efectivo"),("fp_transf","Transferencia"),
                                  ("fp_pix","PIX"),("fp_cripto","Cripto"),("fp_tarjeta","Tarjeta")])
            + "</div></div>"
        )
        fotos_html = "".join(
            "<div class='foto-row foto-empty' id='fr"+sfx+"-"+str(fi2)+"'>"
            "<span class='foto-num'>"+str(fi2)+"</span>"
            "<label class='upload-lbl'>"
            "<input type='file' accept='image/*' onchange='uploadFoto"+sfx.replace("-","")+
            "(this,"+str(fi2)+")' style='display:none'>&#128247; Foto "+str(fi2)+"</label>"
            "<span class='fstatus' id='fst"+sfx+"-"+str(fi2)+"'></span>"
            "<input type='hidden' name='foto"+str(fi2)+"_up"+sfx+"' id='furl"+sfx+"-"+str(fi2)+"' value=''></div>"
            for fi2 in range(1, n_fotos + 1)
        )
        return (
            "<div class='card'><h2>"+label+"</h2>"
            + fi("url", "\U0001f517 Link del anuncio (para buscar fotos)", ph="https://alugueportodegalinhas...")
            + frow(fi("nome","Nombre propiedad","text","Capri Residence 202"),
                   fi("distancia","Distancia al mar","text","80m"))
            + frow(fi("quartos","Cuartos","number","1","min='0' max='20'"),
                   fi("banheiros","Ba\xf1os","number","1","min='0' max='20'"),
                   fi("hospedes","Personas","number","2","min='1' max='30'"))
            + fi("amenidades","Amenidades (separadas por coma)","text","Wi-Fi, A/C, Piscina")
            + "<div class='sep'></div>"
            # ── Precios ──
            + "<div class='row'>"
              "<div class='field' style='flex:1'><label class='lbl'>Diaria regular R$</label>"
              "<input type='number' name='preco_noche"+sfx+"' id='pnoche"+sfx+"' placeholder='500' min='0' "
              "oninput='calcNP(\""+sfx+"\")'></div>"
              "<div class='field' style='flex:1'><label class='lbl'>Diaria con descuento R$ <small style='color:#aaa'>(opcional)</small></label>"
              "<div style='display:flex;gap:6px;align-items:center'>"
              "<input type='number' name='preco_descuento"+sfx+"' id='pdesc"+sfx+"' placeholder='—' min='0' "
              "style='flex:1' oninput='calcNP(\""+sfx+"\")'>"
              "<div class='desc-badge' id='pbadge"+sfx+"'>—</div>"
              "</div></div>"
              "</div>"
            + "<div class='row'>"
              "<div class='field' style='flex:1'><label class='lbl'>N\xba noches</label>"
              "<input type='number' name='n_noites"+sfx+"' id='nnoites"+sfx+"' placeholder='—' min='1' max='365' "
              "oninput='calcNP(\""+sfx+"\")'></div>"
              "<div class='field' style='flex:1'><label class='lbl'>Tasa de limpieza R$</label>"
              "<input type='number' name='taxa_limpeza"+sfx+"' id='tlimpeza"+sfx+"' placeholder='0' min='0' "
              "oninput='calcNP(\""+sfx+"\")'></div>"
              "</div>"
            + "<div class='calc-display-row'>"
              "<span class='calc-display-lbl'>Subtotal</span>"
              "<span class='calc-display-val' id='psubtotal"+sfx+"'>—</span>"
              "</div>"
            + "<div class='row'>"
              "<div class='field' style='flex:1'><label class='lbl'>Margen ganancia %</label>"
              "<input type='number' name='margen_pct"+sfx+"' id='mpct"+sfx+"' placeholder='0' min='0' max='100' step='1' "
              "oninput='calcNP(\""+sfx+"\")'></div>"
              "<div class='field' style='flex:1'><label class='lbl'>Ganancia R$</label>"
              "<div class='calc-display-row' style='height:42px;margin:0'>"
              "<span class='calc-display-val inp-green' id='ganancia"+sfx+"'>—</span>"
              "</div></div>"
              "</div>"
            + "<div class='calc-display-row calc-total'>"
              "<span class='calc-display-lbl'>TOTAL</span>"
              "<span class='calc-display-val' id='ptotal-disp"+sfx+"'>—</span>"
              "</div>"
            + "<input type='hidden' id='ptotal"+sfx+"' name='preco_total"+sfx+"' value=''>"
            + "<input type='hidden' name='ganancia_r"+sfx+"' id='ganancia-hid"+sfx+"' value=''>"
            + "<div class='sep'></div>"
            + frow(fi("reserva_anticipo","Anticipo %","number","50","min='0' max='100'"),
                   fi("saldo_plazo","Saldo antes del check-in","text","15 d\xedas"))
            + fi("cond_extra","Nota libre en condiciones","text","Incluye ropa de cama...")
            + fps_html
            + "<div class='sep'></div>"
            + ("".join(
                "<div class='field'><label class='lbl' style='color:#888;font-weight:500'>\u2795 "
                + str(_sn) + " R$</label>"
                "<input type='number' name='svc_" + str(_si) + "_monto" + sfx + "' "
                "placeholder='0' min='0'></div>"
                for _si, _sn in enumerate(custom_services or [])
               ) if custom_services else "")
            + fi("mapa_url","\U0001f4cd Link Google Maps (cualquier link, desde celular o web)","url","https://maps.app.goo.gl/...")
            + fi("observaciones","Observaciones para el cliente","text","Check-in 14hs...")
            + "<div class='sep'></div>"
            + "<div class='field'><label class='lbl'>Fotos (hasta 5)</label>"
            + fotos_html + "</div>"
            + "</div>"
        )

    css_np = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh;padding-bottom:30px}
.header{background:#87A286;padding:16px;text-align:center}
.logo{color:#fff;font-size:17px;font-weight:300;letter-spacing:4px}
.logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:2px}
.card{background:#fff;border-radius:14px;margin:12px;padding:18px;box-shadow:0 2px 14px rgba(0,0,0,.07)}
h2{font-size:12px;font-weight:700;color:#87A286;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
.field{margin-bottom:11px}
label.lbl{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#87A286;margin-bottom:4px}
input[type=text],input[type=number],input[type=url],input[type=date],textarea,select{width:100%;padding:10px 12px;border:1.5px solid #CDC6C3;border-radius:9px;font-size:15px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit}
input:focus,textarea:focus,select:focus{border-color:#87A286}
.row{display:flex;gap:8px}.row .field{flex:1;min-width:0}
.sep{height:1px;background:#EDE9E3;margin:10px 0}
.inp-hl{border-color:#87A286!important;background:#f0f7f0!important;font-weight:700}
.inp-green{color:#2e7d32!important;font-weight:600}
.pago-opts{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.pago-opt{display:flex;align-items:center;gap:5px;font-size:13px;background:#EDE9E3;padding:6px 10px;border-radius:20px;cursor:pointer}
.pago-opt input{width:15px;height:15px;accent-color:#87A286}
.noches-badge{background:#e8f5e9;border-radius:9px;padding:10px 12px;font-size:15px;font-weight:700;color:#2e7d32;border:1.5px solid #c8e6c9}
.desc-badge{background:#FFF3E0;border:1.5px solid #FFA726;border-radius:9px;padding:10px 10px;font-size:13px;font-weight:700;color:#E65100;min-width:52px;text-align:center;white-space:nowrap;flex-shrink:0}
.desc-badge.empty{background:#F5F2EE;border-color:#ddd;color:#ccc}
.calc-display-row{display:flex;justify-content:space-between;align-items:center;background:#F5F2EE;border-radius:9px;padding:10px 14px;margin-bottom:11px}
.calc-display-lbl{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#999}
.calc-display-val{font-size:15px;font-weight:700;color:#3D3D3D}
.calc-display-row.calc-total{background:#87A286}
.calc-display-row.calc-total .calc-display-lbl{color:rgba(255,255,255,.8)}
.calc-display-row.calc-total .calc-display-val{color:#fff;font-size:17px}
.wa-row{display:flex;gap:8px;align-items:flex-end}
.wa-sel{width:100px;flex-shrink:0}
.btn-add-opt{display:block;margin:0 12px 12px;border:2px dashed #CDC6C3;border-radius:12px;padding:14px;text-align:center;color:#87A286;font-size:14px;font-weight:600;cursor:pointer;background:#fff}
.btn-enviar{display:block;margin:0 12px;padding:16px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;width:calc(100%-24px);text-align:center}
.foto-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #EDE9E3}
.foto-row:last-child{border-bottom:none}
.foto-num{width:18px;text-align:center;font-size:12px;color:#CDC6C3;font-weight:700;flex-shrink:0}
.upload-lbl{flex:1;background:#EDE9E3;border-radius:8px;padding:8px 12px;font-size:13px;cursor:pointer;color:#555}
.fstatus{font-size:12px;color:#87A286;min-width:24px;text-align:right}
/* ── Panel interno ── */
.int-panel{display:flex;align-items:center;justify-content:space-between;background:#3D3D3D;padding:10px 14px;position:sticky;top:0;z-index:100}
.int-title{color:rgba(255,255,255,.85);font-size:12px;font-weight:600;letter-spacing:.5px}
.int-actions{display:flex;gap:8px}
.btn-hist-trigger{background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.25);border-radius:8px;padding:6px 12px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}
.btn-hist-trigger:active{background:rgba(255,255,255,.22)}
/* ── Modal historial ── */
.hist-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:1000;align-items:flex-end}
.hist-sheet{background:#fff;border-radius:20px 20px 0 0;width:100%;max-height:85vh;overflow-y:auto;padding-bottom:24px}
.hist-header{display:flex;align-items:center;justify-content:space-between;padding:16px 16px 12px;border-bottom:1px solid #EDE9E3;position:sticky;top:0;background:#fff;z-index:1}
.hist-title{font-size:15px;font-weight:700;color:#3D3D3D}
.hist-close{background:none;border:none;font-size:24px;color:#aaa;cursor:pointer;line-height:1;padding:0 4px}
.hist-item{border-bottom:1px solid #EDE9E3;padding:14px 16px}
.hist-item:last-child{border-bottom:none}
.hist-name{font-size:15px;font-weight:600;color:#3D3D3D;margin-bottom:2px}
.hist-meta{font-size:12px;color:#87A286;margin-bottom:2px}
.hist-wa{font-size:12px;color:#aaa}
.hist-acts{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.hbtn{padding:7px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;border:none;font-family:inherit;text-decoration:none;display:inline-block}
.hbtn-view{background:#EDE9E3;color:#3D3D3D}
.hbtn-edit{background:#87A286;color:#fff}
.hbtn-send{background:#3D3D3D;color:#fff}
.hbtn-del{background:#fee2e2;color:#b91c1c;padding:7px 10px}
.hbtn-del:hover{background:#fecaca}
.hbtn:disabled{opacity:.5;cursor:not-allowed}
.edit-banner{background:#fff3cd;border-left:4px solid #ffc107;padding:10px 14px;margin:10px 12px 0;border-radius:6px;font-size:13px;color:#856404}
/* ── Modal ajustes ── */
.cfg-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:flex-end}
.cfg-modal.open{display:flex}
.cfg-sheet{background:#fff;border-radius:20px 20px 0 0;width:100%;max-height:92vh;overflow-y:auto;padding-bottom:env(safe-area-inset-bottom,20px)}
.cfg-header{display:flex;align-items:center;justify-content:space-between;padding:16px 18px 12px;border-bottom:1px solid #eee;position:sticky;top:0;background:#fff;z-index:1}
.cfg-title{font-size:15px;font-weight:700;color:#3D3D3D}
.cfg-close{background:none;border:none;font-size:24px;color:#aaa;cursor:pointer;line-height:1;padding:0 4px}
.cfg-body{padding:16px 18px}
.cfg-section-title{font-size:11px;font-weight:700;text-transform:uppercase;color:#87A286;letter-spacing:.8px;margin:18px 0 10px}
.cfg-section-title:first-child{margin-top:0}
.cfg-row{margin-bottom:14px}
.cfg-lbl{display:block;font-size:13px;font-weight:600;color:#555;margin-bottom:5px}
.cfg-lbl small{font-weight:400;color:#aaa}
.cfg-input{width:100%;border:1.5px solid #ddd;border-radius:10px;padding:9px 12px;font-size:14px;font-family:inherit;color:#3D3D3D;background:#fff}
.cfg-input:focus{outline:none;border-color:#87A286}
.cfg-range-row{display:flex;align-items:center;gap:10px}
.cfg-range{flex:1;accent-color:#87A286;height:6px}
.cfg-range-val{min-width:40px;text-align:right;font-size:14px;font-weight:700;color:#3D3D3D}
.cfg-checks{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.cfg-check-lbl{display:flex;align-items:center;gap:5px;font-size:13px;color:#3D3D3D;background:#EDE9E3;padding:7px 11px;border-radius:8px;cursor:pointer}
.cfg-check-lbl input{accent-color:#87A286;width:15px;height:15px}
.cfg-save{width:100%;padding:14px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:6px}
.cfg-save:active{background:#6e8b6d}
"""
    opt2_display = "display:none"
    html_np = (
        "<!DOCTYPE html>\n<html lang='es'>\n<head>\n"
        "<meta charset='UTF-8'>\n"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>\n"
        "<title>Nuevo Presupuesto \xb7 Porto Flats</title>\n"
        "<style>"+css_np+"</style>\n</head>\n<body>\n"
        "<div class='header'><div class='logo'>PORTO FLATS</div>"
        "<div class='logo-sub'>Nuevo presupuesto manual</div></div>\n"
        "<div class='int-panel'>"
        "<span class='int-title'>📋 Panel de Ejecución</span>"
        "<div class='int-actions'>"
        "<button type='button' class='btn-hist-trigger' onclick='openHistorial()'>📋 Historial</button>"
        "<button type='button' class='btn-hist-trigger' onclick='openSettings()'>⚙️ Ajustes</button>"
        "</div></div>\n"
        + ("<div class='edit-banner'>✏️ Editando propuesta anterior — modificá los campos y enviá de nuevo.</div>\n"
           if edit_id else "")
        + "<form method='POST' action='/nuevo-presupuesto'>\n"
        # ── Datos del cliente ──
        "<div class='card'><h2>\U0001f464 Datos del cliente</h2>"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Nombre</label><input type='text' name='nombre' placeholder='Juan' required></div>"
        "<div class='field'><label class='lbl'>Apellido</label><input type='text' name='apellido' placeholder='García'></div>"
        "</div>"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Fecha entrada</label><input type='date' name='fecha_entrada' id='fecha_entrada' onchange='calcNoches()'></div>"
        "<div class='field'><label class='lbl'>Fecha salida</label><input type='date' name='fecha_salida' id='fecha_salida' onchange='calcNoches()'></div>"
        "</div>"
        "<div class='row'>"
        "<div class='field'><label class='lbl'>Noches <span style='color:#87A286'>(auto)</span></label>"
        "<div class='noches-badge' id='noches-badge'>—</div>"
        "<input type='hidden' name='noites' id='noites_hidden'></div>"
        "<div class='field'><label class='lbl'>Personas</label><input type='number' name='personas' placeholder='2' min='1' max='30'></div>"
        "</div>"
        "<div class='field'><label class='lbl'>Notas internas (no se env\xedan al cliente)</label>"
        "<input type='text' name='notas_internas' placeholder='Familia con ni\xf1os, prefiere piscina...'></div>"
        "</div>\n"
        # ── Contacto ──
        "<div class='card'><h2>\U0001f4f2 Contacto</h2>"
        "<div class='wa-row'>"
        "<div class='field wa-sel'><label class='lbl'>Pa\xeds</label>"
        "<select name='pais'>"
        "<option value='BR'>\U0001f1e7\U0001f1f7 +55</option>"
        "<option value='AR'>\U0001f1e6\U0001f1f7 +549</option>"
        "<option value='US'>\U0001f1fa\U0001f1f8 +1</option>"
        "</select></div>"
        "<div class='field' style='flex:1'><label class='lbl'>WhatsApp (sin c\xf3digo de pa\xeds)</label>"
        "<input type='text' name='whatsapp_num' placeholder='81 9 1234-5678' required></div>"
        "</div>"
        "<div class='field'><label class='lbl'>Email del cliente <small style='color:#aaa;text-transform:none'>(opcional)</small></label>"
        "<input type='email' name='email_cliente' placeholder='cliente@email.com'></div>"
        "</div>\n"
        # ── Opción 1 ──
        + _opt_fields("_0", "\U0001f3e0 Opci\xf3n 1", n_fotos=n_fotos, custom_services=cfg.get("custom_services", []))
        # ── Botón agregar opción 2 ──
        + "<div class='btn-add-opt' onclick='showOpt2()'>+ Agregar opci\xf3n 2 (opcional)</div>\n"
        # ── Opción 2 (oculta) ──
        + "<div id='opt2-block' style='"+opt2_display+"'>"
        + _opt_fields("_1", "\U0001f3e0 Opci\xf3n 2", n_fotos=n_fotos, custom_services=cfg.get("custom_services", []))
        + "<div style='text-align:center;margin:0 12px 8px'><button type='button' onclick='hideOpt2()' "
          "style='background:none;border:none;color:#aaa;font-size:13px;cursor:pointer'>✕ Quitar opci\xf3n 2</button></div>"
        + "</div>\n"
        # ── Botón enviar ──
        + "<button type='submit' class='btn-enviar'>\U0001f4e4 Enviar propuesta por WhatsApp</button>\n"
        + "</form>\n"
        "<script>\n"
        "function calcNoches(){\n"
        "  const a=document.getElementById('fecha_entrada').value;\n"
        "  const b=document.getElementById('fecha_salida').value;\n"
        "  const badge=document.getElementById('noches-badge');\n"
        "  const hid=document.getElementById('noites_hidden');\n"
        "  if(!a||!b){badge.textContent='—';hid.value='';return;}\n"
        "  const diff=Math.round((new Date(b+' 12:00')-new Date(a+' 12:00'))/(1000*60*60*24));\n"
        "  if(diff>0){\n"
        "    badge.textContent=diff+(diff===1?' noche':' noches');hid.value=diff;\n"
        "    // Auto-llenar noches en las opciones si están vacías o tienen el valor anterior\n"
        "    ['_0','_1'].forEach(sfx=>{\n"
        "      const el=document.getElementById('nnoites'+sfx);\n"
        "      if(el&&(!el.value||el.dataset.auto==='1')){el.value=diff;el.dataset.auto='1';calcNP(sfx);}\n"
        "    });\n"
        "  } else{badge.textContent='—';hid.value='';}\n"
        "}\n"
        "function showOpt2(){document.getElementById('opt2-block').style.display='block';this.style.display='none';}\n"
        "function hideOpt2(){document.getElementById('opt2-block').style.display='none';"
        "document.querySelector('.btn-add-opt').style.display='block';}\n"
        "function calcNP(sfx){\n"
        "  function fmt(v){return v>0?'R$ '+Math.round(v).toLocaleString('pt-BR'):'—';}\n"
        "  const reg  = parseFloat(document.getElementById('pnoche'+sfx)?.value)||0;\n"
        "  const desc = parseFloat(document.getElementById('pdesc'+sfx)?.value)||0;\n"
        "  const nn   = parseInt(document.getElementById('nnoites'+sfx)?.value)||0;\n"
        "  const lp   = parseFloat(document.getElementById('tlimpeza'+sfx)?.value)||0;\n"
        "  const pct  = parseFloat(document.getElementById('mpct'+sfx)?.value)||0;\n"
        "  // Badge descuento\n"
        "  const badge=document.getElementById('pbadge'+sfx);\n"
        "  if(badge){\n"
        "    if(desc>0&&reg>0&&desc<reg){\n"
        "      const d=Math.round((reg-desc)/reg*100);\n"
        "      badge.textContent='-'+d+'%';badge.className='desc-badge';\n"
        "    }else{badge.textContent='—';badge.className='desc-badge empty';}\n"
        "  }\n"
        "  // Diaria efectiva\n"
        "  const diaria=(desc>0&&reg>0&&desc<reg)?desc:reg;\n"
        "  // Subtotal\n"
        "  const subtotal = nn>0&&diaria>0 ? diaria*nn+lp : 0;\n"
        "  const el_sub=document.getElementById('psubtotal'+sfx);\n"
        "  if(el_sub)el_sub.textContent=fmt(subtotal);\n"
        "  // Ganancia y total\n"
        "  const ganancia = subtotal>0&&pct>0 ? Math.round(subtotal*pct/100) : 0;\n"
        "  const total    = subtotal + ganancia;\n"
        "  const el_gan=document.getElementById('ganancia'+sfx);\n"
        "  if(el_gan)el_gan.textContent=fmt(ganancia);\n"
        "  const el_ganhid=document.getElementById('ganancia-hid'+sfx);\n"
        "  if(el_ganhid)el_ganhid.value=ganancia||'';\n"
        "  const el_td=document.getElementById('ptotal-disp'+sfx);\n"
        "  if(el_td)el_td.textContent=fmt(total);\n"
        "  const el_th=document.getElementById('ptotal'+sfx);\n"
        "  if(el_th)el_th.value=total||'';\n"
        "}\n"
        "async function uploadFoto(sfx,input,fi){\n"
        "  const st=document.getElementById('fst'+sfx+'-'+fi);\n"
        "  const ur=document.getElementById('furl'+sfx+'-'+fi);\n"
        "  const file=input.files[0];if(!file)return;\n"
        "  st.textContent='…';\n"
        "  const fd=new FormData();fd.append('file',file);\n"
        "  try{\n"
        "    const r=await fetch('/upload-foto',{method:'POST',body:fd});\n"
        "    const j=await r.json();\n"
        "    if(j.ok){ur.value=j.url;st.textContent='✅';}\n"
        "    else{st.textContent='❌';}\n"
        "  }catch(e){st.textContent='❌';}\n"
        "}\n"
        "function uploadFoto_0(input,fi){uploadFoto('_0',input,fi);}\n"
        "function uploadFoto_1(input,fi){uploadFoto('_1',input,fi);}\n"
        # ── Historial functions ──────────────────────────────────────────────
        "async function openHistorial(){\n"
        "  const modal=document.getElementById('hist-modal');\n"
        "  modal.style.display='flex';\n"
        "  const list=document.getElementById('hist-list');\n"
        "  list.innerHTML='<p style=\"text-align:center;color:#999;padding:24px\">Cargando...</p>';\n"
        "  try{\n"
        "    const r=await fetch('/api/historial');\n"
        "    const j=await r.json();\n"
        "    if(!j.ok||!j.propuestas.length){\n"
        "      list.innerHTML='<p style=\"text-align:center;color:#999;padding:24px\">No hay propuestas en los últimos 45 días.</p>';\n"
        "      return;\n"
        "    }\n"
        "    list.innerHTML=j.propuestas.map(p=>{\n"
        "      const d=p.created_at?new Date(p.created_at).toLocaleString('es-AR',{day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'}):'';\n"
        "      return `<div class='hist-item'>`\n"
        "        +`<div class='hist-name'>${p.nombre||'Sin nombre'}</div>`\n"
        "        +`<div class='hist-meta'>${d} · ${p.ci||'?'} → ${p.co||'?'} · ${p.noites||'?'} noches</div>`\n"
        "        +`<div class='hist-wa'>${p.wa_dest||''}</div>`\n"
        "        +`<div class='hist-acts'>`\n"
        "        +`<a href='${p.short_url}' target='_blank' class='hbtn hbtn-view'>👁 Ver</a>`\n"
        "        +`<button class='hbtn hbtn-edit' onclick='editProp(\"${p.id}\")'>✏️ Editar</button>`\n"
        "        +`<button class='hbtn hbtn-send' id='rb-${p.id}' onclick='reenviarProp(\"${p.id}\")'>📤 Reenviar</button>`\n"
        "        +`<button class='hbtn hbtn-del' onclick='eliminarProp(\"${p.id}\",this)' title='Eliminar'>✕</button>`\n"
        "        +`</div></div>`;\n"
        "    }).join('');\n"
        "  }catch(e){\n"
        "    list.innerHTML='<p style=\"color:#c00;padding:20px\">Error: '+e.message+'</p>';\n"
        "  }\n"
        "}\n"
        "function closeHistorial(){\n"
        "  document.getElementById('hist-modal').style.display='none';\n"
        "}\n"
        "async function reenviarProp(id){\n"
        "  if(!confirm('¿Reenviar esta propuesta por WhatsApp?'))return;\n"
        "  const btn=document.getElementById('rb-'+id);\n"
        "  if(btn){btn.disabled=true;btn.textContent='Enviando…';}\n"
        "  try{\n"
        "    const r=await fetch('/api/reenviar/'+id,{method:'POST'});\n"
        "    const j=await r.json();\n"
        "    if(btn){btn.textContent=j.ok?'✅ Enviado':'❌ Error';}\n"
        "    if(!j.ok&&btn){btn.disabled=false;}\n"
        "  }catch(e){if(btn){btn.textContent='❌ Error';btn.disabled=false;}}\n"
        "}\n"
        "async function eliminarProp(id,btn){\n"
        "  if(!confirm('\\u00bfEliminar esta propuesta del historial?'))return;\n"
        "  btn.disabled=true;btn.textContent='...';\n"
        "  try{\n"
        "    const r=await fetch('/api/eliminar/'+id,{method:'POST'});\n"
        "    const j=await r.json();\n"
        "    if(j.ok){\n"
        "      openHistorial();\n"
        "    }else{btn.disabled=false;btn.textContent='\\u2715';alert('Error al eliminar.');}\n"
        "  }catch(e){btn.disabled=false;btn.textContent='\\u2715';}\n"
        "}\n"
        "async function editProp(id){\n"
        "  closeHistorial();\n"
        "  try{\n"
        "    const r=await fetch('/api/propuesta/'+id);\n"
        "    const j=await r.json();\n"
        "    if(!j.ok){alert('No se pudo cargar la propuesta.');return;}\n"
        "    fillForm(j.propuesta.form_data||{});\n"
        "    window.scrollTo({top:0,behavior:'smooth'});\n"
        "    if(!document.querySelector('.edit-banner')){\n"
        "      const b=document.createElement('div');\n"
        "      b.className='edit-banner';\n"
        "      b.textContent='✏️ Editando propuesta anterior — modificá y enviá de nuevo.';\n"
        "      document.querySelector('.int-panel').insertAdjacentElement('afterend',b);\n"
        "    }\n"
        "  }catch(e){alert('Error: '+e.message);}\n"
        "}\n"
        "function fillForm(fd){\n"
        "  Object.entries(fd).forEach(([k,v])=>{\n"
        "    const el=document.querySelector('[name=\"'+k+'\"]');\n"
        "    if(!el)return;\n"
        "    if(el.type==='file'||el.type==='checkbox')return;\n"
        "    el.value=v;\n"
        "  });\n"
        "  // Mostrar opción 2 si hay datos\n"
        "  const has2=Object.keys(fd).some(k=>k.endsWith('_1')&&fd[k]);\n"
        "  if(has2&&document.getElementById('opt2-block')){\n"
        "    document.getElementById('opt2-block').style.display='block';\n"
        "    const addBtn=document.querySelector('.btn-add-opt');\n"
        "    if(addBtn)addBtn.style.display='none';\n"
        "  }\n"
        "  calcNoches();\n"
        "}\n"
        # ── Pre-cargar desde ?edit=ID (en carga de página) ──────────────────
        "const EDIT_DATA=" + edit_data_json + ";\n"
        "if(EDIT_DATA){fillForm(EDIT_DATA);}\n"
        "if(new URLSearchParams(location.search).get('open')==='historial'){setTimeout(openHistorial,300);}\n"
        # ── Settings JS ──────────────────────────────────────────────────────
        "// ── Configuración ──\n"
        "const CFG=" + cfg_json + ";\n"
        "function openSettings(){\n"
        "  const m=document.getElementById('cfg-modal');\n"
        "  m.classList.add('open');\n"
        "  document.body.style.overflow='hidden';\n"
        "  _cfgRange('cfg-nfotos','cfg-nfotos-val','');\n"
        "  _cfgRange('cfg-margen','cfg-margen-val','%');\n"
        "  _cfgRange('cfg-anticipo','cfg-anticipo-val','%');\n"
        "  _cfgRange('cfg-dias','cfg-dias-val',' días');\n"
        "  _cfgLoad();\n"
        "}\n"
        "function closeSettings(){\n"
        "  document.getElementById('cfg-modal').classList.remove('open');\n"
        "  document.body.style.overflow='';\n"
        "}\n"
        "function _cfgLoad(){\n"
        "  fetch('/api/settings').then(r=>r.json()).then(d=>{\n"
        "    const s=d.settings||{};\n"
        "    const nf=document.getElementById('cfg-nfotos');\n"
        "    if(nf){nf.value=s.n_fotos||8;document.getElementById('cfg-nfotos-val').textContent=s.n_fotos||8;}\n"
        "    const mp=document.getElementById('cfg-margen');\n"
        "    if(mp){mp.value=s.margen_pct||25;document.getElementById('cfg-margen-val').textContent=(s.margen_pct||25)+'%';}\n"
        "    const ap=document.getElementById('cfg-anticipo');\n"
        "    if(ap){ap.value=s.reserva_anticipo||50;document.getElementById('cfg-anticipo-val').textContent=(s.reserva_anticipo||50)+'%';}\n"
        "    const sp=document.getElementById('cfg-saldo');\n"
        "    if(sp){sp.value=s.saldo_plazo||'15 días antes del check-in';}\n"
        "    const mi=document.getElementById('cfg-msgintro');\n"
        "    if(mi){mi.value=s.msg_intro||'';}\n"
        "    const dh=document.getElementById('cfg-dias');\n"
        "    if(dh){dh.value=s.dias_historial||45;document.getElementById('cfg-dias-val').textContent=(s.dias_historial||45)+' días';}\n"
        "    const ce=document.getElementById('cfg-condextra');\n"
        "    if(ce){ce.value=s.cond_extra_default||'';}\n"
        "    const fps=s.forma_pago_defaults||['fp_transf'];\n"
        "    ['fp_efectivo','fp_transf','fp_pix','fp_cripto','fp_tarjeta'].forEach(k=>{\n"
        "      const el=document.getElementById('cfg-'+k);\n"
        "      if(el)el.checked=fps.includes(k);\n"
        "    });\n"
        "    const sve=document.getElementById('cfg-services');\n"
        "    if(sve){sve.value=(s.custom_services||[]).join('\\n');}\n"
        "  });\n"
        "}\n"
        "function _cfgRange(id,valId,suffix){\n"
        "  const el=document.getElementById(id);\n"
        "  const vl=document.getElementById(valId);\n"
        "  if(el&&vl){el.addEventListener('input',()=>vl.textContent=el.value+(suffix||''));}\n"
        "}\n"
        "function saveSettings(){\n"
        "  const fps=[];\n"
        "  ['fp_efectivo','fp_transf','fp_pix','fp_cripto','fp_tarjeta'].forEach(k=>{\n"
        "    if(document.getElementById('cfg-'+k)&&document.getElementById('cfg-'+k).checked)fps.push(k);\n"
        "  });\n"
        "  const svEl=document.getElementById('cfg-services');\n"
        "  const svcs=svEl?svEl.value.split('\\n').map(s=>s.trim()).filter(s=>s):[];\n"
        "  const payload={\n"
        "    n_fotos:parseInt(document.getElementById('cfg-nfotos').value)||8,\n"
        "    margen_pct:parseInt(document.getElementById('cfg-margen').value)||25,\n"
        "    reserva_anticipo:parseInt(document.getElementById('cfg-anticipo').value)||50,\n"
        "    saldo_plazo:document.getElementById('cfg-saldo').value.trim(),\n"
        "    msg_intro:document.getElementById('cfg-msgintro').value.trim(),\n"
        "    dias_historial:parseInt(document.getElementById('cfg-dias').value)||45,\n"
        "    cond_extra_default:document.getElementById('cfg-condextra').value.trim(),\n"
        "    forma_pago_defaults:fps,\n"
        "    custom_services:svcs,\n"
        "  };\n"
        "  const btn=document.getElementById('cfg-save-btn');\n"
        "  btn.disabled=true;btn.textContent='Guardando...';\n"
        "  fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})\n"
        "  .then(r=>r.json()).then(d=>{\n"
        "    if(d.ok){\n"
        "      btn.textContent='✅ Guardado';\n"
        "      setTimeout(()=>location.reload(),600);\n"
        "    } else {\n"
        "      btn.textContent='❌ Error';\n"
        "      btn.disabled=false;\n"
        "    }\n"
        "  }).catch(()=>{btn.textContent='❌ Error';btn.disabled=false;});\n"
        "}\n"
        "</script>\n"
        # ── Modal historial ─────────────────────────────────────────────────
        "<div class='hist-modal' id='hist-modal' onclick='if(event.target===this)closeHistorial()'>\n"
        "<div class='hist-sheet'>\n"
        "<div class='hist-header'>"
        "<span class='hist-title'>📋 Historial de propuestas <small style='color:#aaa;font-size:11px;font-weight:400'>(últimos 45 días)</small></span>"
        "<button class='hist-close' onclick='closeHistorial()'>×</button>"
        "</div>\n"
        "<div id='hist-list'></div>\n"
        "</div></div>\n"
        # ── Modal ajustes ────────────────────────────────────────────────────
        "<div class='cfg-modal' id='cfg-modal' onclick='if(event.target===this)closeSettings()'>\n"
        "<div class='cfg-sheet'>\n"
        "<div class='cfg-header'>"
        "<span class='cfg-title'>⚙️ Ajustes de plantilla</span>"
        "<button class='cfg-close' onclick='closeSettings()'>×</button>"
        "</div>\n"
        "<div class='cfg-body'>\n"
        # Fotos
        "<p class='cfg-section-title'>📸 Fotos por opción</p>"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Cantidad de fotos <small>(1–10)</small></label>"
        "<div class='cfg-range-row'>"
        "<input type='range' class='cfg-range' id='cfg-nfotos' min='1' max='10' step='1' value='8'>"
        "<span class='cfg-range-val' id='cfg-nfotos-val'>8</span>"
        "</div></div>\n"
        # Márgenes y pagos
        "<p class='cfg-section-title'>\U0001f4b0 Precios y pagos</p>"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Margen sugerido <small>(% por defecto)</small></label>"
        "<div class='cfg-range-row'>"
        "<input type='range' class='cfg-range' id='cfg-margen' min='0' max='60' step='1' value='25'>"
        "<span class='cfg-range-val' id='cfg-margen-val'>25%</span>"
        "</div></div>\n"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Anticipo reserva <small>(% por defecto)</small></label>"
        "<div class='cfg-range-row'>"
        "<input type='range' class='cfg-range' id='cfg-anticipo' min='0' max='100' step='5' value='50'>"
        "<span class='cfg-range-val' id='cfg-anticipo-val'>50%</span>"
        "</div></div>\n"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Plazo saldo</label>"
        "<input type='text' class='cfg-input' id='cfg-saldo' placeholder='15 d\xedas antes del check-in'>"
        "</div>\n"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Formas de pago por defecto</label>"
        "<div class='cfg-checks'>"
        "<label class='cfg-check-lbl'><input type='checkbox' id='cfg-fp_transf'> Transferencia</label>"
        "<label class='cfg-check-lbl'><input type='checkbox' id='cfg-fp_pix'> PIX</label>"
        "<label class='cfg-check-lbl'><input type='checkbox' id='cfg-fp_efectivo'> Efectivo</label>"
        "<label class='cfg-check-lbl'><input type='checkbox' id='cfg-fp_tarjeta'> Tarjeta</label>"
        "<label class='cfg-check-lbl'><input type='checkbox' id='cfg-fp_cripto'> Cripto</label>"
        "</div></div>\n"
        "<p class='cfg-section-title'>\u2795 Servicios adicionales</p>\n"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Nombres de servicios <small style='font-weight:400'>(uno por línea — aparecen como campo en el formulario)</small></label>"
        "<textarea class='cfg-input' id='cfg-services' rows='4' style='font-size:13px' "
        "placeholder='Traslado aeropuerto&#10;Cambio de moneda'></textarea>"
        "</div>\n"
        "<p class='cfg-section-title'>\U0001f4ac Mensaje WhatsApp</p>"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Intro del mensaje al cliente</label>"
        "<textarea class='cfg-input' id='cfg-msgintro' rows='3' "
        "placeholder='Te preparamos una propuesta de alojamiento en Porto de Galinhas.'></textarea>"
        "</div>\n"
        "<p class='cfg-section-title'>\U0001f4cb Condiciones y retenci\xf3n</p>"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>Condici\xf3n extra por defecto</label>"
        "<input type='text' class='cfg-input' id='cfg-condextra' "
        "placeholder='Incluye ropa de cama y toallas.'>"
        "</div>\n"
        "<div class='cfg-row'>"
        "<label class='cfg-lbl'>D\xedas de historial</label>"
        "<div class='cfg-range-row'>"
        "<input type='range' class='cfg-range' id='cfg-dias' min='7' max='90' step='1' value='45'>"
        "<span class='cfg-range-val' id='cfg-dias-val'>45 d\xedas</span>"
        "</div></div>\n"
        "<button class='cfg-save' id='cfg-save-btn' onclick='saveSettings()'>Guardar ajustes</button>"
        "</div>\n"
        "</div></div>\n"
        "</body></html>"
    )
    return Response(html_np.encode("utf-8"), content_type="text/html; charset=utf-8")




# ── RECIBO DE PAGO ─────────────────────────────────────────────────────────────
import secrets as _sec_mod

_RECEIPTS_FILE = "/app/receipts.json"

# Textos y defaults globales del módulo de recibos
POL_DEFAULT = (
    "Cancelación hasta 7 días antes del check-in: reembolso del 50% del depósito.\n"
    "Cancelación con menos de 7 días: sin reembolso.\n"
    "No-show: sin reembolso."
)
ENERGIA_DEFAULT = "Incluye uso racional de energia (10 Kw/dia). Excedente: R$ 2/Kw."
CONDO_DEFAULT = "Condominio: R$ 250/mes. Se acordo abonar el 50%. No incluido en este recibo."
FOOTER_DEFAULT = "M&A Empreendimentos Ltda. / CNPJ: 51.057.038/0001-31"

def _load_receipts():
    try:
        with open(_RECEIPTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_receipts(data):
    with open(_RECEIPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _next_recibo_num():
    recs = _load_receipts()
    nums = []
    for v in recs.values():
        try:
            n = int(str(v.get("numero", "0")).replace("REC-", ""))
            nums.append(n)
        except Exception:
            pass
    nxt = (max(nums) + 1) if nums else 1
    return "REC-" + str(nxt).zfill(3)


_CSS_RECIBO_FORM = (
    "*{box-sizing:border-box;margin:0;padding:0}"
    "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "background:#EDE9E3;color:#3D3D3D;min-height:100vh;padding-bottom:90px}"
    ".header{background:#87A286;padding:14px 16px;text-align:center}"
    ".logo{color:#fff;font-size:18px;font-weight:300;letter-spacing:5px;text-transform:uppercase}"
    ".logo-sub{color:rgba(255,255,255,.7);font-size:10px;letter-spacing:2px;margin-top:2px}"
    ".nav{background:#3D3D3D;padding:9px 12px;display:flex;align-items:center;gap:6px}"
    ".nav-title{color:rgba(255,255,255,.45);font-size:11px;flex:1;font-weight:500}"
    ".nbtn{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);color:#fff;"
    "padding:6px 12px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit}"
    ".nbtn:active{background:rgba(255,255,255,.22)}"
    ".card{background:#fff;border-radius:14px;margin:10px 12px;padding:16px;border:1px solid #E8E4DE}"
    ".st{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;"
    "margin-bottom:12px;padding-bottom:6px;border-bottom:1.5px solid #F0EDE8}"
    ".fi{margin-bottom:11px}.fi:last-child{margin-bottom:0}"
    "label{display:block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.9px;"
    "color:#87A286;margin-bottom:4px}"
    "input,select,textarea{width:100%;padding:10px 12px;border:1.5px solid #D4CEC9;border-radius:9px;"
    "font-size:13px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit;"
    "-webkit-appearance:none;appearance:none}"
    "input:focus,select:focus,textarea:focus{border-color:#87A286;box-shadow:0 0 0 3px rgba(135,162,134,.12)}"
    "input[readonly]{background:#F6F4F1;color:#999;border-color:#E0DDD9}"
    "input::placeholder,textarea::placeholder{color:#C4BDB8}"
    "input[type=date]{color:#3D3D3D}"
    ".r2{display:grid;grid-template-columns:1fr 1fr;gap:10px}"
    ".togrow{display:flex;align-items:center;justify-content:space-between}"
    ".toglbl{font-size:13px;color:#3D3D3D;font-weight:500}"
    ".toggle{position:relative;width:44px;height:26px;flex-shrink:0}"
    ".toggle input{opacity:0;width:0;height:0}"
    ".slider-tog{position:absolute;inset:0;background:#D4CEC9;border-radius:26px;cursor:pointer;transition:.2s}"
    ".slider-tog:before{content:'';position:absolute;width:20px;height:20px;left:3px;bottom:3px;"
    "background:#fff;border-radius:50%;transition:.2s}"
    "input:checked+.slider-tog{background:#87A286}"
    "input:checked+.slider-tog:before{transform:translateX(18px)}"
    ".sec-coll{display:none;margin-top:11px}.sec-coll.open{display:block}"
    ".svc-head{display:grid;grid-template-columns:2fr 1fr 1fr 32px;gap:6px;margin-bottom:4px}"
    ".svc-head span{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#B0A9A4;padding:0 2px}"
    ".svc-row{display:grid;grid-template-columns:2fr 1fr 1fr 32px;gap:6px;align-items:center;margin-bottom:7px}"
    ".svc-row input{padding:8px 9px;font-size:12px}"
    ".del-btn{width:30px;height:30px;border:1.5px solid #E8D0D0;border-radius:7px;background:#fff;"
    "color:#c88;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;line-height:1}"
    ".add-btn{display:flex;align-items:center;gap:6px;padding:9px 14px;border:1.5px dashed #D4CEC9;"
    "border-radius:9px;background:transparent;color:#87A286;font-size:12px;font-weight:700;cursor:pointer;"
    "margin-top:6px;width:100%;justify-content:center;font-family:inherit}"
    ".add-btn:active{border-color:#87A286;background:#F8FBF8}"
    ".actbar{position:fixed;bottom:0;left:0;right:0;background:#fff;border-top:1.5px solid #EDEBE7;"
    "padding:10px 12px;display:flex;gap:8px;z-index:50}"
    ".btn-save{flex:1;padding:13px;background:#4A90D9;color:#fff;border:none;border-radius:12px;"
    "font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}"
    ".btn-save:active{background:#3680C9}"
    ".btn-wa{flex:1;padding:13px;background:#25D366;color:#fff;border:none;border-radius:12px;"
    "font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}"
    ".btn-wa:active{background:#1DB954}"
    ".modal-overlay{position:fixed;inset:0;background:rgba(40,35,30,.55);z-index:100;display:none;"
    "align-items:flex-end;justify-content:center}"
    ".modal-overlay.open{display:flex}"
    ".modal-box{background:#EDE9E3;border-radius:20px 20px 0 0;width:100%;max-height:82vh;overflow-y:auto}"
    ".modal-head{background:#87A286;padding:14px 16px;border-radius:20px 20px 0 0;"
    "display:flex;justify-content:space-between;align-items:center}"
    ".modal-head h3{color:#fff;font-size:15px;font-weight:600;margin:0}"
    ".modal-close{background:rgba(255,255,255,.2);border:none;color:#fff;width:28px;height:28px;"
    "border-radius:50%;font-size:16px;cursor:pointer;font-family:inherit;padding:0;line-height:1}"
    ".mbody{padding:12px}"
    ".mcard{background:#fff;border-radius:12px;padding:14px;margin-bottom:10px;border:1px solid #E8E4DE}"
    ".msec{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#87A286;margin-bottom:10px}"
    ".mfi{margin-bottom:9px}.mfi:last-child{margin-bottom:0}"
    ".mfi label{display:block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.7px;color:#87A286;margin-bottom:4px}"
    ".mfi input,.mfi select,.mfi textarea{width:100%;padding:9px 11px;border:1.5px solid #D4CEC9;"
    "border-radius:8px;font-size:13px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit;"
    "-webkit-appearance:none;appearance:none}"
    ".mfi input:focus,.mfi select:focus,.mfi textarea:focus{border-color:#87A286}"
    ".mr2{display:grid;grid-template-columns:1fr 1fr;gap:8px}"
    ".msave-btn{width:100%;padding:12px;background:#87A286;color:#fff;border:none;border-radius:10px;"
    "font-size:14px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:8px}"
    ".hitem{background:#fff;border-radius:12px;padding:13px;margin-bottom:8px;border:1px solid #E8E4DE}"
    ".hitem-name{font-size:13px;font-weight:700;color:#3D3D3D}"
    ".hitem-meta{font-size:11px;color:#999;margin-top:2px}"
    ".hbtns{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}"
    ".hbtn{padding:5px 10px;border-radius:7px;border:none;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit}"
    ".hbtn-view{background:#87A286;color:#fff}"
    ".hbtn-del{background:#fff;color:#c08080;border:1px solid #E8D0D0}"
    ".prev-wrap{background:#fff;border-radius:14px;margin:10px 12px;overflow:hidden;border:1px solid #E8E4DE}"
    ".prev-lbl{background:#F6F4F1;padding:10px 16px;font-size:10px;font-weight:700;text-transform:uppercase;"
    "letter-spacing:1.5px;color:#87A286;border-bottom:1px solid #EDEBE7}"
    ".p-hdr{background:#87A286;padding:16px;text-align:center}"
    ".p-logo{color:#fff;font-size:14px;font-weight:300;letter-spacing:4px;text-transform:uppercase}"
    ".p-tipo{color:rgba(255,255,255,.75);font-size:9px;letter-spacing:1.5px;margin-top:3px;text-transform:uppercase}"
    ".p-num{color:rgba(255,255,255,.9);font-size:11px;font-weight:600;margin-top:5px}"
    ".p-body{padding:14px}"
    ".p-sec{margin-bottom:12px}"
    ".p-sect{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;"
    "border-bottom:1px solid #F0EDE8;padding-bottom:3px;margin-bottom:7px}"
    ".p-row{display:flex;justify-content:space-between;font-size:11px;color:#999;margin-bottom:3px;gap:6px}"
    ".p-row strong{color:#3D3D3D;font-weight:600;text-align:right}"
    ".p-box{background:#F6F4F1;border-radius:8px;padding:12px;margin-top:4px}"
    ".p-boxr{display:flex;justify-content:space-between;font-size:13px;font-weight:700;color:#3D3D3D}"
    ".p-saldo{font-size:11px;color:#87A286;text-align:right;margin-top:4px}"
    ".p-nota{font-size:11px;color:#888;font-style:italic;margin-top:10px;padding:9px 11px;"
    "background:#FAFAF8;border-radius:7px;border-left:3px solid #E8E4DE}"
    ".p-cond{font-size:11px;color:#666;margin-top:9px;padding:9px 11px;background:#F8FBF8;"
    "border-radius:7px;border-left:3px solid rgba(135,162,134,.4)}"
    ".p-cond-t{display:block;font-size:9px;text-transform:uppercase;letter-spacing:1px;"
    "color:#87A286;margin-bottom:3px;font-weight:700}"
    ".p-foot{background:#F2F0ED;padding:8px 14px;font-size:10px;color:#B0A9A4;text-align:center}"
    ".p-dlwrap{text-align:center;padding:12px;border-top:1px solid #F0EDE8}"
    ".p-dlbtn{display:inline-block;background:#87A286;color:#fff;border:none;padding:9px 26px;"
    "border-radius:18px;font-size:12px;font-weight:600;cursor:pointer;font-family:inherit}"
    ".toast{display:none;position:fixed;top:20px;left:50%;transform:translateX(-50%);"
    "background:#3D3D3D;color:#fff;padding:10px 22px;border-radius:20px;font-size:13px;"
    "font-weight:600;z-index:999;white-space:nowrap}"
)

_JS_RECIBO_FORM = (
    "var svcCount=0;\n"
    "function tog(cb,secId){"
    "var sec=document.getElementById(secId);"
    "if(sec)sec.classList.toggle('open',cb.checked);updatePreview();}\n"
    "function addSvc(){\n"
    "svcCount++;\n"
    "var c=document.getElementById('svc-container');\n"
    "var d=document.createElement('div');\n"
    "d.className='svc-row';d.id='svc-row-'+svcCount;\n"
    "d.innerHTML='<input name=\"svc_desc[]\" placeholder=\"Concepto\" oninput=\"updatePreview()\">'"
    "+'<input name=\"svc_pesos[]\" placeholder=\"$ 0\" onblur=\"fmtField(this)\" oninput=\"updatePreview()\">'"
    "+'<input name=\"svc_reales[]\" placeholder=\"R$ 0\" onblur=\"fmtField(this)\" oninput=\"updatePreview()\">'"
    "+'<button type=\"button\" class=\"del-btn\" onclick=\"delSvc('+svcCount+')\">&#xd7;</button>';\n"
    "c.appendChild(d);\n"
    "}\n"
    "function delSvc(i){var el=document.getElementById('svc-row-'+i);if(el){el.remove();updatePreview();}}\n"
    "function pN(v){return parseFloat((v||'').replace(/\\./g,'').replace(',','.'))||0;}\n"
    "function fmtN(n){return n.toFixed(2).replace('.',',').replace(/\\B(?=(\\d{3})+(?!\\d))/g,'.');}\n"
    "function fmtField(el){var n=pN(el.value);if(n>0)el.value=fmtN(n);}\n"
    "function calcNights(){\n"
    "var ci=document.getElementById('f-ci').value;\n"
    "var co=document.getElementById('f-co').value;\n"
    "if(ci&&co){var d=Math.round((new Date(co)-new Date(ci))/86400000);\n"
    "document.getElementById('f-noches').value=d>0?d:'';}\n"
    "updatePreview();}\n"
    "function calcSaldo(){\n"
    "var tipo=document.getElementById('tipo-val').value;\n"
    "var t=pN(document.getElementById('f-total').value);\n"
    "var m=pN(document.getElementById('f-monto').value);\n"
    "var el=document.getElementById('f-saldo');\n"
    "if(tipo==='final'){el.value='0,00';}\n"
    "else if(t>0&&m>0){el.value=fmtN(Math.max(0,t-m));}\n"
    "updatePreview();}\n"
    "function onTipoChange(){calcSaldo();updatePreview();}\n"
    "function fd(s){if(!s)return '';var p=s.split('-');return p.length===3?p[2]+'/'+p[1]+'/'+p[0]:s;}\n"
    "var _symMap={BRL:'R$',USD:'U$S',ARS:'$'};\n"
    "var _tipoLbl={reserva:'RECIBO DE RESERVA',parcial:'RECIBO DE PAGO PARCIAL',final:'RECIBO DE PAGO FINAL'};\n"
    "function _sv(id,v){var el=document.getElementById(id);if(el)el.textContent=v||'';}\n"
    "function _sd(id,show){var el=document.getElementById(id);if(el)el.style.display=show?'flex':'none';}\n"
    "function _sb(id,show){var el=document.getElementById(id);if(el)el.style.display=show?'block':'none';}\n"
    "function updatePreview(){\n"
    "var tipo=document.getElementById('tipo-val').value;\n"
    "var nom=((document.getElementById('f-nom').value||'')+' '+(document.getElementById('f-ape').value||'')).trim();\n"
    "var wa=(document.getElementById('f-wa')&&document.getElementById('f-wa').value)||'';\n"
    "var apto=(document.getElementById('f-apto')&&document.getElementById('f-apto').value)||'';\n"
    "var ci=document.getElementById('f-ci').value||'';\n"
    "var co=document.getElementById('f-co').value||'';\n"
    "var noch=document.getElementById('f-noches').value||'';\n"
    "var monto=document.getElementById('f-monto').value||'';\n"
    "var saldo=document.getElementById('f-saldo').value||'';\n"
    "var nota=(document.getElementById('f-nota')&&document.getElementById('f-nota').value)||'';\n"
    "var moneda=(document.getElementById('f-moneda')&&document.getElementById('f-moneda').value)||'BRL';\n"
    "var num=(document.getElementById('f-num')&&document.getElementById('f-num').value)||'REC-001';\n"
    "var fecha=(document.getElementById('f-fecha')&&document.getElementById('f-fecha').value)||'';\n"
    "var footer=(document.getElementById('f-footer')&&document.getElementById('f-footer').value)||'';\n"
    "var sym=_symMap[moneda]||'R$';\n"
    "_sv('p-tipo',_tipoLbl[tipo]||'RECIBO DE PAGO');\n"
    "_sv('p-num',num+(fecha?' \xb7 '+fd(fecha):''));\n"
    "_sv('p-nom',nom||'—');\n"
    "_sd('p-wa-r',!!wa);_sv('p-wa',wa);\n"
    "_sv('p-apto',apto||'—');\n"
    "_sd('p-ci-r',!!ci);_sv('p-ci',fd(ci));\n"
    "_sd('p-co-r',!!co);_sv('p-co',fd(co));\n"
    "_sd('p-noch-r',!!noch);_sv('p-noch',noch+(noch?' noches':''));\n"
    "_sv('p-monto',monto?sym+' '+monto:'—');\n"
    "var hasSaldo=saldo&&saldo!=='0,00'&&tipo!=='final';\n"
    "_sb('p-saldo-r',!!hasSaldo);\n"
    "if(hasSaldo)_sv('p-saldo',sym+' '+saldo);\n"
    "_sb('p-nota-b',!!nota);_sv('p-nota',nota);\n"
    "_sv('p-foot',footer);\n"
    "var polEl=document.getElementById('tog-pol');\n"
    "var polOn=polEl&&polEl.checked;\n"
    "_sb('p-pol-b',!!polOn);\n"
    "if(polOn){var pt=document.getElementById('pol-txt');_sv('p-pol',pt?pt.value:'');}\n"
    "var enEl=document.getElementById('tog-en');\n"
    "var enOn=enEl&&enEl.checked;\n"
    "_sb('p-en-b',!!enOn);\n"
    "if(enOn){var et=document.getElementById('en-txt');_sv('p-en',et?et.value:'');}\n"
    "var cdEl=document.getElementById('tog-cd');\n"
    "var cdOn=cdEl&&cdEl.checked;\n"
    "_sb('p-cd-b',!!cdOn);\n"
    "if(cdOn){var ct=document.getElementById('cd-txt');_sv('p-cd',ct?ct.value:'');}\n"
    "var rows=document.getElementById('svc-container').querySelectorAll('.svc-row');\n"
    "var svcs=[];\n"
    "rows.forEach(function(r){\n"
    "var ins=r.querySelectorAll('input');\n"
    "var c2=(ins[0]&&ins[0].value.trim())||'';\n"
    "var p2=(ins[1]&&ins[1].value.trim())||'';\n"
    "var re=(ins[2]&&ins[2].value.trim())||'';\n"
    "if(c2||p2||re)svcs.push({c:c2,p:p2,re:re});});\n"
    "var ss=document.getElementById('p-svc-s');\n"
    "var se=document.getElementById('p-svcs');\n"
    "if(svcs.length&&ss&&se){\n"
    "ss.style.display='block';\n"
    "se.innerHTML=svcs.map(function(s){"
    "return '<div class=\"p-row\"><span>'+s.c+'</span><strong>'+(s.re?sym+' '+s.re:(s.p?'$ '+s.p:''))+'</strong></div>';"
    "}).join('');}\n"
    "else if(ss)ss.style.display='none';}\n"
    "document.addEventListener('DOMContentLoaded',function(){\n"
    "document.getElementById('f-total').addEventListener('input',calcSaldo);\n"
    "document.getElementById('f-total').addEventListener('blur',function(){fmtField(this);calcSaldo();});\n"
    "document.getElementById('f-monto').addEventListener('input',calcSaldo);\n"
    "document.getElementById('f-monto').addEventListener('blur',function(){fmtField(this);calcSaldo();});\n"
    "updatePreview();\n"
    "});\n"
)

_JS_RECIBO_HIST = """
async function openHistorial(){
  document.getElementById('hist-overlay').classList.add('open');
  var listEl=document.getElementById('hist-list');
  var subEl=document.getElementById('hist-sub');
  listEl.innerHTML='<div style="text-align:center;padding:20px;color:#aaa">Cargando...</div>';
  try{
    var r=await fetch('/api/historial-recibos');
    var items=await r.json();
    subEl.textContent=items.length+' recibo'+(items.length!==1?'s':'')+' guardados';
    if(!items.length){listEl.innerHTML='<div style="text-align:center;padding:20px;color:#aaa">Sin recibos guardados</div>';return;}
    var h='';
    var tipo_ico={reserva:'✅',parcial:'🟠',final:'🏁'};
    var sym_map={BRL:'R$',USD:'U$S',ARS:'$'};
    items.forEach(function(p){
      var ico=tipo_ico[p.tipo]||'📋';
      var sym=sym_map[p.moneda]||'R$';
      h+='<div class="hitem">';
      h+='<div class="hitem-name">'+ico+' '+(p.nombre||'Sin nombre')+'</div>';
      h+='<div class="hitem-meta">'+p.numero+' · '+p.fecha_pago+' · '+sym+' '+p.monto+'</div>';
      h+='<div class="hbtns">';
      h+='<button class="hbtn hbtn-view" onclick="location.href=\'/recibo/'+p.id+'\'">👁 Ver</button>';
      h+='<button class="hbtn" style="background:#4A90D9;color:#fff" onclick="location.href=\'/nuevo-recibo?edit='+p.id+'\'">✏️ Editar</button>';
      h+='<button class="hbtn" style="background:#25D366;color:#fff" id="reb-'+p.id+'" onclick="reenviarRecibo(\''+p.id+'\')">📤 Reenviar</button>';
      h+='<button class="hbtn hbtn-del" onclick="delRecibo(\''+p.id+'\')">✕ Eliminar</button>';
      h+='</div></div>';
    });
    listEl.innerHTML=h;
  }catch(e){listEl.innerHTML='<div style="color:#c88;padding:10px">Error al cargar historial</div>';}
}
function closeHistorial(e){
  if(!e||e.target===document.getElementById('hist-overlay'))
    document.getElementById('hist-overlay').classList.remove('open');
}
async function delRecibo(id){
  if(!confirm('¿Eliminar este recibo del historial?'))return;
  await fetch('/recibo/'+id+'/delete',{method:'POST'});
  openHistorial();
}
if(new URLSearchParams(location.search).get('open')==='historial'){setTimeout(openHistorial,300);}
async function reenviarRecibo(id){
  if(!confirm('¿Reenviar recibo por WhatsApp al cliente?'))return;
  var btn=document.getElementById('reb-'+id);
  if(btn){btn.textContent='Enviando...';btn.disabled=true;}
  try{
    var r=await fetch('/recibo/'+id+'/enviar-wa',{method:'POST'});
    var d=await r.json();
    alert(d.ok?'✅ Enviado por WhatsApp':'❌ '+(d.error||'Error al enviar'));
  }catch(e){alert('❌ Error de red');}
  if(btn){btn.textContent='📤 Reenviar';btn.disabled=false;}
}
(function(){
  var p=new URLSearchParams(location.search);
  if(p.get('saved')==='1'){
    var div=document.createElement('div');
    div.style.cssText='position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#87A286;color:#fff;padding:12px 28px;border-radius:20px;font-size:14px;font-weight:600;z-index:300;box-shadow:0 4px 12px rgba(0,0,0,.2)';
    div.textContent='✅ Guardado en historial';
    document.body.appendChild(div);
    setTimeout(function(){div.remove();},3000);
  }
})();
"""


@app.route("/nuevo-recibo", methods=["GET"])
def nuevo_recibo_form():
    from datetime import date as _date
    import json as _json
    edit_id = request.args.get("edit", "")
    edata = {}
    if edit_id:
        edata = _load_receipts().get(edit_id, {})
    numero = edata.get("numero") or _next_recibo_num()
    today_iso = _date.today().isoformat()  # yyyy-mm-dd para input type=date

    # POL_DEFAULT / ENERGIA_DEFAULT / CONDO_DEFAULT / FOOTER_DEFAULT → globals

    edit_id_html = ("<input type='hidden' name='edit_id' value='" + edit_id + "'>") if edit_id else ""
    _ed_json = _json.dumps(edata, ensure_ascii=False) if edata else ""

    # Prefill JS: convierte fechas dd/mm/yyyy → yyyy-mm-dd para date inputs
    prefill_js_html = (
        "<script>document.addEventListener('DOMContentLoaded',function(){"
        "var ed=" + _ed_json + ";"
        "if(!Object.keys(ed).length)return;"
        "var f=document.getElementById('f');"
        "function sv(n,v){var el=f.querySelector('[name=\"'+n+'\"]');if(el&&v!==undefined&&v!==null&&v!=='')el.value=v;}"
        "function toIso(s){if(!s)return '';var p=s.split('/');return p.length===3?p[2]+'-'+p[1]+'-'+p[0]:s;}"
        "sv('nombre',ed.nombre);sv('apellido',ed.apellido);sv('dni',ed.dni);sv('wa',ed.wa);sv('email',ed.email);"
        "sv('apto',ed.apto);sv('apto_desc',ed.apto_desc);"
        "sv('checkin',toIso(ed.checkin));sv('checkout',toIso(ed.checkout));"
        "sv('noches',ed.noches);sv('personas',ed.personas);"
        "sv('monto',ed.monto);sv('ref',ed.ref);sv('total',ed.total);sv('saldo',ed.saldo);sv('nota',ed.nota);"
        "sv('pol_texto',ed.pol_texto);sv('energia_texto',ed.energia_texto);sv('condo_texto',ed.condo_texto);"
        "sv('footer_texto',ed.footer_texto);sv('fecha_pago',toIso(ed.fecha_pago));"
        "if(ed.moneda){var ms=f.querySelector('[name=\"moneda\"]');if(ms)ms.value=ed.moneda;}"
        "if(ed.forma_pago){var fps=f.querySelector('[name=\"forma_pago\"]');if(fps)fps.value=ed.forma_pago;}"
        "if(ed.tipo){var ts=document.getElementById('tipo-val');if(ts)ts.value=ed.tipo;}"
        "['pol','energia','condo'].forEach(function(k){"
        "var show=ed['show_'+k]==='1';var cb=document.getElementById('tog-'+k);"
        "if(cb&&show){cb.checked=true;tog(cb,'sec-'+k);}});"
        "if(ed.servicios&&ed.servicios.length){"
        "var c=document.getElementById('svc-container');var r0=document.getElementById('svc-row-0');"
        "ed.servicios.forEach(function(s,i){"
        "if(i===0&&r0){r0.querySelector('[name=\"svc_desc[]\"]').value=s.desc||'';"
        "r0.querySelector('[name=\"svc_pesos[]\"]').value=s.pesos||'';"
        "r0.querySelector('[name=\"svc_reales[]\"]').value=s.reales||'';}"
        "else{addSvc();var rows=c.querySelectorAll('.svc-row');var last=rows[rows.length-1];"
        "last.querySelector('[name=\"svc_desc[]\"]').value=s.desc||'';"
        "last.querySelector('[name=\"svc_pesos[]\"]').value=s.pesos||'';"
        "last.querySelector('[name=\"svc_reales[]\"]').value=s.reales||'';}});}"
        "updatePreview();"
        "});</script>"
    ) if edata else ""

    html = (
        "<!DOCTYPE html><html lang='es'><head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'>"
        "<title>Nuevo Recibo \xb7 Porto Flats</title>"
        "<style>" + _CSS_RECIBO_FORM + "</style></head><body>"

        # Header
        "<div class='header'>"
        "<div class='logo'>Porto Flats</div>"
        "<div class='logo-sub'>Nuevo Recibo de Pago</div>"
        "</div>"

        # Nav bar
        "<div class='nav'>"
        "<span class='nav-title'>Nuevo recibo</span>"
        "<button type='button' class='nbtn' onclick='openHistorial()'>&#x1F4CB; Historial</button>"
        "<button type='button' class='nbtn' onclick=\"document.getElementById('set-ov').classList.add('open')\">&#x2699; Ajustes</button>"
        "</div>"

        "<form id='f' action='/nuevo-recibo' method='POST'>"
        + edit_id_html

        # Tipo dropdown
        + "<div class='card'>"
        "<div class='st'>&#x1F9FE; Tipo de recibo</div>"
        "<div class='fi'><label>Tipo</label>"
        "<select name='tipo' id='tipo-val' onchange='onTipoChange()'>"
        "<option value='reserva'>&#x2705; Reserva</option>"
        "<option value='parcial'>&#x1F7E0; Pago parcial</option>"
        "<option value='final'>&#x1F3C1; Pago final</option>"
        "</select></div></div>"

        # Identificación
        "<div class='card'>"
        "<div class='st'>&#x1F4CB; Identificaci\xf3n</div>"
        "<div class='r2'>"
        "<div class='fi'><label>N\xba de recibo</label><input id='f-num' name='numero' value='" + numero + "' required oninput='updatePreview()'></div>"
        "<div class='fi'><label>Fecha</label><input id='f-fecha' name='fecha_pago' type='date' value='" + today_iso + "' required oninput='updatePreview()'></div>"
        "</div></div>"

        # Cliente
        "<div class='card'>"
        "<div class='st'>&#x1F464; Cliente</div>"
        "<div class='r2'>"
        "<div class='fi'><label>Nombre</label><input id='f-nom' name='nombre' required placeholder='Valeria' oninput='updatePreview()'></div>"
        "<div class='fi'><label>Apellido</label><input id='f-ape' name='apellido' placeholder='Acosta' oninput='updatePreview()'></div>"
        "</div>"
        "<div class='r2'>"
        "<div class='fi'><label>DNI / Pasaporte</label><input name='dni' placeholder='32.924.618'></div>"
        "<div class='fi'><label>WhatsApp</label><input id='f-wa' name='wa' placeholder='+54 9 11...' oninput='updatePreview()'></div>"
        "</div>"
        "<div class='fi'><label>Email</label><input name='email' type='email' placeholder='correo@ejemplo.com'></div>"
        "</div>"

        # Reserva
        "<div class='card'>"
        "<div class='st'>&#x1F3E0; Reserva</div>"
        "<div class='r2'>"
        "<div class='fi'><label>Apartamento</label><input id='f-apto' name='apto' placeholder='Nixxus Premium' required oninput='updatePreview()'></div>"
        "<div class='fi'><label>Descripci\xf3n</label><input name='apto_desc' placeholder='2 cuartos / 2 ba\xf1os'></div>"
        "</div>"
        "<div class='r2'>"
        "<div class='fi'><label>Check-in</label><input id='f-ci' name='checkin' type='date' onchange='calcNights()'></div>"
        "<div class='fi'><label>Check-out</label><input id='f-co' name='checkout' type='date' onchange='calcNights()'></div>"
        "</div>"
        "<div class='r2'>"
        "<div class='fi'><label>Noches (auto)</label><input id='f-noches' name='noches' readonly></div>"
        "<div class='fi'><label>Personas</label><input name='personas' type='number' min='1' placeholder='2'></div>"
        "</div></div>"

        # Servicios
        "<div class='card'>"
        "<div class='st'>&#x1F4E6; Servicios <span style='color:#C4BDB8;font-weight:400;font-size:9px;text-transform:none;letter-spacing:0'>(opcional)</span></div>"
        "<div class='svc-head'><span>Concepto</span><span>Pesos</span><span>Reales</span><span></span></div>"
        "<div id='svc-container'>"
        "<div class='svc-row' id='svc-row-0'>"
        "<input name='svc_desc[]' placeholder='Anticipo reserva' oninput='updatePreview()'>"
        "<input name='svc_pesos[]' placeholder='$ 0' onblur='fmtField(this)' oninput='updatePreview()'>"
        "<input name='svc_reales[]' placeholder='R$ 0' onblur='fmtField(this)' oninput='updatePreview()'>"
        "<div></div>"
        "</div>"
        "</div>"
        "<button type='button' class='add-btn' onclick='addSvc()'>+ Agregar fila</button>"
        "</div>"

        # Pago
        "<div class='card'>"
        "<div class='st'>&#x1F4B3; Pago</div>"
        "<div class='r2'>"
        "<div class='fi'><label>Monto abonado</label><input id='f-monto' name='monto' required placeholder='2.400,00'></div>"
        "<div class='fi'><label>Moneda</label>"
        "<select id='f-moneda' name='moneda' onchange='updatePreview()'>"
        "<option value='BRL'>BRL — R$</option>"
        "<option value='USD'>USD — U$S</option>"
        "<option value='ARS'>ARS — $</option>"
        "</select></div></div>"
        "<div class='fi'><label>Forma de pago</label>"
        "<select name='forma_pago'>"
        "<option>PIX</option><option>Transferencia bancaria</option>"
        "<option>Tarjeta de cr\xe9dito</option><option>Efectivo</option><option>USDT</option>"
        "</select></div>"
        "<div class='fi'><label>Referencia / ID</label><input name='ref' placeholder='TRF-12345'></div>"
        "</div>"

        # Resumen
        "<div class='card'>"
        "<div class='st'>&#x1F4B0; Resumen <span style='color:#C4BDB8;font-weight:400;font-size:9px;text-transform:none;letter-spacing:0'>(opcional)</span></div>"
        "<div class='r2'>"
        "<div class='fi'><label>Valor total</label><input id='f-total' name='total' placeholder='4.800,00'></div>"
        "<div class='fi'><label>Saldo pendiente (auto)</label><input id='f-saldo' name='saldo' readonly></div>"
        "</div>"
        "<div class='fi'><label>Nota / concepto</label>"
        "<textarea id='f-nota' name='nota' rows='2' placeholder='Saldo a pagar 72hs antes del check-in.' oninput='updatePreview()'></textarea>"
        "</div></div>"

        # Política cancelación
        "<div class='card'>"
        "<div class='togrow'>"
        "<span class='toglbl'>&#x1F4CB; Pol\xedtica de cancelaci\xf3n</span>"
        "<label class='toggle'><input type='checkbox' id='tog-pol' name='show_pol' value='1' onchange=\"tog(this,'sec-pol')\"><span class='slider-tog'></span></label>"
        "</div>"
        "<div class='sec-coll' id='sec-pol'>"
        "<textarea id='pol-txt' name='pol_texto' rows='4' oninput='updatePreview()'>" + POL_DEFAULT + "</textarea>"
        "</div></div>"

        # Energía
        "<div class='card'>"
        "<div class='togrow'>"
        "<span class='toglbl'>&#x26A1; Energ\xeda</span>"
        "<label class='toggle'><input type='checkbox' id='tog-en' name='show_energia' value='1' onchange=\"tog(this,'sec-energia')\"><span class='slider-tog'></span></label>"
        "</div>"
        "<div class='sec-coll' id='sec-energia'>"
        "<textarea id='en-txt' name='energia_texto' rows='2' oninput='updatePreview()'>" + ENERGIA_DEFAULT + "</textarea>"
        "</div></div>"

        # Condominio
        "<div class='card'>"
        "<div class='togrow'>"
        "<span class='toglbl'>&#x1F3E2; Condominio</span>"
        "<label class='toggle'><input type='checkbox' id='tog-cd' name='show_condo' value='1' onchange=\"tog(this,'sec-condo')\"><span class='slider-tog'></span></label>"
        "</div>"
        "<div class='sec-coll' id='sec-condo'>"
        "<textarea id='cd-txt' name='condo_texto' rows='2' oninput='updatePreview()'>" + CONDO_DEFAULT + "</textarea>"
        "</div></div>"

        # Footer
        "<div class='card'>"
        "<div class='st'>&#x1F3E2; Pie de p\xe1gina</div>"
        "<div class='fi'><input id='f-footer' name='footer_texto' value='" + FOOTER_DEFAULT + "' placeholder='Empresa / CNPJ' oninput='updatePreview()'></div>"
        "</div>"

        "</form>"

        # Vista previa
        "<div class='prev-wrap'>"
        "<div class='prev-lbl'>&#x1F441; Vista previa — como ve el cliente</div>"
        "<div class='p-hdr'>"
        "<div class='p-logo'>Porto Flats</div>"
        "<div class='p-tipo' id='p-tipo'>RECIBO DE RESERVA</div>"
        "<div class='p-num' id='p-num'>" + numero + "</div>"
        "</div>"
        "<div class='p-body'>"
        "<div class='p-sec'>"
        "<div class='p-sect'>Cliente</div>"
        "<div class='p-row'><span>Nombre</span><strong id='p-nom'>—</strong></div>"
        "<div class='p-row' id='p-wa-r' style='display:none'><span>WhatsApp</span><strong id='p-wa'></strong></div>"
        "</div>"
        "<div class='p-sec'>"
        "<div class='p-sect'>Reserva</div>"
        "<div class='p-row'><span>Apartamento</span><strong id='p-apto'>—</strong></div>"
        "<div class='p-row' id='p-ci-r' style='display:none'><span>Check-in</span><strong id='p-ci'></strong></div>"
        "<div class='p-row' id='p-co-r' style='display:none'><span>Check-out</span><strong id='p-co'></strong></div>"
        "<div class='p-row' id='p-noch-r' style='display:none'><span>Noches</span><strong id='p-noch'></strong></div>"
        "</div>"
        "<div id='p-svc-s' class='p-sec' style='display:none'>"
        "<div class='p-sect'>Servicios</div>"
        "<div id='p-svcs'></div>"
        "</div>"
        "<div class='p-box'>"
        "<div class='p-boxr'><span>Monto abonado</span><span id='p-monto'>—</span></div>"
        "<div class='p-saldo' id='p-saldo-r' style='display:none'>Saldo pendiente: <strong id='p-saldo'></strong></div>"
        "</div>"
        "<div class='p-nota' id='p-nota-b' style='display:none'><span id='p-nota'></span></div>"
        "<div class='p-cond' id='p-pol-b' style='display:none'><span class='p-cond-t'>Pol\xedtica de cancelaci\xf3n</span><span id='p-pol'></span></div>"
        "<div class='p-cond' id='p-en-b' style='display:none'><span class='p-cond-t'>Energ\xeda</span><span id='p-en'></span></div>"
        "<div class='p-cond' id='p-cd-b' style='display:none'><span class='p-cond-t'>Condominio</span><span id='p-cd'></span></div>"
        "</div>"
        "<div class='p-foot' id='p-foot'>" + FOOTER_DEFAULT + "</div>"
        "<div class='p-dlwrap'><button class='p-dlbtn' type='button'>&#x2B07;&#xFE0F; Descargar PDF</button></div>"
        "</div>"

        # Barra de acciones
        "<div class='actbar'>"
        "<button type='submit' form='f' name='accion' value='guardar' class='btn-save'>&#x1F4BE; Guardar</button>"
        "<button type='submit' form='f' name='accion' value='enviar_wa' class='btn-wa'>&#x1F4F2; Generar + WhatsApp</button>"
        "</div>"

        + prefill_js_html

        # Modal Historial
        + "<div class='modal-overlay' id='hist-overlay' onclick='closeHistorial(event)'>"
        "<div class='modal-box'>"
        "<div class='modal-head'>"
        "<h3>&#x1F4CB; Historial de recibos</h3>"
        "<button class='modal-close' onclick='closeHistorial()'>&#x2715;</button>"
        "</div>"
        "<div class='mbody'>"
        "<div id='hist-sub' style='font-size:11px;color:#999;margin-bottom:10px'></div>"
        "<div id='hist-list'></div>"
        "</div></div></div>"

        # Modal Ajustes
        "<div class='modal-overlay' id='set-ov' onclick=\"if(event.target===this)this.classList.remove('open')\">"
        "<div class='modal-box'>"
        "<div class='modal-head'>"
        "<h3>&#x2699; Ajustes del sistema</h3>"
        "<button class='modal-close' onclick=\"document.getElementById('set-ov').classList.remove('open')\">&#x2715;</button>"
        "</div>"
        "<div class='mbody'>"
        "<div class='mcard'>"
        "<div class='msec'>&#x1F3E2; Empresa</div>"
        "<div class='mfi'><label>Raz\xf3n social</label><input id='s-emp' placeholder='M&amp;A Empreendimentos Ltda.'></div>"
        "<div class='mfi'><label>CNPJ / RUT</label><input id='s-cnpj' placeholder='51.057.038/0001-31'></div>"
        "<div class='mfi'><label>Pie de p\xe1gina</label><input id='s-foot' placeholder='Empresa / CNPJ'></div>"
        "</div>"
        "<div class='mcard'>"
        "<div class='msec'>&#x1F4F1; WhatsApp y env\xedos</div>"
        "<div class='mfi'><label>Mensaje de intro WA</label>"
        "<textarea id='s-wmsg' rows='2' placeholder='Hola {nombre}, te env\xedo tu recibo!'></textarea>"
        "</div>"
        "<div class='mr2'>"
        "<div class='mfi'><label>Moneda por defecto</label>"
        "<select id='s-mon'><option value='BRL'>BRL — R$</option>"
        "<option value='USD'>USD — U$S</option><option value='ARS'>ARS — $</option></select>"
        "</div>"
        "<div class='mfi'><label>Forma de pago</label>"
        "<select id='s-fp'><option>PIX</option><option>Transferencia</option><option>Efectivo</option></select>"
        "</div></div>"
        "</div>"
        "<div class='mcard'>"
        "<div class='msec'>&#x1F4CB; Textos predeterminados</div>"
        "<div class='mfi'><label>Pol\xedtica de cancelaci\xf3n</label>"
        "<textarea id='s-pol' rows='4'>" + POL_DEFAULT + "</textarea>"
        "</div>"
        "<div class='mfi'><label>Energ\xeda</label>"
        "<textarea id='s-en' rows='2'>" + ENERGIA_DEFAULT + "</textarea>"
        "</div>"
        "<div class='mfi'><label>Condominio</label>"
        "<textarea id='s-cd' rows='2'>" + CONDO_DEFAULT + "</textarea>"
        "</div>"
        "</div>"
        "<div class='mcard'>"
        "<div class='msec'>&#x1F522; Numeraci\xf3n</div>"
        "<div class='mr2'>"
        "<div class='mfi'><label>Prefijo</label><input id='s-prefix' value='REC-'></div>"
        "<div class='mfi'><label>Pr\xf3ximo n\xba</label><input type='number' id='s-next' value='1' min='1'></div>"
        "</div>"
        "</div>"
        "<button class='msave-btn' onclick='saveReciboSettings()'>&#x2705; Guardar configuraci\xf3n</button>"
        "</div></div></div>"

        "<div class='toast' id='toast'></div>"
        "<script>" + _JS_RECIBO_FORM + _JS_RECIBO_HIST
        + "function saveReciboSettings(){"
        "document.getElementById('set-ov').classList.remove('open');"
        "var t=document.getElementById('toast');"
        "t.textContent='✅ Configuraci\xf3n guardada';"
        "t.style.display='block';"
        "setTimeout(function(){t.style.display='none';},2500);}"
        "</script>"
        "</body></html>"
    )
    return Response(html.encode("utf-8"), content_type="text/html; charset=utf-8")


@app.route("/nuevo-recibo", methods=["POST"])
def nuevo_recibo_post():
    from datetime import datetime as _dt
    fv = lambda k, d="": request.form.get(k, d).strip()

    svcs = []
    descs = request.form.getlist("svc_desc[]")
    pesos = request.form.getlist("svc_pesos[]")
    reales = request.form.getlist("svc_reales[]")
    for i, desc in enumerate(descs):
        desc = desc.strip()
        if desc:
            svcs.append({
                "desc": desc,
                "pesos": pesos[i].strip() if i < len(pesos) else "",
                "reales": reales[i].strip() if i < len(reales) else "",
            })

    edit_id = fv("edit_id")
    recs_pre = _load_receipts()
    rid = edit_id if (edit_id and edit_id in recs_pre) else _sec_mod.token_hex(5)

    rec = {
        "id": rid,
        "created": _dt.utcnow().isoformat(),
        "tipo": fv("tipo", "reserva"),
        "numero": fv("numero"),
        "fecha_pago": fv("fecha_pago"),
        "nombre": fv("nombre"),
        "apellido": fv("apellido"),
        "dni": fv("dni"),
        "wa": fv("wa"),
        "email": fv("email"),
        "apto": fv("apto"),
        "apto_desc": fv("apto_desc"),
        "checkin": fv("checkin"),
        "checkout": fv("checkout"),
        "noches": fv("noches"),
        "personas": fv("personas"),
        "servicios": svcs,
        "monto": fv("monto"),
        "moneda": fv("moneda", "BRL"),
        "forma_pago": fv("forma_pago"),
        "ref": fv("ref"),
        "total": fv("total"),
        "saldo": fv("saldo"),
        "nota": fv("nota"),
        "show_pol": fv("show_pol"),
        "pol_texto": fv("pol_texto"),
        "show_energia": fv("show_energia"),
        "energia_texto": fv("energia_texto"),
        "show_condo": fv("show_condo"),
        "condo_texto": fv("condo_texto"),
        "footer_texto": fv("footer_texto"),
    }

    def _fmt_date(s):
        if s and len(s) == 10 and s[4] == "-":
            p = s.split("-")
            return p[2] + "/" + p[1] + "/" + p[0]
        return s

    rec["checkin"] = _fmt_date(rec.get("checkin", ""))
    rec["checkout"] = _fmt_date(rec.get("checkout", ""))
    rec["fecha_pago"] = _fmt_date(rec.get("fecha_pago", ""))

    recs = _load_receipts()
    recs[rid] = rec
    _save_receipts(recs)

    base = os.environ.get("PROPUESTAS_DOMAIN", request.host_url.rstrip("/"))
    accion = fv("accion", "enviar_wa")

    if accion == "guardar":
        return redirect(base + "/nuevo-recibo?saved=1")

    if accion == "enviar_wa":
        wa_raw = rec.get("wa", "").strip()
        wa_num = wa_raw.replace(" ", "").replace("-", "").replace("+", "")
        if wa_num:
            nombre_cl = (rec.get("nombre", "") + " " + rec.get("apellido", "")).strip() or "cliente"
            sym = {"BRL": "R$", "USD": "U$S", "ARS": "$"}.get(rec.get("moneda", "BRL"), "R$")
            link = base + "/recibo/" + rid
            msg = (
                "¡Hola " + nombre_cl + "! \U0001f44b\n\n"
                "Te enviamos tu recibo de pago " + rec.get("numero", "") + " de Porto Flats.\n\n"
                "\U0001f4b0 Monto abonado: " + sym + " " + rec.get("monto", "") + "\n"
                "\U0001f4cb Ver comprobante:\n" + link + "\n\n"
                "¡Muchas gracias! \U0001f3e0"
            )
            _evo_send_text(wa_num, msg)
        return redirect(base + "/recibo/" + rid + "?wa=sent")

    return redirect(base + "/recibo/" + rid)


# ─── Ver recibo (vista cliente) ────────────────────────────────────────────────

@app.route("/recibo/<rid>", methods=["GET"])
def ver_recibo(rid):
    recs = _load_receipts()
    rec = recs.get(rid)
    if not rec:
        return "Recibo no encontrado.", 404

    tipo = rec.get("tipo", "reserva")
    tipo_labels = {
        "reserva": ("✅", "Reserva Confirmada", "#2E7D32"),
        "parcial": ("\U0001f7e0", "Pago Parcial Recibido", "#E65100"),
        "final":   ("\U0001f3c1", "Pago Final Completado", "#1565C0"),
    }
    tipo_ico, tipo_txt, tipo_color = tipo_labels.get(tipo, ("✅", "Recibo de Pago", "#2E7D32"))
    tipo_lbl_map = {
        "reserva": "RECIBO DE RESERVA",
        "parcial": "RECIBO DE PAGO PARCIAL",
        "final":   "RECIBO DE PAGO FINAL",
    }
    tipo_lbl = tipo_lbl_map.get(tipo, "RECIBO DE PAGO")

    nombre_full = (rec.get("nombre", "") + " " + rec.get("apellido", "")).strip()
    moneda = rec.get("moneda", "BRL")
    sym = {"BRL": "R$", "USD": "U$S", "ARS": "$"}.get(moneda, "R$")
    numero = rec.get("numero", "")
    fecha_pago = rec.get("fecha_pago", "")
    apto = rec.get("apto", "")
    apto_desc = rec.get("apto_desc", "")
    checkin = rec.get("checkin", "")
    checkout = rec.get("checkout", "")
    noches = rec.get("noches", "")
    monto = rec.get("monto", "")
    saldo = rec.get("saldo", "")
    nota = rec.get("nota", "")
    show_pol = rec.get("show_pol", "")
    pol_texto = rec.get("pol_texto", "")
    show_energia = rec.get("show_energia", "")
    energia_texto = rec.get("energia_texto", "")
    show_condo = rec.get("show_condo", "")
    condo_texto = rec.get("condo_texto", "")
    footer_texto = rec.get("footer_texto", FOOTER_DEFAULT)
    wa_sent = request.args.get("wa") == "sent"
    wa_num = rec.get("wa", "")

    def _row(label, val, show=True):
        if not show or not val:
            return ""
        return "<div class='p-row'><span>" + label + "</span><strong>" + str(val) + "</strong></div>"

    svcs_html = ""
    servicios = rec.get("servicios", [])
    if servicios:
        rows_html = ""
        for s in servicios:
            desc = s.get("desc", "")
            re_val = s.get("reales", "")
            pe_val = s.get("pesos", "")
            val_str = (sym + " " + re_val) if re_val else ("$ " + pe_val if pe_val else "")
            if desc:
                rows_html += "<div class='p-row'><span>" + desc + "</span><strong>" + val_str + "</strong></div>"
        if rows_html:
            svcs_html = "<div class='p-sec'><div class='p-sect'>Servicios</div>" + rows_html + "</div>"

    saldo_html = ""
    if saldo and saldo != "0,00" and tipo != "final":
        saldo_html = "<div class='p-saldo'>Saldo pendiente: <strong>" + sym + " " + saldo + "</strong></div>"

    nota_html = ""
    if nota:
        nota_html = "<div class='p-nota'>" + nota + "</div>"

    cond_html = ""
    if show_pol == "1" and pol_texto:
        cond_html += "<div class='p-cond'><span class='p-cond-t'>Pol\xedtica de cancelaci\xf3n</span><span>" + pol_texto + "</span></div>"
    if show_energia == "1" and energia_texto:
        cond_html += "<div class='p-cond'><span class='p-cond-t'>Energ\xeda</span><span>" + energia_texto + "</span></div>"
    if show_condo == "1" and condo_texto:
        cond_html += "<div class='p-cond'><span class='p-cond-t'>Condominio</span><span>" + condo_texto + "</span></div>"

    base_url = os.environ.get("PROPUESTAS_DOMAIN", request.host_url.rstrip("/"))
    pdf_url = base_url + "/recibo/" + rid + "/pdf"

    wa_banner = ""
    if wa_sent:
        wa_banner = ("<div style='background:#E8F5E9;border-left:4px solid #4CAF50;padding:12px 16px;"
                     "margin:10px 12px;border-radius:8px;font-size:13px;color:#2E7D32;font-weight:600;'>"
                     "\U0001f4f2 Recibo enviado por WhatsApp a " + wa_num + "</div>")

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Recibo " + numero + " — Porto Flats</title>"
        "<style>"
        + _CSS_RECIBO_FORM +
        "</style></head><body>"
        "<div class='header'>"
        "<div class='logo'>Porto Flats</div>"
        "<div class='logo-sub'>Recibo de pago</div>"
        "</div>"
        + wa_banner +
        "<div class='prev-wrap' style='margin:12px'>"
        "<div class='p-hdr'>"
        "<div class='p-logo'>Porto Flats</div>"
        "<div class='p-tipo'>" + tipo_lbl + "</div>"
        "<div class='p-num'>" + numero + (("· " + fecha_pago) if fecha_pago else "") + "</div>"
        "</div>"
        "<div class='p-body'>"
        "<div class='p-sec'>"
        "<div class='p-sect'>Cliente</div>"
        + _row("Nombre", nombre_full)
        + _row("WhatsApp", wa_num)
        +
        "</div>"
        "<div class='p-sec'>"
        "<div class='p-sect'>Reserva</div>"
        + _row("Apartamento", (apto + (" — " + apto_desc if apto_desc else "")) if apto else "")
        + _row("Check-in", checkin)
        + _row("Check-out", checkout)
        + _row("Noches", noches + " noches" if noches else "")
        +
        "</div>"
        + svcs_html +
        "<div class='p-box'>"
        "<div class='p-boxr'><span>Monto abonado</span><span>" + sym + " " + monto + "</span></div>"
        + saldo_html +
        "</div>"
        + nota_html
        + cond_html +
        "</div>"
        "<div class='p-foot'>" + footer_texto + "</div>"
        "<div class='p-dlwrap'>"
        "<a href='" + pdf_url + "' class='p-dlbtn' download>&#x2B07;&#xFE0F; Descargar PDF</a>"
        "</div>"
        "</div>"
        "</body></html>"
    )
    return Response(html.encode("utf-8"), content_type="text/html; charset=utf-8")


@app.route("/recibo/<rid>/pdf", methods=["GET"])
def recibo_pdf(rid):
    recs = _load_receipts()
    rec = recs.get(rid)
    if not rec:
        return "Recibo no encontrado.", 404

    base_url = os.environ.get("PROPUESTAS_DOMAIN", request.host_url.rstrip("/"))
    src_url = base_url + "/recibo/" + rid

    try:
        import pdfkit
        options = {
            "page-size": "A4",
            "margin-top": "0",
            "margin-right": "0",
            "margin-bottom": "0",
            "margin-left": "0",
            "encoding": "UTF-8",
            "no-outline": None,
            "enable-local-file-access": None,
        }
        pdf_bytes = pdfkit.from_url(src_url, False, options=options)
        numero = rec.get("numero", rid)
        nombre = (rec.get("nombre", "") + " " + rec.get("apellido", "")).strip() or rid
        fname = "recibo_" + numero + "_" + nombre.replace(" ", "_") + ".pdf"
        return Response(
            pdf_bytes,
            content_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=\"" + fname + "\""},
        )
    except Exception as e:
        return "Error generando PDF: " + str(e), 500


# ─── API Historial ─────────────────────────────────────────────────────────────

@app.route("/api/historial-recibos", methods=["GET"])
def api_historial_recibos():
    recs = _load_receipts()
    lst = []
    for rid, r in recs.items():
        nombre_full = (r.get("nombre", "") + " " + r.get("apellido", "")).strip()
        lst.append({
            "id": rid,
            "numero": r.get("numero", ""),
            "tipo": r.get("tipo", "reserva"),
            "nombre": nombre_full,
            "apto": r.get("apto", ""),
            "monto": r.get("monto", ""),
            "moneda": r.get("moneda", "BRL"),
            "fecha_pago": r.get("fecha_pago", ""),
            "created": r.get("created", ""),
            "wa": r.get("wa", ""),
        })
    lst.sort(key=lambda x: x.get("created", ""), reverse=True)
    return jsonify({"recibos": lst})


# ─── Eliminar recibo ───────────────────────────────────────────────────────────

@app.route("/recibo/<rid>/delete", methods=["POST"])
def delete_recibo(rid):
    recs = _load_receipts()
    if rid in recs:
        del recs[rid]
        _save_receipts(recs)
    base = os.environ.get("PROPUESTAS_DOMAIN", request.host_url.rstrip("/"))
    return redirect(base + "/nuevo-recibo?saved=1")


# ─── Reenviar WhatsApp ────────────────────────────────────────────────────────

@app.route("/recibo/<rid>/enviar-wa", methods=["POST"])
def enviar_recibo_wa(rid):
    recs = _load_receipts()
    rec = recs.get(rid)
    if not rec:
        return jsonify({"ok": False, "error": "not found"}), 404
    wa_raw = rec.get("wa", "").strip()
    wa_num = wa_raw.replace(" ", "").replace("-", "").replace("+", "")
    if not wa_num:
        return jsonify({"ok": False, "error": "no wa number"}), 400
    base = os.environ.get("PROPUESTAS_DOMAIN", request.host_url.rstrip("/"))
    nombre_cl = (rec.get("nombre", "") + " " + rec.get("apellido", "")).strip() or "cliente"
    sym = {"BRL": "R$", "USD": "U$S", "ARS": "$"}.get(rec.get("moneda", "BRL"), "R$")
    link = base + "/recibo/" + rid
    msg = (
        "¡Hola " + nombre_cl + "! \U0001f44b\n\n"
        "Te enviamos tu recibo de pago " + rec.get("numero", "") + " de Porto Flats.\n\n"
        "\U0001f4b0 Monto abonado: " + sym + " " + rec.get("monto", "") + "\n"
        "\U0001f4cb Ver comprobante:\n" + link + "\n\n"
        "¡Muchas gracias! 🏠"
    )
    ok = _evo_send_text(wa_num, msg)
    return jsonify({"ok": ok})
