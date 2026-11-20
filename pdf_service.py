# ============================================================
# pdf_service.py — Génération de rapports PDF
# ============================================================

from fpdf import FPDF
from datetime import datetime


def _safe_pdf_text(value) -> str:
    """Convertit le texte vers le jeu Latin-1 des polices PDF intégrées."""
    replacements = {
        "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE",
        "—": "-", "–": "-", "…": "...", "’": "'", "‘": "'",
        "“": '"', "”": '"', "•": "-",
    }
    text = str(value)
    for character, replacement in replacements.items():
        text = text.replace(character, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


class SalesPDF(FPDF):
    def header(self):
        self.set_font('helvetica', 'B', 15)
        self.cell(0, 10, 'Rapport d\'Analyse de Viabilité Commerciale', 0, 1, 'C')
        self.set_font('helvetica', '', 10)
        self.cell(0, 10, f'Généré le : {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 1, 'R')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}} - Sales Advisor AI', 0, 0, 'C')

def generate_sales_pdf(data: dict) -> bytes:
    country = data['country']
    analysis = data['analysis']
    sale_type = data['sale_type']

    pdf = SalesPDF()
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    content_width = pdf.w - pdf.l_margin - pdf.r_margin

    # Section 1: Informations Générales
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 10, f"Détails du projet", 0, 1, 'L', fill=True)
    pdf.ln(2)

    pdf.set_font('helvetica', '', 11)
    pdf.cell(50, 8, "Pays cible:", 0)
    pdf.set_font('helvetica', 'B', 11)
    pdf.cell(0, 8, _safe_pdf_text(f"{country['name']} ({country['official']})"), 0, 1)

    pdf.set_font('helvetica', '', 11)
    pdf.cell(50, 8, "Type de vente:", 0)
    pdf.set_font('helvetica', 'B', 11)
    pdf.cell(0, 8, _safe_pdf_text(sale_type), 0, 1)
    pdf.ln(5)

    # Section 2: Données Pays
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 10, "Indicateurs Macro-économiques", 0, 1, 'L', fill=True)
    pdf.ln(2)

    pdf.set_font('helvetica', '', 11)
    col_w = 45
    pdf.cell(col_w, 8, "Région:", 0); pdf.cell(0, 8, _safe_pdf_text(country['region']), 0, 1)
    pdf.cell(col_w, 8, "Capitale:", 0); pdf.cell(0, 8, _safe_pdf_text(country['capital']), 0, 1)
    pdf.cell(col_w, 8, "Population:", 0); pdf.cell(0, 8, f"{country['population']:,}".replace(',', ' '), 0, 1)
    pdf.cell(col_w, 8, "Revenu:", 0); pdf.cell(0, 8, _safe_pdf_text(country['income_level']), 0, 1)

    gdp = f"{country['gdp_pc']:,.2f} USD".replace(',', ' ') if isinstance(country['gdp_pc'], (int, float)) else "N/A"
    pdf.cell(col_w, 8, "PIB/habitant:", 0); pdf.cell(0, 8, gdp, 0, 1)

    net = f"{country['internet_users']:.1f}%" if isinstance(country['internet_users'], (int, float)) else "N/A"
    pdf.cell(col_w, 8, "Accès Internet:", 0); pdf.cell(0, 8, net, 0, 1)
    pdf.ln(5)

    # Section 3: Analyse IA
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 10, "Analyse de Viabilité", 0, 1, 'L', fill=True)
    pdf.ln(2)

    # Taux
    pdf.set_font('helvetica', 'B', 11)
    pdf.cell(50, 8, f"Score de succès: {analysis['success_rate']}%", 0)
    pdf.cell(0, 8, f"Avis: {'FAVORABLE' if analysis['favorable'] else 'PEU FAVORABLE'}", 0, 1)
    pdf.ln(2)

    pdf.set_font('helvetica', '', 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(content_width, 7, _safe_pdf_text(analysis['analysis']))
    pdf.ln(5)

    # Section 4: Opportunités & Risques
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 10, "Points clés", 0, 1, 'L', fill=True)
    pdf.ln(2)

    pdf.set_font('helvetica', 'B', 11)
    pdf.cell(0, 8, "Opportunités:", 0, 1)
    pdf.set_font('helvetica', '', 11)
    for opp in analysis['opportunities']:
        pdf.set_x(pdf.l_margin + 5)
        pdf.multi_cell(content_width - 5, 7, _safe_pdf_text(f"- {opp}"))
    pdf.ln(2)

    pdf.set_font('helvetica', 'B', 11)
    pdf.cell(0, 8, "Risques:", 0, 1)
    pdf.set_font('helvetica', '', 11)
    for risk in analysis['risks']:
        pdf.set_x(pdf.l_margin + 5)
        pdf.multi_cell(content_width - 5, 7, _safe_pdf_text(f"- {risk}"))
    pdf.ln(5)

    # Section 5: Recommandation
    pdf.set_font('helvetica', 'B', 12)
    pdf.cell(0, 10, "Recommandation stratégique", 0, 1, 'L', fill=True)
    pdf.ln(2)
    pdf.set_font('helvetica', 'I', 11)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(content_width, 7, _safe_pdf_text(analysis['recommendation']))

    return bytes(pdf.output())
