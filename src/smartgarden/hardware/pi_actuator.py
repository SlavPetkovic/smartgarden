# src/smartgarden/hardware/pi_actuator.py
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from smartgarden.models.types import ActuationEvent, ActionType, DeviceState


@dataclass
class PiActuator:
    light_pin: int = 24
    pump_pin: int = 23
    active_low: bool = True  # many relay boards are active-low

    def __post_init__(self) -> None:
        import RPi.GPIO as GPIO

        self._GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.light_pin, GPIO.OUT)
        GPIO.setup(self.pump_pin, GPIO.OUT)

        # start OFF
        self._write(self.light_pin, on=False)
        self._write(self.pump_pin, on=False)

    def _write(self, pin: int, on: bool) -> None:
        # Convert logical on/off to actual output level
        if self.active_low:
            level = self._GPIO.LOW if on else self._GPIO.HIGH
        else:
            level = self._GPIO.HIGH if on else self._GPIO.LOW
        self._GPIO.output(pin, level)

    def set_light(self, on: bool, reason: str = "") -> ActuationEvent:
        self._write(self.light_pin, on=on)
        ts = datetime.now(timezone.utc)

        return ActuationEvent(
            timestamp=ts,
            action_type=ActionType.LIGHT,
            state=DeviceState.ON if on else DeviceState.OFF,
            duration_seconds=None,
            reason=reason,
        )

    def pulse_pump(self, duration_seconds: float, reason: str = "", simulate_wait: bool = True) -> list[ActuationEvent]:
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be > 0")

        events: list[ActuationEvent] = []

        ts_on = datetime.now(timezone.utc)
        self._write(self.pump_pin, on=True)
        events.append(
            ActuationEvent(
                timestamp=ts_on,
                action_type=ActionType.IRRIGATE,
                state=DeviceState.ON,
                duration_seconds=duration_seconds,
                reason=reason,
            )
        )

        # On real hardware we DO want to wait
        time.sleep(duration_seconds)

        ts_off = datetime.now(timezone.utc)
        self._write(self.pump_pin, on=False)
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
