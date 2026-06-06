#!/usr/bin/env python3
"""Generate a sample Muster-4 PDF invoice for visual verification.

Run:
    python tests/generate_sample_invoice.py
"""

import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from krankenfahrt.services.billing import (
    Muster4Data,
    TripLineItem,
    generate_muster4_invoice,
)


def main():
    # ── Sample data: AOK patient with 5 dialysis trips ───────────
    positionen = [
        TripLineItem(
            datum=date(2026, 6, 1),
            abholort="Hauptstraße 42, 44137 Dortmund",
            zielort="Dialysezentrum Dortmund, Rheinische Str. 22, 44137 Dortmund",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        ),
        TripLineItem(
            datum=date(2026, 6, 3),
            abholort="Hauptstraße 42, 44137 Dortmund",
            zielort="Dialysezentrum Dortmund, Rheinische Str. 22, 44137 Dortmund",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        ),
        TripLineItem(
            datum=date(2026, 6, 5),
            abholort="Hauptstraße 42, 44137 Dortmund",
            zielort="Dialysezentrum Dortmund, Rheinische Str. 22, 44137 Dortmund",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        ),
        TripLineItem(
            datum=date(2026, 6, 8),
            abholort="Hauptstraße 42, 44137 Dortmund",
            zielort="Dialysezentrum Dortmund, Rheinische Str. 22, 44137 Dortmund",
            fahrzeugtyp="Sitz",
            einzelpreis_eur=45.00,
        ),
        TripLineItem(
            datum=date(2026, 6, 10),
            abholort="Hauptstraße 42, 44137 Dortmund",
            zielort="Dialysezentrum Dortmund, Rheinische Str. 22, 44137 Dortmund",
            fahrzeugtyp="Liege",
            einzelpreis_eur=55.00,
        ),
    ]

    data = Muster4Data(
        rechnungsnummer="R2026-0042",
        rechnungsdatum=date(2026, 6, 15),
        leistungszeitraum="01.06.2026 – 10.06.2026",
        patient_name="Erika Mustermann",
        patient_geburtsdatum="15.03.1958",
        patient_strasse="Hauptstraße 42",
        patient_ort="44137 Dortmund",
        patient_versichertennummer="A123456789",
        kk_name="AOK NordWest",
        kk_strasse="Postfach 10 20 40",
        kk_ort="44020 Dortmund",
        kk_ik_nummer="104080123",
        positionen=positionen,
    )

    output_dir = Path(__file__).resolve().parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    pdf_path = generate_muster4_invoice(data, output_dir=output_dir)
    print(f"✅ Sample invoice generated: {pdf_path}")


if __name__ == "__main__":
    main()
