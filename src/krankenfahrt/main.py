"""Main entry point — starts all three Telegram bots in one asyncio event loop."""

import asyncio

import structlog
from telegram.ext import Application, ApplicationBuilder
from tortoise import Tortoise

from krankenfahrt.alerting import AlertManager, DeadmanSwitch, RateRule
from krankenfahrt.config import config
from krankenfahrt.health import HealthServer, make_db_health_check
from krankenfahrt.logging_setup import setup_logging
from krankenfahrt.metrics_server import MetricsServer, bump_heartbeat
from krankenfahrt.models.schema import (
    Driver, DriverBreak, Escalation, Patient, RecurringTrip, Trip, TripEvent, Vehicle,
)
from krankenfahrt.services.morning_push import run_morning_push_loop

logger = structlog.get_logger(__name__)


# ── Alerting ──────────────────────────────────────────────────


def _make_telegram_notifier(chef_bot: Application):
    """Create a Telegram notifier for the alert manager.

    Sends alerts via the Chef bot to configured admin chat IDs.
    """
    async def send_alert(alert_name: str, message: str) -> None:
        # Determine target chat IDs
        if config.ALERTING_CHEF_CHAT_ID != 0:
            chat_ids = [config.ALERTING_CHEF_CHAT_ID]
        else:
            chat_ids = config.ADMIN_TELEGRAM_IDS

        if not chat_ids:
            logger.warning(
                "Alert %s has no target chat IDs — ADMIN_TELEGRAM_IDS is empty",
                alert_name,
            )
            return

        for chat_id in chat_ids:
            try:
                await chef_bot.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                )
            except Exception:
                logger.exception(
                    "Failed to send alert %s to chat %s",
                    alert_name,
                    chat_id,
                )

    return send_alert


def _build_alert_rules() -> list:
    """Build the default alerting rule set from config."""
    from krankenfahrt.alerting import Severity

    return [
        # ── High error rate (5xx) ──────────────────────────
        RateRule(
            name="High HTTP Error Rate",
            description=(
                "http_errors_total is rising faster than "
                f"{config.ALERTING_ERROR_RATE_THRESHOLD}/s"
            ),
            metric_name="http_errors_total",
            threshold_per_second=config.ALERTING_ERROR_RATE_THRESHOLD,
            operator="gt",
            duration_seconds=config.ALERTING_ERROR_RATE_DURATION,
            severity=Severity.CRITICAL,
            cooldown_seconds=config.ALERTING_COOLDOWN,
        ),

        # ── Deadman switch ─────────────────────────────────
        DeadmanSwitch(
            name="Application Heartbeat Missing",
            description=(
                "The application heartbeat has not been updated. "
                "The service may be down or frozen."
            ),
            metric_name="krankenfahrt_heartbeat_timestamp_seconds",
            max_age_seconds=config.ALERTING_DEADMAN_MAX_AGE,
            severity=Severity.CRITICAL,
            cooldown_seconds=config.ALERTING_COOLDOWN,
        ),

        # ── LLM fallback rate ──────────────────────────────
        RateRule(
            name="High LLM Fallback Rate",
            description=(
                "LLM requests are failing over to the fallback "
                "provider frequently"
            ),
            metric_name="krankenfahrt_llm_fallback_total",
            threshold_per_second=0.1,
            operator="gt",
            duration_seconds=120,
            severity=Severity.WARNING,
            cooldown_seconds=config.ALERTING_COOLDOWN,
        ),

        # ── LLM retry storms ───────────────────────────────
        RateRule(
            name="LLM Retry Storm",
            description=(
                "LLM calls are being retried at an unusually high rate"
            ),
            metric_name="krankenfahrt_llm_retry_total",
            threshold_per_second=0.5,
            operator="gt",
            duration_seconds=60,
            severity=Severity.WARNING,
            cooldown_seconds=config.ALERTING_COOLDOWN,
        ),

        # ── DB retry pressure ──────────────────────────────
        RateRule(
            name="Database Retry Pressure",
            description=(
                "Database write operations are being retried at a high rate"
            ),
            metric_name="krankenfahrt_db_retry_total",
            threshold_per_second=0.2,
            operator="gt",
            duration_seconds=120,
            severity=Severity.WARNING,
            cooldown_seconds=config.ALERTING_COOLDOWN,
        ),
    ]


async def _heartbeat_loop() -> None:
    """Bump the heartbeat metric every 15 seconds."""
    while True:
        bump_heartbeat()
        await asyncio.sleep(15)


async def init_database() -> None:
    """Initialize Tortoise ORM with SQLite."""
    await Tortoise.init(
        db_url=config.DATABASE_URL,
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()


async def build_patient_bot() -> Application:
    """Build the @FahrGast bot for patients."""
    app = ApplicationBuilder().token(config.PATIENT_BOT_TOKEN).build()

    from krankenfahrt.bots.patient_bot import register_handlers
    register_handlers(app)
    return app


async def build_driver_bot() -> Application:
    """Build the @FahrLenker bot for drivers."""
    app = ApplicationBuilder().token(config.DRIVER_BOT_TOKEN).build()

    from krankenfahrt.bots.driver_bot import register_handlers as register_driver_handlers
    register_driver_handlers(app)
    return app


async def build_chef_bot() -> Application:
    """Build the @FahrtenChef bot for owner/dispatcher."""
    app = ApplicationBuilder().token(config.CHEF_BOT_TOKEN).build()

    from krankenfahrt.bots.chef_bot import register_handlers
    register_handlers(app)

    from krankenfahrt.bots.chef_bot_escalation import register_handlers as register_escalation
    register_escalation(app)

    return app


async def _precache_whisper() -> None:
    """Pre-cache the faster-whisper model during startup.

    Downloads the model if not already cached in WHISPER_CACHE_DIR.
    On first deploy this takes ~30-60s for the 'small' model (~500MB).
    Subsequent deploys with persistent volume skip the download.
    """
    import glob
    import os as _os

    cache_dir = config.WHISPER_CACHE_DIR
    model_size = config.WHISPER_MODEL
    device = config.WHISPER_DEVICE

    # Check if already cached
    cfgs = glob.glob(_os.path.join(cache_dir, "**", "config.json"), recursive=True)
    if cfgs:
        logger.info("Whisper model already cached", dir=cache_dir, count=len(cfgs))
        return

    logger.info("Downloading whisper model...", model=model_size, device=device, dir=cache_dir)
    from faster_whisper import WhisperModel
    WhisperModel(model_size, device=device, compute_type="int8", download_root=cache_dir)
    logger.info("Whisper model download complete")


async def main() -> None:
    """Start all bots + health-check HTTP server + alerting."""
    setup_logging()

    logger.info("Krankenfahrt starting...")

    # Init database first (health server needs it for the DB ping)
    await init_database()
    logger.info("Database initialized")

    # Pre-cache whisper model during startup so first transcription is fast.
    # Model loads from WHISPER_CACHE_DIR; downloads ~1-2 GB on first deploy.
    try:
        await _precache_whisper()
    except Exception:
        logger.warning("Whisper pre-cache failed — transcription will lazy-load", exc_info=True)

    # Start health-check HTTP server with DB liveness probe
    db_check = make_db_health_check()
    health_server = HealthServer(
        host=config.HEALTH_HOST,
        port=config.HEALTH_PORT,
        db_check=db_check,
    )
    await health_server.start()

    # Start the Prometheus metrics server
    metrics_server = MetricsServer(
        host=config.HEALTH_HOST,
        port=config.METRICS_PORT,
    )
    await metrics_server.start()

    # Build bots
    patient_bot = await build_patient_bot()
    driver_bot = await build_driver_bot()
    chef_bot = await build_chef_bot()

    # Register global error handler on all bots
    async def _error_handler(update, context):
        from telegram.error import Conflict as _Conflict
        if isinstance(context.error, _Conflict):
            # Deploy overlap: another instance is still polling. Suppress —
            # the old instance will be killed shortly by Railway.
            logger.warning("Telegram Conflict during deploy overlap — suppressing")
            return
        logger.error("Unhandled error", exc_info=context.error)
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ Interner Fehler. Bitte versuche es erneut oder kontaktiere den Support."
            )

    patient_bot.add_error_handler(_error_handler)
    driver_bot.add_error_handler(_error_handler)
    chef_bot.add_error_handler(_error_handler)

    # Initialize all three
    await patient_bot.initialize()
    await driver_bot.initialize()
    await chef_bot.initialize()

    # Pre-poll delay — gives Railway's health check time to kill the old
    # container during rolling deploys, avoiding Telegram Conflict errors
    # when two instances poll the same bot tokens simultaneously.
    import asyncio as _asyncio
    logger.info("Waiting 15s before starting polling (deploy overlap guard)...")
    await _asyncio.sleep(15)

    # Start polling — Application.start() does NOT fetch updates!
    await patient_bot.updater.start_polling()
    await driver_bot.updater.start_polling()
    await chef_bot.updater.start_polling()

    await patient_bot.start()
    await driver_bot.start()
    await chef_bot.start()

    logger.info("All three bots running (polling started)")

    # Start morning-push background loop
    morning_push_task = asyncio.create_task(run_morning_push_loop(driver_bot))
    logger.info("Morning-Push background task started")

    # Start heartbeat loop (feeds deadman switch)
    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    logger.info("Heartbeat loop started (15s interval)")

    # Start alerting engine
    alert_manager = None
    alert_task = None
    if config.ALERTING_ENABLED:
        notifier = _make_telegram_notifier(chef_bot)
        alert_rules = _build_alert_rules()
        alert_manager = AlertManager(
            rules=alert_rules,
            notifier=notifier,
            eval_interval=config.ALERTING_EVAL_INTERVAL,
        )
        alert_task = asyncio.create_task(alert_manager._eval_loop())
        logger.info(
            "Alerting started — %d rules, interval %ds",
            len(alert_rules),
            config.ALERTING_EVAL_INTERVAL,
        )

    try:
        # Keep running until interrupted
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        morning_push_task.cancel()
        heartbeat_task.cancel()
        if alert_task is not None:
            alert_task.cancel()
        await patient_bot.stop()
        await driver_bot.stop()
        await chef_bot.stop()
        await patient_bot.shutdown()
        await driver_bot.shutdown()
        await chef_bot.shutdown()
        await health_server.stop()
        await metrics_server.stop()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
