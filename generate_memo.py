"""Génère la fiche mémo A4 portrait pour le CSM pendant la démo prospect Neil."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white
from reportlab.pdfgen import canvas

W, H = A4  # 210 x 297 mm portrait
MARGIN = 10 * mm

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


def draw_section_block(c, x, y, w, h, num, title, timing, color, color_light, items):
    # Background
    rounded_rect(c, x, y, w, h, 4, fill=white, stroke=GRAY200)

    # Header bar
    header_h = 14
    rounded_rect(c, x, y + h - header_h, w, header_h, 4, fill=color_light)
    c.setFillColor(color_light)
    c.rect(x, y + h - header_h, w, 6, fill=1, stroke=0)
    c.setStrokeColor(GRAY200)
    c.setLineWidth(0.3)
    c.line(x, y + h - header_h, x + w, y + h - header_h)

    # Section number circle
    circle_r = 5
    cx_pos = x + 10
    cy_pos = y + h - header_h / 2
    c.setFillColor(color)
    c.circle(cx_pos, cy_pos, circle_r, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(cx_pos, cy_pos - 2.5, str(num))

    # Title
    c.setFillColor(GRAY900)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x + 20, cy_pos - 2.5, title)

    # Timing badge
    c.setFillColor(color)
    c.setFont("Helvetica-Bold", 6)
    tw = c.stringWidth(timing, "Helvetica-Bold", 6) + 8
    rounded_rect(c, x + w - tw - 4, cy_pos - 4.5, tw, 9, 3, fill=color_light)
    c.setFillColor(color)
    c.drawString(x + w - tw, cy_pos - 2.5, timing)

    # Items
    text_x = x + 6
    text_y = y + h - header_h - 9
    c.setFont("Helvetica", 6)
    line_h = 7.5

    for item in items:
        if text_y < y + 3:
            break
        if not item:
            text_y -= 3
            continue
        if item.startswith("WOW:"):
            c.setFillColor(GREEN)
            c.setFont("Helvetica-Bold", 5.5)
            c.drawString(text_x, text_y, "✨ " + item[4:].strip())
            c.setFont("Helvetica", 6)
        elif item.startswith("SAY:"):
            c.setFillColor(PURPLE)
            c.setFont("Helvetica-Oblique", 5.5)
            text = item[4:].strip()
            max_w = w - 12
            if c.stringWidth(text, "Helvetica-Oblique", 5.5) > max_w:
                text = text[:int(max_w / 3.2)] + "…"
            c.drawString(text_x + 2, text_y, "🎤 " + text)
            c.setFont("Helvetica", 6)
        elif item.startswith("NAV:"):
            c.setFillColor(GRAY400)
            c.setFont("Helvetica", 5.5)
            c.drawString(text_x, text_y, "→ " + item[4:].strip())
            c.setFont("Helvetica", 6)
        elif item.startswith("•"):
            c.setFillColor(GRAY900)
            c.drawString(text_x, text_y, item)
        else:
            c.setFillColor(GRAY500)
            c.drawString(text_x, text_y, item)
        text_y -= line_h
    c.setFillColor(GRAY900)


def build_pdf(output_path):
    c = canvas.Canvas(output_path, pagesize=A4)

    # Background
    c.setFillColor(white)
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Top bar
    bar_h = 20
    rounded_rect(c, 0, H - bar_h, W, bar_h, 0, fill=GREEN)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(MARGIN, H - 14, "NEIL — Fiche mémo démo prospect")
    c.setFont("Helvetica", 7)
    c.drawRightString(W - MARGIN, H - 11, "60 min · Dataset Poudlard · Visio")
    c.setFont("Helvetica", 5.5)
    c.drawRightString(W - MARGIN, H - 18, "Usage interne @neil.app")

    # Sections data
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
                "• FORMATION = programme pédago (UE, modules)",
                "• La Formule fait le pont",
                "SAY:Même programme vendu en initiale ET apprentissage",
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
                "• Module = quoi / Séance = quand + pour qui",
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
            "num": "6", "title": "Conclusion", "timing": "3 min",
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

    # Layout: 2 columns, 4 rows
    content_top = H - bar_h - 5
    content_bottom = MARGIN - 2
    content_h = content_top - content_bottom

    cols = 2
    rows = 4
    col_gap = 5
    row_gap = 4
    usable_w = W - 2 * MARGIN
    col_w = (usable_w - (cols - 1) * col_gap) / cols
    row_h = (content_h - (rows - 1) * row_gap) / rows

    positions = []
    for row in range(rows):
        for col in range(cols):
            x = MARGIN + col * (col_w + col_gap)
            y = content_top - (row + 1) * row_h - row * row_gap
            positions.append((x, y, col_w, row_h))

    # Prep block (position 0)
    prep_x, prep_y, prep_w, prep_h = positions[0]
    rounded_rect(c, prep_x, prep_y, prep_w, prep_h, 4, fill=GRAY50, stroke=GRAY200)

    ph_h = 14
    rounded_rect(c, prep_x, prep_y + prep_h - ph_h, prep_w, ph_h, 4, fill=GRAY200)
    c.setFillColor(GRAY200)
    c.rect(prep_x, prep_y + prep_h - ph_h, prep_w, 6, fill=1, stroke=0)
    c.setStrokeColor(GRAY200)
    c.setLineWidth(0.3)
    c.line(prep_x, prep_y + prep_h - ph_h, prep_x + prep_w, prep_y + prep_h - ph_h)

    c.setFillColor(GRAY500)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(prep_x + 6, prep_y + prep_h - ph_h / 2 - 2.5, "⚙  Préparation")
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(GRAY400)
    rounded_rect(c, prep_x + prep_w - 55, prep_y + prep_h - ph_h / 2 - 4.5, 50, 9, 3, fill=white)
    c.drawString(prep_x + prep_w - 50, prep_y + prep_h - ph_h / 2 - 2.5, "Avant démo")

    prep_items = [
        "• Lancer le seeder Poudlard",
        "• Vérifier Harry dans Étudiants",
        "• Planning rempli avec séances",
        "• Notes et bulletins générés",
        "• Espace étudiant activable",
        "",
        "LÉGENDE :",
        "→  Navigation dans Neil",
        "🎤 Phrase à prononcer",
        "✨ Effet WOW à souligner",
        "•  Action / point clé",
    ]
    ty = prep_y + prep_h - ph_h - 9
    c.setFont("Helvetica", 6)
    for item in prep_items:
        if ty < prep_y + 3:
            break
        if not item:
            ty -= 3
            continue
        if item == "LÉGENDE :":
            c.setFillColor(GRAY900)
            c.setFont("Helvetica-Bold", 6)
            c.drawString(prep_x + 6, ty, item)
            c.setFont("Helvetica", 6)
        elif item.startswith("→"):
            c.setFillColor(GRAY400)
            c.drawString(prep_x + 6, ty, item)
        elif item.startswith("🎤"):
            c.setFillColor(PURPLE)
            c.drawString(prep_x + 6, ty, item)
        elif item.startswith("✨"):
            c.setFillColor(GREEN)
            c.drawString(prep_x + 6, ty, item)
        else:
            c.setFillColor(GRAY900)
            c.drawString(prep_x + 6, ty, item)
        ty -= 7.5

    # Draw 7 section blocks in positions 1-7
    for i, sec in enumerate(sections):
        pos_idx = i + 1
        if pos_idx >= len(positions):
            break
        x, y, w, h = positions[pos_idx]
        draw_section_block(
            c, x, y, w, h,
            sec["num"], sec["title"], sec["timing"],
            sec["color"], sec["color_light"], sec["items"]
        )

    c.save()
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    build_pdf("/Users/adriensarlat/Claude/neil-demo/memo-demo-neil.pdf")
