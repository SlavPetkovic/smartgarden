from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class ActionType(str, Enum):
    IRRIGATE = "irrigate"
    LIGHT = "light"


class DeviceState(str, Enum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class SensorReading:
    """
    One snapshot of sensor data.

    Keep this hardware-agnostic. Even if your Pi provides extra fields,
    store them here only if they are meaningful to control decisions.
    """
    timestamp: datetime

    # Environment
    temperature_c: float
    humidity_pct: float
    pressure_hpa: float
    light_lux: float

    # Soil
    soil_moisture: float  # raw or normalized; start raw, calibrate later
    soil_temperature_c: float

    # Optional fields (can be None if sensor not present)
    gas_ohms: Optional[float] = None
    altitude_m: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "temperature_c": self.temperature_c,
            "humidity_pct": self.humidity_pct,
            "pressure_hpa": self.pressure_hpa,
            "light_lux": self.light_lux,
            "soil_moisture": self.soil_moisture,
            "soil_temperature_c": self.soil_temperature_c,
            "gas_ohms": self.gas_ohms,
            "altitude_m": self.altitude_m,
        }


@dataclass(frozen=True)
class TrendIndicators:
    """
    Derived trend-based indicators computed from historical sensor data.

    These are the 'invention-facing' metrics: not raw sensors, but time-based features.
    """
    window_minutes: int

    # Moisture trend: negative means drying
    moisture_slope_per_min: float

    # Simple estimate of how fast moisture decays after watering (optional)
    moisture_decay_rate_per_min: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_minutes": self.window_minutes,
            "moisture_slope_per_min": self.moisture_slope_per_min,
            "moisture_decay_rate_per_min": self.moisture_decay_rate_per_min,
        }


@dataclass(frozen=True)
class Prediction:
    """
    Predictive outputs used for control decisions.
    """
    predicted_time_to_stress_minutes: Optional[float]  # None if cannot predict
    stress_threshold: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_time_to_stress_minutes": self.predicted_time_to_stress_minutes,
            "stress_threshold": self.stress_threshold,
        }


@dataclass(frozen=True)
class ControlDecision:
    """
    The controller's decision at a point in time.
    """
    timestamp: datetime
    should_irrigate: bool
    should_light_on: bool

    # Optional parameters for actuation
    pump_duration_seconds: Optional[float] = None

    # Explainability / audit (helps debugging + future patent narrative)
    indicators: Optional[TrendIndicators] = None
    prediction: Optional[Prediction] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "should_irrigate": self.should_irrigate,
            "should_light_on": self.should_light_on,
            "pump_duration_seconds": self.pump_duration_seconds,
            "reason": self.reason,
            "indicators": self.indicators.to_dict() if self.indicators else None,
            "prediction": self.prediction.to_dict() if self.prediction else None,
        }


@dataclass(frozen=True)
class ActuationEvent:
    """
    What the system actually did (or attempted to do).
    Store these in DB to enable feedback-based calibration.
    """
    timestamp: datetime
    action_type: ActionType
    state: DeviceState

    # For irrigation pulses, duration is important
    duration_seconds: Optional[float] = None

    # Why it was executed (ties back to ControlDecision)
    reason: str = ""

    # Optional: snapshot of predictive context
    predicted_time_to_stress_minutes: Optional[float] = None
    moisture_at_time: Optional[float] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action_type": self.action_type.value,
            "state": self.state.value,
            "duration_seconds": self.duration_seconds,
            "reason": self.reason,
            "predicted_time_to_stress_minutes": self.predicted_time_to_stress_minutes,
            "moisture_at_time": self.moisture_at_time,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ControlState:
    """
    Adaptive parameters that evolve over time.

    Start simple; we'll add more once the feedback loop exists.
    """
    updated_at: datetime

    # Learned / calibrated parameter: expected moisture increase per second of pump pulse
    # (initially a guess; updated from observed soil response)
    absorption_gain_per_sec: float = 1.0

    # Learned / calibrated parameter: expected moisture loss per minute (drying rate)
    drying_rate_per_min: float = 0.0

    # Cooldown tracking
    last_irrigation_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "updated_at": self.updated_at.isoformat(),
            "absorption_gain_per_sec": self.absorption_gain_per_sec,
            "drying_rate_per_min": self.drying_rate_per_min,
            "last_irrigation_at": self.last_irrigation_at.isoformat() if self.last_irrigation_at else None,
        }
