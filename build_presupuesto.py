# -*- coding: utf-8 -*-
"""
Generador de PDF "Presupuesto" - Porto Flats
Minimalista, branding sage green / warm ivory
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- Fonts (Lato como sustituto de Montserrat/Raleway Light) ----------
FONT_DIR = "/usr/share/fonts/truetype/lato/"
pdfmetrics.registerFont(TTFont("Lato-Light", FONT_DIR + "Lato-Light.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Regular", FONT_DIR + "Lato-Regular.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Bold", FONT_DIR + "Lato-Bold.ttf"))
pdfmetrics.registerFont(TTFont("Lato-Semibold", FONT_DIR + "Lato-Semibold.ttf"))

# ---------- Paleta Porto Flats ----------
SAGE = colors.HexColor("#87A286")
IVORY = colors.HexColor("#EDE9E3")
SAND = colors.HexColor("#E7D7C9")
STONE = colors.HexColor("#CDC6C3")
DARK_ACCENT = colors.HexColor("#74A4B1")
TEXT_DARK = colors.HexColor("#3A3A3A")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


def draw_presupuesto(filename, data):
    c = canvas.Canvas(filename, pagesize=A4)

    # ============ HEADER ============
    # Logo (seahorse) + wordmark
    logo_path = "logo_seahorse_sage.png"
    logo_w = 9 * mm
    logo_h = logo_w * (305 / 151)
    c.drawImage(logo_path, MARGIN, PAGE_H - MARGIN - logo_h + 2*mm,
                width=logo_w, height=logo_h, mask='auto')

    c.setFont("Lato-Light", 17)
    c.setFillColor(TEXT_DARK)
    c.drawString(MARGIN + logo_w + 4*mm, PAGE_H - MARGIN - 5*mm, "P O R T O")
    c.setFont("Lato-Semibold", 17)
    c.drawString(MARGIN + logo_w + 4*mm, PAGE_H - MARGIN - 11*mm, "F L A T S")

    # Presupuesto N° + fecha (derecha)
    c.setFont("Lato-Regular", 9)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 2*mm, "PRESUPUESTO")
    c.setFont("Lato-Bold", 12)
    c.setFillColor(TEXT_DARK)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 7*mm, f"N° {data['numero']}")
    c.setFont("Lato-Regular", 9)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 12*mm, f"Fecha: {data['fecha']}")

    # Linea separadora
    y = PAGE_H - MARGIN - 18*mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.6)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    # ============ DATOS CLIENTE ============
    y -= 9*mm
    c.setFont("Lato-Regular", 8.5)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawString(MARGIN, y, "PREPARADO PARA")
    y -= 5.5*mm
    c.setFont("Lato-Bold", 12)
    c.setFillColor(TEXT_DARK)
    c.drawString(MARGIN, y, data['cliente'])

    # ============ PROPIEDAD - tarjeta ivory ============
    y -= 11*mm
    card_h = 38*mm
    c.setFillColor(IVORY)
    c.roundRect(MARGIN, y - card_h, PAGE_W - 2*MARGIN, card_h, 3*mm, stroke=0, fill=1)

    inner_x = MARGIN + 7*mm
    ty = y - 8*mm
    c.setFont("Lato-Bold", 13)
    c.setFillColor(TEXT_DARK)
    c.drawString(inner_x, ty, data['propiedad'])

    ty -= 6*mm
    c.setFont("Lato-Regular", 9.5)
    c.setFillColor(colors.HexColor("#5C5C5C"))
    c.drawString(inner_x, ty, data['ubicacion_desc'])

    # Caracteristicas en 2 columnas
    ty -= 7*mm
    col1_x = inner_x
    col2_x = inner_x + (PAGE_W - 2*MARGIN - 14*mm) / 2
    for i, feat in enumerate(data['caracteristicas']):
        col_x = col1_x if i % 2 == 0 else col2_x
        row = i // 2
        fy = ty - row * 5.2*mm
        c.setFillColor(SAGE)
        c.circle(col_x + 1*mm, fy + 1.6*mm, 1*mm, stroke=0, fill=1)
        c.setFont("Lato-Regular", 9)
        c.setFillColor(TEXT_DARK)
        c.drawString(col_x + 4*mm, fy, feat)

    y -= card_h

    # ============ DETALLE DE LA RESERVA ============
    y -= 11*mm
    c.setFont("Lato-Semibold", 10)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "DETALLE DE LA RESERVA")
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.6)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    y -= 7*mm
    reserva_items = [
        ("Check-in", data['checkin']),
        ("Check-out", data['checkout']),
        ("Noches", str(data['noches'])),
        ("Personas", str(data['personas'])),
    ]
    col_w = (PAGE_W - 2*MARGIN) / 4
    for i, (label, val) in enumerate(reserva_items):
        x = MARGIN + i * col_w
        c.setFont("Lato-Regular", 8)
        c.setFillColor(colors.HexColor("#8A8A8A"))
        c.drawString(x, y, label.upper())
        c.setFont("Lato-Bold", 11)
        c.setFillColor(TEXT_DARK)
        c.drawString(x, y - 5.5*mm, val)

    # ============ DETALLE DE PRECIOS (tabla) ============
    y -= 16*mm
    c.setFont("Lato-Semibold", 10)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "DETALLE DE PRECIOS")
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    y -= 8*mm
    table_w = PAGE_W - 2*MARGIN
    desc_x = MARGIN
    val_x = PAGE_W - MARGIN

    c.setFont("Lato-Regular", 9.5)
    for label, val in data['items_precio']:
        c.setFillColor(TEXT_DARK)
        c.drawString(desc_x, y, label)
        c.setFillColor(colors.HexColor("#5C5C5C"))
        c.drawRightString(val_x, y, val)
        y -= 6.5*mm

    # Linea antes del total
    y -= 1*mm
    c.setStrokeColor(STONE)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    # ============ TOTAL ============
    y -= 12*mm
    total_h = 16*mm
    c.setFillColor(SAGE)
    c.roundRect(MARGIN, y - total_h + 4*mm, PAGE_W - 2*MARGIN, total_h, 2.5*mm, stroke=0, fill=1)
    c.setFont("Lato-Regular", 10)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 6*mm, y - 4*mm, "VALOR TOTAL")
    c.setFont("Lato-Bold", 16)
    c.drawRightString(PAGE_W - MARGIN - 6*mm, y - 5*mm, data['total'])

    # ============ FORMA DE PAGO / CONDICIONES ============
    y -= total_h + 9*mm
    c.setFont("Lato-Semibold", 10)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "CONDICIONES DE PAGO")
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    y -= 6*mm
    c.setFont("Lato-Regular", 8.5)
    c.setFillColor(TEXT_DARK)
    for line in data['condiciones']:
        # bullet
        c.setFillColor(SAGE)
        c.circle(MARGIN + 1*mm, y + 1.6*mm, 0.8*mm, stroke=0, fill=1)
        c.setFillColor(TEXT_DARK)
        c.drawString(MARGIN + 4*mm, y, line)
        y -= 5*mm

    # ============ UBICACION ============
    y -= 4*mm
    c.setFont("Lato-Semibold", 9)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "UBICACION")
    y -= 5.5*mm
    c.setFont("Lato-Regular", 9)
    c.setFillColor(DARK_ACCENT)
    c.drawString(MARGIN, y, data['ubicacion_link'])
    c.linkURL(data['ubicacion_link'], (MARGIN, y - 1*mm, MARGIN + 120*mm, y + 4*mm), relative=0)

    # ============ FOOTER ============
    foot_y = 14 * mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.6)
    c.line(MARGIN, foot_y + 8*mm, PAGE_W - MARGIN, foot_y + 8*mm)

    c.setFont("Lato-Light", 9)
    c.setFillColor(SAGE)
    c.drawCentredString(PAGE_W/2, foot_y + 3*mm, "Tu lugar en Porto de Galinhas.")

    c.setFont("Lato-Regular", 7)
    c.setFillColor(colors.HexColor("#A0A0A0"))
    c.drawCentredString(PAGE_W/2, foot_y - 2*mm, "M&A Empreendimentos Ltda. / CNPJ: 51.057.038/0001-31")

    c.save()


def _fmt_brl(v):
    """Formatea número como R$ X.XXX"""
    try:
        return f"R$ {int(round(float(v))):,}".replace(",", ".")
    except Exception:
        return f"R$ {v}"


def _draw_strike(c, x, y, text, font, size, color, right=False):
    """Dibuja texto con tachado (strikethrough)."""
    c.setFont(font, size)
    c.setFillColor(color)
    if right:
        c.drawRightString(x, y, text)
        w = c.stringWidth(text, font, size)
        x0 = x - w
    else:
        c.drawString(x, y, text)
        x0 = x
        w = c.stringWidth(text, font, size)
    mid_y = y + size * 0.30
    c.setStrokeColor(color)
    c.setLineWidth(0.7)
    c.line(x0, mid_y, x0 + w, mid_y)


def draw_presupuesto_v2(filename, data):
    """
    Presupuesto Porto Flats — formato v2.
    data keys:
      numero, fecha, cliente, propiedad,
      distancia (opt), personas, checkin, hora_checkin, checkout, hora_checkout,
      noches, caracteristicas (list[str]),
      total_brl (number), limpieza_brl (number),
      cochera (str, opt), traslado (str, opt),
      forma_pago, anticipo_pct (int, default 50),
      observaciones (str, opt), url_link (str, opt)
    Calcula automáticamente:
      diaria_descuento = (total_brl - limpieza_brl) / noches
      diaria_regular   = diaria_descuento * 1.10  (tachada)
    """
    noches = max(int(data.get("noches", 1) or 1), 1)
    total_brl    = float(data.get("total_brl", 0) or 0)
    limpieza_brl = float(data.get("limpieza_brl", 0) or 0)
    diaria_desc  = (total_brl - limpieza_brl) / noches
    diaria_reg   = diaria_desc * 1.10
    anticipo_pct = int(data.get("anticipo_pct", 50) or 50)

    STONE_LIGHT = colors.HexColor("#E8E4E0")

    c = canvas.Canvas(filename, pagesize=A4)

    # ── HEADER ────────────────────────────────────────────────
    logo_path = "logo_seahorse_sage.png"
    logo_w = 9 * mm
    logo_h = logo_w * (305 / 151)
    c.drawImage(logo_path, MARGIN, PAGE_H - MARGIN - logo_h + 2*mm,
                width=logo_w, height=logo_h, mask="auto")

    c.setFont("Lato-Light", 17)
    c.setFillColor(TEXT_DARK)
    c.drawString(MARGIN + logo_w + 4*mm, PAGE_H - MARGIN - 5*mm, "P O R T O")
    c.setFont("Lato-Semibold", 17)
    c.drawString(MARGIN + logo_w + 4*mm, PAGE_H - MARGIN - 11*mm, "F L A T S")

    c.setFont("Lato-Regular", 8.5)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 2*mm, "PRESUPUESTO")
    c.setFont("Lato-Bold", 12)
    c.setFillColor(TEXT_DARK)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 7*mm, f"N° {data['numero']}")
    c.setFont("Lato-Regular", 8.5)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - MARGIN - 12*mm, f"Fecha: {data['fecha']}")

    y = PAGE_H - MARGIN - 18*mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.6)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)

    # ── PREPARADO PARA ────────────────────────────────────────
    y -= 8*mm
    c.setFont("Lato-Regular", 8)
    c.setFillColor(colors.HexColor("#8A8A8A"))
    c.drawString(MARGIN, y, "PREPARADO PARA")
    y -= 5.5*mm
    c.setFont("Lato-Bold", 12)
    c.setFillColor(TEXT_DARK)
    c.drawString(MARGIN, y, data["cliente"].upper())

    # ── TARJETA PROPIEDAD ─────────────────────────────────────
    y -= 10*mm
    feats = data.get("caracteristicas", [])
    n_rows = max(1, (len(feats) + 1) // 2)
    card_h = 17*mm + n_rows * 5*mm
    c.setFillColor(IVORY)
    c.roundRect(MARGIN, y - card_h, PAGE_W - 2*MARGIN, card_h, 3*mm, stroke=0, fill=1)

    ix = MARGIN + 6*mm
    ty = y - 7*mm
    c.setFont("Lato-Bold", 12)
    c.setFillColor(TEXT_DARK)
    c.drawString(ix, ty, data["propiedad"])

    ty -= 5.5*mm
    c.setFont("Lato-Regular", 8.5)
    c.setFillColor(SAGE)
    dist = data.get("distancia", "Porto de Galinhas, PE, Brasil")
    c.drawString(ix, ty, dist + "  ·  Porto de Galinhas, PE, Brasil")

    ty -= 6*mm
    col2_x = ix + (PAGE_W - 2*MARGIN - 12*mm) / 2
    for i, feat in enumerate(feats):
        col_x = ix if i % 2 == 0 else col2_x
        fy = ty - (i // 2) * 5*mm
        c.setFillColor(SAGE)
        c.circle(col_x + 1*mm, fy + 1.5*mm, 0.9*mm, stroke=0, fill=1)
        c.setFont("Lato-Regular", 8.5)
        c.setFillColor(TEXT_DARK)
        c.drawString(col_x + 3.5*mm, fy, feat)

    y -= card_h + 8*mm

    # ── FECHAS / RESERVA ──────────────────────────────────────
    c.setFont("Lato-Semibold", 9)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "DETALLE DE LA RESERVA")
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.5)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 7*mm

    cols = [
        ("CHECK-IN",  data.get("checkin", ""), data.get("hora_checkin", "14:00 hs")),
        ("CHECK-OUT", data.get("checkout", ""), data.get("hora_checkout", "12:00 hs")),
        ("NOCHES",    str(noches), ""),
        ("PERSONAS",  str(data.get("personas", "")), ""),
    ]
    col_w = (PAGE_W - 2*MARGIN) / 4
    for i, (lbl, v1, v2) in enumerate(cols):
        cx = MARGIN + i * col_w
        c.setFont("Lato-Regular", 7.5)
        c.setFillColor(colors.HexColor("#8A8A8A"))
        c.drawString(cx, y, lbl)
        c.setFont("Lato-Bold", 10)
        c.setFillColor(TEXT_DARK)
        c.drawString(cx, y - 5*mm, v1)
        if v2:
            c.setFont("Lato-Regular", 8)
            c.setFillColor(colors.HexColor("#8A8A8A"))
            c.drawString(cx, y - 9.5*mm, v2)

    y -= 17*mm

    # ── PRECIOS ───────────────────────────────────────────────
    c.setFont("Lato-Semibold", 9)
    c.setFillColor(SAGE)
    c.drawString(MARGIN, y, "DETALLE DE PRECIOS")
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.line(MARGIN, y, PAGE_W - MARGIN, y)
    y -= 7*mm

    GRAY = colors.HexColor("#A0A0A0")
    RIGHT = PAGE_W - MARGIN

    # Diaria regular — tachada en gris
    c.setFont("Lato-Regular", 9.5)
    c.setFillColor(GRAY)
    c.drawString(MARGIN, y, "Diaria regular:")
    _draw_strike(c, RIGHT, y, _fmt_brl(diaria_reg), "Lato-Regular", 9.5, GRAY, right=True)
    y -= 6.5*mm

    # Diaria c/descuento — normal
    c.setFont("Lato-Regular", 9.5)
    c.setFillColor(TEXT_DARK)
    c.drawString(MARGIN, y, "Diaria c/descuento:")
    c.drawRightString(RIGHT, y, _fmt_brl(diaria_desc))
    y -= 6.5*mm

    # Limpieza
    c.drawString(MARGIN, y, "T.B. Limpieza:")
    c.drawRightString(RIGHT, y, _fmt_brl(limpieza_brl))
    y -= 6.5*mm

    # Cochera
    cochera = data.get("cochera", "No incluye") or "No incluye"
    c.drawString(MARGIN, y, "Cochera:")
    c.drawRightString(RIGHT, y, cochera)
    y -= 6.5*mm

    # Traslado (opcional)
    traslado = (data.get("traslado", "") or "").strip()
    if traslado:
        c.drawString(MARGIN, y, "Traslado:")
        c.drawRightString(RIGHT, y, traslado)
        y -= 6.5*mm

    # Línea + TOTAL
    y -= 2*mm
    c.setStrokeColor(STONE)
    c.line(MARGIN, y, RIGHT, y)

    y -= 11*mm
    total_box_h = 14*mm
    c.setFillColor(SAGE)
    c.roundRect(MARGIN, y - total_box_h + 4*mm, PAGE_W - 2*MARGIN, total_box_h,
                2.5*mm, stroke=0, fill=1)
    c.setFont("Lato-Regular", 10)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 6*mm, y - 4*mm, "VALOR TOTAL")
    c.setFont("Lato-Bold", 16)
    c.drawRightString(RIGHT - 6*mm, y - 5*mm, _fmt_brl(total_brl))

    # ── CONDICIONES ───────────────────────────────────────────
    y -= total_box_h + 6*mm
    c.setFont("Lato-Regular", 9)
    c.setFillColor(TEXT_DARK)

    forma_pago = data.get("forma_pago", "Transferencia bancaria") or "Transferencia bancaria"
    c.drawString(MARGIN, y, f"Forma de pago: {forma_pago}")
    y -= 5.5*mm
    c.drawString(MARGIN, y, "Consultar para pagos en Pesos Arg.")
    y -= 5.5*mm
    c.drawString(MARGIN, y,
                 f"La reserva se confirma con un anticipo del {anticipo_pct}% del importe total.")
    y -= 5.5*mm

    # Observaciones
    obs = (data.get("observaciones", "") or "").strip()
    if obs:
        y -= 3*mm
        c.setFont("Lato-Semibold", 9)
        c.setFillColor(SAGE)
        c.drawString(MARGIN, y, "OBSERVACIONES")
        y -= 5*mm
        c.setFont("Lato-Regular", 8.5)
        c.setFillColor(TEXT_DARK)
        # Wrap long text at 80 chars approx
        import textwrap
        for line in textwrap.wrap(obs, width=85):
            c.drawString(MARGIN, y, line)
            y -= 4.5*mm

    # URL link
    url_link = (data.get("url_link", "") or "").strip()
    if url_link:
        y -= 4*mm
        c.setFont("Lato-Semibold", 9)
        c.setFillColor(SAGE)
        c.drawString(MARGIN, y, "VER PROPIEDAD:")
        y -= 5.5*mm
        c.setFont("Lato-Regular", 8.5)
        c.setFillColor(DARK_ACCENT)
        c.drawString(MARGIN, y, url_link)
        c.linkURL(url_link, (MARGIN, y - 1*mm, MARGIN + 120*mm, y + 4*mm), relative=0)

    # ── FOOTER ────────────────────────────────────────────────
    foot_y = 14*mm
    c.setStrokeColor(STONE)
    c.setLineWidth(0.6)
    c.line(MARGIN, foot_y + 8*mm, PAGE_W - MARGIN, foot_y + 8*mm)
    c.setFont("Lato-Light", 9)
    c.setFillColor(SAGE)
    c.drawCentredString(PAGE_W/2, foot_y + 3*mm, "Tu lugar en Porto de Galinhas.")
    c.setFont("Lato-Regular", 7)
    c.setFillColor(colors.HexColor("#A0A0A0"))
    c.drawCentredString(PAGE_W/2, foot_y - 2*mm,
                        "M&A Empreendimentos Ltda. / CNPJ: 51.057.038/0001-31")

    c.save()


if __name__ == "__main__":
    sample_data = {
        "numero": "002510",
        "fecha": "15/06/2026",
        "cliente": "Juan Perez",
        "propiedad": "Nixxus Premium",
        "ubicacion_desc": "A 40 m de la playa - Porto de Galinhas, PE, Brasil",
        "caracteristicas": [
            "Estudio - 1 dormitorio",
            "1 baño",
            "Cocina con heladera y microondas",
            "Aire acondicionado",
            "Ropa de cama y toallas incluidas",
            "Wi-Fi",
        ],
        "checkin": "25/03/2026",
        "checkout": "31/03/2026",
        "noches": 6,
        "personas": 2,
        "items_precio": [
            ("Diaria regular", "R$ 462"),
            ("Diaria con descuento (x6 noches)", "R$ 375"),
            ("Limpieza final", "R$ 150"),
            ("Cochera", "No incluye"),
        ],
        "total": "R$ 2.400",
        "condiciones": [
            "Forma de pago: transferencia bancaria (Brasil) - consultar pago en pesos ARG.",
            "La reserva se confirma con un anticipo del 50% del valor total.",
            "Temporada alta: el saldo se abona 15 dias antes del check-in.",
        ],
        "ubicacion_link": "https://maps.app.goo.gl/2yoVcbySKRrbAPrm8",
    }
    draw_presupuesto("Presupuesto_PortoFlats_demo.pdf", sample_data)
    print("OK")
