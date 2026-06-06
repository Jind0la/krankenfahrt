"""Basic smoke tests for configuration and imports."""

import os


def test_config_defaults():
    """Config can be imported and has expected attributes."""
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")

    from krankenfahrt.config import config

    assert config.COMPANY_NAME == "Krankenfahrt"
    assert config.DATABASE_URL.startswith("sqlite://")
    assert config.DISPATCH_MODE == "greedy"
    assert config.LOG_LEVEL == "INFO"
    assert config.HEALTH_HOST == "0.0.0.0"
    assert config.HEALTH_PORT == 8080
    assert config.WHISPER_DEVICE == "cpu"
    assert config.ADMIN_TELEGRAM_IDS == []


def test_imports_resolve():
    """All core modules import without errors."""
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")

    import krankenfahrt.config
    import krankenfahrt.core.dispatch
    import krankenfahrt.core.state_machine
    import krankenfahrt.models.schema
    import krankenfahrt.services.geo
    import krankenfahrt.logging_setup
    import krankenfahrt.metrics_server
