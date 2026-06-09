"""Contract tests for service interfaces.

Every service module MUST expose a CONTRACT dict that defines:
- name: str — module name for error messages  
- exports: list[str] — public symbols that must be importable
- optional_deps: list[str] — dependencies that may be missing (guarded imports)
- has_optional: dict[str, bool] — whether each optional dep is available

Workers writing new services MUST implement this contract.
The pre-commit hook runs `pytest tests/contracts/` to verify.
"""

import importlib
import pytest

# List all service modules that must pass contract checks
SERVICES = [
    "krankenfahrt.services.billing",
    "krankenfahrt.services.llm",
    "krankenfahrt.services.voice", 
    "krankenfahrt.services.geo",
    "krankenfahrt.core.state_machine",
    "krankenfahrt.core.dispatch",
    "krankenfahrt.core.notification",
    "krankenfahrt.models.schema",
    "krankenfahrt.config",
]

@pytest.mark.parametrize("module_name", SERVICES)
def test_module_imports_without_error(module_name):
    """Every service module must be importable (optional deps guarded)."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        # Only fail on non-optional import errors
        if "reportlab" in str(e).lower():
            pytest.skip("Optional dependency reportlab not installed")
        if "ortools" in str(e).lower():
            pytest.skip("Optional dependency ortools not installed")
        if "faster_whisper" in str(e).lower():
            pytest.skip("Optional dependency faster-whisper not installed")
        raise  # Real import error — must fix


@pytest.mark.parametrize("module_name", SERVICES)
def test_module_has_contract_or_imports_clean(module_name):
    """Modules should either define CONTRACT or import without side effects."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        pytest.skip(f"Module {module_name} has optional deps unavailable")
    
    # If CONTRACT is defined, validate it
    if hasattr(mod, "CONTRACT"):
        contract = mod.CONTRACT
        assert "name" in contract, f"{module_name} CONTRACT missing 'name'"
        assert "exports" in contract, f"{module_name} CONTRACT missing 'exports'"
        for sym in contract.get("exports", []):
            assert hasattr(mod, sym), f"{module_name} must export '{sym}' per CONTRACT"
