"""Main entry point — starts all three Telegram bots in one asyncio event loop."""

import asyncio

import structlog
from telegram.ext import Application, ApplicationBuilder
from tortoise import Tortoise

from krankenfahrt.config import config
from krankenfahrt.health import HealthServer, make_db_health_check
from krankenfahrt.logging_setup import setup_logging
from krankenfahrt.metrics_server import MetricsServer
from krankenfahrt.models.schema import (
    Driver, Patient, RecurringTrip, Trip, TripEvent, Vehicle,
)

logger = structlog.get_logger(__name__)


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
    return app


async def main() -> None:
    """Start all bots + health-check HTTP server."""
    setup_logging()

    logger.info("Krankenfahrt starting...")

    # Init database first (health server needs it for the DB ping)
    await init_database()
    logger.info("Database initialized")

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

    # Initialize + start all three
    await patient_bot.initialize()
    await driver_bot.initialize()
    await chef_bot.initialize()

    await patient_bot.start()
    await driver_bot.start()
    await chef_bot.start()

    logger.info("All three bots running")

    try:
        # Keep running until interrupted
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
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
