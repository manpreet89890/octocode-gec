import unittest
from datetime import datetime, timedelta, timezone

from scheduler import Assessment, SchedulerInputError, generate_schedule


UTC = timezone.utc
BASE = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def forecast(hours: int = 8):
    return [
        {"timestamp": BASE + timedelta(hours=index), "temperature_c": 24}
        for index in range(hours)
    ]


def task(task_id: str = "spray", **overrides):
    value = {
        "id": task_id,
        "duration_minutes": 60,
        "earliest_start": BASE,
        "deadline": BASE + timedelta(hours=8),
        "original_start": BASE,
        "priority": 1,
        "resources": ["tractor"],
    }
    value.update(overrides)
    return value


def suitable_when_temperature_is_at_least_20(
    _task, _start, _end, points
):
    if not points or any(point.data.get("temperature_c", 0) < 20 for point in points):
        return Assessment("unsuitable", ("Temperature is too low.",))
    return Assessment("suitable", ("Temperature is suitable.",), ("TEMP-20",))


class SchedulerTests(unittest.TestCase):
    def test_schedules_a_suitable_window_and_preserves_input(self):
        original = task()
        result = generate_schedule(
            [original], forecast(), suitable_when_temperature_is_at_least_20
        )

        self.assertEqual(result.proposed_schedule[0]["start"], BASE)
        self.assertEqual(result.unchanged_tasks, ("spray",))
        self.assertEqual(original["original_start"], BASE)
        self.assertEqual(result.proposed_schedule[0]["assessment"]["rule_references"], ["TEMP-20"])

    def test_moves_when_original_window_is_unsuitable(self):
        def evaluator(_task, start, _end, _points):
            return Assessment(
                "unsuitable" if start == BASE else "suitable",
                ("Rain at original time.",),
            )

        result = generate_schedule([task()], forecast(), evaluator)

        self.assertEqual(result.proposed_schedule[0]["start"], BASE + timedelta(hours=1))
        self.assertEqual(result.changed_tasks, ("spray",))
        self.assertIn("Moved to a suitable forecast window.", result.reasons["spray"])

    def test_respects_duration_and_deadline(self):
        constrained = task(
            duration_minutes=120,
            deadline=BASE + timedelta(hours=3),
            original_start=None,
        )
        result = generate_schedule([constrained], forecast(), lambda *_: Assessment("suitable"))

        self.assertEqual(result.proposed_schedule[0]["end"], BASE + timedelta(hours=2))
        self.assertEqual(result.proposed_schedule[0]["end"] <= constrained["deadline"], True)

    def test_dependencies_are_scheduled_before_dependents(self):
        prerequisite = task("prepare", original_start=None, priority=1)
        dependent = task(
            "spray",
            original_start=None,
            earliest_start=BASE,
            dependencies=["prepare"],
            priority=5,
        )
        result = generate_schedule(
            [dependent, prerequisite],
            forecast(),
            lambda *_: Assessment("suitable"),
        )

        starts = {entry["task_id"]: entry["start"] for entry in result.proposed_schedule}
        self.assertLess(starts["prepare"], starts["spray"])

    def test_same_resource_tasks_do_not_overlap(self):
        first = task("first", original_start=None)
        second = task("second", original_start=None)
        result = generate_schedule(
            [first, second], forecast(), lambda *_: Assessment("suitable")
        )

        entries = {entry["task_id"]: entry for entry in result.proposed_schedule}
        self.assertGreaterEqual(entries["second"]["start"], entries["first"]["end"])

    def test_insufficient_data_is_not_suitable(self):
        result = generate_schedule(
            [task(original_start=None)],
            forecast(),
            lambda *_: Assessment("insufficient_data", ("Rain data is missing.",)),
        )

        self.assertEqual(result.proposed_schedule, ())
        self.assertEqual(result.unscheduled_tasks[0]["task_id"], "spray")
        self.assertIn("insufficient", result.unscheduled_tasks[0]["reasons"][0])

    def test_forecast_change_reassesses_candidate_windows(self):
        calls = []

        def evaluator(_task, start, _end, points):
            calls.append((start, points[0].data["temperature_c"]))
            return Assessment("suitable" if points[0].data["temperature_c"] >= 20 else "unsuitable")

        changed_forecast = forecast()
        changed_forecast[0]["temperature_c"] = 10
        result = generate_schedule([task()], changed_forecast, evaluator)

        self.assertEqual(result.proposed_schedule[0]["start"], BASE + timedelta(hours=1))
        self.assertGreaterEqual(len(calls), 2)

    def test_reports_no_feasible_window_instead_of_dropping_task(self):
        result = generate_schedule(
            [task(original_start=None)],
            forecast(),
            lambda *_: Assessment("unsuitable", ("Wind is too strong.",)),
        )

        self.assertEqual(result.unscheduled_tasks[0]["task_id"], "spray")
        self.assertEqual(len(result.unscheduled_tasks), 1)

    def test_invalid_dependencies_and_cycles_are_explicit(self):
        with self.assertRaisesRegex(SchedulerInputError, "unknown dependency"):
            generate_schedule(
                [task(dependencies=["missing"])],
                forecast(),
                lambda *_: Assessment("suitable"),
            )

        first = task("first", dependencies=["second"])
        second = task("second", dependencies=["first"])
        with self.assertRaisesRegex(SchedulerInputError, "cycle"):
            generate_schedule([first, second], forecast(), lambda *_: Assessment("suitable"))

    def test_candidate_assessment_receives_candidate_window(self):
        assessed_starts = []

        def evaluator(_task, start, end, points):
            assessed_starts.append((start, end, tuple(point.timestamp for point in points)))
            return Assessment("suitable")

        generate_schedule([task()], forecast(), evaluator)

        self.assertTrue(assessed_starts)
        self.assertEqual(assessed_starts[0][0], BASE)
        self.assertEqual(assessed_starts[0][1], BASE + timedelta(hours=1))


if __name__ == "__main__":
    unittest.main()
