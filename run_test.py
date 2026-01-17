from __future__ import annotations

import logging
from threading import Thread

from smartgarden.config import get_settings
from smartgarden.sensing.mock_reader import MockSensorReader
from smartgarden.actuation.mock_actuator import MockActuator
from smartgarden.services.scheduler import make_scheduler


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_debug)

    print(f"[RUN] SmartGarden starting in '{settings.env}' mode")
    print(f"[RUN] DB path: {settings.db_path}")

    reader = MockSensorReader()
    actuator = MockActuator()

    scheduler = make_scheduler(
        settings=settings,
        reader=reader,
        actuator=actuator,
    )

    thread = Thread(target=scheduler.run_forever, daemon=True)
    thread.start()
    print("[RUN] Scheduler started")

    try:
        while True:
            thread.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\n[RUN] Shutdown requested. Exiting.")


if __name__ == "__main__":
    main()
