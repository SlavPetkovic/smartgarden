from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from smartgarden.config import Settings
from smartgarden.control.engine import ControlEngine
from smartgarden.control.constraints import apply_constraints
from smartgarden.models.types import (
    ControlState,
    SensorReading,
    ActuationEvent,
)
from smartgarden.storage.sqlite_repo import SQLiteRepo


class SensorReader(Protocol):
    def read(self) -> SensorReading: ...


class Actuator(Protocol):
    def set_light(self, on: bool, reason: str = "") -> ActuationEvent: ...
    def pulse_pump(
        self,
        duration_seconds: float,
        reason: str = "",
        simulate_wait: bool = True,
    ) -> list[ActuationEvent]: ...


@dataclass
class Scheduler:
    settings: Settings
    reader: SensorReader
    actuator: Actuator
    engine: ControlEngine
    repo: SQLiteRepo
    state: ControlState

    def _process_due_calibrations(self) -> None:
        now = datetime.now(timezone.utc)
        jobs = self.repo.fetch_due_calibration_jobs(now=now, limit=5)

        for job in jobs:
            due_at = datetime.fromisoformat(job["due_at"])
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)

            sample = self.repo.fetch_first_reading_at_or_after(due_at)
            if sample is None:
                continue

            sample_ts, post_moisture = sample
            pre_moisture = float(job["pre_moisture"])
            pulse_seconds = float(job["pulse_duration_seconds"])

            delta = post_moisture - pre_moisture
            if abs(delta) < self.settings.min_calibration_delta or pulse_seconds <= 0:
                gain_est = 0.0
                applied_gain = self.state.absorption_gain_per_sec
            else:
                gain_est = delta / pulse_seconds
                alpha = self.settings.calibration_alpha
                applied_gain = (1 - alpha) * self.state.absorption_gain_per_sec + alpha * gain_est

                self.state = ControlState(
                    updated_at=now,
                    absorption_gain_per_sec=applied_gain,
                    drying_rate_per_min=self.state.drying_rate_per_min,
                    last_irrigation_at=self.state.last_irrigation_at,
                )
                self.repo.upsert_control_state(self.state)

            self.repo.complete_calibration_job(
                job_id=int(job["id"]),
                completed_at=sample_ts,
                post_moisture=post_moisture,
                delta_moisture=delta,
                gain_estimate_per_sec=gain_est,
                applied_gain_per_sec=applied_gain,
            )

            if self.settings.log_debug:
                print(
                    "[CALIBRATION] job completed "
                    f"(id={job['id']}) pre={pre_moisture:.2f} post={post_moisture:.2f} "
                    f"delta={delta:.2f} gain_est={gain_est:.4f} applied_gain={applied_gain:.4f}"
                )

    def _today_local_range_utc(self, now_utc: datetime) -> tuple[datetime, datetime]:
        tz = ZoneInfo(self.settings.timezone_str)
        local = now_utc.astimezone(tz)
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return (start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc))

    def _decision_kind(self, should_irrigate: bool, reason: str) -> str:
        # Convention: constraints should prefix with "Blocked:"
        if reason and reason.lower().startswith("blocked"):
            return "blocked"
        return "irrigate" if should_irrigate else "no_action"

    def run_forever(self) -> None:
        if self.settings.log_debug:
            print("[SCHEDULER] starting loop")

        while True:
            try:
                # 0) process learning feedback first
                self._process_due_calibrations()

                now_utc = datetime.now(timezone.utc)

                # 1) read sensors
                reading = self.reader.read()
                if self.settings.log_debug:
                    print(f"[SCHEDULER] read: {reading.to_dict()}")

                # 2) store reading
                self.repo.insert_sensor_reading(reading)

                # 3) decide (engine)
                readings = self.repo.fetch_recent_readings(minutes=self.settings.history_window_minutes)
                decision = self.engine.decide(readings, self.state)
                if self.settings.log_debug:
                    print(f"[SCHEDULER] decision (pre-constraints): {decision.to_dict()}")

                # 4) safety stats
                day_start_utc, day_end_utc = self._today_local_range_utc(now_utc)
                irrigation_seconds_today = self.repo.sum_irrigation_seconds_in_range(day_start_utc, day_end_utc)

                hour_start_utc = now_utc - timedelta(hours=1)
                irrigation_pulses_last_hour = self.repo.count_irrigation_pulses_in_range(hour_start_utc, now_utc)

                # 5) apply constraints (nighttime, budgets, pulse limits)
                decision = apply_constraints(
                    settings=self.settings,
                    now_utc=now_utc,
                    latest=reading,
                    state=self.state,
                    decision=decision,
                    irrigation_seconds_today=irrigation_seconds_today,
                    irrigation_pulses_last_hour=irrigation_pulses_last_hour,
                )
                if self.settings.log_debug:
                    print(f"[SCHEDULER] decision (post-constraints): {decision.to_dict()}")

                predicted_tts = decision.prediction.predicted_time_to_stress_minutes if decision.prediction else None

                # 5.5) log decision for analytics
                self.repo.insert_decision(
                    timestamp=now_utc,
                    decision=self._decision_kind(decision.should_irrigate, decision.reason),
                    reason=decision.reason,
                    pump_duration_seconds=decision.pump_duration_seconds,
                    predicted_time_to_stress_minutes=predicted_tts,
                )

                # 6) lighting actuation + log
                light_event = self.actuator.set_light(decision.should_light_on, reason=decision.reason)
                self.repo.insert_actuation_event(
                    ActuationEvent(
                        timestamp=light_event.timestamp,
                        action_type=light_event.action_type,
                        state=light_event.state,
                        duration_seconds=light_event.duration_seconds,
                        reason=light_event.reason,
                        predicted_time_to_stress_minutes=predicted_tts,
                        moisture_at_time=reading.soil_moisture,
                        metadata=light_event.metadata,
                    )
                )

                # 7) irrigation actuation + log + update state + schedule calibration job
                if decision.should_irrigate and decision.pump_duration_seconds:
                    pre_moisture = reading.soil_moisture

                    events = self.actuator.pulse_pump(
                        duration_seconds=decision.pump_duration_seconds,
                        reason=decision.reason,
                        simulate_wait=False,
                    )

                    # Dev realism hook: allow mock reader to adjust values after irrigation
                    if hasattr(self.reader, "notify_irrigation"):
                        try:
                            self.reader.notify_irrigation(decision.pump_duration_seconds)
                        except Exception:
                            pass

                    for ev in events:
                        self.repo.insert_actuation_event(
                            ActuationEvent(
                                timestamp=ev.timestamp,
                                action_type=ev.action_type,
                                state=ev.state,
                                duration_seconds=ev.duration_seconds,
                                reason=ev.reason,
                                predicted_time_to_stress_minutes=predicted_tts,
                                moisture_at_time=pre_moisture,
                                metadata=ev.metadata,
                            )
                        )

                    # Use the ON event timestamp for cooldown + calibration scheduling
                    irrigation_on_ts = events[0].timestamp

                    self.state = ControlState(
                        updated_at=datetime.now(timezone.utc),
                        absorption_gain_per_sec=self.state.absorption_gain_per_sec,
                        drying_rate_per_min=self.state.drying_rate_per_min,
                        last_irrigation_at=irrigation_on_ts,
                    )
                    self.repo.upsert_control_state(self.state)

                    due_at = irrigation_on_ts + timedelta(seconds=self.settings.calibration_delay_seconds)
                    job_id = self.repo.create_calibration_job(
                        irrigation_on_timestamp=irrigation_on_ts,
                        pre_moisture=pre_moisture,
                        pulse_duration_seconds=decision.pump_duration_seconds,
                        due_at=due_at,
                    )
                    if self.settings.log_debug:
                        print(
                            f"[CALIBRATION] created job id={job_id} due_at={due_at.isoformat()} "
                            f"pre_moisture={pre_moisture:.2f} pulse_s={decision.pump_duration_seconds:.2f}"
                        )

                time.sleep(self.settings.control_interval_seconds)

            except Exception as e:
                print(f"[SCHEDULER][ERROR] {e}")
                time.sleep(2)


def make_scheduler(settings: Settings, reader: SensorReader, actuator: Actuator) -> Scheduler:
    engine = ControlEngine(settings=settings)
    repo = SQLiteRepo(db_path=settings.db_path)
    state = repo.get_control_state()

    return Scheduler(
        settings=settings,
        reader=reader,
        actuator=actuator,
        engine=engine,
        repo=repo,
        state=state,
    )
