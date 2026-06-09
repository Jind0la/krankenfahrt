"""Tests for Muster-4 PDF billing module."""

import os
import re
import tempfile
import zlib
import base64
from datetime import date
from pathlib import Path

import pytest

# Ensure env vars are set before any imports
os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")

from krankenfahrt.services.billing import (
    Muster4Data,
    TripLineItem,
    generate_muster4_invoice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_pdf_text(path: Path) -> str:
    """Extract readable text from a ReportLab-generated PDF."""
    content = path.read_bytes()
    pattern = rb"/Filter.*?ASCII85Decode.*?FlateDecode.*?/Length \d+.*?>>\s*\nstream\n(.*?)endstream"
    texts = []
    for m in re.finditer(pattern, content, re.DOTALL):
        raw = m.group(1).strip()
        try:
            decoded = base64.a85decode(raw, adobe=True)
            decompressed = zlib.decompress(decoded)
            parts = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
            texts.append(
                " ".join(t.decode("latin-1", errors="replace") for t in parts)
            )
        except Exception:
            pass
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_sample_data(**overrides) -> Muster4Data:
    """Build a minimal Muster4Data for testing."""
    positionen = [
        TripLineItem(
            datum=date(2026, 6, 1),
            abholort="Teststraße 1, 12345 Teststadt",
            zielort="Zielstraße 2, 12345 Teststadt",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        ),
        TripLineItem(
            datum=date(2026, 6, 2),
            abholort="Teststraße 1, 12345 Teststadt",
            zielort="Zielstraße 2, 12345 Teststadt",
            fahrzeugtyp="Liege",
            einzelpreis_eur=55.00,
        ),
    ]
    defaults = {
        "rechnungsnummer": "R2026-0001",
        "rechnungsdatum": date(2026, 6, 10),
        "leistungszeitraum": "01.06.2026 – 02.06.2026",
        "patient_name": "Max Mustermann",
        "patient_geburtsdatum": "01.01.1970",
        "patient_strasse": "Teststraße 1",
        "patient_ort": "12345 Teststadt",
        "patient_versichertennummer": "T123456789",
        "kk_name": "Test Krankenkasse",
        "kk_strasse": "KK-Straße 1",
        "kk_ort": "12345 KK-Stadt",
        "kk_ik_nummer": "109999999",
        "positionen": positionen,
    }
    defaults.update(overrides)
    return Muster4Data(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTripLineItem:
    def test_gesamtpreis_single(self):
        item = TripLineItem(
            datum=date(2026, 1, 1),
            abholort="A",
            zielort="B",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        )
        assert item.gesamtpreis_eur == 45.00

    def test_gesamtpreis_multiple_quantity(self):
        item = TripLineItem(
            datum=date(2026, 1, 1),
            abholort="A",
            zielort="B",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=10.50,
            anzahl=3,
        )
        assert item.gesamtpreis_eur == 31.50

    def test_gesamtpreis_rounding(self):
        item = TripLineItem(
            datum=date(2026, 1, 1),
            abholort="A",
            zielort="B",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=10.333,
            anzahl=3,
        )
        assert item.gesamtpreis_eur == 31.00  # 10.333 * 3 = 30.999 → 31.00


class TestMuster4Data:
    def test_defaults(self):
        data = _make_sample_data()
        assert data.rechnungsnummer == "R2026-0001"
        assert len(data.positionen) == 2

    def test_positionen_default_empty(self):
        data = Muster4Data(
            rechnungsnummer="R-empty",
            rechnungsdatum=date(2026, 1, 1),
            leistungszeitraum="01.01.2026",
            patient_name="X",
            patient_geburtsdatum="01.01.2000",
            patient_strasse="X",
            patient_ort="X",
            patient_versichertennummer="X",
            kk_name="X",
            kk_strasse="X",
            kk_ort="X",
        )
        assert data.positionen == []

    def test_optional_overrides(self):
        data = _make_sample_data(
            steuernummer="OVERRIDE-STNR",
            ik_nummer="OVERRIDE-IK",
        )
        assert data.steuernummer == "OVERRIDE-STNR"
        assert data.ik_nummer == "OVERRIDE-IK"


class TestGenerateInvoice:
    def test_generates_pdf(self):
        """PDF is written to disk with expected filename."""
        data = _make_sample_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            assert path.exists()
            assert path.suffix == ".pdf"
            assert path.name == "R2026-0001.pdf"
            assert path.stat().st_size > 0

    def test_pdf_is_valid(self):
        """Generated file starts with PDF magic bytes."""
        data = _make_sample_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            with open(path, "rb") as f:
                header = f.read(5)
            assert header == b"%PDF-"

    def test_pdf_contains_expected_text(self):
        """PDF stream contains key Muster-4 elements."""
        data = _make_sample_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            text = _extract_pdf_text(path)

            assert "RECHNUNG" in text or "Rechnung" in text
            assert "Max Mustermann" in text
            assert "Test Krankenkasse" in text
            assert "Nettobetrag" in text or "net" in text.lower()
            assert "Muster-4" in text or "Muster 4" in text
            assert "SGB V" in text

    def test_single_page(self):
        """Typical invoice with 2 items fits on one page."""
        data = _make_sample_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            import re

            content = path.read_bytes()
            pages = re.findall(rb"/Type\s*/Page[^s]", content)
            assert len(pages) == 1, f"Expected 1 page, got {len(pages)}"

    def test_empty_positions(self):
        """Invoice with no line items still generates."""
        data = _make_sample_data(positionen=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            assert path.exists()
            assert path.stat().st_size > 0

    def test_many_positions_multipage(self):
        """Invoice with many items may span multiple pages without error."""
        positionen = [
            TripLineItem(
                datum=date(2026, 6, i),
                abholort=f"Straße {i}, Stadt",
                zielort=f"Ziel {i}, Stadt",
                fahrzeugtyp="Sitz",
                einzelpreis_eur=45.00,
            )
            for i in range(1, 21)
        ]
        data = _make_sample_data(positionen=positionen)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            assert path.exists()
            # Should be at least 1 page, possibly 2
            import re

            content = path.read_bytes()
            pages = re.findall(rb"/Type\s*/Page[^s]", content)
            assert len(pages) >= 1

    def test_logo_path_nonexistent_handled(self):
        """Nonexistent logo path does not crash generation."""
        data = _make_sample_data(logo_path="/nonexistent/logo.png")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            assert path.exists()

    def test_output_dir_created(self):
        """Output directory is created if it doesn't exist."""
        data = _make_sample_data()
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "rechnungen" / "2026"
            path = generate_muster4_invoice(data, output_dir=nested)
            assert path.exists()
            assert nested.exists()


class TestFinancialCalculations:
    def test_net_total(self):
        """Net total is sum of all line items."""
        data = _make_sample_data()  # 45.00 + 55.00 = 100.00
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            text = _extract_pdf_text(path)
            assert "100.00" in text, f"Expected 100.00 in: {text}"

    def test_vat_calculation(self):
        """7% VAT is correctly calculated."""
        data = _make_sample_data()  # net 100.00, VAT 7.00, gross 107.00
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            text = _extract_pdf_text(path)
            assert "7.00" in text, f"Expected 7.00 in: {text}"
            assert "107.00" in text, f"Expected 107.00 in: {text}"

    def test_zero_amounts(self):
        """Zero-price items handled correctly."""
        positionen = [
            TripLineItem(
                datum=date(2026, 1, 1),
                abholort="A",
                zielort="B",
                fahrzeugtyp="Sitz",
                einzelpreis_eur=0.00,
            )
        ]
        data = _make_sample_data(positionen=positionen)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_muster4_invoice(data, output_dir=tmpdir)
            assert path.exists()
            text = _extract_pdf_text(path)
            assert "0.00" in text, f"Expected 0.00 in: {text}"
