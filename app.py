# -*- coding: utf-8 -*-
"""
Porto Flats - Servicio PDF + Mini-anuncio
API Flask para generar presupuestos en PDF y paginas de propiedad desde n8n
"""
import base64
import os
import tempfile
from flask import Flask, request, jsonify, Response
from build_presupuesto import draw_presupuesto
from build_recibo import draw_recibo

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "porto-flats-pdf"})


@app.route("/propiedad", methods=["GET"])
def propiedad_page():
    """
    Mini-anuncio de propiedad para enviar al cliente por WhatsApp.
    Params:
      t  = titulo/nombre
      d  = distancia al mar (ej: "40m del mar")
      c  = cuartos
      b  = banos
      h  = hospedes max
      a  = amenidades (comma-separated)
      p  = precio por noche en BRL
      l  = limpieza en BRL
      m  = link Google Maps
      o  = link anuncio original
      ci = check-in
      co = check-out
      n  = noches
    """
    t   = request.args.get("t", "Propiedad")
    d   = request.args.get("d", "Porto de Galinhas, PE")
    c   = request.args.get("c", "1")
    b   = request.args.get("b", "1")
    h   = request.args.get("h", "2")
    a   = request.args.get("a", "")
    p   = request.args.get("p", "")
    lim = request.args.get("l", "")
    m   = request.args.get("m", "")
    orig = request.args.get("o", "")
    ci  = request.args.get("ci", "")
    co  = request.args.get("co", "")
    n   = request.args.get("n", "")
    wa_num = os.environ.get("WA_NUMBER", "5511999999999")

    amenidades_list = [x.strip() for x in a.split(",") if x.strip()] if a else []
    amenidades_html = "".join(
        '<span class="tag">' + x + '</span>' for x in amenidades_list
    )

    price_html = ""
    if p:
        limpieza_part = ('<div class="price-detail">+ R$ ' + lim + ' limpieza</div>') if lim else ''
        price_html = (
            '<div class="price-box">'
            '<div class="price-main">R$ ' + p + '<span class="price-sub"> / noche</span></div>'
            + limpieza_part +
            '</div>'
        )

    dates_html = ""
    if ci or co:
        if n and n != "1":
            noches_label = n + " noches"
        elif n == "1":
            noches_label = "1 noche"
        else:
            noches_label = ""
        noches_div = ('<div class="date-noches">' + noches_label + '</div>') if noches_label else ''
        dates_html = (
            '<div class="dates-box">'
            '<div class="date-item">'
            '<span class="date-label">Check-in</span>'
            '<span class="date-val">' + (ci or "...") + '</span>'
            '</div>'
            '<div class="date-sep">to</div>'
            '<div class="date-item">'
            '<span class="date-label">Check-out</span>'
            '<span class="date-val">' + (co or "...") + '</span>'
            '</div>'
            + noches_div +
            '</div>'
        )

    cuartos_s = "s" if c != "1" else ""
    banos_s   = "s" if b != "1" else ""
    maps_btn  = ("<a href='" + m + "' class='btn btn-light' target='_blank'>Ver en Google Maps</a>") if m else ""
    orig_btn  = ("<a href='" + orig + "' class='btn btn-light' target='_blank'>Ver anuncio completo</a>") if orig else ""
    wa_text   = "Hola!+Me+interesa+" + t.replace(" ", "+")

    price_section  = ("<div class='card'><div class='sec-title'>Precio por noche</div>" + price_html + "</div>") if p else ""
    dates_section  = ("<div class='card'><div class='sec-title'>Tus fechas</div>" + dates_html + "</div>") if (ci or co) else ""
    ameni_section  = ("<div class='card'><div class='sec-title'>Incluye</div><div class='tags'>" + amenidades_html + "</div></div>") if amenidades_list else ""

    html = (
        "<!DOCTYPE html>"
        "<html lang='es'>"
        "<head>"
        "<meta charset='UTF-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1.0, maximum-scale=1.0'>"
        "<title>" + t + " . Porto Flats</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}"
        ".header{background:#87A286;padding:20px 16px;text-align:center}"
        ".logo{color:#fff;font-size:20px;font-weight:300;letter-spacing:5px;text-transform:uppercase}"
        ".logo-sub{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}"
        ".card{background:#fff;border-radius:14px;margin:14px;padding:22px;box-shadow:0 2px 14px rgba(0,0,0,.07)}"
        ".badge{display:inline-block;background:#E7D7C9;color:#3D3D3D;border-radius:20px;padding:4px 14px;font-size:12px;margin-bottom:12px}"
        "h1{font-size:24px;font-weight:400;line-height:1.3}"
        ".location{color:#87A286;font-size:13px;margin-top:6px}"
        ".features{display:flex;gap:16px;margin-top:16px;flex-wrap:wrap}"
        ".feat{display:flex;align-items:center;gap:6px;font-size:14px;color:#555}"
        ".feat-icon{font-size:18px}"
        ".sec-title{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;margin-bottom:10px}"
        ".tags{display:flex;flex-wrap:wrap;gap:8px}"
        ".tag{background:#EDE9E3;border-radius:20px;padding:5px 13px;font-size:13px;color:#555}"
        ".price-box{background:#EDE9E3;border-radius:10px;padding:16px;text-align:center}"
        ".price-main{font-size:30px;font-weight:300}"
        ".price-sub{font-size:14px;color:#888}"
        ".price-detail{font-size:13px;color:#888;margin-top:4px}"
        ".dates-box{background:#EDE9E3;border-radius:10px;padding:16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}"
        ".date-item{flex:1;min-width:90px}"
        ".date-label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#87A286;margin-bottom:3px}"
        ".date-val{font-size:16px;font-weight:500}"
        ".date-sep{font-size:20px;color:#CDC6C3}"
        ".date-noches{width:100%;text-align:center;font-size:13px;color:#888;margin-top:6px}"
        ".btn{display:block;text-align:center;padding:14px;border-radius:10px;font-size:15px;text-decoration:none;margin-top:10px;font-weight:500}"
        ".btn-green{background:#87A286;color:#fff}"
        ".btn-light{background:#EDE9E3;color:#3D3D3D}"
        ".footer{text-align:center;padding:20px 16px 32px;color:#aaa;font-size:12px;line-height:1.7}"
        "</style>"
        "</head>"
        "<body>"
        "<div class='header'>"
        "<div class='logo'>Porto Flats</div>"
        "<div class='logo-sub'>Porto de Galinhas . Pernambuco . Brasil</div>"
        "</div>"
        "<div class='card'>"
        "<div class='badge'>" + d + "</div>"
        "<h1>" + t + "</h1>"
        "<div class='location'>Porto de Galinhas . PE . Brasil</div>"
        "<div class='features'>"
        "<div class='feat'><span class='feat-icon'>bed</span>" + c + " cuarto" + cuartos_s + "</div>"
        "<div class='feat'><span class='feat-icon'>shower</span>" + b + " bano" + banos_s + "</div>"
        "<div class='feat'><span class='feat-icon'>people</span>Hasta " + h + " personas</div>"
        "<div class='feat'><span class='feat-icon'>wave</span>Primera linea</div>"
        "</div>"
        "</div>"
        + price_section
        + dates_section
        + ameni_section +
        "<div class='card'>"
        "<div class='sec-title'>Te interesa?</div>"
        "<a href='https://wa.me/" + wa_num + "?text=" + wa_text + "' class='btn btn-green'>Consultar por WhatsApp</a>"
        + maps_btn
        + orig_btn +
        "</div>"
        "<div class='footer'>"
        "Porto Flats . Alquileres temporarios<br>"
        "Porto de Galinhas . Pernambuco . Brasil<br>"
        "<small>Pagina generada para tu consulta personal</small>"
        "</div>"
        "</body>"
        "</html>"
    )

    return Response(html, mimetype="text/html; charset=utf-8")


@app.route("/generar-recibo", methods=["POST"])
def generar_recibo():
    """
    Body JSON:
    {
      "numero":     "REC-001",
      "fecha_pago": "15/06/2026",
      "cliente":    "Juan Perez",
      "propiedad":  "Nixxus Premium",
      "checkin":    "25/06/2026",
      "checkout":   "01/07/2026",
      "noches":     6,
      "concepto":   "Anticipo 50%",
      "monto":      "1.200",
      "moneda":     "BRL",
      "forma_pago": "Transferencia bancaria"
    }
    Devuelve: { "ok": true, "filename": "...", "pdf_base64": "...", "size_bytes": N }
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

        original_dir = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        draw_recibo(tmp_path, data)
        os.chdir(original_dir)

        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)

        pdf_b64  = base64.b64encode(pdf_bytes).decode("utf-8")
        filename = "Recibo_PortoFlats_" + data["numero"] + ".pdf"

        return jsonify({
            "ok":         True,
            "filename":   filename,
            "pdf_base64": pdf_b64,
            "size_bytes": len(pdf_bytes)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/generar-pdf", methods=["POST"])
def generar_pdf():
    """
    Body JSON esperado:
    {
      "numero": "002510",
      "fecha": "15/06/2026",
      "cliente": "Juan Perez",
      "propiedad": "Nixxus Premium",
      "ubicacion_desc": "A 40 m de la playa - Porto de Galinhas, PE, Brasil",
      "caracteristicas": ["Estudio", "1 bano", "Wi-Fi", ...],
      "checkin": "25/06/2026",
      "checkout": "01/07/2026",
      "noches": 6,
      "personas": 2,
      "items_precio": [["Diaria (x6 noches)", "R$ 375"], ["Limpieza", "R$ 150"]],
      "total": "R$ 2.400",
      "condiciones": ["50% de anticipo.", "..."],
      "ubicacion_link": "https://maps.app.goo.gl/..."
    }
    Devuelve: { "ok": true, "filename": "...", "pdf_base64": "...", "size_bytes": N }
    """
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "Body JSON requerido"}), 400

        required = ["numero", "fecha", "cliente", "propiedad",
                    "checkin", "checkout", "noches", "personas", "total"]
        missing = [f for f in required if f not in data]
        if missing:
            return jsonify({"error": "Faltan campos: " + str(missing)}), 400

        data.setdefault("ubicacion_desc", "Porto de Galinhas, PE, Brasil")
        data.setdefault("caracteristicas", [])
        data.setdefault("items_precio", [])
        data.setdefault("condiciones", [
            "Reserva confirma con anticipo del 50% del valor total.",
            "Saldo se abona 15 dias antes del check-in (temporada alta).",
            "Pago: transferencia bancaria (Brasil) o consultar en pesos ARG."
        ])
        data.setdefault("ubicacion_link", "https://portoflats-my-site-1.wixsite.com/porto-flats")

        data["items_precio"] = [tuple(i) for i in data["items_precio"]]

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        original_dir = os.getcwd()
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        draw_presupuesto(tmp_path, data)
        os.chdir(original_dir)

        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
        os.unlink(tmp_path)

        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        filename = "Presupuesto_PortoFlats_" + data["numero"] + ".pdf"

        return jsonify({
            "ok": True,
            "filename": filename,
            "pdf_base64": pdf_b64,
            "size_bytes": len(pdf_bytes)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
