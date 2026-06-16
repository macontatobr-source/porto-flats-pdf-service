# -*- coding: utf-8 -*-
"""
Porto Flats â Servicio PDF + Mini-anuncio + Panel de RevisiÃ³n
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

# ââ Evolution API ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
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
            "caption": caption or "\U0001f4c4 Tu presupuesto Porto Flats. Â¡Estamos a disposiciÃ³n!"
        }, headers=_evo_headers(), timeout=45)
    except Exception as e:
        print(f"[EVO pdf error] {e}")

def _tinyurl(url):
    try:
        r = http.get(f"https://tinyurl.com/api-create.php?url={url}", timeout=10)
        return r.text.strip() or url
    except Exception:
        return url


# ââ /health âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "porto-flats-pdf"})


# ââ /propiedad ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/propiedad", methods=["GET"])
def propiedad_page():
    """
    Mini-anuncio de propiedad para el cliente.
    Params: t, d, c, b, h, a, p, l, m, o, ci, co, n, f1..f10
    """
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
    wa_num = WA_NUM

    fotos_list = [request.args.get(f"f{i}", "") for i in range(1, 11)]
    fotos_list = [f for f in fotos_list if f]

    gallery_html = ""
    if fotos_list:
        imgs = "".join(
            f'<img src="{f}" class="g-img" loading="lazy" onerror="this.style.display=\'none\'">'
            for f in fotos_list
        )
        gallery_html = f'<div class="gallery">{imgs}</div>'

    amenidades_list = [x.strip() for x in a.split(",") if x.strip()] if a else []
    amenidades_html = "".join(f'<span class="tag">{x}</span>' for x in amenidades_list)

    price_html = ""
    if p:
        price_html = f"""
        <div class="price-box">
          <div class="price-main">R$ {p}<span class="price-sub"> / noche</span></div>
          {'<div class="price-detail">+ R$ ' + lim + ' limpieza</div>' if lim else ''}
        </div>"""

    dates_html = ""
    if ci or co:
        noches_label = f"{n} noche{'s' if n != '1' else ''}" if n else ""
        dates_html = f"""
        <div class="dates-box">
          <div class="date-item">
            <span class="date-label">Check-in</span>
            <span class="date-val">{ci or "â"}</span>
          </div>
          <div class="date-sep">â</div>
          <div class="date-item">
            <span class="date-label">Check-out</span>
            <span class="date-val">{co or "â"}</span>
          </div>
          {'<div class="date-noches">' + noches_label + '</div>' if noches_label else ''}
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>{t} Â· Porto Flats</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}}
.header{{background:#87A286;padding:20px 16px;text-align:center}}
.logo{{color:#fff;font-size:20px;font-weight:300;letter-spacing:5px;text-transform:uppercase}}
.logo-sub{{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}}
.card{{background:#fff;border-radius:14px;margin:14px;padding:22px;box-shadow:0 2px 14px rgba(0,0,0,.07)}}
.badge{{display:inline-block;background:#E7D7C9;color:#3D3D3D;border-radius:20px;padding:4px 14px;font-size:12px;margin-bottom:12px}}
h1{{font-size:24px;font-weight:400;line-height:1.3}}
.location{{color:#87A286;font-size:13px;margin-top:6px}}
.features{{display:flex;gap:16px;margin-top:16px;flex-wrap:wrap}}
.feat{{display:flex;align-items:center;gap:6px;font-size:14px;color:#555}}
.feat-icon{{font-size:18px}}
.sec-title{{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1.5px;color:#87A286;margin-bottom:10px}}
.tags{{display:flex;flex-wrap:wrap;gap:8px}}
.tag{{background:#EDE9E3;border-radius:20px;padding:5px 13px;font-size:13px;color:#555}}
.price-box{{background:#EDE9E3;border-radius:10px;padding:16px;text-align:center}}
.price-main{{font-size:30px;font-weight:300}}
.price-sub{{font-size:14px;color:#888}}
.price-detail{{font-size:13px;color:#888;margin-top:4px}}
.dates-box{{background:#EDE9E3;border-radius:10px;padding:16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.date-item{{flex:1;min-width:90px}}
.date-label{{display:block;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#87A286;margin-bottom:3px}}
.date-val{{font-size:16px;font-weight:500}}
.date-sep{{font-size:20px;color:#CDC6C3}}
.date-noches{{width:100%;text-align:center;font-size:13px;color:#888;margin-top:6px}}
.btn{{display:block;text-align:center;padding:14px;border-radius:10px;font-size:15px;text-decoration:none;margin-top:10px;font-weight:500}}
.btn-green{{background:#87A286;color:#fff}}
.btn-light{{background:#EDE9E3;color:#3D3D3D}}
.footer{{text-align:center;padding:20px 16px 32px;color:#aaa;font-size:12px;line-height:1.7}}
.gallery{{display:flex;overflow-x:auto;gap:10px;padding:14px 14px 4px;scrollbar-width:none;-ms-overflow-style:none}}
.gallery::-webkit-scrollbar{{display:none}}
.g-img{{height:220px;min-width:300px;max-width:340px;object-fit:cover;border-radius:12px;flex-shrink:0;background:#CDC6C3}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">Porto Flats</div>
  <div class="logo-sub">Porto de Galinhas Â· Pernambuco Â· Brasil</div>
</div>
{gallery_html}
<div class="card">
  <div class="badge">\U0001f4cd {d}</div>
  <h1>{t}</h1>
  <div class="location">Porto de Galinhas Â· PE Â· Brasil</div>
  <div class="features">
    <div class="feat"><span class="feat-icon">\U0001f6cf</span>{c} cuarto{"s" if c != "1" else ""}</div>
    <div class="feat"><span class="feat-icon">\U0001f6bf</span>{b} baÃ±o{"s" if b != "1" else ""}</div>
    <div class="feat"><span class="feat-icon">\U0001f465</span>Hasta {h} personas</div>
  </div>
</div>
{"<div class='card'><div class='sec-title'>Precio por noche</div>" + price_html + "</div>" if p else ""}
{"<div class='card'><div class='sec-title'>Tus fechas</div>" + dates_html + "</div>" if (ci or co) else ""}
{"<div class='card'><div class='sec-title'>Incluye</div><div class='tags'>" + amenidades_html + "</div></div>" if amenidades_list else ""}
<div class="card">
  <div class="sec-title">Â¿Te interesa?</div>
  <a href="https://wa.me/{wa_num}?text=Hola!+Me+interesa+{t.replace(' ', '+')}" class="btn btn-green">\U0001f4ac Consultar por WhatsApp</a>
  {"<a href='" + m + "' class='btn btn-light' target='_blank'>\U0001f4cd Ver en Google Maps</a>" if m else ""}
  {"<a href='" + orig + "' class='btn btn-light' target='_blank'>\U0001f517 Ver anuncio completo</a>" if orig else ""}
</div>
<div class="footer">
  Porto Flats Â· Alquileres temporarios<br>
  Porto de Galinhas Â· Pernambuco Â· Brasil<br>
  <small>PÃ¡gina generada para tu consulta personal</small>
</div>
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


# ââ /generar-pdf âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
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

        # Detectar formato por presencia de total_brl
        use_v2 = "total_brl" in data

        if use_v2:
            required = ["numero", "cliente", "propiedad", "checkin", "checkout",
                        "noches", "total_brl"]
            missing = [f for f in required if f not in data]
            if missing:
                return jsonify({"error": f"Faltan: {missing}"}), 400
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
                return jsonify({"error": f"Faltan: {missing}"}), 400
            data.setdefault("ubicacion_desc", "Porto de Galinhas, PE, Brasil")
            data.setdefault("caracteristicas", [])
            data.setdefault("items_precio", [])
            data.setdefault("condiciones", [
                "Reserva confirma con anticipo del 50% del valor total.",
                "Saldo se abona 15 dÃ­as antes del check-in.",
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
        filename = f"Presupuesto_PortoFlats_{data['numero']}.pdf"

        return jsonify({"ok": True, "filename": filename,
                        "pdf_base64": pdf_b64, "size_bytes": len(pdf_bytes)})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ââ /generar-recibo âââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
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


# ââ /despachar ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/despachar", methods=["POST"])
def despachar():
    """
    Recibe datos editados del Panel, genera PDF y envÃ­a WhatsApp al cliente.
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
            return jsonify({"error": f"Faltan: {missing}"}), 400

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

        # ââ NÃºmero de presupuesto âââââââââââââââââââââââââââââ
        num_pres = data.get("numero_pres") or str(int(datetime.now().timestamp() * 1000))[-6:]
        fecha    = datetime.now().strftime("%d/%m/%Y")

        # ââ Mini-anuncio URL ââââââââââââââââââââââââââââââââââ
        BASE_URL = os.environ.get("SERVICE_URL", "https://pf-pdf-service.bg4ga1.easypanel.host")
        from urllib.parse import urlencode, quote

        def ep(v):
            return quote(str(v) if v is not None else "", safe="")

        amenidades = ", ".join(caracteristicas)
        diaria_desc = (total_brl - limpieza) / noches if noches else 0
        mini_params = {
            "t": propiedad, "d": distancia,
            "c": str(data.get("cuartos", 1)), "b": str(data.get("banos", 1)),
            "h": str(personas), "a": amenidades,
            "p": str(int(diaria_desc)), "l": str(int(limpieza)),
            "ci": checkin, "co": checkout, "n": str(noches),
        }
        mini_url = BASE_URL + "/propiedad?" + "&".join(f"{k}={ep(v)}" for k, v in mini_params.items())
        for i, foto_url in enumerate(fotos[:10], 1):
            mini_url += f"&f{i}={ep(foto_url)}"

        short_url = _tinyurl(mini_url)

        # ââ Mensaje WhatsApp ââââââââââââââââââââââââââââââââââ
        eW = "\U0001f44b"
        ePF = "\U0001f3d6"
        eCal = "\U0001f4c5"
        eMoon = "\U0001f319"
        eCasa = "\U0001f3e1"
        eMoney = "\U0001f4b0"
        eLink = "\U0001f517"
        DIV = "â" * 16

        nombre_corto = cliente.split()[0].title() if cliente else "cliente"
        feats_txt = "\n".join(f"â¢ {f}" for f in caracteristicas[:8])

        msg = f"{eW} Hola {nombre_corto}!\n\n"
        msg += f"Somos *Porto Flats* {ePF}\n"
        msg += f"Te enviamos tu presupuesto para Porto de Galinhas!\n\n"
        msg += f"{eCal} Check-in:  *{checkin}* Â· desde las {hora_ci}\n"
        msg += f"{eCal} Check-out: *{checkout}* Â· hasta las {hora_co}\n"
        msg += f"{eMoon} *{noches} noches*\n\n"
        msg += f"{DIV}\n\n"
        msg += f"{eCasa} *{propiedad}*\n"
        if distancia:
            msg += f"â {distancia}\n"
        if feats_txt:
            msg += feats_txt + "\n"
        msg += f"\n{eMoney} *Total: R$ {int(total_brl):,}*".replace(",", ".")
        msg += f"\nAnticipo para confirmar: {anticipo}% del total\n\n"
        msg += f"{DIV}\n\n"
        msg += f"{eLink} Ver fotos y detalles:\n{short_url}\n\n"
        if obs:
            msg += f"â¹ï¸ {obs}\n\n"
        msg += f"Cualquier consulta, estamos a disposiciÃ³n!\n"
        msg += f"*Porto Flats* {ePF}"

        # ââ Generar PDF âââââââââââââââââââââââââââââââââââââââ
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
        filename = f"Presupuesto_PortoFlats_{num_pres}.pdf"

        # ââ Enviar WhatsApp âââââââââââââââââââââââââââââââââââ
        _evo_send_text(numero_wa, msg)
        _evo_send_pdf(numero_wa, pdf_b64, filename)

        # ââ Notificar a Marcelo âââââââââââââââââââââââââââââââ
        confirmacion = (f"â Presupuesto enviado a *{nombre_corto}* ({numero_wa})\n"
                        f"Total: R$ {int(total_brl):,} Â· {noches} noches\n"
                        f"Propiedad: {propiedad}").replace(",", ".")
        _evo_send_text(MARCELO_NUM, confirmacion)

        # ââ Actualizar Sheets vÃ­a n8n (si estÃ¡ configurado) âââ
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


# ââ /panel ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/panel", methods=["GET"])
def panel():
    """
    Panel de RevisiÃ³n para que Marcelo edite y apruebe antes de enviar.
    ParÃ¡metro opcional: ?d=BASE64_JSON con datos pre-cargados desde WF01.
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
    if opt.get("quartos"):   feats.append(f"{opt['quartos']} cuarto(s)")
    if opt.get("banheiros"): feats.append(f"{opt['banheiros']} baÃ±o(s)")
    if opt.get("hospedes"):  feats.append(f"Hasta {opt['hospedes']} personas")
    if opt.get("amenidades"):
        feats += [x.strip() for x in str(opt["amenidades"]).split(",") if x.strip()]
    pre_caracteristicas = "\n".join(feats)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Panel de RevisiÃ³n Â· Porto Flats</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#EDE9E3;color:#3D3D3D;min-height:100vh}}
.header{{background:#87A286;padding:18px 16px;text-align:center}}
.logo{{color:#fff;font-size:18px;font-weight:300;letter-spacing:5px}}
.logo-sub{{color:rgba(255,255,255,.7);font-size:11px;letter-spacing:2px;margin-top:3px}}
.card{{background:#fff;border-radius:14px;margin:14px;padding:20px;box-shadow:0 2px 14px rgba(0,0,0,.07)}}
h2{{font-size:13px;font-weight:700;color:#87A286;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}}
.field{{margin-bottom:12px}}
label{{display:block;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.8px;color:#87A286;margin-bottom:4px}}
input,select,textarea{{width:100%;padding:10px 12px;border:1.5px solid #CDC6C3;border-radius:9px;font-size:15px;color:#3D3D3D;background:#fff;outline:none;font-family:inherit}}
input:focus,select:focus,textarea:focus{{border-color:#87A286}}
textarea{{resize:vertical;min-height:70px;line-height:1.5}}
.row{{display:flex;gap:10px}}
.row .field{{flex:1;min-width:0}}
.calc-box{{background:#EDE9E3;border-radius:10px;padding:14px;margin-bottom:12px}}
.calc-row{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;font-size:14px}}
.calc-row:last-child{{margin-bottom:0}}
.calc-label{{color:#555}}
.calc-val{{font-weight:600;color:#3D3D3D}}
.strike{{text-decoration:line-through;color:#999;font-weight:400}}
.calc-val.main{{color:#87A286;font-size:16px}}
.fotos-toggle{{display:flex;align-items:center;gap:8px;cursor:pointer;color:#87A286;font-size:13px;font-weight:600;margin-bottom:0}}
.fotos-toggle input[type=checkbox]{{width:18px;height:18px;cursor:pointer;accent-color:#87A286}}
#fotos-section{{display:none;margin-top:12px}}
#fotos-section.open{{display:block}}
.foto-field{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.foto-num{{font-size:12px;color:#999;width:20px;flex-shrink:0;text-align:right}}
.foto-field input{{margin-bottom:0}}
.btn-enviar{{display:block;width:100%;padding:16px;background:#87A286;color:#fff;border:none;border-radius:12px;font-size:17px;font-weight:700;cursor:pointer;margin:8px 0;letter-spacing:.5px}}
.btn-enviar:active{{background:#6d8b6c}}
.btn-enviar:disabled{{background:#CDC6C3;cursor:not-allowed}}
.msg-box{{text-align:center;padding:12px;font-size:14px;border-radius:10px;margin-top:8px;display:none}}
.msg-ok{{background:#e8f5e9;color:#2e7d32}}
.msg-err{{background:#ffebee;color:#c62828}}
.tip{{font-size:11px;color:#999;margin-top:4px}}
</style>
</head>
<body>
<div class="header">
  <div class="logo">PORTO FLATS</div>
  <div class="logo-sub">Panel de RevisiÃ³n</div>
</div>

<!-- CLIENTE -->
<div class="card">
  <h2>\U0001f464 Cliente</h2>
  <div class="field">
    <label>Nombre completo</label>
    <input id="cliente" value="{pre_cliente}" placeholder="MARIA DE LOS ANGELES ROLANDI" required>
  </div>
  <div class="field">
    <label>WhatsApp (con cÃ³digo de paÃ­s)</label>
    <input id="numero_wa" value="{pre_wa}" placeholder="5491112345678" required>
    <p class="tip">Sin +, sin espacios. Ej: 5491112345678</p>
  </div>
</div>

<!-- PROPIEDAD -->
<div class="card">
  <h2>\U0001f3e1 Propiedad</h2>
  <div class="field">
    <label>Nombre de la propiedad</label>
    <input id="propiedad" value="{pre_propiedad}" placeholder="Nixxus Premium" required>
  </div>
  <div class="row">
    <div class="field">
      <label>Distancia al mar</label>
      <input id="distancia" value="{pre_distancia}" placeholder="40m del mar">
    </div>
    <div class="field">
      <label>Personas</label>
      <input id="personas" type="number" min="1" max="20" value="{pre_personas or 2}">
    </div>
  </div>
  <div class="row">
    <div class="field">
      <label>Cuartos</label>
      <input id="cuartos" type="number" min="0" max="10" value="{pre_cuartos or 1}">
    </div>
    <div class="field">
      <label>BaÃ±os</label>
      <input id="banos" type="number" min="0" max="10" value="{pre_banos or 1}">
    </div>
  </div>
  <div class="field">
    <label>CaracterÃ­sticas (una por lÃ­nea)</label>
    <textarea id="caracteristicas" rows="5" placeholder="Estudio&#10;1 baÃ±o&#10;Aire acondicionado&#10;Wi-Fi&#10;Cocina equipada">{pre_caracteristicas}</textarea>
  </div>
</div>

<!-- FECHAS -->
<div class="card">
  <h2>\U0001f4c5 Fechas de la reserva</h2>
  <div class="row">
    <div class="field">
      <label>Check-in</label>
      <input id="checkin" value="{pre_checkin}" placeholder="25/04/2025" required>
    </div>
    <div class="field">
      <label>Check-out</label>
      <input id="checkout" value="{pre_checkout}" placeholder="05/05/2025" required>
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
    <input id="noches" type="number" min="1" value="{pre_noches or 1}" oninput="recalc()" required>
  </div>
</div>

<!-- PRECIOS -->
<div class="card">
  <h2>\U0001f4b0 Precios</h2>
  <div class="row">
    <div class="field">
      <label>Total R$ (editable)</label>
      <input id="total_brl" type="number" min="0" step="10" value="{pre_total}" oninput="recalc()" placeholder="1800" required>
    </div>
    <div class="field">
      <label>T.B. Limpieza R$</label>
      <input id="limpieza_brl" type="number" min="0" step="10" value="{pre_limpieza or 0}" oninput="recalc()" placeholder="200">
    </div>
  </div>
  <div class="calc-box">
    <div class="calc-row">
      <span class="calc-label">Diaria regular (tachada en PDF):</span>
      <span class="calc-val strike" id="diaria_reg">R$ â</span>
    </div>
    <div class="calc-row">
      <span class="calc-label">Diaria c/descuento:</span>
      <span class="calc-val" id="diaria_desc">R$ â</span>
    </div>
    <div class="calc-row" style="margin-top:8px;padding-top:8px;border-top:1px solid #CDC6C3">
      <span class="calc-label" style="font-weight:700">TOTAL:</span>
      <span class="calc-val main" id="total_disp">R$ â</span>
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
    <label>Traslado (dejar vacÃ­o si no aplica)</label>
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
    {''.join(f'<div class="foto-field"><span class="foto-num">{i}</span><input id="f{i}" type="url" placeholder="https://..."></div>' for i in range(1, 11))}
    <p class="tip">PegÃ¡ URLs de Google Drive, Wix Media, Dropbox, etc.</p>
  </div>
</div>

<!-- ENVIAR -->
<div class="card">
  <button class="btn-enviar" id="btn-enviar" onclick="enviar()">
    â Enviar al cliente
  </button>
  <div class="msg-box" id="msg-box"></div>
</div>

<!-- Campos ocultos de contexto -->
<input type="hidden" id="row_number"  value="{pre_row_number}">
<input type="hidden" id="rowTimestamp" value="{pre_timestamp}">

<script>
function recalc() {{
  const total  = parseFloat(document.getElementById('total_brl').value)  || 0;
  const limp   = parseFloat(document.getElementById('limpieza_brl').value) || 0;
  const noches = parseInt(document.getElementById('noches').value)        || 1;
  const dDesc  = noches > 0 ? (total - limp) / noches : 0;
  const dReg   = dDesc * 1.10;
  const fmt = v => 'R$ ' + Math.round(v).toLocaleString('es-AR');
  document.getElementById('diaria_reg').textContent  = fmt(dReg);
  document.getElementById('diaria_desc').textContent = fmt(dDesc);
  document.getElementById('total_disp').textContent  = fmt(total);
}}

function toggleFotos() {{
  const sec = document.getElementById('fotos-section');
  sec.classList.toggle('open', document.getElementById('fotos-chk').checked);
}}

async function enviar() {{
  const btn = document.getElementById('btn-enviar');
  const msgBox = document.getElementById('msg-box');
  btn.disabled = true;
  btn.textContent = 'Enviandoâ¦';
  msgBox.style.display = 'none';

  const feats = document.getElementById('caracteristicas').value
    .split('\\n').map(s => s.trim()).filter(Boolean);

  const fotos = [];
  for (let i = 1; i <= 10; i++) {{
    const v = (document.getElementById('f' + i) || {{}}).value || '';
    if (v.trim()) fotos.push(v.trim());
  }}

  const payload = {{
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
  }};

  // Validaciones bÃ¡sicas
  if (!payload.cliente || !payload.numero_wa || !payload.propiedad) {{
    showMsg('Falta nombre, WhatsApp o propiedad.', false);
    btn.disabled = false; btn.textContent = 'â Enviar al cliente'; return;
  }}
  if (payload.total_brl <= 0) {{
    showMsg('El total debe ser mayor a 0.', false);
    btn.disabled = false; btn.textContent = 'â Enviar al cliente'; return;
  }}

  try {{
    const r = await fetch('/despachar', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }});
    const j = await r.json();
    if (j.ok) {{
      showMsg('â Enviado! Presupuesto NÂ° ' + j.num_pres + ' â PDF + mensaje enviados al cliente.', true);
      btn.textContent = 'â Enviado';
    }} else {{
      showMsg('Error: ' + (j.error || 'desconocido'), false);
      btn.disabled = false; btn.textContent = 'â Enviar al cliente';
    }}
  }} catch(e) {{
    showMsg('Error de red: ' + e.message, false);
    btn.disabled = false; btn.textContent = 'â Enviar al cliente';
  }}
}}

function showMsg(text, ok) {{
  const b = document.getElementById('msg-box');
  b.textContent = text;
  b.className = 'msg-box ' + (ok ? 'msg-ok' : 'msg-err');
  b.style.display = 'block';
}}

// Calcular al cargar si hay datos
recalc();
</script>
</body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


# ââ /recibo-form ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
@app.route("/recibo-form", methods=["GET"])
def recibo_form():
    """Formulario web para generar recibo manualmente."""
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Generar Recibo Â· Porto Flats</title>
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
        <label>NÂ° Recibo</label>
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
        <option>SeÃ±al reserva</option>
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
    return Response(html, mimetype="text/html; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
