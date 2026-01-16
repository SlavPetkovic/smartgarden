from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _env_str(key: str, default: str | None = None) -> str:
    val = os.getenv(key, default)
    if val is None or val.strip() == "":
        raise ValueError(f"Missing required environment variable: {key}")
    return val


def _env_int(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    return int(val)


def _env_float(key: str, default: float) -> float:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    return float(val)


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.getenv(key)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    # Runtime
    env: str
    base_dir: Path
    db_path: Path
    timezone_str: str  # e.g. "America/New_York"

    # Timing
    sample_interval_seconds: int
    control_interval_seconds: int

    # History / prediction
    history_window_minutes: int
    stress_moisture_threshold: float
    preempt_minutes: int

    # Pump (base)
    pump_pulse_seconds: float
    pump_min_cooldown_seconds: int

    # Lighting
    light_lux_threshold: float

    # Adaptive dosing
    target_buffer_above_stress: float
    pump_min_pulse_seconds: float
    pump_max_pulse_seconds: float

    # Adaptive calibration
    calibration_delay_seconds: int
    calibration_alpha: float
    min_calibration_delta: float

    # Nighttime + safety constraints
    watering_window_start_hour: int          # local hour 0-23
    watering_window_end_hour: int            # local hour 0-23
    emergency_moisture_threshold: float      # allow watering outside window if <= this
    daily_irrigation_budget_seconds: float   # max pump ON time per day
    max_irrigation_pulses_per_hour: int      # count of irrigation pulses per hour

    # Logging
    log_debug: bool


def get_settings() -> Settings:
    env = _env_str("ENV", "development").lower()
    if env not in {"development", "production"}:
        raise ValueError("ENV must be 'development' or 'production'")

    base_dir = Path(_env_str("SMARTGARDEN_BASE_DIR", str(Path.cwd()))).resolve()
    default_db_path = base_dir / "data" / "smartgarden.db"
    db_path = Path(os.getenv("SMARTGARDEN_DB_PATH", str(default_db_path))).resolve()

    return Settings(
        env=env,
        base_dir=base_dir,
        db_path=db_path,
        timezone_str=_env_str("TIMEZONE", "America/New_York"),

        sample_interval_seconds=_env_int("SAMPLE_INTERVAL_SECONDS", 10),
        control_interval_seconds=_env_int("CONTROL_INTERVAL_SECONDS", 10),

        history_window_minutes=_env_int("HISTORY_WINDOW_MINUTES", 60),
        stress_moisture_threshold=_env_float("STRESS_MOISTURE_THRESHOLD", 350.0),
        preempt_minutes=_env_int("PREEMPT_MINUTES", 30),

        pump_pulse_seconds=_env_float("PUMP_PULSE_SECONDS", 3.0),
        pump_min_cooldown_seconds=_env_int("PUMP_MIN_COOLDOWN_SECONDS", 300),

        light_lux_threshold=_env_float("LIGHT_LUX_THRESHOLD", 100.0),

        target_buffer_above_stress=_env_float("TARGET_BUFFER_ABOVE_STRESS", 40.0),
        pump_min_pulse_seconds=_env_float("PUMP_MIN_PULSE_SECONDS", 1.0),
        pump_max_pulse_seconds=_env_float("PUMP_MAX_PULSE_SECONDS", 12.0),

        calibration_delay_seconds=_env_int("CALIBRATION_DELAY_SECONDS", 300),
        calibration_alpha=_env_float("CALIBRATION_ALPHA", 0.2),
        min_calibration_delta=_env_float("MIN_CALIBRATION_DELTA", 2.0),

        watering_window_start_hour=_env_int("WATERING_WINDOW_START_HOUR", 7),
        watering_window_end_hour=_env_int("WATERING_WINDOW_END_HOUR", 22),
        emergency_moisture_threshold=_env_float("EMERGENCY_MOISTURE_THRESHOLD", 300.0),
        daily_irrigation_budget_seconds=_env_float("DAILY_IRRIGATION_BUDGET_SECONDS", 120.0),
        max_irrigation_pulses_per_hour=_env_int("MAX_IRRIGATION_PULSES_PER_HOUR", 6),

        log_debug=_env_bool("LOG_DEBUG", True),
    )
