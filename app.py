# -*- coding: utf-8 -*-
"""
Porto Flats - Servicio PDF
API Flask para generar presupuestos en PDF desde n8n
"""
import base64
import os
import tempfile
from flask import Flask, request, jsonify
from build_presupuesto import draw_presupuesto

app = Flask(__name__)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "porto-flats-pdf"})


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
            return jsonify({"error": f"Faltan campos: {missing}"}), 400

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
        filename = f"Presupuesto_PortoFlats_{data['numero']}.pdf"

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
