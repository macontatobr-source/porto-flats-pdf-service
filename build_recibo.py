# -*- coding: utf-8 -*-
"""
Generador de recibo de pago "ticket" - Porto Flats
Formato compacto tipo ticket termico (100 x 220 mm)
"""
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os

FONT_DIR = "/usr/share/fonts/truetype/lato/"
pdfmetrics.registerFont(TTFont("Lato-Light",    FONT_DIR + "Lato-Light.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Regular",  FONT_DIR + "Lato-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Bold",     FONT_DIR + "Lato-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Semibold", FONT_DIR + "Lato-Semibold.ttf"))

SAGE      = colors.HexColor("#87A286")
IVORY     = colors.HexColor("#EDE9E3")
STONE     = colors.HexColor("#CDC6C3")
TEXT_DARK = colors.HexColor("#3A3A3A")
GREY      = colors.HexColor("#8A8A8A")
WHITE     = colors.white

W   = 100 * mm
H   = 220 * mm
PAD =   8 * mm

MONEDA_SYM = {"BRL": "R$", "ARS": "AR$", "USD": "US$"}


def _hline(c, y, dashed=False):
    c.setStrokeColor(STONE)
    c.setLineWidth(0.5)
    c.setDash([2, 3] if dashed else [])
    c.line(PAD, y, W - PAD, y)
    c.setDash([])


def draw_recibo(filename, data):
    """
    data keys requeridos: numero, fecha_pago, cliente, propiedad, monto
    data keys opcionales: checkin, checkout, noches, concepto, moneda, forma_pago
    moneda: "BRL" (default) | "ARS" | "USD"
    """
    c = canvas.Canvas(filename, pagesize=(W, H))
    y = H - PAD

    # LOGO + MARCA
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "logo_seahorse_sage.png")
    lw = 7 * mm
    lh = lw * (305 / 151)
    c.drawImage(logo_path, W / 2 - lw / 2, y - lh,
                width=lw, height=lh, mask="auto")
    y -= lh + 4 * mm

    c.setFont("Lato-Light", 11)
    c.setFillColor(TEXT_DARK)
    c.drawCentredString(W / 2, y, "P O R T O   F L A T S")
    y -= 4.5 * mm
    c.setFont("Lato-Regular", 7)
    c.setFillColor(GREY)
    c.drawCentredString(W / 2, y, "Porto de Galinhas  .  PE  .  Brasil")
    y -= 6 * mm

    _hline(c, y)
    y -= 7 * mm

    # TITULO
    c.setFont("Lato-Bold", 10)
    c.setFillColor(SAGE)
    c.drawCentredString(W / 2, y, "COMPROBANTE DE PAGO")
    y -= 5 * mm
    c.setFont("Lato-Regular", 7.5)
    c.setFillColor(GREY)
    c.drawCentredString(W / 2, y,
        "N " + data["numero"] + "   .   " + data["fecha_pago"])
    y -= 7 * mm

    _hline(c, y)
    y -= 7 * mm

    # FILAS clave/valor
    def row(label, val, bold_val=False):
        nonlocal y
        if not val:
            return
        c.setFont("Lato-Regular", 7)
        c.setFillColor(GREY)
        c.drawString(PAD, y, label.upper())
        c.setFont("Lato-Bold" if bold_val else "Lato-Regular", 8)
        c.setFillColor(TEXT_DARK)
        c.drawRightString(W - PAD, y, str(val))
        y -= 5.5 * mm

    row("Cliente",    data["cliente"],   bold_val=True)
    row("Propiedad",  data["propiedad"])
    row("Check-in",   data.get("checkin", ""))
    row("Check-out",  data.get("checkout", ""))
    if data.get("noches"):
        row("Noches", str(data["noches"]))

    y -= 1 * mm
    _hline(c, y)
    y -= 7 * mm

    row("Concepto",      data.get("concepto", "Pago"))
    row("Forma de pago", data.get("forma_pago", "Transferencia"))

    y -= 2 * mm
    _hline(c, y)
    y -= 8 * mm

    # MONTO grande
    c.setFont("Lato-Regular", 7.5)
    c.setFillColor(GREY)
    c.drawCentredString(W / 2, y, "MONTO RECIBIDO")
    y -= 8 * mm

    sym = MONEDA_SYM.get(data.get("moneda", "BRL"), "R$")
    c.setFont("Lato-Bold", 20)
    c.setFillColor(TEXT_DARK)
    c.drawCentredString(W / 2, y, sym + " " + str(data["monto"]))
    y -= 9 * mm

    # CAJA VERDE
    box_h = 11 * mm
    c.setFillColor(SAGE)
    c.roundRect(PAD, y - box_h + 4 * mm, W - 2 * PAD, box_h,
                2 * mm, stroke=0, fill=1)
    c.setFont("Lato-Bold", 10)
    c.setFillColor(WHITE)
    c.drawCentredString(W / 2, y - 3 * mm, "PAGO RECIBIDO")
    y -= box_h + 7 * mm

    # FOOTER
    _hline(c, y, dashed=True)
    y -= 5 * mm
    c.setFont("Lato-Regular", 6.5)
    c.setFillColor(GREY)
    c.drawCentredString(W / 2, y, "NO VALIDO COMO COMPROBANTE FISCAL")
    y -= 4 * mm
    c.setFont("Lato-Light", 6)
    c.drawCentredString(W / 2, y, "M&A Empreendimentos Ltda. . CNPJ: 51.057.038/0001-31")

    c.save()


if __name__ == "__main__":
    sample = {
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
        "forma_pago": "Transferencia bancaria",
    }
    draw_recibo("Recibo_PortoFlats_demo.pdf", sample)
    print("OK - Recibo generado")
