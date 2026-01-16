from __future__ import annotations

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

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
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_timestamp
ON sensor_readings(timestamp);

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
);

CREATE INDEX IF NOT EXISTS idx_actuation_events_timestamp
ON actuation_events(timestamp);

CREATE TABLE IF NOT EXISTS control_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  updated_at TEXT NOT NULL,
  absorption_gain_per_sec REAL NOT NULL,
  drying_rate_per_min REAL NOT NULL,
  last_irrigation_at TEXT
);

INSERT OR IGNORE INTO control_state (id, updated_at, absorption_gain_per_sec, drying_rate_per_min, last_irrigation_at)
VALUES (1, datetime('now'), 1.0, 0.0, NULL);

-- Persistent calibration jobs to support adaptive learning
CREATE TABLE IF NOT EXISTS calibration_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  irrigation_on_timestamp TEXT NOT NULL,
  pre_moisture REAL NOT NULL,
  pulse_duration_seconds REAL NOT NULL,
  due_at TEXT NOT NULL,

  completed_at TEXT,
  post_moisture REAL,
  delta_moisture REAL,
  gain_estimate_per_sec REAL,
  applied_gain_per_sec REAL
);

CREATE INDEX IF NOT EXISTS idx_calibration_jobs_due_at
ON calibration_jobs(due_at);

CREATE INDEX IF NOT EXISTS idx_calibration_jobs_completed_at
ON calibration_jobs(completed_at);
"""
