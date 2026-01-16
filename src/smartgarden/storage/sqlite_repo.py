# src/smartgarden/storage/sqlite_repo.py
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from smartgarden.models.types import (
    ActionType,
    DeviceState,
    SensorReading,
    ActuationEvent,
    ControlState,
)


def _iso(dt: datetime) -> str:
    """Normalize datetimes to UTC ISO-8601 strings."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> Optional[datetime]:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class SQLiteRepo:
    """
    SQLite repository that supports:
      - sensor readings history
      - actuation events
      - adaptive control state
      - calibration jobs for feedback-based learning
      - (optional) control_decisions for analytics page
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
        finally:
            conn.close()

    # ---------------------------
    # Schema
    # ---------------------------

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            c = conn.cursor()

            # Sensor readings
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_readings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT NOT NULL,

                  temperature_c REAL NOT NULL,
                  humidity_pct REAL NOT NULL,
                  pressure_hpa REAL NOT NULL,
                  light_lux REAL NOT NULL,

                  soil_moisture REAL NOT NULL,
                  soil_temperature_c REAL NOT NULL,

                  gas_ohms REAL,
                  altitude_m REAL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_sensor_readings_ts ON sensor_readings(timestamp)")

            # Actuation events
            # action_type: 'irrigate' or 'light'
            # state: 'on' or 'off'
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS actuation_events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT NOT NULL,
                  action_type TEXT NOT NULL,
                  state TEXT NOT NULL,

                  duration_seconds REAL,
                  reason TEXT,

                  predicted_time_to_stress_minutes REAL,
                  moisture_at_time REAL,

                  metadata_json TEXT
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_actuation_events_ts ON actuation_events(timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_actuation_events_type ON actuation_events(action_type)")

            # Control state (single row)
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS control_state (
                  id INTEGER PRIMARY KEY CHECK (id = 1),
                  updated_at TEXT NOT NULL,
                  absorption_gain_per_sec REAL NOT NULL,
                  drying_rate_per_min REAL NOT NULL,
                  last_irrigation_at TEXT
                )
                """
            )

            # Calibration jobs
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_jobs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,

                  irrigation_on_timestamp TEXT NOT NULL,
                  pre_moisture REAL NOT NULL,
                  pulse_duration_seconds REAL NOT NULL,

                  due_at TEXT NOT NULL,

                  status TEXT NOT NULL DEFAULT 'pending',  -- pending|completed

                  completed_at TEXT,
                  post_moisture REAL,
                  delta_moisture REAL,
                  gain_estimate_per_sec REAL,
                  applied_gain_per_sec REAL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_calibration_jobs_due ON calibration_jobs(due_at)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_calibration_jobs_status ON calibration_jobs(status)")

            # (Optional) decisions table for analytics/history
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS control_decisions (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT NOT NULL,
                  decision TEXT NOT NULL,               -- irrigate|no_action|blocked
                  reason TEXT,
                  pump_duration_seconds REAL,
                  predicted_time_to_stress_minutes REAL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_control_decisions_ts ON control_decisions(timestamp)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_control_decisions_decision ON control_decisions(decision)")

            # Ensure the control_state single row exists
            row = c.execute("SELECT id FROM control_state WHERE id = 1").fetchone()
            if row is None:
                now = datetime.now(timezone.utc)
                c.execute(
                    """
                    INSERT INTO control_state (id, updated_at, absorption_gain_per_sec, drying_rate_per_min, last_irrigation_at)
                    VALUES (1, ?, ?, ?, NULL)
                    """,
                    (_iso(now), 1.0, 0.0),
                )

            conn.commit()

    # ---------------------------
    # Sensor readings
    # ---------------------------

    def insert_sensor_reading(self, reading: SensorReading) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sensor_readings (
                  timestamp,
                  temperature_c, humidity_pct, pressure_hpa, light_lux,
                  soil_moisture, soil_temperature_c,
                  gas_ohms, altitude_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(reading.timestamp),
                    float(reading.temperature_c),
                    float(reading.humidity_pct),
                    float(reading.pressure_hpa),
                    float(reading.light_lux),
                    float(reading.soil_moisture),
                    float(reading.soil_temperature_c),
                    float(reading.gas_ohms) if reading.gas_ohms is not None else None,
                    float(reading.altitude_m) if reading.altitude_m is not None else None,
                ),
            )
            conn.commit()

    def fetch_recent_readings(self, minutes: int) -> list[SensorReading]:
        since = datetime.now(timezone.utc) - timedelta(minutes=int(minutes))
        since_s = _iso(since)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  timestamp,
                  temperature_c, humidity_pct, pressure_hpa, light_lux,
                  soil_moisture, soil_temperature_c,
                  gas_ohms, altitude_m
                FROM sensor_readings
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (since_s,),
            ).fetchall()

        out: list[SensorReading] = []
        for r in rows:
            ts = _parse_iso(r["timestamp"]) or datetime.now(timezone.utc)
            out.append(
                SensorReading(
                    timestamp=ts,
                    temperature_c=float(r["temperature_c"]),
                    humidity_pct=float(r["humidity_pct"]),
                    pressure_hpa=float(r["pressure_hpa"]),
                    light_lux=float(r["light_lux"]),
                    soil_moisture=float(r["soil_moisture"]),
                    soil_temperature_c=float(r["soil_temperature_c"]),
                    gas_ohms=float(r["gas_ohms"]) if r["gas_ohms"] is not None else None,
                    altitude_m=float(r["altitude_m"]) if r["altitude_m"] is not None else None,
                )
            )
        return out

    def fetch_first_reading_at_or_after(self, ts: datetime) -> Optional[tuple[datetime, float]]:
        ts_s = _iso(ts)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT timestamp, soil_moisture
                FROM sensor_readings
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT 1
                """,
                (ts_s,),
            ).fetchone()

        if row is None:
            return None

        found_ts = _parse_iso(row["timestamp"]) or ts
        return (found_ts, float(row["soil_moisture"]))

    # ---------------------------
    # Actuation events
    # ---------------------------

    def insert_actuation_event(self, event: ActuationEvent) -> None:
        metadata_json: Optional[str] = None
        if event.metadata:
            try:
                metadata_json = json.dumps(event.metadata)
            except Exception:
                metadata_json = None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO actuation_events (
                  timestamp, action_type, state,
                  duration_seconds, reason,
                  predicted_time_to_stress_minutes, moisture_at_time,
                  metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _iso(event.timestamp),
                    event.action_type.value,
                    event.state.value,
                    float(event.duration_seconds) if event.duration_seconds is not None else None,
                    event.reason,
                    float(event.predicted_time_to_stress_minutes)
                    if event.predicted_time_to_stress_minutes is not None
                    else None,
                    float(event.moisture_at_time) if event.moisture_at_time is not None else None,
                    metadata_json,
                ),
            )
            conn.commit()

    def sum_irrigation_seconds_in_range(self, start: datetime, end: datetime) -> float:
        start_s = _iso(start)
        end_s = _iso(end)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(duration_seconds), 0.0) AS total
                FROM actuation_events
                WHERE action_type = ?
                  AND state = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                """,
                (ActionType.IRRIGATE.value, DeviceState.ON.value, start_s, end_s),
            ).fetchone()

        return float(row["total"]) if row and row["total"] is not None else 0.0

    def count_irrigation_pulses_in_range(self, start: datetime, end: datetime) -> int:
        start_s = _iso(start)
        end_s = _iso(end)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM actuation_events
                WHERE action_type = ?
                  AND state = ?
                  AND timestamp >= ?
                  AND timestamp < ?
                """,
                (ActionType.IRRIGATE.value, DeviceState.ON.value, start_s, end_s),
            ).fetchone()

        return int(row["cnt"]) if row and row["cnt"] is not None else 0

    # ---------------------------
    # Control state
    # ---------------------------

    def get_control_state(self) -> ControlState:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM control_state WHERE id = 1").fetchone()

        if row is None:
            now = datetime.now(timezone.utc)
            return ControlState(
                updated_at=now,
                absorption_gain_per_sec=1.0,
                drying_rate_per_min=0.0,
                last_irrigation_at=None,
            )

        return ControlState(
            updated_at=_parse_iso(row["updated_at"]) or datetime.now(timezone.utc),
            absorption_gain_per_sec=float(row["absorption_gain_per_sec"]),
            drying_rate_per_min=float(row["drying_rate_per_min"]),
            last_irrigation_at=_parse_iso(row["last_irrigation_at"]),
        )

    def upsert_control_state(self, state: ControlState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE control_state
                SET updated_at = ?,
                    absorption_gain_per_sec = ?,
                    drying_rate_per_min = ?,
                    last_irrigation_at = ?
                WHERE id = 1
                """,
                (
                    _iso(state.updated_at),
                    float(state.absorption_gain_per_sec),
                    float(state.drying_rate_per_min),
                    _iso(state.last_irrigation_at) if state.last_irrigation_at else None,
                ),
            )
            conn.commit()

    # ---------------------------
    # Calibration jobs
    # ---------------------------

    def create_calibration_job(
        self,
        *,
        irrigation_on_timestamp: datetime,
        pre_moisture: float,
        pulse_duration_seconds: float,
        due_at: datetime,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO calibration_jobs (
                  irrigation_on_timestamp, pre_moisture, pulse_duration_seconds, due_at, status
                ) VALUES (?, ?, ?, ?, 'pending')
                """,
                (
                    _iso(irrigation_on_timestamp),
                    float(pre_moisture),
                    float(pulse_duration_seconds),
                    _iso(due_at),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def fetch_due_calibration_jobs(self, *, now: datetime, limit: int = 5) -> list[dict[str, Any]]:
        now_s = _iso(now)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM calibration_jobs
                WHERE status = 'pending'
                  AND due_at <= ?
                ORDER BY due_at ASC
                LIMIT ?
                """,
                (now_s, int(limit)),
            ).fetchall()

        return [dict(r) for r in rows]

    def complete_calibration_job(
        self,
        *,
        job_id: int,
        completed_at: datetime,
        post_moisture: float,
        delta_moisture: float,
        gain_estimate_per_sec: float,
        applied_gain_per_sec: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE calibration_jobs
                SET status = 'completed',
                    completed_at = ?,
                    post_moisture = ?,
                    delta_moisture = ?,
                    gain_estimate_per_sec = ?,
                    applied_gain_per_sec = ?
                WHERE id = ?
                """,
                (
                    _iso(completed_at),
                    float(post_moisture),
                    float(delta_moisture),
                    float(gain_estimate_per_sec),
                    float(applied_gain_per_sec),
                    int(job_id),
                ),
            )
            conn.commit()

    # ---------------------------
    # Decisions (for Analytics page)
    # ---------------------------

    def insert_decision(
        self,
        *,
        timestamp: datetime,
        decision: str,  # irrigate|no_action|blocked
        reason: str | None,
        pump_duration_seconds: float | None,
        predicted_time_to_stress_minutes: float | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO control_decisions (
                  timestamp, decision, reason, pump_duration_seconds, predicted_time_to_stress_minutes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    _iso(timestamp),
                    decision,
                    reason,
                    float(pump_duration_seconds) if pump_duration_seconds is not None else None,
                    float(predicted_time_to_stress_minutes)
                    if predicted_time_to_stress_minutes is not None
                    else None,
                ),
            )
            conn.commit()

    def fetch_decisions_since(self, since: datetime, limit: int = 20) -> list[dict[str, Any]]:
        since_s = _iso(since)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, decision, reason, pump_duration_seconds, predicted_time_to_stress_minutes
                FROM control_decisions
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (since_s, int(limit)),
            ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "decision": r["decision"],
                "reason": r["reason"],
                "pump_duration_seconds": r["pump_duration_seconds"],
                "predicted_time_to_stress_minutes": r["predicted_time_to_stress_minutes"],
            }
            for r in rows
        ]

    def count_decisions_since(self, since: datetime, decision: str, reason_like: str | None = None) -> int:
        since_s = _iso(since)
        with self._connect() as conn:
            if reason_like:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM control_decisions
                    WHERE timestamp >= ?
                      AND decision = ?
                      AND reason LIKE ?
                    """,
                    (since_s, decision, f"%{reason_like}%"),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM control_decisions
                    WHERE timestamp >= ?
                      AND decision = ?
                    """,
                    (since_s, decision),
                ).fetchone()

        return int(row["cnt"]) if row and row["cnt"] is not None else 0

    def avg_soil_moisture_since(self, since: datetime) -> float | None:
        since_s = _iso(since)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT AVG(soil_moisture) AS avg_m FROM sensor_readings WHERE timestamp >= ?",
                (since_s,),
            ).fetchone()

        if row is None or row["avg_m"] is None:
            return None
        return float(row["avg_m"])










    def fetch_readings_since(self, since: datetime, limit: int = 2000) -> list[SensorReading]:
        since_s = _iso(since)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  timestamp,
                  temperature_c, humidity_pct, pressure_hpa, light_lux,
                  soil_moisture, soil_temperature_c,
                  gas_ohms, altitude_m
                FROM sensor_readings
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (since_s, int(limit)),
            ).fetchall()

        out: list[SensorReading] = []
        for r in rows:
            ts = _parse_iso(r["timestamp"]) or datetime.now(timezone.utc)
            out.append(
                SensorReading(
                    timestamp=ts,
                    temperature_c=float(r["temperature_c"]),
                    humidity_pct=float(r["humidity_pct"]),
                    pressure_hpa=float(r["pressure_hpa"]),
                    light_lux=float(r["light_lux"]),
                    soil_moisture=float(r["soil_moisture"]),
                    soil_temperature_c=float(r["soil_temperature_c"]),
                    gas_ohms=float(r["gas_ohms"]) if r["gas_ohms"] is not None else None,
                    altitude_m=float(r["altitude_m"]) if r["altitude_m"] is not None else None,
                )
            )
        return out

    def fetch_irrigation_events_since(self, since: datetime, limit: int = 500) -> list[dict[str, Any]]:
        """
        Returns irrigation 'ON' events (pulses). Dictionary objects so it's easy to serialize.

        Fields:
          - timestamp
          - duration_seconds
          - reason
          - predicted_time_to_stress_minutes
          - moisture_at_time
        """
        since_s = _iso(since)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  timestamp, duration_seconds, reason,
                  predicted_time_to_stress_minutes, moisture_at_time
                FROM actuation_events
                WHERE timestamp >= ?
                  AND action_type = ?
                  AND state = ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (
                    since_s,
                    ActionType.IRRIGATE.value,
                    DeviceState.ON.value,
                    int(limit),
                ),
            ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "duration_seconds": r["duration_seconds"],
                "reason": r["reason"],
                "predicted_time_to_stress_minutes": r["predicted_time_to_stress_minutes"],
                "moisture_at_time": r["moisture_at_time"],
            }
            for r in rows
        ]


    def fetch_latest_reading(self) -> Optional[SensorReading]:
        """
        Return the most recent sensor reading, or None if table is empty.
        """
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  timestamp,
                  temperature_c, humidity_pct, pressure_hpa, light_lux,
                  soil_moisture, soil_temperature_c,
                  gas_ohms, altitude_m
                FROM sensor_readings
                ORDER BY timestamp DESC
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        ts = _parse_iso(row["timestamp"]) or datetime.now(timezone.utc)
        return SensorReading(
            timestamp=ts,
            temperature_c=float(row["temperature_c"]),
            humidity_pct=float(row["humidity_pct"]),
            pressure_hpa=float(row["pressure_hpa"]),
            light_lux=float(row["light_lux"]),
            soil_moisture=float(row["soil_moisture"]),
            soil_temperature_c=float(row["soil_temperature_c"]),
            gas_ohms=float(row["gas_ohms"]) if row["gas_ohms"] is not None else None,
            altitude_m=float(row["altitude_m"]) if row["altitude_m"] is not None else None,
        )
