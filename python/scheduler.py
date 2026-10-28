"""Deterministic, explainable scheduling for weather-aware agricultural tasks.

The scheduler does not fetch weather or persist changes. Callers provide normalized
forecast points and an assessment evaluator. The evaluator is called for every
candidate window, allowing agricultural rules to be applied to the proposed time
instead of reusing the original task assessment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence


class SchedulerInputError(ValueError):
    """Raised when tasks, forecast data, or scheduling options are invalid."""


@dataclass(frozen=True)
class Task:
    id: str
    duration_minutes: int
    earliest_start: datetime
    deadline: datetime
    original_start: datetime | None = None
    preferred_start: datetime | None = None
    preferred_end: datetime | None = None
    priority: int = 0
    dependencies: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    title: str = ""
    activity: str = ""
    crop_name: str = ""
    crop_stage: str = ""
    chemical_target: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Task":
        required = ("id", "duration_minutes", "earliest_start", "deadline")
        missing = [key for key in required if key not in value]
        if missing:
            raise SchedulerInputError(
                f"Task is missing required field(s): {', '.join(missing)}"
            )
        task = cls(
            id=_as_non_empty_string(value["id"], "task id"),
            duration_minutes=_as_positive_int(
                value["duration_minutes"], "duration_minutes"
            ),
            earliest_start=_as_datetime(value["earliest_start"], "earliest_start"),
            deadline=_as_datetime(value["deadline"], "deadline"),
            original_start=_optional_datetime(value.get("original_start")),
            preferred_start=_optional_datetime(value.get("preferred_start")),
            preferred_end=_optional_datetime(value.get("preferred_end")),
            priority=_as_int(value.get("priority", 0), "priority"),
            dependencies=tuple(
                _as_non_empty_string(item, "dependency id")
                for item in value.get("dependencies", ())
            ),
            resources=tuple(
                _as_non_empty_string(item, "resource id")
                for item in value.get("resources", ())
            ),
            title=str(value.get("title", "")),
            activity=str(value.get("activity", "")).upper(),
            crop_name=str(value.get("crop_name", "")),
            crop_stage=str(value.get("crop_stage", "")),
            chemical_target=(
                None
                if value.get("chemical_target") is None
                else str(value["chemical_target"])
            ),
        )
        if task.deadline <= task.earliest_start:
            raise SchedulerInputError(
                f"Task {task.id!r} deadline must be after earliest_start"
            )
        if task.original_start and task.original_start.tzinfo is None:
            raise SchedulerInputError(f"Task {task.id!r} original_start must be timezone-aware")
        if task.preferred_start and task.preferred_end:
            if task.preferred_end <= task.preferred_start:
                raise SchedulerInputError(
                    f"Task {task.id!r} preferred_end must be after preferred_start"
                )
        return task


@dataclass(frozen=True)
class ForecastPoint:
    timestamp: datetime
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "ForecastPoint":
        if isinstance(value, ForecastPoint):
            point = value
        elif isinstance(value, Mapping) and "timestamp" in value:
            point = cls(
                timestamp=_as_datetime(value["timestamp"], "forecast timestamp"),
                data={
                    key: item for key, item in value.items() if key != "timestamp"
                },
            )
        else:
            raise SchedulerInputError(
                "Each forecast point must contain a timezone-aware timestamp"
            )
        if point.timestamp.tzinfo is None:
            raise SchedulerInputError("Forecast timestamps must be timezone-aware")
        return point


@dataclass(frozen=True)
class Assessment:
    status: str
    reasons: tuple[str, ...] = ()
    rule_references: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: Any) -> "Assessment":
        if isinstance(value, Assessment):
            assessment = value
        elif isinstance(value, Mapping):
            status = str(value.get("status", "")).strip().lower()
            reasons = tuple(str(item) for item in value.get("reasons", ()))
            references = tuple(
                str(item) for item in value.get("rule_references", ())
            )
            assessment = cls(status, reasons, references)
        else:
            raise SchedulerInputError("Assessment must be a mapping or Assessment")
        if assessment.status not in {"suitable", "unsuitable", "insufficient_data"}:
            raise SchedulerInputError(
                "Assessment status must be suitable, unsuitable, or insufficient_data"
            )
        return assessment


@dataclass(frozen=True)
class CandidateWindow:
    task_id: str
    start: datetime
    end: datetime
    assessment: Assessment


@dataclass(frozen=True)
class ScheduleResult:
    proposed_schedule: tuple[Mapping[str, Any], ...]
    alternatives: Mapping[str, tuple[Mapping[str, Any], ...]]
    changed_tasks: tuple[str, ...]
    unchanged_tasks: tuple[str, ...]
    unscheduled_tasks: tuple[Mapping[str, Any], ...]
    reasons: Mapping[str, tuple[str, ...]]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_schedule": list(self.proposed_schedule),
            "alternatives": {
                task_id: list(windows) for task_id, windows in self.alternatives.items()
            },
            "changed_tasks": list(self.changed_tasks),
            "unchanged_tasks": list(self.unchanged_tasks),
            "unscheduled_tasks": list(self.unscheduled_tasks),
            "reasons": {
                task_id: list(task_reasons)
                for task_id, task_reasons in self.reasons.items()
            },
            "limitations": list(self.limitations),
        }


AssessmentEvaluator = Callable[
    [Task, datetime, datetime, tuple[ForecastPoint, ...]], Assessment | Mapping[str, Any]
]


def generate_candidate_windows(
    task: Task | Mapping[str, Any],
    forecast: Sequence[ForecastPoint | Mapping[str, Any]],
    evaluator: AssessmentEvaluator,
) -> tuple[CandidateWindow, ...]:
    """Generate and assess windows aligned to the forecast's actual resolution."""
    normalized_task = _normalize_task(task)
    points = _normalize_forecast(forecast)
    if len(points) < 2:
        return ()
    resolution = _forecast_resolution(points)
    coverage_end = points[-1].timestamp + resolution
    candidates: list[CandidateWindow] = []
    duration = timedelta(minutes=normalized_task.duration_minutes)
    starts = {point.timestamp for point in points}
    if normalized_task.original_start is not None:
        starts.add(normalized_task.original_start)
    for start in sorted(starts):
        end = start + duration
        if start < normalized_task.earliest_start or end > normalized_task.deadline:
            continue
        if end > coverage_end:
            continue
        window_points = tuple(
            item for item in points
            if (
                (
                    item.data["period_end"] > start
                    if "period_end" in item.data
                    else item.timestamp >= start
                )
                and item.timestamp < end
            )
        )
        if not _has_continuous_forecast(window_points, start, end, resolution):
            continue
        assessment = Assessment.from_value(evaluator(normalized_task, start, end, window_points))
        candidates.append(CandidateWindow(normalized_task.id, start, end, assessment))
    return tuple(candidates)


def generate_schedule(
    tasks: Iterable[Task | Mapping[str, Any]],
    forecast: Sequence[ForecastPoint | Mapping[str, Any]],
    assessments: AssessmentEvaluator,
    options: Mapping[str, Any] | None = None,
) -> ScheduleResult:
    """Return a proposed schedule without mutating tasks or persisting changes.

    This is a constraint-aware greedy scheduler, not a proof of global optimality.
    Tasks are considered in dependency order, then by descending priority. A task
    is only scheduled after all prerequisites have been scheduled.
    """
    normalized_tasks = tuple(_normalize_task(task) for task in tasks)
    _validate_tasks(normalized_tasks)
    points = _normalize_forecast(forecast)
    options = options or {}
    max_alternatives = _as_non_negative_int(
        options.get("max_alternatives", 3), "max_alternatives"
    )
    limitations: list[str] = [
        "Greedy ranking is deterministic but does not prove global optimality."
    ]
    if len(points) < 2:
        limitations.append(
            "At least two forecast points are required to establish forecast resolution."
        )

    ordered = _dependency_order(normalized_tasks)
    task_by_id = {task.id: task for task in normalized_tasks}
    scheduled: dict[str, dict[str, Any]] = {}
    alternatives: dict[str, tuple[Mapping[str, Any], ...]] = {}
    reasons: dict[str, tuple[str, ...]] = {}
    unscheduled: list[Mapping[str, Any]] = []

    for task_id in ordered:
        task = task_by_id[task_id]
        dependency_entries = [scheduled.get(dep) for dep in task.dependencies]
        if any(entry is None for entry in dependency_entries):
            message = "A prerequisite could not be scheduled."
            reasons[task.id] = (message,)
            unscheduled.append({"task_id": task.id, "reasons": [message]})
            continue
        dependency_end = max(
            (entry["end"] for entry in dependency_entries if entry is not None),
            default=task.earliest_start,
        )

        candidates = generate_candidate_windows(task, points, assessments)
        feasible = [
            candidate
            for candidate in candidates
            if candidate.assessment.status == "suitable"
            and candidate.start >= dependency_end
            and not _overlaps_resource(candidate, task, scheduled)
        ]
        ranked = sorted(feasible, key=lambda item: _candidate_rank(item, task))
        if not ranked:
            task_reasons = _explain_no_window(task, candidates, dependency_end, scheduled)
            reasons[task.id] = tuple(task_reasons)
            unscheduled.append({"task_id": task.id, "reasons": task_reasons})
            continue

        selected = ranked[0]
        entry = _schedule_entry(task, selected)
        scheduled[task.id] = entry
        alternatives[task.id] = tuple(
            _schedule_entry(task, candidate) for candidate in ranked[1 : max_alternatives + 1]
        )
        if selected.start == task.original_start:
            reasons[task.id] = ("Original start remains suitable.",)
        else:
            reasons[task.id] = tuple(
                ["Moved to a suitable forecast window."]
                + list(selected.assessment.reasons)
            )

    proposed = tuple(sorted(scheduled.values(), key=lambda item: item["start"]))
    changed = tuple(
        task.id
        for task in normalized_tasks
        if task.id in scheduled and scheduled[task.id]["start"] != task.original_start
    )
    unchanged = tuple(
        task.id
        for task in normalized_tasks
        if task.id in scheduled and scheduled[task.id]["start"] == task.original_start
    )
    return ScheduleResult(
        proposed_schedule=proposed,
        alternatives=alternatives,
        changed_tasks=changed,
        unchanged_tasks=unchanged,
        unscheduled_tasks=tuple(unscheduled),
        reasons=reasons,
        limitations=tuple(limitations),
    )


def generate_plan_schedule(
    payload: Mapping[str, Any],
    assessment_evaluator: AssessmentEvaluator | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Adapt the backend plan contract to the shared ``ScheduleProposal`` shape.

    The optional evaluator is the integration point for Member 3's agricultural
    rules. If it is omitted, conservative metric-based checks are used; missing
    metrics produce ``INSUFFICIENT_INFO`` rather than a safe recommendation.
    """
    if not isinstance(payload, Mapping):
        raise SchedulerInputError("Plan payload must be an object")
    plan_id = _as_non_empty_string(payload.get("plan_id"), "plan_id")
    raw_tasks = payload.get("tasks")
    raw_periods = payload.get("forecast_periods")
    if not isinstance(raw_tasks, Sequence) or isinstance(raw_tasks, (str, bytes)):
        raise SchedulerInputError("tasks must be an array")
    if not isinstance(raw_periods, Sequence) or isinstance(raw_periods, (str, bytes)):
        raise SchedulerInputError("forecast_periods must be an array")
    policy = payload.get("policy", {})
    if not isinstance(policy, Mapping):
        raise SchedulerInputError("policy must be an object")

    tasks = tuple(_contract_task(value) for value in raw_tasks)
    periods = tuple(_contract_period(value) for value in raw_periods)
    if assessment_evaluator is None:
        def evaluator(
            task: Task,
            start: datetime,
            end: datetime,
            points: tuple[ForecastPoint, ...],
        ) -> Assessment:
            if task.activity == "IRRIGATION":
                points = tuple(
                    point for point in periods
                    if point.timestamp.astimezone(start.tzinfo).date()
                    == start.astimezone(start.tzinfo).date()
                )
            return _default_contract_assessment(task, start, end, points)
    else:
        evaluator = assessment_evaluator
    options = {
        "max_alternatives": 0,
    }
    schedule = generate_schedule(tasks, periods, evaluator, options)
    by_id = {task.id: task for task in tasks}
    schedule_by_id = {
        entry["task_id"]: entry for entry in schedule.proposed_schedule
    }
    unscheduled_by_id = {
        entry["task_id"]: entry for entry in schedule.unscheduled_tasks
    }
    output_tasks = [
        _contract_task_result(
            by_id[task.id],
            schedule_by_id.get(task.id),
            unscheduled_by_id.get(task.id),
            schedule.reasons.get(task.id, ()),
            periods,
        )
        for task in tasks
    ]
    summary = {
        "total_tasks": len(tasks),
        "unchanged_count": sum(
            result["change_type"] == "UNCHANGED" for result in output_tasks
        ),
        "rescheduled_count": sum(
            result["change_type"] == "RESCHEDULED" for result in output_tasks
        ),
        "unfeasible_count": sum(
            result["change_type"] in {"UNFEASIBLE_CONFLICT", "INSUFFICIENT_INFO"}
            for result in output_tasks
        ),
    }
    status = (
        "FEASIBLE"
        if summary["unfeasible_count"] == 0
        else "PARTIAL_FEASIBLE"
        if summary["rescheduled_count"] or summary["unchanged_count"]
        else "CONFLICT_UNRESOLVED"
    )
    at = generated_at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise SchedulerInputError("generated_at must be timezone-aware")
    return {
        "plan_id": plan_id,
        "generated_at": at.isoformat(),
        "evaluated_weather_source": str(payload.get("weather_source", "NORMALIZED_FORECAST")),
        "overall_status": status,
        "tasks": output_tasks,
        "summary": summary,
        "applied_constraints": {
            "respect_dependencies": bool(policy.get("respect_dependencies", True)),
            "respect_deadlines": bool(policy.get("respect_deadlines", True)),
            "priorities_considered": bool(policy.get("prioritize_critical_tasks", True)),
        },
        "unfeasible_reasons": [
            {"task_id": item["task_id"], "reasons": item["reasons"]}
            for item in output_tasks
            if item["change_type"] in {"UNFEASIBLE_CONFLICT", "INSUFFICIENT_INFO"}
        ],
    }


def _normalize_task(task: Task | Mapping[str, Any]) -> Task:
    if isinstance(task, Task):
        return task
    if isinstance(task, Mapping):
        return Task.from_mapping(task)
    raise SchedulerInputError("Tasks must be mappings or Task instances")


def _contract_task(value: Any) -> Task:
    if not isinstance(value, Mapping):
        raise SchedulerInputError("Each task must be an object")
    window = value.get("planned_window")
    if not isinstance(window, Mapping):
        raise SchedulerInputError("Each task must contain planned_window")
    start = _as_datetime(window.get("start_time"), "planned_window.start_time")
    end = _as_datetime(window.get("end_time"), "planned_window.end_time")
    duration = value.get("duration_hours")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise SchedulerInputError("duration_hours must be positive")
    if end <= start:
        raise SchedulerInputError("planned_window.end_time must be after start_time")
    return Task.from_mapping(
        {
            "id": value.get("task_id"),
            "title": value.get("title", ""),
            "activity": value.get("activity", ""),
            "duration_minutes": round(float(duration) * 60),
            "earliest_start": start,
            "deadline": _as_datetime(value.get("deadline"), "deadline"),
            "original_start": start,
            "preferred_start": start,
            "preferred_end": end,
            "priority": _contract_priority(value.get("priority", "MEDIUM")),
            "dependencies": value.get("dependencies", ()),
            "resources": tuple(value.get("resources", ())),
            "crop_name": value.get("crop_name", ""),
            "crop_stage": value.get("crop_stage", ""),
            "chemical_target": value.get("chemical_target"),
        }
    )


def _contract_period(value: Any) -> ForecastPoint:
    if not isinstance(value, Mapping):
        raise SchedulerInputError("Each forecast period must be an object")
    start = _as_datetime(value.get("start_time"), "forecast start_time")
    end = _as_datetime(value.get("end_time"), "forecast end_time")
    if end <= start:
        raise SchedulerInputError("forecast end_time must be after start_time")
    return ForecastPoint(
        timestamp=start,
        data={**value, "period_end": end},
    )


def _contract_priority(value: Any) -> int:
    priorities = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    if isinstance(value, str) and value.upper() in priorities:
        return priorities[value.upper()]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise SchedulerInputError("priority must be LOW, MEDIUM, HIGH, CRITICAL, or an integer")


def _default_contract_assessment(
    task: Task,
    _start: datetime,
    _end: datetime,
    points: tuple[ForecastPoint, ...],
) -> Assessment:
    if not points:
        return Assessment("insufficient_data", ("No forecast data covers this window.",))
    required = ("rainfall_mm", "wind_speed_kmh", "wind_gust_kmh", "temperature_c")
    missing = [
        field for field in required
        if any(point.data.get(field) is None for point in points)
    ]
    if missing:
        return Assessment(
            "insufficient_data",
            (f"Required forecast data is missing: {', '.join(missing)}.",),
        )
    rainfall = sum(float(point.data["rainfall_mm"]) for point in points)
    gust = max(float(point.data["wind_gust_kmh"]) for point in points)
    activity = task.activity
    if activity == "IRRIGATION" and rainfall >= 10:
        return Assessment(
            "suitable",
            (f"Natural rainfall ({rainfall:g} mm) is sufficient; irrigation is not required.",),
            ("NATURAL_RAINFALL_ADEQUATE",),
        )
    if activity == "SPRAYING" and (rainfall > 0 or gust > 15):
        return Assessment(
            "unsuitable",
            (f"Rainfall ({rainfall:g} mm) or wind gusts ({gust:g} km/h) make spraying unsafe.",),
            ("RAIN_DRIFT_CONFLICT",),
        )
    if activity == "HARVESTING" and rainfall > 0:
        return Assessment(
            "unsuitable",
            (f"Rainfall ({rainfall:g} mm) makes harvesting unsafe.",),
            ("HARVEST_RAIN_CONFLICT",),
        )
    return Assessment("suitable", ("Forecast conditions are suitable for this activity.",))


def _contract_task_result(
    task: Task,
    entry: Mapping[str, Any] | None,
    unscheduled: Mapping[str, Any] | None,
    reasons: Sequence[str],
    periods: Sequence[ForecastPoint],
) -> dict[str, Any]:
    original_end = task.original_start + timedelta(minutes=task.duration_minutes)
    if unscheduled:
        change_type = (
            "INSUFFICIENT_INFO"
            if any("insufficient" in reason.lower() for reason in reasons)
            else "UNFEASIBLE_CONFLICT"
        )
        proposed = None
    elif entry is None:
        change_type = "UNFEASIBLE_CONFLICT"
        proposed = None
    elif entry["start"] == task.original_start:
        change_type = "UNCHANGED"
        proposed = None
    else:
        change_type = "RESCHEDULED"
        proposed = _contract_window(entry["start"], entry["end"])
    result_reasons = list(reasons) or ["No schedule change was required."]
    if change_type == "RESCHEDULED":
        result_reasons.insert(0, "Moved to a suitable forecast window.")
    if change_type == "UNFEASIBLE_CONFLICT":
        result_reasons = list(reasons) or ["No feasible window satisfies all hard constraints."]
    alternative = (
        _period_summary(task.activity, proposed, periods)
        if proposed is not None
        else None
    )
    return {
        "task_id": task.id,
        "activity": task.activity,
        "title": task.title,
        "original_window": _contract_window(task.original_start, original_end),
        "proposed_window": proposed,
        "change_type": change_type,
        "reasons": result_reasons,
        "reasons_hindi": [],
        "confidence": "HIGH" if change_type in {"UNCHANGED", "RESCHEDULED"} else "LOW",
        "limiting_factors": (
            ["DEPENDENCY_OR_RESOURCE_CONFLICT"]
            if change_type == "UNFEASIBLE_CONFLICT"
            else []
        ),
        "alternative_weather": alternative,
    }


def _contract_window(start: datetime, end: datetime) -> dict[str, str]:
    return {"start_time": start.isoformat(), "end_time": end.isoformat()}


def _period_summary(
    activity: str,
    window: Mapping[str, str] | None,
    periods: Sequence[ForecastPoint],
) -> dict[str, Any] | None:
    if window is None:
        return None
    start = datetime.fromisoformat(window["start_time"])
    end = datetime.fromisoformat(window["end_time"])
    matched = [
        point for point in periods
        if point.timestamp < end
        and point.data.get("period_end", point.timestamp) > start
    ]
    if not matched:
        return None
    return {
        "avg_rainfall_mm": sum(float(point.data["rainfall_mm"]) for point in matched) / len(matched),
        "max_wind_speed_kmh": max(float(point.data["wind_speed_kmh"]) for point in matched),
        "avg_temperature_c": sum(float(point.data["temperature_c"]) for point in matched) / len(matched),
        "condition_text": str(matched[0].data.get("condition_text", "")),
    }


def _normalize_forecast(
    forecast: Sequence[ForecastPoint | Mapping[str, Any]],
) -> tuple[ForecastPoint, ...]:
    points = tuple(sorted((ForecastPoint.from_value(item) for item in forecast), key=lambda p: p.timestamp))
    if len({point.timestamp for point in points}) != len(points):
        raise SchedulerInputError("Forecast timestamps must be unique")
    if any(left.timestamp >= right.timestamp for left, right in zip(points, points[1:])):
        raise SchedulerInputError("Forecast timestamps must be strictly increasing")
    return points


def _validate_tasks(tasks: Sequence[Task]) -> None:
    ids = [task.id for task in tasks]
    if len(set(ids)) != len(ids):
        raise SchedulerInputError("Task IDs must be unique")
    known = set(ids)
    for task in tasks:
        unknown = set(task.dependencies) - known
        if unknown:
            raise SchedulerInputError(
                f"Task {task.id!r} has unknown dependency/dependencies: {', '.join(sorted(unknown))}"
            )
        if task.original_start is not None:
            original_end = task.original_start + timedelta(minutes=task.duration_minutes)
            if original_end > task.deadline:
                raise SchedulerInputError(
                    f"Task {task.id!r} original schedule exceeds its deadline"
                )
    _dependency_order(tasks)


def _dependency_order(tasks: Sequence[Task]) -> tuple[str, ...]:
    task_by_id = {task.id: task for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()
    result: list[str] = []

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise SchedulerInputError("Task dependencies contain a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in task_by_id[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)
        result.append(task_id)

    for task in sorted(tasks, key=lambda item: (-item.priority, item.id)):
        visit(task.id)
    return tuple(result)


def _forecast_resolution(points: Sequence[ForecastPoint]) -> timedelta:
    deltas = [
        right.timestamp - left.timestamp
        for left, right in zip(points, points[1:])
    ]
    return min(deltas)


def _has_continuous_forecast(
    points: Sequence[ForecastPoint],
    start: datetime,
    end: datetime,
    resolution: timedelta,
) -> bool:
    if not points:
        return False
    if "period_end" in points[0].data:
        return points[0].timestamp <= start and points[-1].data["period_end"] >= end
    if points[0].timestamp != start:
        return False
    expected_points = max(1, (end - start + resolution - timedelta(microseconds=1)) // resolution)
    if len(points) < expected_points:
        return False
    return all(
        right.timestamp - left.timestamp <= resolution
        for left, right in zip(points, points[1:])
    )


def _candidate_rank(candidate: CandidateWindow, task: Task) -> tuple[Any, ...]:
    original_distance = (
        abs((candidate.start - task.original_start).total_seconds())
        if task.original_start
        else float("inf")
    )
    outside_preferred = 0
    if task.preferred_start and task.preferred_end:
        outside_preferred = int(
            candidate.start < task.preferred_start
            or candidate.end > task.preferred_end
        )
    return (outside_preferred, original_distance, candidate.start)


def _overlaps_resource(
    candidate: CandidateWindow,
    task: Task,
    scheduled: Mapping[str, Mapping[str, Any]],
) -> bool:
    if not task.resources:
        return False
    resources = set(task.resources)
    return any(
        resources.intersection(entry["resources"])
        and candidate.start < entry["end"]
        and candidate.end > entry["start"]
        for entry in scheduled.values()
    )


def _schedule_entry(task: Task, candidate: CandidateWindow) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "start": candidate.start,
        "end": candidate.end,
        "resources": list(task.resources),
        "assessment": {
            "status": candidate.assessment.status,
            "reasons": list(candidate.assessment.reasons),
            "rule_references": list(candidate.assessment.rule_references),
        },
    }


def _explain_no_window(
    task: Task,
    candidates: Sequence[CandidateWindow],
    dependency_end: datetime,
    scheduled: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    if not candidates:
        return ["No forecast-covered candidate window satisfies the task duration and deadline."]
    if all(candidate.assessment.status == "insufficient_data" for candidate in candidates):
        return ["Weather assessment is insufficient for every forecast-covered candidate window."]
    if all(candidate.assessment.status != "suitable" for candidate in candidates):
        return ["No candidate window was assessed as suitable."]
    if all(candidate.start < dependency_end for candidate in candidates):
        return ["All suitable windows occur before the dependencies finish."]
    if all(_overlaps_resource(candidate, task, scheduled) for candidate in candidates):
        return ["All suitable windows conflict with an exclusive resource."]
    return ["No suitable window satisfies the dependency or exclusive-resource constraints."]


def _as_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as error:
            raise SchedulerInputError(
                f"{field_name} must be a valid ISO 8601 datetime"
            ) from error
    if not isinstance(value, datetime):
        raise SchedulerInputError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        raise SchedulerInputError(f"{field_name} must be timezone-aware")
    return value


def _optional_datetime(value: Any) -> datetime | None:
    return None if value is None else _as_datetime(value, "datetime")


def _as_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchedulerInputError(f"{field_name} must be a non-empty string")
    return value.strip()


def _as_positive_int(value: Any, field_name: str) -> int:
    result = _as_int(value, field_name)
    if result <= 0:
        raise SchedulerInputError(f"{field_name} must be positive")
    return result


def _as_non_negative_int(value: Any, field_name: str) -> int:
    result = _as_int(value, field_name)
    if result < 0:
        raise SchedulerInputError(f"{field_name} must not be negative")
    return result


def _as_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchedulerInputError(f"{field_name} must be an integer")
    return value
