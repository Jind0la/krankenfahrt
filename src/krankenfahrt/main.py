"""Main entry point — starts all three Telegram bots in one asyncio event loop."""

import asyncio

import structlog
from telegram.ext import Application, ApplicationBuilder
from tortoise import Tortoise

from krankenfahrt.config import config
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

    # Handler registrieren
    # from krankenfahrt.bots.patient_bot import register_handlers
    # register_handlers(app)
    return app


async def build_driver_bot() -> Application:
    """Build the @FahrLenker bot for drivers."""
    app = ApplicationBuilder().token(config.DRIVER_BOT_TOKEN).build()

    # from krankenfahrt.bots.driver_bot import register_handlers
    # register_handlers(app)
    return app


async def build_chef_bot() -> Application:
    """Build the @FahrtenChef bot for owner/dispatcher."""
    app = ApplicationBuilder().token(config.CHEF_BOT_TOKEN).build()

    from krankenfahrt.bots.chef_bot import register_handlers
    register_handlers(app)
    return app


async def main() -> None:
    """Start all bots + health-check / metrics HTTP server."""
    setup_logging()

    logger.info("Krankenfahrt starting...")

    # Init database first (health server needs live DB)
    await init_database()
    logger.info("Database initialized")

    # Start the Prometheus metrics + health-check HTTP server
    metrics_server = MetricsServer(
        host=config.HEALTH_HOST,
        port=config.HEALTH_PORT,
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
        await metrics_server.stop()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
