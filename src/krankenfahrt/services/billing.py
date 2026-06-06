"""
Billing module: Muster-4 PDF invoices + CSV export for Abrechnungsdaten.

Generates DIN-compliant invoices following the German SGB V
Muster-4 format for Krankentransport billing to statutory health insurance (GKV).

Also provides CSV export with UTF-8-BOM for Excel-compatible billing data.

Usage:
    from krankenfahrt.services.billing import generate_muster4_invoice, export_billing_csv
    pdf_path = generate_muster4_invoice(data)
    csv_path = await export_billing_csv(filters=ExportFilters(date_from=...))
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import structlog

# ReportLab is optional — only needed for PDF invoice generation.
# CSV export works without it.
try:
    from reportlab.lib import colors as _rl_colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import (
        Frame,
        Image,
        PageTemplate,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False
    # Dummy values so constants don't break module import
    A4 = (595.27, 841.89)
    cm = 28.3465
    mm = 2.83465
    TA_CENTER = 1
    TA_LEFT = 0
    TA_RIGHT = 2

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Muster-4 constants
# ---------------------------------------------------------------------------

TAX_RATE = 0.07  # 7% VAT for Krankentransport (§ 12 Abs. 2 Nr. 8 UStG)

PAGE_W, PAGE_H = A4  # 595.27 x 841.89 points

# Margins
LEFT_MARGIN = 20 * mm
RIGHT_MARGIN = 20 * mm
TOP_MARGIN = 25 * mm
BOTTOM_MARGIN = 25 * mm

# Fonts
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_OBLIQUE = "Helvetica-Oblique"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class TripLineItem:
    """A single billable trip line on the invoice."""

    datum: date
    abholort: str
    zielort: str
    fahrzeugtyp: str  # Sitz, Liege, Rad, KTW
    einzelpreis_eur: float
    anzahl: int = 1

    @property
    def gesamtpreis_eur(self) -> float:
        return round(self.einzelpreis_eur * self.anzahl, 2)


@dataclass
class Muster4Data:
    """All data needed to fill a Muster-4 invoice."""

    rechnungsnummer: str
    rechnungsdatum: date
    leistungszeitraum: str  # e.g. "01.01.2026 – 31.01.2026"

    # Patient
    patient_name: str
    patient_geburtsdatum: str
    patient_strasse: str
    patient_ort: str
    patient_versichertennummer: str

    # Krankenkasse
    kk_name: str
    kk_strasse: str
    kk_ort: str
    kk_ik_nummer: str = ""

    # Line items
    positionen: Sequence[TripLineItem] = field(default_factory=list)

    # Optional overrides
    steuernummer: str | None = None
    ik_nummer: str | None = None
    logo_path: str | None = None


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------


def _build_styles() -> dict[str, ParagraphStyle]:
    """Build consistent paragraph styles for Muster-4 layout."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "M4_Title",
            parent=base["Title"],
            fontName=FONT_BOLD,
            fontSize=14,
            leading=18,
            spaceAfter=6,
        ),
        "heading": ParagraphStyle(
            "M4_Heading",
            parent=base["Heading2"],
            fontName=FONT_BOLD,
            fontSize=9,
            leading=12,
            spaceAfter=3,
        ),
        "normal": ParagraphStyle(
            "M4_Normal",
            parent=base["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=11,
        ),
        "small": ParagraphStyle(
            "M4_Small",
            parent=base["Normal"],
            fontName=FONT_REGULAR,
            fontSize=7,
            leading=9,
        ),
        "right": ParagraphStyle(
            "M4_Right",
            parent=base["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=11,
            alignment=TA_RIGHT,
        ),
        "bold": ParagraphStyle(
            "M4_Bold",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=8.5,
            leading=11,
        ),
        "center": ParagraphStyle(
            "M4_Center",
            parent=base["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=11,
            alignment=TA_CENTER,
        ),
        "table_header": ParagraphStyle(
            "M4_TH",
            fontName=FONT_BOLD,
            fontSize=7,
            leading=9,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "M4_TD",
            fontName=FONT_REGULAR,
            fontSize=7,
            leading=9,
        ),
        "table_cell_right": ParagraphStyle(
            "M4_TD_R",
            fontName=FONT_REGULAR,
            fontSize=7,
            leading=9,
            alignment=TA_RIGHT,
        ),
    }


# ---------------------------------------------------------------------------
# PDF builder
# ---------------------------------------------------------------------------

# Column widths for the line-item table (A4 portrait with 20mm margins)
#  Lfd.Nr | Datum      | Beschreibung (Abhol → Ziel, Typ) | Anzahl | Einzel € | Gesamt €
COL_WIDTHS = [8 * mm, 20 * mm, 95 * mm, 12 * mm, 20 * mm, 20 * mm]

TABLE_HEADERS = [
    "Nr.",
    "Datum",
    "Leistungsbeschreibung",
    "Anz.",
    "Einzelpreis",
    "Gesamtpreis",
]


def _eur(val: float) -> str:
    """Format a float as EUR string."""
    return f"{val:,.2f} \u20ac"


def _build_sender_block(data: Muster4Data) -> list[Paragraph]:
    """Sender / Leistungserbringer block (top-left)."""
    styles = _build_styles()
    ik = data.ik_nummer or config.COMPANY_IK_NUMMER
    stnr = data.steuernummer or config.COMPANY_TAX_ID
    return [
        Paragraph(config.COMPANY_NAME, styles["bold"]),
        Paragraph(config.COMPANY_STREET, styles["normal"]),
        Paragraph(config.COMPANY_CITY, styles["normal"]),
        Paragraph("", styles["normal"]),
        Paragraph(f"Tel: {config.COMPANY_PHONE}", styles["small"]),
        Paragraph(f"E-Mail: {config.COMPANY_EMAIL}", styles["small"]),
        Paragraph(f"IK-Nummer: {ik}", styles["small"]),
        Paragraph(f"Steuernummer: {stnr}", styles["small"]),
    ]


def _build_recipient_block(data: Muster4Data) -> list[Paragraph]:
    """Krankenkasse recipient block (below sender, right side address field)."""
    styles = _build_styles()
    lines = [
        Paragraph(data.kk_name, styles["bold"]),
        Paragraph(data.kk_strasse, styles["normal"]),
        Paragraph(data.kk_ort, styles["normal"]),
    ]
    if data.kk_ik_nummer:
        lines.append(Paragraph(f"IK: {data.kk_ik_nummer}", styles["small"]))
    return lines


def _build_patient_block(data: Muster4Data) -> list[Paragraph]:
    """Patient info block."""
    styles = _build_styles()
    return [
        Paragraph("<b>Versicherte/r:</b>", styles["normal"]),
        Paragraph(data.patient_name, styles["normal"]),
        Paragraph(f"geb. {data.patient_geburtsdatum}", styles["normal"]),
        Paragraph(data.patient_strasse, styles["normal"]),
        Paragraph(data.patient_ort, styles["normal"]),
        Paragraph(f"Vers.-Nr.: {data.patient_versichertennummer}", styles["small"]),
    ]


def _build_invoice_header(data: Muster4Data) -> list[Paragraph]:
    """Invoice number, date, and title block (top-right)."""
    styles = _build_styles()
    return [
        Paragraph("RECHNUNG", styles["title"]),
        Paragraph(
            f"Rechnungsnummer: <b>{data.rechnungsnummer}</b>",
            styles["normal"],
        ),
        Paragraph(
            f"Rechnungsdatum: {data.rechnungsdatum.strftime('%d.%m.%Y')}",
            styles["normal"],
        ),
        Paragraph(
            f"Leistungszeitraum: {data.leistungszeitraum}",
            styles["normal"],
        ),
    ]


def _build_line_item_table(data: Muster4Data) -> Table:
    """Build the itemized table of billable trips."""
    styles = _build_styles()
    style_th = styles["table_header"]
    style_td = styles["table_cell"]
    style_tdr = styles["table_cell_right"]

    # Header row
    rows = [[Paragraph(h, style_th) for h in TABLE_HEADERS]]

    # Data rows
    for i, pos in enumerate(data.positionen, 1):
        beschreibung = f"{pos.abholort} → {pos.zielort}<br/><i>{pos.fahrzeugtyp}</i>"
        rows.append(
            [
                Paragraph(str(i), style_td),
                Paragraph(pos.datum.strftime("%d.%m.%Y"), style_td),
                Paragraph(beschreibung, style_td),
                Paragraph(str(pos.anzahl), style_td),
                Paragraph(_eur(pos.einzelpreis_eur), style_tdr),
                Paragraph(_eur(pos.gesamtpreis_eur), style_tdr),
            ]
        )

    table = Table(rows, colWidths=COL_WIDTHS, repeatRows=1)

    # Calculate net total
    net_total = sum(p.gesamtpreis_eur for p in data.positionen)

    table.setStyle(
        TableStyle(
            [
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), _rl_colors.HexColor("#E8E8E8")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _rl_colors.black),
                # Body
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                # Inner grid
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _rl_colors.Color(0.7, 0.7, 0.7)),
                ("BOX", (0, 0), (-1, -1), 0.5, _rl_colors.black),
                # Align numeric columns right
                ("ALIGN", (3, 0), (5, -1), "RIGHT"),
                # Total row background
                ("BACKGROUND", (0, -1), (-1, -1), _rl_colors.HexColor("#F5F5F5")),
            ]
        )
    )

    return table


def _build_summary_block(data: Muster4Data) -> Table:
    """Build the net/VAT/gross summary block (right-aligned)."""
    styles = _build_styles()
    net_total = sum(p.gesamtpreis_eur for p in data.positionen)
    vat = round(net_total * TAX_RATE, 2)
    gross_total = round(net_total + vat, 2)

    rows = [
        [
            Paragraph("Nettobetrag:", styles["right"]),
            Paragraph(_eur(net_total), styles["right"]),
        ],
        [
            Paragraph("zzgl. 7% USt.:", styles["right"]),
            Paragraph(_eur(vat), styles["right"]),
        ],
        [
            Paragraph("<b>Gesamtbetrag:</b>", styles["bold"]),
            Paragraph(f"<b>{_eur(gross_total)}</b>", styles["bold"]),
        ],
    ]

    # Width: right-align the block
    total_width = 80 * mm
    label_w = 50 * mm
    amount_w = 30 * mm

    table = Table(rows, colWidths=[label_w, amount_w])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, -1), "RIGHT"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 2), (-1, 2), 0.5, _rl_colors.black),
                ("TOPPADDING", (0, 2), (-1, 2), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _build_footer_block() -> list[Paragraph]:
    """Payment terms, bank details, signature."""
    styles = _build_styles()
    return [
        Paragraph("<b>Zahlungsbedingungen:</b>", styles["bold"]),
        Paragraph(
            "Zahlbar innerhalb von 14 Tagen nach Rechnungserhalt ohne Abzug.",
            styles["normal"],
        ),
        Paragraph("", styles["normal"]),
        Paragraph("<b>Bankverbindung:</b>", styles["bold"]),
        Paragraph(f"{config.COMPANY_BANK_NAME}", styles["normal"]),
        Paragraph(f"IBAN: {config.COMPANY_IBAN}", styles["normal"]),
        Paragraph(f"BIC: {config.COMPANY_BIC}", styles["normal"]),
        Paragraph("", styles["normal"]),
        Paragraph(
            "Gemäß § 302 SGB V erfolgt die Abrechnung nach Muster 4.",
            styles["small"],
        ),
    ]


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------


def _build_page_template() -> PageTemplate:
    """Build a two-frame page template: address window + main content."""

    # Address window (DIN 5008 Fensterkuvert — 45 x 90 mm, positioned for window envelope)
    addr_frame = Frame(
        LEFT_MARGIN + 5 * mm,  # slight indent from left
        PAGE_H - TOP_MARGIN - 40 * mm,  # y position (from bottom)
        90 * mm,  # width
        35 * mm,  # height
        leftPadding=0,
        bottomPadding=0,
        rightPadding=0,
        topPadding=0,
        id="address_window",
    )

    # Main content frame
    content_frame = Frame(
        LEFT_MARGIN,
        BOTTOM_MARGIN,
        PAGE_W - LEFT_MARGIN - RIGHT_MARGIN,
        PAGE_H - TOP_MARGIN - BOTTOM_MARGIN - 45 * mm,  # leave room for address window
        leftPadding=0,
        bottomPadding=0,
        rightPadding=0,
        topPadding=0,
        id="content",
    )

    return PageTemplate(
        id="Muster4",
        frames=[addr_frame, content_frame],
        onPage=_draw_static_elements,
    )


def _draw_static_elements(canvas, doc):
    """Draw static elements on each page: footer line, page number."""
    canvas.saveState()
    # Footer line
    canvas.setStrokeColor(_rl_colors.Color(0.7, 0.7, 0.7))
    canvas.setLineWidth(0.5)
    canvas.line(
        LEFT_MARGIN,
        BOTTOM_MARGIN + 8 * mm,
        PAGE_W - RIGHT_MARGIN,
        BOTTOM_MARGIN + 8 * mm,
    )
    # Page number
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawRightString(
        PAGE_W - RIGHT_MARGIN,
        BOTTOM_MARGIN + 3 * mm,
        f"Seite {canvas.getPageNumber()}",
    )
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_muster4_invoice(
    data: Muster4Data,
    output_dir: str | Path = ".",
) -> Path:
    """Generate a Muster-4 PDF invoice and save it to disk.

    Args:
        data: All invoice data (company, patient, KK, line items).
        output_dir: Directory to write the PDF. Filename is derived from
                    the invoice number (e.g. ``R2026-0042.pdf``).

    Returns:
        Path to the generated PDF file.
    """
    if not _HAS_REPORTLAB:
        raise ImportError(
            "ReportLab is required for PDF invoice generation. "
            "Install with: pip install reportlab"
        )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{data.rechnungsnummer}.pdf"

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=LEFT_MARGIN,
        rightMargin=RIGHT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=f"Rechnung {data.rechnungsnummer}",
        author=config.COMPANY_NAME,
        subject=f"Muster-4 Krankentransport {data.rechnungsnummer}",
    )

    doc.addPageTemplates([_build_page_template()])

    styles = _build_styles()
    story = []

    # ── Address window (for window envelope, DIN 5008) ────────────────
    story.extend(_build_recipient_block(data))
    # Minimal spacer: recipient block itself provides enough clearance

    # ── Sender block + Invoice header (top area) ─────────────────────
    # Build as a two-column table: sender left, header right
    sender_paras = _build_sender_block(data)
    header_paras = _build_invoice_header(data)

    # If logo, insert it before sender
    logo = None
    if data.logo_path and Path(data.logo_path).exists():
        logo = Image(
            data.logo_path,
            width=50 * mm,
            height=15 * mm,
            kind="proportional",
        )

    # Build sender column
    sender_items = sender_paras
    if logo:
        sender_items = [logo, Spacer(1, 3 * mm)] + sender_items

    # Pack into a two-column layout table
    header_table = Table(
        [[sender_items, header_paras]],
        colWidths=[90 * mm, 74 * mm],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ]
        )
    )

    story.append(header_table)
    story.append(Spacer(1, 3 * mm))

    # ── Patient block ────────────────────────────────────────────────
    story.append(Paragraph("<b>Angaben zum Versicherten</b>", styles["heading"]))
    patient_table = Table(
        [[_build_patient_block(data)]],
        colWidths=[90 * mm],
    )
    patient_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, _rl_colors.Color(0.7, 0.7, 0.7)),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, _rl_colors.Color(0.85, 0.85, 0.85)),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(patient_table)
    story.append(Spacer(1, 3 * mm))

    # ── Line item table ──────────────────────────────────────────────
    story.append(Paragraph("<b>Erbrachte Leistungen</b>", styles["heading"]))
    story.append(Spacer(1, 2 * mm))
    story.append(_build_line_item_table(data))
    story.append(Spacer(1, 3 * mm))

    # ── Summary block ────────────────────────────────────────────────
    summary = _build_summary_block(data)
    # Right-align the summary
    summary_table = Table(
        [[Spacer(94 * mm, 1), summary]],
        colWidths=[94 * mm, 80 * mm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 4 * mm))

    # ── Footer ───────────────────────────────────────────────────────
    story.extend(_build_footer_block())
    story.append(Spacer(1, 4 * mm))

    # Signature line
    sig_table = Table(
        [
            [
                Paragraph("Ort, Datum", styles["small"]),
                Paragraph("Unterschrift", styles["small"]),
            ]
        ],
        colWidths=[90 * mm, 84 * mm],
    )
    sig_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (0, 0), 0.5, _rl_colors.black),
                ("LINEBELOW", (1, 0), (1, 0), 0.5, _rl_colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 15),
            ]
        )
    )
    story.append(sig_table)

    # ── Build PDF ────────────────────────────────────────────────────
    doc.build(story)
    logger.info("Muster-4 invoice written: %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Convenience: generate from Trip model objects
# ---------------------------------------------------------------------------


async def generate_invoice_for_trips(
    trips: Sequence,
    patient_name: str,
    patient_geburtsdatum: str,
    patient_strasse: str,
    patient_ort: str,
    patient_versichertennummer: str,
    kk_name: str,
    kk_strasse: str,
    kk_ort: str,
    kk_ik_nummer: str = "",
    rechnungsnummer: str | None = None,
    output_dir: str | Path = ".",
) -> Path:
    """Generate a Muster-4 invoice from Trip ORM model objects.

    This is the primary integration point for Chef-Bot: pass a list of
    ``Trip`` ORM objects (already fetched with ``.prefetch_related("patient")``)
    and get a PDF invoice back.
    """
    today = date.today()

    if rechnungsnummer is None:
        year = today.strftime("%Y")
        rechnungsnummer = f"R{year}-{today.strftime('%m%d')}-{today.strftime('%H%M')}"

    positionen: list[TripLineItem] = []
    for trip in trips:
        # Determine vehicle type from the trip's vehicle or patient default
        fahrzeugtyp = "Sitz"
        if hasattr(trip, "vehicle") and trip.vehicle:
            fahrzeugtyp = trip.vehicle.vehicle_type or "Sitz"
        elif hasattr(trip, "patient") and trip.patient:
            fahrzeugtyp = trip.patient.vehicle_type or "Sitz"

        trip_date = trip.scheduled_pickup.date() if trip.scheduled_pickup else today

        positionen.append(
            TripLineItem(
                datum=trip_date,
                abholort=trip.pickup_addr or "",
                zielort=trip.dest_addr or "",
                fahrzeugtyp=fahrzeugtyp,
                einzelpreis_eur=trip.fare_eur or 0.0,
            )
        )

    # Sort by date
    positionen.sort(key=lambda p: p.datum)

    # Leistungszeitraum from first and last trip dates
    if positionen:
        first_date = positionen[0].datum
        last_date = positionen[-1].datum
        leistungszeitraum = (
            f"{first_date.strftime('%d.%m.%Y')} – {last_date.strftime('%d.%m.%Y')}"
        )
    else:
        leistungszeitraum = today.strftime("%d.%m.%Y")

    data = Muster4Data(
        rechnungsnummer=rechnungsnummer,
        rechnungsdatum=today,
        leistungszeitraum=leistungszeitraum,
        patient_name=patient_name,
        patient_geburtsdatum=patient_geburtsdatum,
        patient_strasse=patient_strasse,
        patient_ort=patient_ort,
        patient_versichertennummer=patient_versichertennummer,
        kk_name=kk_name,
        kk_strasse=kk_strasse,
        kk_ort=kk_ort,
        kk_ik_nummer=kk_ik_nummer,
        positionen=positionen,
    )

    return generate_muster4_invoice(data, output_dir=output_dir)


# ---------------------------------------------------------------------------
# CSV Export for billing data (Abrechnungsdaten)
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "Rechnungsnummer",
    "Abrechnungsdatum",
    "Fahrtdatum",
    "Patient Name",
    "Krankenkasse",
    "Versichertennummer",
    "Abholadresse",
    "Zieladresse",
    "Fahrzeugtyp",
    "Fahrpreis (EUR)",
    "Fahrtstatus",
    "Abrechnungsstatus",
]

DATE_FORMAT = "%d.%m.%Y"


@dataclass
class ExportFilters:
    """Filter criteria for billing CSV export."""

    date_from: date | None = None
    date_to: date | None = None
    billing_status: str | None = None  # None = all, "offen" | "exportiert" | "abgerechnet"
    status: str | None = None  # None = all, e.g. "abgeschlossen"


def _generate_invoice_number(trip_id: int, trip_date: datetime) -> str:
    """Generate a human-readable invoice number from trip ID and date.

    Format: R-YYYYMMDD-NNNN (e.g. R-20260603-0042)
    """
    return f"R-{trip_date.strftime('%Y%m%d')}-{trip_id:04d}"


def _format_date(dt: datetime | None) -> str:
    """Format a datetime as German date string or empty cell."""
    if dt is None:
        return ""
    return dt.strftime(DATE_FORMAT)


async def export_billing_csv(
    filters: ExportFilters | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Export billing records as a UTF-8-BOM CSV file for Excel compatibility.

    Queries completed trips with patient data (JOIN), applies optional
    date/status filters, and writes a semicolon-delimited CSV.

    Args:
        filters: Optional filter criteria (date range, status).
        output_dir: Target directory (default: PROJECT_ROOT/data/exports/).

    Returns:
        Path to the generated CSV file.
    """
    import csv

    from krankenfahrt.models.schema import Trip

    filters = filters or ExportFilters()

    # Query: trips with patient join, sorted by pickup date descending
    query = Trip.all().select_related("patient").order_by("-scheduled_pickup")

    if filters.date_from:
        query = query.filter(scheduled_pickup__gte=filters.date_from)
    if filters.date_to:
        query = query.filter(scheduled_pickup__lte=filters.date_to)
    if filters.billing_status:
        query = query.filter(billing_status=filters.billing_status)
    if filters.status:
        query = query.filter(status=filters.status)

    trips = await query

    # Output directory
    if output_dir is None:
        output_dir = config.PROJECT_ROOT / "data" / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"abrechnung_{timestamp}.csv"
    filepath = output_dir / filename

    rows_written = 0
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_HEADERS)

        for trip in trips:
            patient = trip.patient
            invoice_nr = _generate_invoice_number(trip.id, trip.scheduled_pickup)
            row = [
                invoice_nr,
                _format_date(datetime.now()),
                _format_date(trip.scheduled_pickup),
                patient.name,
                patient.insurance_provider or "",
                patient.insurance_number or "",
                trip.pickup_addr,
                trip.dest_addr,
                trip.vehicle_type,
                f"{trip.fare_eur:.2f}".replace(".", ",") if trip.fare_eur else "",
                trip.status,
                trip.billing_status,
            ]
            writer.writerow(row)
            rows_written += 1

    logger.info("CSV export complete: %d trips → %s", rows_written, filepath)
    return filepath


def generate_csv_in_memory(trips_data: list[dict]) -> io.BytesIO:
    """Generate a CSV in memory (for direct Telegram upload).

    Args:
        trips_data: List of dicts with keys matching CSV_HEADERS.

    Returns:
        BytesIO buffer with UTF-8-BOM CSV content.
    """
    import csv

    buf = io.BytesIO()
    buf.write(b"\xef\xbb\xbf")  # UTF-8 BOM

    text_wrapper = io.TextIOWrapper(
        buf, encoding="utf-8", newline="", write_through=True
    )
    writer = csv.writer(text_wrapper, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_HEADERS)

    for row_dict in trips_data:
        row = [row_dict.get(header, "") for header in CSV_HEADERS]
        writer.writerow(row)

    text_wrapper.detach()
    buf.seek(0)
    return buf
