from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone

from smartgarden.models.types import SensorReading


@dataclass(frozen=True)
class MockRanges:
    # Ambient
    temperature_c_min: float = 15.0
    temperature_c_max: float = 30.0
    humidity_pct_min: float = 30.0
    humidity_pct_max: float = 70.0
    pressure_hpa_min: float = 950.0
    pressure_hpa_max: float = 1050.0
    light_lux_min: float = 0.0
    light_lux_max: float = 1000.0

    # Soil moisture bounds (raw-ish)
    soil_moisture_min: float = 200.0
    soil_moisture_max: float = 800.0

    # Soil temperature
    soil_temperature_c_min: float = 10.0
    soil_temperature_c_max: float = 25.0

    # Optional
    gas_ohms_min: float = 0.0
    gas_ohms_max: float = 500.0
    altitude_m_min: float = 0.0
    altitude_m_max: float = 500.0


class MockSensorReader:
    """
    Development-only sensor reader.

    Key improvement vs random snapshots:
    - soil moisture follows a simple dynamic model:
        * gradual drying over time
        * small noise
        * optional bump after watering (notify_irrigation)

    This produces realistic slopes so the predictive engine behaves sensibly.
    """

    def __init__(
        self,
        ranges: MockRanges | None = None,
        seed: int | None = None,
        drying_rate_per_min: float = 1.2,
        noise_amplitude: float = 0.8,
        irrigation_bump: float = 40.0,
    ):
        self.ranges = ranges or MockRanges()
        if seed is not None:
            random.seed(seed)

        self.drying_rate_per_min = float(drying_rate_per_min)
        self.noise_amplitude = float(noise_amplitude)

        # How much moisture increases when we simulate a watering pulse
        self.irrigation_bump = float(irrigation_bump)

        # Internal state
        r = self.ranges
        self._soil_moisture = random.uniform(r.soil_moisture_min, r.soil_moisture_max)
        self._last_ts: datetime | None = None

        # Accumulates pending moisture increases from irrigation events
        self._pending_irrigation_delta: float = 0.0

    def notify_irrigation(self, duration_seconds: float) -> None:
        """
        Optional hook: call this after a pump pulse to simulate increased moisture.

        We intentionally keep it simple: moisture increase is proportional to pulse duration.
        Later, this is where calibration behavior can be modeled.
        """
        # You can tune this coefficient later; for now it is "bump per pulse-second"
        bump_per_second = self.irrigation_bump / 3.0  # 3s pulse -> ~irrigation_bump
        self._pending_irrigation_delta += bump_per_second * max(0.0, duration_seconds)

    def read(self) -> SensorReading:
        r = self.ranges
        ts = datetime.now(timezone.utc)

        # Ambient (still random, because these change faster and are less critical)
        temperature_c = round(random.uniform(r.temperature_c_min, r.temperature_c_max), 2)
        humidity_pct = round(random.uniform(r.humidity_pct_min, r.humidity_pct_max), 2)
        pressure_hpa = round(random.uniform(r.pressure_hpa_min, r.pressure_hpa_max), 2)
        light_lux = round(random.uniform(r.light_lux_min, r.light_lux_max), 2)

        # Soil temperature (random within band for now)
        soil_temperature_c = round(
            random.uniform(r.soil_temperature_c_min, r.soil_temperature_c_max), 2
        )

        # Optional sensors
        gas_ohms = round(random.uniform(r.gas_ohms_min, r.gas_ohms_max), 2)
        altitude_m = round(random.uniform(r.altitude_m_min, r.altitude_m_max), 2)

        # --- soil moisture model (gradual dynamics) ---
        if self._last_ts is None:
            dt_min = 0.0
        else:
            dt_min = max((ts - self._last_ts).total_seconds() / 60.0, 0.0)

        # Apply drying over time
        self._soil_moisture -= self.drying_rate_per_min * dt_min

        # Apply pending irrigation effect (if any)
        if self._pending_irrigation_delta != 0.0:
            self._soil_moisture += self._pending_irrigation_delta
            self._pending_irrigation_delta = 0.0

        # Apply small noise
        self._soil_moisture += random.uniform(-self.noise_amplitude, self.noise_amplitude)

        # Clamp to bounds
        self._soil_moisture = max(
            r.soil_moisture_min, min(r.soil_moisture_max, self._soil_moisture)
        )

        self._last_ts = ts
        soil_moisture = round(self._soil_moisture, 2)

        return SensorReading(
            timestamp=ts,
            temperature_c=temperature_c,
            humidity_pct=humidity_pct,
            pressure_hpa=pressure_hpa,
            light_lux=light_lux,
            soil_moisture=soil_moisture,
            soil_temperature_c=soil_temperature_c,
            gas_ohms=gas_ohms,
            altitude_m=altitude_m,
        )
