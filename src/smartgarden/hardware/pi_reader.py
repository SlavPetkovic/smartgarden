# src/smartgarden/hardware/pi_reader.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from smartgarden.models.types import SensorReading


@dataclass
class PiSensorReader:
    """
    Raspberry Pi sensor reader (I2C).
    Uses:
      - BME680 (temp/humidity/pressure/gas/altitude)
      - VEML7700 (light)
      - Seesaw (soil moisture + soil temp)
    """

    def __post_init__(self) -> None:
        # Import Pi-only libs here so your laptop dev mode doesn't break
        import board
        import adafruit_bme680
        import adafruit_veml7700
        from adafruit_seesaw.seesaw import Seesaw

        i2c = board.I2C()

        self._veml = adafruit_veml7700.VEML7700(i2c)

        self._bme = adafruit_bme680.Adafruit_BME680_I2C(i2c, debug=False)
        self._bme.sea_level_pressure = 1013.25  # adjust for your location if desired

        self._ss = Seesaw(i2c, addr=0x36)

    def read(self) -> SensorReading:
        ts = datetime.now(timezone.utc)

        temperature_c = round(float(self._bme.temperature), 2)
        humidity_pct = round(float(self._bme.humidity), 2)
        pressure_hpa = round(float(self._bme.pressure), 2)
        gas_ohms = round(float(self._bme.gas), 2)
        altitude_m = round(float(self._bme.altitude), 2)

        light_lux = round(float(self._veml.light), 2)

        soil_moisture = round(float(self._ss.moisture_read()), 2)
        soil_temperature_c = round(float(self._ss.get_temp()), 2)

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
