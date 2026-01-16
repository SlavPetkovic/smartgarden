from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from smartgarden.models.types import ActuationEvent, ActionType, DeviceState

@dataclass
class MockActuator:
    """
    Development-only actuator.

    Simulates:
      - pump pulses (ON for N seconds, then OFF)
      - light ON/OFF

    Returns ActuationEvent objects so you can store them and use them for
    feedback-based calibration later.
    """
    pump_state: DeviceState = DeviceState.OFF
    light_state: DeviceState = DeviceState.OFF

    def set_light(self, on: bool, reason: str = "") -> ActuationEvent:
        self.light_state = DeviceState.ON if on else DeviceState.OFF
        ts = datetime.now(timezone.utc)

        print(f"[ACTUATOR][MOCK] light -> {self.light_state.value} | reason={reason}")

        return ActuationEvent(
            timestamp=ts,
            action_type=ActionType.LIGHT,
            state=self.light_state,
            duration_seconds=None,
            reason=reason,
        )

    def pulse_pump(self, duration_seconds: float, reason: str = "", simulate_wait: bool = True) -> list[ActuationEvent]:
        """
        Turn pump ON for duration_seconds, then OFF.

        In dev mode, we can optionally sleep to mimic real timing.
        """
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be > 0")

        events: list[ActuationEvent] = []

        ts_on = datetime.now(timezone.utc)
        self.pump_state = DeviceState.ON
        print(f"[ACTUATOR][MOCK] pump -> on  ({duration_seconds:.2f}s) | reason={reason}")

        events.append(
            ActuationEvent(
                timestamp=ts_on,
                action_type=ActionType.IRRIGATE,
                state=DeviceState.ON,
                duration_seconds=duration_seconds,
                reason=reason,
            )
        )

        if simulate_wait:
            time.sleep(duration_seconds)

        ts_off = datetime.now(timezone.utc)
        self.pump_state = DeviceState.OFF
        print(f"[ACTUATOR][MOCK] pump -> off | reason={reason}")

        events.append(
            ActuationEvent(
                timestamp=ts_off,
                action_type=ActionType.IRRIGATE,
                state=DeviceState.OFF,
                duration_seconds=None,
                reason=reason,
            )
        )

        return events
