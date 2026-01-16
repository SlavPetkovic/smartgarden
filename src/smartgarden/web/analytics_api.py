from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import APIRouter

from smartgarden.config import get_settings
from smartgarden.storage.sqlite_repo import SQLiteRepo

router = APIRouter()


def _since(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


@router.get("/summary")
async def summary(hours: int = 24) -> dict[str, Any]:
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)

    now = datetime.now(timezone.utc)
    last_24h = repo.sum_irrigation_seconds_in_range(now - timedelta(hours=24), now)
    last_7d = repo.sum_irrigation_seconds_in_range(now - timedelta(days=7), now)

    avg_m = repo.avg_soil_moisture_since(_since(hours))
    state = repo.get_control_state()

    # Stress avoided: count predictive irrigations (heuristic: decision=irrigate and reason contains "Predicted stress")
    avoided = repo.count_decisions_since(_since(24), decision="irrigate", reason_like="Predicted stress")

    return {
        "avg_soil_moisture": avg_m,
        "water_used_24h": last_24h,
        "water_used_7d": last_7d,
        "stress_events_avoided_24h": avoided,
        "absorption_gain_per_sec": state.absorption_gain_per_sec,
    }


@router.get("/timeseries")
async def timeseries(hours: int = 24) -> dict[str, Any]:
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)

    since = _since(hours)

    readings = repo.fetch_readings_since(since, limit=2000)
    irrig = repo.fetch_irrigation_events_since(since, limit=500)

    # attach soil moisture at event by nearest prior reading (simple)
    # repo method returns already enriched; if not, it's OK to be null.
    return {
        "readings": [r.to_dict() for r in readings],
        "irrigations": [e for e in irrig],
    }


@router.get("/decisions")
async def decisions(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    settings = get_settings()
    repo = SQLiteRepo(db_path=settings.db_path)

    since = _since(hours)
    items = repo.fetch_decisions_since(since, limit=limit)
    return {"items": items}
