"""Génère la fiche mémo A4 portrait pour le CSM pendant la démo prospect Neil.

Layout optimisé : bandeau prep/légende horizontal + 2 colonnes à hauteur variable.
Texte lisible (8pt body, 9pt titres).
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

W, H = A4
MARGIN = 8 * mm

# Neil brand colors
GREEN = HexColor("#3a786c")
GREEN_LIGHT = HexColor("#e8f5f1")
PURPLE = HexColor("#6b33b3")
PURPLE_LIGHT = HexColor("#f3edfb")
ORANGE = HexColor("#b37a2a")
ORANGE_LIGHT = HexColor("#fef6e8")
BLUE = HexColor("#3a6c96")
BLUE_LIGHT = HexColor("#eaf2f8")
RED = HexColor("#b33a3a")
RED_LIGHT = HexColor("#fde8e8")
FINANCE = HexColor("#2e7d52")
FINANCE_LIGHT = HexColor("#e8f5ec")
PINK = HexColor("#b33a6b")
PINK_LIGHT = HexColor("#fde8f5")
GRAY50 = HexColor("#fafafa")
GRAY200 = HexColor("#e5e5e5")
GRAY400 = HexColor("#a3a3a3")
GRAY500 = HexColor("#737373")
GRAY900 = HexColor("#171717")

# Sizing
LINE_H = 10
HEADER_H = 16
BLOCK_PAD_TOP = 8
BLOCK_PAD_BOTTOM = 5
COL_GAP = 5
FONT_BODY = 7.5
FONT_SMALL = 7
FONT_TITLE = 8.5
FONT_TIMING = 7


def rounded_rect(c, x, y, w, h, r, fill=None, stroke=None):
    c.saveState()
    if fill:
        c.setFillColor(fill)
    if stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(0.5)
    else:
        c.setStrokeColor(fill or white)
    p = c.beginPath()
    p.roundRect(x, y, w, h, r)
    p.close()
    if fill and stroke:
        c.drawPath(p, fill=1, stroke=1)
    elif fill:
        c.drawPath(p, fill=1, stroke=0)
    else:
        c.drawPath(p, fill=0, stroke=1)
    c.restoreState()


def calc_block_height(items):
    content_lines = 0
    empty_gaps = 0
    for item in items:
        if not item:
            empty_gaps += 1
        else:
            content_lines += 1
    return HEADER_H + BLOCK_PAD_TOP + content_lines * LINE_H + empty_gaps * 4 + BLOCK_PAD_BOTTOM


def draw_item(c, text_x, text_y, item, max_w):
    if item.startswith("WOW:"):
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", FONT_SMALL)
        c.drawString(text_x, text_y, "✨ " + item[4:].strip())
    elif item.startswith("SAY:"):
        c.setFillColor(PURPLE)
        c.setFont("Helvetica-Oblique", FONT_SMALL)
        text = item[4:].strip()
        if c.stringWidth(text, "Helvetica-Oblique", FONT_SMALL) > max_w - 14:
            text = text[:int((max_w - 14) / 3.5)] + "…"
        c.drawString(text_x + 2, text_y, "🎤 " + text)
    elif item.startswith("NAV:"):
        c.setFillColor(GRAY400)
        c.setFont("Helvetica", FONT_SMALL)
        c.drawString(text_x, text_y, "→ " + item[4:].strip())
    elif item.startswith("•"):
        c.setFillColor(GRAY900)
        c.setFont("Helvetica", FONT_BODY)
        c.drawString(text_x, text_y, item)
    else:
        c.setFillColor(GRAY500)
        c.setFont("Helvetica", FONT_BODY)
        c.drawString(text_x, text_y, item)
    c.setFont("Helvetica", FONT_BODY)


def draw_section_block(c, x, y, w, h, num, title, timing, color, color_light, items):
    # Background
    rounded_rect(c, x, y, w, h, 5, fill=white, stroke=GRAY200)

    # Header bar
    rounded_rect(c, x, y + h - HEADER_H, w, HEADER_H, 5, fill=color_light)
    c.setFillColor(color_light)
    c.rect(x, y + h - HEADER_H, w, 6, fill=1, stroke=0)
    c.setStrokeColor(GRAY200)
    c.setLineWidth(0.3)
    c.line(x, y + h - HEADER_H, x + w, y + h - HEADER_H)

    # Number circle
    cx_pos = x + 11
    cy_pos = y + h - HEADER_H / 2
    c.setFillColor(color)
    c.circle(cx_pos, cy_pos, 5.5, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(cx_pos, cy_pos - 2.8, str(num))

    # Title
    c.setFillColor(GRAY900)
    c.setFont("Helvetica-Bold", FONT_TITLE)
    c.drawString(x + 22, cy_pos - 3, title)

    # Timing badge
    c.setFont("Helvetica-Bold", FONT_TIMING)
    tw = c.stringWidth(timing, "Helvetica-Bold", FONT_TIMING) + 10
    rounded_rect(c, x + w - tw - 4, cy_pos - 5, tw, 10, 4, fill=color_light)
    c.setFillColor(color)
    c.drawString(x + w - tw, cy_pos - 2.5, timing)

    # Items
    text_x = x + 7
    text_y = y + h - HEADER_H - BLOCK_PAD_TOP
    max_w = w - 14

    for item in items:
        if text_y < y + 3:
            break
        if not item:
            text_y -= 4
            continue
        draw_item(c, text_x, text_y, item, max_w)
        text_y -= LINE_H
    c.setFillColor(GRAY900)


def build_pdf(output_path):
    c = canvas.Canvas(output_path, pagesize=A4)

    c.setFillColor(white)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # ── Top bar ──
    bar_h = 20
    rounded_rect(c, 0, H - bar_h, W, bar_h, 0, fill=GREEN)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN, H - 14, "NEIL — Fiche mémo démo prospect")
    c.setFont("Helvetica", 7.5)
    c.drawRightString(W - MARGIN, H - 12, "60 min · Dataset Poudlard · Visio")
    c.setFont("Helvetica", 6)
    c.drawRightString(W - MARGIN, H - 18.5, "Usage interne @neil.app")

    # ── Prep + Legend strip ──
    strip_top = H - bar_h - 3
    strip_h = 52
    strip_y = strip_top - strip_h
    usable_w = W - 2 * MARGIN

    # Prep block (left 55%)
    prep_w = usable_w * 0.57
    rounded_rect(c, MARGIN, strip_y, prep_w, strip_h, 5, fill=GRAY50, stroke=GRAY200)

    ph_h = 14
    rounded_rect(c, MARGIN, strip_y + strip_h - ph_h, prep_w, ph_h, 5, fill=GRAY200)
    c.setFillColor(GRAY200)
    c.rect(MARGIN, strip_y + strip_h - ph_h, prep_w, 5, fill=1, stroke=0)
    c.setStrokeColor(GRAY200)
    c.setLineWidth(0.3)
    c.line(MARGIN, strip_y + strip_h - ph_h, MARGIN + prep_w, strip_y + strip_h - ph_h)

    c.setFillColor(GRAY500)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(MARGIN + 6, strip_y + strip_h - ph_h / 2 - 2.8, "⚙  Préparation — avant la démo")

    prep_items = [
        "• Lancer le seeder Poudlard",
        "• Vérifier Harry dans Étudiants",
        "• Planning rempli avec séances",
        "• Notes et bulletins générés",
        "• Espace étudiant activable",
    ]
    ty = strip_y + strip_h - ph_h - 9
    c.setFont("Helvetica", 7)
    c.setFillColor(GRAY900)
    for item in prep_items:
        c.drawString(MARGIN + 7, ty, item)
        ty -= 7

    # Legend block (right 43%)
    leg_x = MARGIN + prep_w + COL_GAP
    leg_w = usable_w - prep_w - COL_GAP
    rounded_rect(c, leg_x, strip_y, leg_w, strip_h, 5, fill=GRAY50, stroke=GRAY200)

    rounded_rect(c, leg_x, strip_y + strip_h - ph_h, leg_w, ph_h, 5, fill=GRAY200)
    c.setFillColor(GRAY200)
    c.rect(leg_x, strip_y + strip_h - ph_h, leg_w, 5, fill=1, stroke=0)
    c.setStrokeColor(GRAY200)
    c.line(leg_x, strip_y + strip_h - ph_h, leg_x + leg_w, strip_y + strip_h - ph_h)

    c.setFillColor(GRAY500)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(leg_x + 6, strip_y + strip_h - ph_h / 2 - 2.8, "Légende")

    legend = [
        (GRAY400, "→  Navigation dans Neil"),
        (PURPLE, "🎤 Phrase à prononcer"),
        (GREEN, "✨ Effet WOW à souligner"),
        (GRAY900, "•  Action / point clé"),
    ]
    ty = strip_y + strip_h - ph_h - 10
    for clr, text in legend:
        c.setFillColor(clr)
        c.setFont("Helvetica", 7.5)
        c.drawString(leg_x + 7, ty, text)
        ty -= 8.5

    # ── Sections data ──
    sections = [
        {
            "num": "0", "title": "Accroche", "timing": "5 min",
            "color": GREEN, "color_light": GREEN_LIGHT,
            "items": [
                "SAY:Combien d'outils pour inscriptions, facturation, plannings, notes ?",
                "NAV:Accueil — laisser les 5 domaines visibles",
                "• Laisser répondre, noter les outils cités",
                "• Poser les 3 principes :",
                "  1. Neil centralise",
                "  2. Neil connecte",
                "  3. Neil accompagne la croissance",
                "• Glisser : API + webhooks si pertinent",
            ]
        },
        {
            "num": "1", "title": "Structure & Concepts", "timing": "10 min",
            "color": BLUE, "color_light": BLUE_LIGHT,
            "items": [
                "NAV:Configuration > Société / Établissements",
                "• Société = juridique (SIREN, IBAN)",
                "• École + Campus = pédagogique",
                "• Hiérarchie : École > Campus > Société",
                "",
                "• FORMULE = offre commerciale (prix)",
                "• FORMATION = programme pédago",
                "• La Formule fait le pont",
                "SAY:Même prog. vendu initiale ET apprentissage",
            ]
        },
        {
            "num": "2", "title": "Inscription Harry Potter", "timing": "15 min",
            "color": ORANGE, "color_light": ORANGE_LIGHT,
            "items": [
                "NAV:Secrétariat > Étudiants > Harry Potter",
                "• Fiche 360° : tous les onglets",
                "• Historique : Prépa > BUSE > ASPIC",
                "NAV:Inscriptions > + Nouvelle inscription",
                "• Master Magie Avancée (9 000€)",
                "• 4 étapes, réductions, échéancier",
                "• ⚠️ NE PAS créer de facture",
                "WOW:Inscription > échéancier > facture auto",
                "NAV:Espace Étudiant > Activer + 2e onglet",
                "WOW:Synchro temps réel portail étudiant",
            ]
        },
        {
            "num": "3", "title": "Pédagogie vivante", "timing": "18 min",
            "color": PURPLE, "color_light": PURPLE_LIGHT,
            "items": [
                "NAV:Pédagogie > Formations > Master Magie",
                "• Classes : ensembles (Maisons × 4)",
                "• UE / Modules : drag & drop, réutilisables",
                "• Module = quoi / Séance = quand + qui",
                "NAV:Module > Documents étudiants",
                "WOW:Vidéo encodée dans Neil, sans limite",
                "NAV:+ Ajouter séance (salle, visio, brouillon)",
                "• Intervenants → planning RH auto",
                "WOW:Brouillon > publier > planning d'un coup",
                "NAV:Évaluations > Relevés > Bulletins",
                "WOW:Import Excel > bulletins générés",
            ]
        },
        {
            "num": "4", "title": "Finance & RH", "timing": "7 min",
            "color": FINANCE, "color_light": FINANCE_LIGHT,
            "items": [
                "NAV:Comptabilité > Échéancier général",
                "• Filtrer par société, export DAF",
                "• Contrôle de gestion instantané",
                "SAY:Votre DAF ne passe plus 2h le lundi",
                "NAV:RH > Utilisateurs > Suivi heures",
                "• Heures vacataires auto depuis planning",
                "NAV:Dumbledore > Droits d'accès",
                "• Rôle + scope (5 dimensions)",
                "• Droits cumulables",
            ]
        },
        {
            "num": "5", "title": "Ressources", "timing": "2 min",
            "color": PINK, "color_light": PINK_LIGHT,
            "items": [
                "NAV:Pédagogie > Ressources partagées",
                "• Étiquettes, droits, versioning",
                "• Disponible pour tous les services",
            ]
        },
        {
            "num": "6", "title": "Conclusion & Qualification", "timing": "3 min",
            "color": RED, "color_light": RED_LIGHT,
            "items": [
                "• Quelle partie vous parle le plus ?",
                "• Combien d'étudiants / écoles ?",
                "• Quels outils aujourd'hui ?",
                "• Outils tiers à conserver ?",
                "• Qui d'autre doit voir Neil ?",
                "• Calendrier de décision ?",
                "",
                "• Curieux → 2e démo approfondie",
                "• Décideur → Workshop config",
                "• Embarquer → Présentation co-animée",
                "• Outils tiers → Démo API",
            ]
        },
    ]

    # ── Flowing 2-column layout ──
    content_top = strip_y - 4
    content_bottom = MARGIN
    col_w = (usable_w - COL_GAP) / 2

    col_y = [content_top, content_top]

    for sec in sections:
        h = calc_block_height(sec["items"])

        # Pick column with more remaining space
        if col_y[0] >= col_y[1]:
            col = 0
        else:
            col = 1

        if col_y[col] - h < content_bottom:
            other = 1 - col
            if col_y[other] - h >= content_bottom:
                col = other
            else:
                continue

        x = MARGIN + col * (col_w + COL_GAP)
        block_y = col_y[col] - h

        draw_section_block(
            c, x, block_y, col_w, h,
            sec["num"], sec["title"], sec["timing"],
            sec["color"], sec["color_light"], sec["items"]
        )

        col_y[col] = block_y - 4

    c.save()
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    build_pdf("/Users/adriensarlat/Claude/neil-demo/memo-demo-neil.pdf")
