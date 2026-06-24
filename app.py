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
from flask import Flask, request, jsonify, Response
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
        http.post(url, json={"number": str(numero), "text": text},
                  headers=_evo_headers(), timeout=30)
    except Exception as e:
        print(f"[EVO text error] {e}")

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

def _tinyurl(url):
    try:
        r = http.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
        return r.text.strip() or url
    except Exception:
        return url


# ── /health ──────────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "porto-flats-pdf"})


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
OPCIONES_SHEET = os.environ.get("OPCIONES_SHEET", "Opciones Pendientes")
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
        row_vals = [str(data_dict.get(h, "")) for h in headers]
        ws.append_row(row_vals, value_input_option="USER_ENTERED")
        all_vals = ws.get_all_values()
        return len(all_vals)
    except Exception as e:
        print(f"[Sheets] append_row error: {e}")
        return None


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
def _cleanup_old_photos(max_days=7):
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


# ── /dashboard ────────────────────────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    """Panel interno: cards con opciones para seleccionar y enviar."""
    row = request.args.get("row", "")
    if not row:
        return Response("Falta ?row=N", status=400, mimetype="text/plain")
    rd = _sheets_get_row(row)
    if not rd:
        return Response("Error leyendo Sheets.", status=500, mimetype="text/plain")
    nombre = rd.get("nombre", "Cliente")
    ci     = rd.get("fecha_entrada", "")
    co     = rd.get("fecha_salida",  "")
    noites = rd.get("noites", "")
    try:
        opciones = json.loads(rd.get("opciones_json", "[]") or "[]")
    except Exception:
        opciones = []
    if not opciones:
        return Response("No hay opciones en esta fila.", status=404, mimetype="text/plain")

    def _card(i, opt):
        nome      = opt.get("nome", opt.get("Title", "Opcion " + str(i+1)))
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
        parts = [
            '<div class="opt-card" id="card-'+str(i)+'">',
            '<div class="card-top"><label class="chk-wrap">',
            '<input type="checkbox" name="sel" value="'+str(i)+'" onchange="updateBtn()">',
            '<span class="chk-txt">Incluir en propuesta</span></label>',
            '<span class="opt-num">#'+str(i+1)+'</span></div>',
            thumb,
            '<div class="card-info"><div class="opt-name">'+nome+'</div>',
            ('<div class="opt-loc">\U0001f4cd '+distancia+'</div>' if distancia else ""),
            ('<div class="opt-feats">'+feats_str+'</div>' if feats_str else ""),
            ('<div class="opt-amenids">'+amenidades+'</div>' if amenidades else ""),
            price_html,
            url_html,
            '</div>',
            '<a href="/editar?row='+str(row)+'&amp;idx='+str(i)+'" class="btn-editar">✏️ Editar propuesta</a>',
            '</div>'
        ]
        return "".join(parts)

    cards_html = "\n".join(_card(i, o) for i, o in enumerate(opciones))
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
    subhead_html = ("<div class='subhead'><span>"+resumen+"</span><span style='color:#87A286;font-size:12px'>fila "+str(row)+"</span></div>"
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
        "  const selected=[...document.querySelectorAll('input[name=sel]:checked')].map(x=>parseInt(x.value));\n"
        "  btn.disabled=true;btn.textContent='Enviando…';msgBox.style.display='none';\n"
        "  try{\n"
        "    const r=await fetch('/enviar-propuesta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({row:'"+str(row)+"',selected})});\n"
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
        "<input type='url' name='mapa_url' value='"+mapa_url+"' placeholder='https://maps.google.com/...'></div>"
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
    """Recibe {row, selected:[0,2]}, envia WhatsApp al cliente con link /propuesta."""
    data     = request.get_json(force=True) or {}
    row      = str(data.get("row", ""))
    selected = data.get("selected", [])
    if not row or not selected:
        return jsonify({"error": "Faltan row o selected"}), 400
    rd = _sheets_get_row(row)
    if not rd:
        return jsonify({"error": "Error leyendo Sheets"}), 500
    nombre   = rd.get("nombre", "")
    whatsapp = rd.get("whatsapp", "")
    ci       = rd.get("fecha_entrada", "")
    co       = rd.get("fecha_salida",  "")
    noites   = rd.get("noites", "")
    sel_str       = ",".join(str(x) for x in selected)
    propuesta_url = SERVICE_URL + "/propuesta?row=" + row + "&sel=" + sel_str
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
    _sheets_update(row, "estado", "Enviado al cliente")
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
    """Landing multi-opcion para el cliente. ?row=N&sel=0,1"""
    from urllib.parse import quote as urlquote
    row     = request.args.get("row", "")
    sel_raw = request.args.get("sel", "")
    if not row:
        return Response("Falta ?row=N", status=400, mimetype="text/plain")
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
        preco_raw  = opt.get("preco_total",  opt.get("total_brl", 0))
        limpeza_raw = opt.get("taxa_limpeza", opt.get("limpieza_brl", 0))
        try:
            preco_v   = float(str(preco_raw).replace(",",".") or 0)
            limpeza_v = float(str(limpeza_raw).replace(",",".") or 0)
        except Exception:
            preco_v = limpeza_v = 0
        fotos = []
        for fi in range(1, 11):
            u = opt.get("foto"+str(fi)+"_up","") or opt.get("foto"+str(fi),"") or opt.get("f"+str(fi),"")
            if u: fotos.append(u)
        carousel = ""
        if fotos:
            imgs = "".join("<img src='"+f+"' class='car-img' loading='lazy' onerror=\"this.style.display='none'\">" for f in fotos)
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
            if noites:
                try:
                    n = int(noites)
                    diaria = (preco_v - limpeza_v) / n if n else preco_v
                    rows_p += "<div class='pr-row'><span>\U0001f319 Precio por noche</span><span>R$ "+str(int(diaria))+"</span></div>"
                    rows_p += "<div class='pr-row'><span>\U0001f4c5 Noches</span><span>\xd7 "+str(n)+"</span></div>"
                except Exception:
                    pass
            if limpeza_v > 0:
                rows_p += "<div class='pr-row'><span>\U0001f9f9 Limpieza</span><span>R$ "+str(int(limpeza_v))+"</span></div>"
            rows_p += "<div class='pr-row pr-total'><span>\U0001f4b0 Total estimado</span><span>R$ "+str(int(preco_v))+"</span></div>"
            price_html = "<div class='card'><div class='sec-title'>Precio estimado</div><div class='pr-table'>"+rows_p+"</div></div>"
        map_html = ""
        if mapa_url:
            embed_url = (mapa_url + ("&" if "?" in mapa_url else "?") + "output=embed"
                         if "google.com/maps" in mapa_url and "output=embed" not in mapa_url
                         else mapa_url)
            map_html = ("<div class='card np'><div class='sec-title'>\U0001f4cd Ubicaci\xf3n</div>"
                        "<div class='maps-wrap'><iframe src='"+embed_url+"' width='100%' height='200' frameborder='0' "
                        "style='border:0;border-radius:12px;display:block' allowfullscreen loading='lazy'></iframe></div>"
                        "<a href='"+mapa_url+"' class='btn btn-maps' target='_blank'>\U0001f5fa Ver en Google Maps</a></div>")
        else:
            loc_q = urlquote(nome + ", Porto de Galinhas, Pernambuco, Brasil")
            map_html = ("<div class='card np'><div class='sec-title'>\U0001f4cd Ubicaci\xf3n</div>"
                        "<div class='maps-wrap'><iframe src='https://maps.google.com/maps?q="+loc_q+"&output=embed' "
                        "width='100%' height='200' frameborder='0' style='border:0;border-radius:12px;display:block' "
                        "allowfullscreen loading='lazy'></iframe></div></div>")
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
.car-img{height:240px;min-width:320px;max-width:360px;object-fit:cover;border-radius:12px;flex-shrink:0;scroll-snap-align:start;background:#CDC6C3}
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
        + "<script>\nconst ROW='"+str(row)+"';\n"
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
          "  try{\n"
          "    const r=await fetch('/confirmar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({row:ROW,opciones_elegidas:opts})});\n"
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
    opciones_eleg = data.get("opciones_elegidas", [])
    if not row:
        return jsonify({"error": "Falta row"}), 400
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
        wa_num    = request.form.get("whatsapp_num", "").strip().replace(" ","").replace("-","")
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
        def _build_opt(sfx):
            """Construye dict de opción desde campos del form con sufijo _0 o _1."""
            def fv(k): return request.form.get(k + sfx, "")
            opt = {}
            for f in ["nome","distancia","quartos","banheiros","hospedes","amenidades",
                      "preco_total","taxa_limpeza","mapa_url","observaciones","cond_extra",
                      "preco_noche","n_noites","margen_pct","preco_sugerido","ganancia_r",
                      "reserva_anticipo","saldo_plazo","url"]:
                v = fv(f)
                if v: opt[f] = v
            # forma_pago
            fps = ["fp_efectivo","fp_transf","fp_pix","fp_cripto","fp_tarjeta"]
            labels = {"fp_efectivo":"Efectivo","fp_transf":"Transferencia",
                      "fp_pix":"PIX","fp_cripto":"Cripto","fp_tarjeta":"Tarjeta"}
            chosen = [labels[k] for k in fps if request.form.get(k+sfx)]
            if chosen: opt["forma_pago"] = " \xb7 ".join(chosen)
            # fotos
            for fi in range(1, 6):
                u = request.form.get("foto"+str(fi)+"_up"+sfx, "")
                if u: opt["foto"+str(fi)+"_up"] = u
            return opt

        opt0 = _build_opt("_0")
        opt1 = _build_opt("_1")
        opciones = [opt0]
        if any(opt1.values()): opciones.append(opt1)

        # ── Guardar en Sheets ──
        data_dict = {
            "nombre":        nombre_completo,
            "fecha_entrada": ci,
            "fecha_salida":  co,
            "noites":        noites,
            "whatsapp":      wa_dest,
            "email":         email_cl,
            "personas":      personas,
            "estado":        "Manual",
            "notas_internas": notas_int,
            "opciones_json": json.dumps(opciones, ensure_ascii=False),
        }
        new_row = _sheets_append_row(data_dict)
        if not new_row:
            return Response("Error guardando en Sheets.", status=500, mimetype="text/plain")

        # ── Enviar WhatsApp al cliente ──
        sel_idxs = ",".join(str(i) for i in range(len(opciones)))
        prop_url  = SERVICE_URL + "/propuesta?row=" + str(new_row) + "&sel=" + sel_idxs
        nombre_corto = nombre.split()[0].title() if nombre else "!"
        msg = ("\U0001f30a Hola *" + nombre_corto + "*!\n\n"
               "Te preparamos una propuesta de alojamiento en Porto de Galinhas.\n\n"
               "\U0001f4cc Ver opciones y confirmar:\n" + prop_url)
        _evo_send_text(wa_dest, msg)

        return redirect("/dashboard?row=" + str(new_row))

    # ── GET ── Renderizar formulario ──────────────────────────────────────────
    def _opt_fields(sfx, label):
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
            for fi2 in range(1, 6)
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
            + frow(fi("preco_noche","Precio/noche R$","number","400",
                      "id='pnoche"+sfx+"' min='0' oninput='calcNP(\""+sfx+"\",\"base\")'"),
                   fi("n_noites","N\xb0 diarias","number","5",
                      "id='nnoites"+sfx+"' min='1' max='365' oninput='calcNP(\""+sfx+"\",\"base\")'"))
            + fi("taxa_limpeza","Tasa de limpieza R$","number","0",
                 "id='tlimpeza"+sfx+"' min='0' oninput='calcNP(\""+sfx+"\",\"base\")'")
            + "<div class='sep'></div>"
            + frow(fi("preco_sugerido","Total sugerido R$ <small style='color:#aaa'>(editable)</small>","number","0",
                      "id='psugerido"+sfx+"' class='inp-hl' min='0' step='1' oninput='calcNP(\""+sfx+"\",\"sug\")'"),
                   fi("margen_pct","Margen %","number","25",
                      "id='mpct"+sfx+"' min='0' oninput='calcNP(\""+sfx+"\",\"pct\")' step='1'"))
            + fi("ganancia_r","Ganancia R$","number","0",
                 "id='ganancia"+sfx+"' class='inp-green' min='0' step='1' oninput='calcNP(\""+sfx+"\",\"gan\")'")
            + "<input type='hidden' id='ptotal"+sfx+"' name='preco_total"+sfx+"' value=''>"
            + "<div class='sep'></div>"
            + frow(fi("reserva_anticipo","Anticipo %","number","50","min='0' max='100'"),
                   fi("saldo_plazo","Saldo antes del check-in","text","15 d\xedas"))
            + fi("cond_extra","Nota libre en condiciones","text","Incluye ropa de cama...")
            + fps_html
            + "<div class='sep'></div>"
            + fi("mapa_url","URL Google Maps","url","https://maps.google.com/...")
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
.wa-row{display:flex;gap:8px;align-items:flex-end}
.wa-sel{width:100px;flex-shrink:0}
.btn-add-opt{display:block;margin:0 12px 12px;border:2px dashed #CDC6C3;border-radius:12px;padding:14px;text-align:center;color:#87A286;font-size:14px;font-weight:600;cursor:pointer;background:#fff}
.btn-enviar{display:block;margin:0 12px;padding:16px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;width:calc(100%-24px);text-align:center}
.foto-row{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid #EDE9E3}
.foto-row:last-child{border-bottom:none}
.foto-num{width:18px;text-align:center;font-size:12px;color:#CDC6C3;font-weight:700;flex-shrink:0}
.upload-lbl{flex:1;background:#EDE9E3;border-radius:8px;padding:8px 12px;font-size:13px;cursor:pointer;color:#555}
.fstatus{font-size:12px;color:#87A286;min-width:24px;text-align:right}
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
        "<form method='POST' action='/nuevo-presupuesto'>\n"
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
        + _opt_fields("_0", "\U0001f3e0 Opci\xf3n 1")
        # ── Botón agregar opción 2 ──
        + "<div class='btn-add-opt' onclick='showOpt2()'>+ Agregar opci\xf3n 2 (opcional)</div>\n"
        # ── Opción 2 (oculta) ──
        + "<div id='opt2-block' style='"+opt2_display+"'>"
        + _opt_fields("_1", "\U0001f3e0 Opci\xf3n 2")
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
        "  if(diff>0){badge.textContent=diff+(diff===1?' noche':' noches');hid.value=diff;}\n"
        "  else{badge.textContent='—';hid.value='';}\n"
        "}\n"
        "function showOpt2(){document.getElementById('opt2-block').style.display='block';this.style.display='none';}\n"
        "function hideOpt2(){document.getElementById('opt2-block').style.display='none';"
        "document.querySelector('.btn-add-opt').style.display='block';}\n"
        "function calcNP(sfx,c){\n"
        "  const nc=parseFloat(document.getElementById('pnoche'+sfx).value)||0;\n"
        "  const nn=parseInt(document.getElementById('nnoites'+sfx).value)||1;\n"
        "  const lp=parseFloat(document.getElementById('tlimpeza'+sfx).value)||0;\n"
        "  const base=nc*nn;\n"
        "  if(c==='pct'){\n"
        "    const pct=parseFloat(document.getElementById('mpct'+sfx).value)||0;\n"
        "    const gan=Math.round(base*pct/100);\n"
        "    document.getElementById('ganancia'+sfx).value=gan;\n"
        "    document.getElementById('psugerido'+sfx).value=Math.round(base+gan+lp);\n"
        "  }else if(c==='sug'){\n"
        "    const sug=parseFloat(document.getElementById('psugerido'+sfx).value)||0;\n"
        "    const gan=Math.round(sug-base-lp);\n"
        "    document.getElementById('ganancia'+sfx).value=gan;\n"
        "    if(base>0)document.getElementById('mpct'+sfx).value=Math.round(gan/base*100);\n"
        "  }else if(c==='gan'){\n"
        "    const gan=parseFloat(document.getElementById('ganancia'+sfx).value)||0;\n"
        "    document.getElementById('psugerido'+sfx).value=Math.round(base+gan+lp);\n"
        "    if(base>0)document.getElementById('mpct'+sfx).value=Math.round(gan/base*100);\n"
        "  }else{\n"
        "    const pct=parseFloat(document.getElementById('mpct'+sfx).value)||25;\n"
        "    const gan=Math.round(base*pct/100);\n"
        "    document.getElementById('ganancia'+sfx).value=gan;\n"
        "    document.getElementById('psugerido'+sfx).value=Math.round(base+gan+lp);\n"
        "  }\n"
        "  document.getElementById('ptotal'+sfx).value=Math.round(base+lp);\n"
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
        "</script>\n</body>\n</html>"
    )
    return Response(html_np.encode('utf-8'), content_type="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
