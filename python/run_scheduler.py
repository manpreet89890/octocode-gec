"""JSON stdin/stdout bridge for the local Next.js scheduler demo."""

from __future__ import annotations

import json
import sys

from scheduler import SchedulerInputError, generate_plan_schedule


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        result = generate_plan_schedule(payload)
        json.dump(result, sys.stdout)
        return 0
    except (SchedulerInputError, json.JSONDecodeError) as error:
        json.dump({"error": str(error)}, sys.stdout)
        return 2
    except Exception as error:
        json.dump({"error": f"Scheduler failed: {error}"}, sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
