"""Entry point for ``python -m organizr_tab_controller``.

Configures structured logging, loads settings from the environment, and
runs the controller with graceful shutdown on SIGINT / SIGTERM.
"""

from __future__ import annotations

import signal
import sys

import structlog


def _configure_logging(log_level: str, log_format: str) -> None:
    """Set up structlog with the chosen format and level."""
    import logging

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    """Load config, wire up signals, and start the controller."""
    from organizr_tab_controller.config import load_settings
    from organizr_tab_controller.controller import TabController

    # Load settings first (may fail fast on missing env vars)
    try:
        settings = load_settings()
    except Exception as exc:
        # Minimal logging before structlog is configured
        print(f"ERROR: Failed to load settings: {exc}", file=sys.stderr)
        sys.exit(1)

    _configure_logging(settings.log_level, settings.log_format)
    logger = structlog.get_logger("main")
    logger.info(
        "organizr_tab_controller_starting",
        version="0.1.0",
        api_url=settings.api_url,
        sync_policy=settings.sync_policy.value,
    )

    controller = TabController(settings)

    # Graceful shutdown on signals
    def _shutdown(signum: int, _frame: object) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = str(signum)
        logger.info("signal_received", signal=sig_name)
        controller.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        controller.start()
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
    finally:
        controller.stop()
        logger.info("organizr_tab_controller_exited")


if __name__ == "__main__":
    main()
