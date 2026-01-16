from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smartgarden.config import Settings
from smartgarden.models.types import ControlDecision, SensorReading, ControlState


def _local_now(settings: Settings, now_utc: datetime) -> datetime:
    tz = ZoneInfo(settings.timezone_str)
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    return now_utc.astimezone(tz)


def is_within_watering_window(settings: Settings, now_utc: datetime) -> bool:
    """
    True if local time is within [start_hour, end_hour).
    Supports windows that wrap midnight (e.g., 22 -> 6).
    """
    local = _local_now(settings, now_utc)
    h = local.hour
    start_h = settings.watering_window_start_hour
    end_h = settings.watering_window_end_hour

    if start_h == end_h:
        # Edge case: treat as "always allowed"
        return True

    if start_h < end_h:
        return start_h <= h < end_h
    # wraps midnight
    return h >= start_h or h < end_h


def apply_constraints(
    *,
    settings: Settings,
    now_utc: datetime,
    latest: SensorReading,
    state: ControlState,
    decision: ControlDecision,
    irrigation_seconds_today: float,
    irrigation_pulses_last_hour: int,
) -> ControlDecision:
    """
    Applies nighttime + safety constraints by overriding/clamping the engine decision.
    Returns a (possibly) modified decision.

    Constraints:
      - Watering allowed only within time window, unless emergency
      - Daily irrigation budget in seconds (sum of ON pulse durations)
      - Max pulses per hour (count of irrigation ON events)
      - Clamp pulse duration to remaining daily budget
    """
    # If engine wasn't going to irrigate, nothing to constrain (we leave lights alone)
    if not decision.should_irrigate or not decision.pump_duration_seconds:
        return decision

    emergency = latest.soil_moisture <= settings.emergency_moisture_threshold

    # Nighttime / time-window constraint
    if not is_within_watering_window(settings, now_utc) and not emergency:
        return replace(
            decision,
            should_irrigate=False,
            pump_duration_seconds=None,
            reason=f"{decision.reason}; Blocked: outside watering window",
        )

    # Pulses-per-hour constraint
    if irrigation_pulses_last_hour >= settings.max_irrigation_pulses_per_hour and not emergency:
        return replace(
            decision,
            should_irrigate=False,
            pump_duration_seconds=None,
            reason=f"{decision.reason}; Blocked: max pulses/hour reached",
        )

    # Daily budget constraint (in seconds)
    remaining = max(0.0, settings.daily_irrigation_budget_seconds - irrigation_seconds_today)
    if remaining <= 0.0 and not emergency:
        return replace(
            decision,
            should_irrigate=False,
            pump_duration_seconds=None,
            reason=f"{decision.reason}; Blocked: daily irrigation budget exceeded",
        )

    # If emergency, still respect a hard max clamp to avoid runaway.
    hard_max = settings.pump_max_pulse_seconds

    # Clamp dose to remaining budget (and safety max)
    clamped = min(float(decision.pump_duration_seconds), remaining if remaining > 0 else hard_max, hard_max)
    clamped = max(settings.pump_min_pulse_seconds, clamped)

    if clamped != decision.pump_duration_seconds:
        return replace(
            decision,
            pump_duration_seconds=clamped,
            reason=f"{decision.reason}; Clamped dose to {clamped:.2f}s (remaining budget={remaining:.2f}s)",
        )

    return decision
