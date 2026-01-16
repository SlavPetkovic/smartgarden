from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from smartgarden.config import Settings
from smartgarden.models.types import (
    SensorReading,
    TrendIndicators,
    Prediction,
    ControlDecision,
    ControlState,
)


class ControlEngine:
    """
    Predictive + adaptive control engine.

    Adds adaptive dosing:
      - computes pump duration based on required moisture increase
      - uses learned absorption_gain_per_sec from ControlState
      - clamps dose to safe min/max pulse limits
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def decide(self, readings: List[SensorReading], state: ControlState) -> ControlDecision:
        now = datetime.now(timezone.utc)

        if len(readings) < 2:
            return ControlDecision(
                timestamp=now,
                should_irrigate=False,
                should_light_on=False,
                reason="Not enough data to compute trends",
            )

        indicators = self._compute_trends(readings)
        latest = readings[-1]
        prediction = self._predict_time_to_stress(latest, indicators)

        # Lighting (v1 policy)
        should_light_on = latest.light_lux < self.settings.light_lux_threshold

        should_irrigate = False
        pump_duration: Optional[float] = None
        reason_parts: list[str] = []

        # Decide irrigation based on prediction OR immediate stress
        # Immediate stress case: moisture already <= threshold
        if latest.soil_moisture <= self.settings.stress_moisture_threshold:
            if self._cooldown_elapsed(state, now):
                should_irrigate = True
                pump_duration = self._compute_dose_seconds(
                    current_moisture=latest.soil_moisture,
                    absorption_gain_per_sec=max(1e-6, state.absorption_gain_per_sec),
                )
                reason_parts.append("Soil at/below stress threshold")
            else:
                reason_parts.append("Soil at/below stress threshold but pump cooldown active")

        # Predictive case
        elif prediction.predicted_time_to_stress_minutes is not None:
            if prediction.predicted_time_to_stress_minutes <= self.settings.preempt_minutes:
                if self._cooldown_elapsed(state, now):
                    should_irrigate = True
                    pump_duration = self._compute_dose_seconds(
                        current_moisture=latest.soil_moisture,
                        absorption_gain_per_sec=max(1e-6, state.absorption_gain_per_sec),
                    )
                    reason_parts.append(
                        f"Predicted stress in {prediction.predicted_time_to_stress_minutes:.1f} min"
                    )
                else:
                    reason_parts.append("Pump cooldown active")
            else:
                reason_parts.append(
                    f"Predicted stress in {prediction.predicted_time_to_stress_minutes:.1f} min (no action)"
                )
        else:
            # slope >= 0 or insufficient drying signal
            reason_parts.append("Soil not drying; no stress predicted")

        if should_light_on:
            reason_parts.append("Low ambient light")

        return ControlDecision(
            timestamp=now,
            should_irrigate=should_irrigate,
            should_light_on=should_light_on,
            pump_duration_seconds=pump_duration,
            indicators=indicators,
            prediction=prediction,
            reason="; ".join(reason_parts),
        )

    def _compute_dose_seconds(self, current_moisture: float, absorption_gain_per_sec: float) -> float:
        """
        Adaptive dosing:
        dose time is proportional to how far current moisture is below target.

        Target = stress_threshold + buffer.
        """
        target = self.settings.stress_moisture_threshold + self.settings.target_buffer_above_stress
        delta_needed = max(0.0, target - current_moisture)

        # Convert moisture deficit to seconds using learned gain
        raw_seconds = delta_needed / absorption_gain_per_sec if absorption_gain_per_sec > 0 else self.settings.pump_pulse_seconds

        # Clamp dose to safety bounds
        seconds = max(self.settings.pump_min_pulse_seconds, min(self.settings.pump_max_pulse_seconds, raw_seconds))

        return float(seconds)

    def _compute_trends(self, readings: List[SensorReading]) -> TrendIndicators:
        # same as before (windowed slope)
        from datetime import timedelta

        window = timedelta(minutes=self.settings.history_window_minutes)
        cutoff = readings[-1].timestamp - window

        windowed = [r for r in readings if r.timestamp >= cutoff]
        if len(windowed) < 2:
            windowed = readings[-2:]

        r0 = windowed[0]
        r1 = windowed[-1]

        dt_minutes = max((r1.timestamp - r0.timestamp).total_seconds() / 60.0, 1e-6)
        moisture_slope = (r1.soil_moisture - r0.soil_moisture) / dt_minutes

        return TrendIndicators(
            window_minutes=int(window.total_seconds() / 60),
            moisture_slope_per_min=moisture_slope,
            moisture_decay_rate_per_min=-moisture_slope if moisture_slope < 0 else 0.0,
        )

    def _predict_time_to_stress(self, latest: SensorReading, indicators: TrendIndicators) -> Prediction:
        slope = indicators.moisture_slope_per_min
        threshold = self.settings.stress_moisture_threshold

        # If soil is not drying, no prediction
        if slope >= 0:
            return Prediction(predicted_time_to_stress_minutes=None, stress_threshold=threshold)

        # If already stressed, predict 0
        delta = latest.soil_moisture - threshold
        if delta <= 0:
            return Prediction(predicted_time_to_stress_minutes=0.0, stress_threshold=threshold)

        minutes = delta / abs(slope)
        return Prediction(predicted_time_to_stress_minutes=minutes, stress_threshold=threshold)

    def _cooldown_elapsed(self, state: ControlState, now: datetime) -> bool:
        if state.last_irrigation_at is None:
            return True
        elapsed = (now - state.last_irrigation_at).total_seconds()
        return elapsed >= self.settings.pump_min_cooldown_seconds
