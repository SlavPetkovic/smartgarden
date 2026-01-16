from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from smartgarden.config import get_settings
from smartgarden.control.constraints import is_within_watering_window
from smartgarden.storage.sqlite_repo import SQLiteRepo

router = APIRouter()


def _today_local_range_utc(timezone_str: str, now_utc: datetime) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_str)
    local = now_utc.astimezone(tz)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return (start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc))


def _to_legacy_payload(latest_dict: dict) -> dict:
    """
    Your original dashboard expects:
      temperature, humidity, pressure, luminosity, soil_moisture, soil_temperature
    Our SensorReading dict uses:
      temperature_c, humidity_pct, pressure_hpa, light_lux, soil_moisture, soil_temperature_c
    """
    return {
        "temperature": latest_dict.get("temperature_c"),
        "humidity": latest_dict.get("humidity_pct"),
        "pressure": latest_dict.get("pressure_hpa"),
        "luminosity": latest_dict.get("light_lux"),
        "soil_moisture": latest_dict.get("soil_moisture"),
        "soil_temperature": latest_dict.get("soil_temperature_c"),
    }


@router.get("/sensors/latest")
async def sensors_latest():
    """
    NEW canonical endpoint under /api (when router is included with prefix="/api").
    Returns the most recent sensor reading in our internal schema.
    """
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)
    latest = repo.fetch_latest_reading()
    if not latest:
        return {"error": "No sensor readings yet"}
    return latest.to_dict()


@router.get("/status")
async def status():
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)

    now_utc = datetime.now(timezone.utc)

    latest = repo.fetch_latest_reading()
    state = repo.get_control_state()

    within_window = is_within_watering_window(settings, now_utc)

    day_start_utc, day_end_utc = _today_local_range_utc(settings.timezone_str, now_utc)
    irrigation_seconds_today = repo.sum_irrigation_seconds_in_range(day_start_utc, day_end_utc)

    hour_start_utc = now_utc - timedelta(hours=1)
    pulses_last_hour = repo.count_irrigation_pulses_in_range(hour_start_utc, now_utc)

    return {
        "time": {
            "now_utc": now_utc.isoformat(),
            "timezone": settings.timezone_str,
            "within_watering_window": within_window,
            "window_start_hour": settings.watering_window_start_hour,
            "window_end_hour": settings.watering_window_end_hour,
        },
        "latest": latest.to_dict() if latest else None,
        "control_state": {
            "updated_at": state.updated_at.isoformat(),
            "absorption_gain_per_sec": state.absorption_gain_per_sec,
            "drying_rate_per_min": state.drying_rate_per_min,
            "last_irrigation_at": state.last_irrigation_at.isoformat() if state.last_irrigation_at else None,
        },
        "constraints": {
            "emergency_moisture_threshold": settings.emergency_moisture_threshold,
            "daily_irrigation_budget_seconds": settings.daily_irrigation_budget_seconds,
            "daily_irrigation_used_seconds": irrigation_seconds_today,
            "daily_irrigation_remaining_seconds": max(
                0.0, settings.daily_irrigation_budget_seconds - irrigation_seconds_today
            ),
            "max_irrigation_pulses_per_hour": settings.max_irrigation_pulses_per_hour,
            "irrigation_pulses_last_hour": pulses_last_hour,
        },
    }


# -------------------------
# Legacy compatibility routes
# -------------------------

legacy_router = APIRouter()


@legacy_router.get("/sensors/latest")
async def legacy_sensors_latest():
    """
    Compatibility endpoint for your original UI JS:
      fetch('/sensors/latest') -> legacy payload keys.
    """
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)
    latest = repo.fetch_latest_reading()
    if not latest:
        return {
            "temperature": None,
            "humidity": None,
            "pressure": None,
            "luminosity": None,
            "soil_moisture": None,
            "soil_temperature": None,
        }
    return _to_legacy_payload(latest.to_dict())
