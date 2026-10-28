import unittest
from datetime import datetime, timezone

from scheduler import generate_plan_schedule


class PlanContractTests(unittest.TestCase):
    def test_backend_contract_returns_shared_schedule_proposal(self):
        payload = {
            "plan_id": "plan-raipur-001",
            "tasks": [
                {
                    "task_id": "task-spray-01",
                    "title": "Pesticide Spraying",
                    "activity": "SPRAYING",
                    "planned_window": {
                        "start_time": "2026-10-29T06:00:00+05:30",
                        "end_time": "2026-10-29T10:00:00+05:30",
                    },
                    "duration_hours": 4.0,
                    "deadline": "2026-10-31T18:00:00+05:30",
                    "priority": "HIGH",
                    "dependencies": [],
                    "crop_name": "Paddy",
                    "crop_stage": "Flowering",
                    "chemical_target": "Tricyclazole",
                },
                {
                    "task_id": "task-irrig-02",
                    "title": "Field Irrigation",
                    "activity": "IRRIGATION",
                    "planned_window": {
                        "start_time": "2026-10-29T14:00:00+05:30",
                        "end_time": "2026-10-29T17:00:00+05:30",
                    },
                    "duration_hours": 3.0,
                    "deadline": "2026-10-30T18:00:00+05:30",
                    "priority": "MEDIUM",
                    "dependencies": [],
                    "crop_name": "Paddy",
                    "crop_stage": "Flowering",
                },
                {
                    "task_id": "task-harv-03",
                    "title": "Early Grain Harvesting",
                    "activity": "HARVESTING",
                    "planned_window": {
                        "start_time": "2026-10-30T07:00:00+05:30",
                        "end_time": "2026-10-30T12:00:00+05:30",
                    },
                    "duration_hours": 5.0,
                    "deadline": "2026-10-31T18:00:00+05:30",
                    "priority": "HIGH",
                    "dependencies": ["task-spray-01"],
                    "crop_name": "Paddy",
                    "crop_stage": "Maturity",
                },
            ],
            "forecast_periods": [
                {
                    "start_time": "2026-10-29T06:00:00+05:30",
                    "end_time": "2026-10-29T12:00:00+05:30",
                    "rainfall_mm": 14.5,
                    "precipitation_probability": 90,
                    "wind_speed_kmh": 22.0,
                    "wind_gust_kmh": 28.0,
                    "relative_humidity_percent": 92,
                    "temperature_c": 23.0,
                    "condition_text": "Heavy Rain",
                },
                {
                    "start_time": "2026-10-29T12:00:00+05:30",
                    "end_time": "2026-10-29T18:00:00+05:30",
                    "rainfall_mm": 8.0,
                    "precipitation_probability": 75,
                    "wind_speed_kmh": 16.0,
                    "wind_gust_kmh": 20.0,
                    "relative_humidity_percent": 88,
                    "temperature_c": 25.0,
                    "condition_text": "Moderate Rain",
                },
                {
                    "start_time": "2026-10-30T06:00:00+05:30",
                    "end_time": "2026-10-30T12:00:00+05:30",
                    "rainfall_mm": 0.0,
                    "precipitation_probability": 10,
                    "wind_speed_kmh": 8.0,
                    "wind_gust_kmh": 11.0,
                    "relative_humidity_percent": 65,
                    "temperature_c": 26.5,
                    "condition_text": "Clear Sky",
                },
                {
                    "start_time": "2026-10-31T06:00:00+05:30",
                    "end_time": "2026-10-31T12:00:00+05:30",
                    "rainfall_mm": 0.0,
                    "precipitation_probability": 5,
                    "wind_speed_kmh": 7.0,
                    "wind_gust_kmh": 9.0,
                    "relative_humidity_percent": 60,
                    "temperature_c": 27.0,
                    "condition_text": "Clear Sky",
                },
            ],
            "policy": {
                "respect_deadlines": True,
                "respect_dependencies": True,
                "prioritize_critical_tasks": True,
            },
        }

        result = generate_plan_schedule(
            payload,
            generated_at=datetime(2026, 10, 28, 12, 45, tzinfo=timezone.utc),
        )

        self.assertEqual(result["plan_id"], "plan-raipur-001")
        self.assertEqual(result["overall_status"], "FEASIBLE")
        by_id = {item["task_id"]: item for item in result["tasks"]}
        self.assertEqual(by_id["task-spray-01"]["change_type"], "RESCHEDULED")
        self.assertEqual(by_id["task-spray-01"]["proposed_window"]["start_time"], "2026-10-30T06:00:00+05:30")
        self.assertEqual(by_id["task-irrig-02"]["change_type"], "UNCHANGED")
        self.assertIsNone(by_id["task-irrig-02"]["proposed_window"])
        self.assertEqual(by_id["task-harv-03"]["proposed_window"]["start_time"], "2026-10-31T06:00:00+05:30")


if __name__ == "__main__":
    unittest.main()
