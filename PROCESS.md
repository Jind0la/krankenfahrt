# Process: Integration-Gap-Protection

## Das Problem

Wenn 30+ Worker parallel Code schreiben, entstehen zwangsläufig Integrationslücken:
- Worker A erwartet `config.ADMIN_TELEGRAM_IDS`, Worker B testet ohne
- Worker C schreibt `billing.py`, Worker D ändert `config.py` 
- Worker E nutzt `_HAS_REPORTLAB`, aber der Guard fehlt

## Die Lösung: Drei-Schichten-Test-Architektur

```
tests/
├── contracts/         ← Gate 1: Kann das Modul importiert werden?
│   └── test_imports.py
├── unit/              ← Gate 2: Funktioniert die Logik isoliert?
│   └── test_*.py      (kein DB, kein Netzwerk, kein Bot)
└── integration/       ← Gate 3: Funktionieren die Komponenten zusammen?
    └── test_*.py      (DB, Auth, Bot-Handler, E2E-Flows)
```

## Pre-Commit Hook

`scripts/pre-commit.sh` läuft automatisch bei jedem Commit:
1. **Contract Gate**: `tests/contracts/` — alle Services importierbar?
2. **Unit Gate**: `tests/unit/` — alle Tests grün?
3. **Lint Gate**: `ruff check src/` — keine Style-Issues?

Integration-Tests laufen NICHT im Pre-Commit (brauchen DB-Config).

## Operator Workflow (nach jeder Worker-Session)

1. `pytest tests/unit/ tests/contracts/` → muss grün sein
2. `pytest tests/integration/` → dokumentieren was fehlschlägt
3. Fehlschläge kategorisieren: Contract-Gap vs Auth-Gap vs Timing-Flake
4. Contract-Gaps sofort fixen (verhindern Produktions-Crashs)
5. Auth-Gaps als Integration-Task ins Kanban

## Contract Pattern für neue Services

Jeder neue Service definiert:

```python
# In services/mein_service.py
CONTRACT = {
    "name": "mein_service",
    "exports": ["public_function", "PublicClass"],
    "optional_deps": ["reportlab"],
    "has_optional": {"reportlab": True}  # Vom import-guard gesetzt
}
```

Der Contract-Test prüft automatisch dass alle `exports` importierbar sind.
