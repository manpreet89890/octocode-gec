import { spawn } from "node:child_process";
import { NextResponse } from "next/server";

const demoPayload = {
  plan_id: "plan-raipur-001",
  tasks: [
    {
      task_id: "task-spray-01",
      title: "Pesticide Spraying",
      activity: "SPRAYING",
      planned_window: {
        start_time: "2026-10-29T06:00:00+05:30",
        end_time: "2026-10-29T10:00:00+05:30",
      },
      duration_hours: 4,
      deadline: "2026-10-31T18:00:00+05:30",
      priority: "HIGH",
      dependencies: [],
      crop_name: "Paddy",
      crop_stage: "Flowering",
      chemical_target: "Tricyclazole",
    },
    {
      task_id: "task-irrig-02",
      title: "Field Irrigation",
      activity: "IRRIGATION",
      planned_window: {
        start_time: "2026-10-29T14:00:00+05:30",
        end_time: "2026-10-29T17:00:00+05:30",
      },
      duration_hours: 3,
      deadline: "2026-10-30T18:00:00+05:30",
      priority: "MEDIUM",
      dependencies: [],
      crop_name: "Paddy",
      crop_stage: "Flowering",
    },
    {
      task_id: "task-harv-03",
      title: "Early Grain Harvesting",
      activity: "HARVESTING",
      planned_window: {
        start_time: "2026-10-30T07:00:00+05:30",
        end_time: "2026-10-30T12:00:00+05:30",
      },
      duration_hours: 5,
      deadline: "2026-10-31T18:00:00+05:30",
      priority: "HIGH",
      dependencies: ["task-spray-01"],
      crop_name: "Paddy",
      crop_stage: "Maturity",
    },
  ],
  forecast_periods: [
    {
      start_time: "2026-10-29T06:00:00+05:30",
      end_time: "2026-10-29T12:00:00+05:30",
      rainfall_mm: 14.5,
      precipitation_probability: 90,
      wind_speed_kmh: 22,
      wind_gust_kmh: 28,
      relative_humidity_percent: 92,
      temperature_c: 23,
      condition_code: "heavy_rain",
      condition_text: "Heavy Rain",
    },
    {
      start_time: "2026-10-29T12:00:00+05:30",
      end_time: "2026-10-29T18:00:00+05:30",
      rainfall_mm: 8,
      precipitation_probability: 75,
      wind_speed_kmh: 16,
      wind_gust_kmh: 20,
      relative_humidity_percent: 88,
      temperature_c: 25,
      condition_code: "moderate_rain",
      condition_text: "Moderate Rain",
    },
    {
      start_time: "2026-10-30T06:00:00+05:30",
      end_time: "2026-10-30T12:00:00+05:30",
      rainfall_mm: 0,
      precipitation_probability: 10,
      wind_speed_kmh: 8,
      wind_gust_kmh: 11,
      relative_humidity_percent: 65,
      temperature_c: 26.5,
      condition_code: "clear",
      condition_text: "Clear Sky",
    },
    {
      start_time: "2026-10-31T06:00:00+05:30",
      end_time: "2026-10-31T12:00:00+05:30",
      rainfall_mm: 0,
      precipitation_probability: 5,
      wind_speed_kmh: 7,
      wind_gust_kmh: 9,
      relative_humidity_percent: 60,
      temperature_c: 27,
      condition_code: "clear",
      condition_text: "Clear Sky",
    },
  ],
  policy: {
    respect_deadlines: true,
    respect_dependencies: true,
    prioritize_critical_tasks: true,
  },
};

function runScheduler(payload: unknown): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const command = process.platform === "win32" ? "python" : "python3";
    const child = spawn(command, ["python/run_scheduler.py"], {
      cwd: process.cwd(),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let output = "";
    let errorOutput = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      output += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      errorOutput += chunk;
    });
    child.on("error", (error) => reject(error));
    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(errorOutput || `Python scheduler exited with code ${code}`));
        return;
      }
      try {
        const result: unknown = JSON.parse(output);
        if (!result || typeof result !== "object" || "error" in result) {
          reject(new Error(
            result && typeof result === "object" && "error" in result
              ? String(result.error)
              : "Python scheduler returned an invalid response",
          ));
          return;
        }
        resolve(result as Record<string, unknown>);
      } catch (error) {
        reject(new Error(`Python scheduler returned invalid JSON: ${String(error)}`));
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

export async function GET() {
  try {
    return NextResponse.json(await runScheduler(demoPayload));
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Schedule service failed" },
      { status: 502 },
    );
  }
}

export async function POST(request: Request) {
  try {
    return NextResponse.json(await runScheduler(await request.json()));
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Schedule service failed" },
      { status: 400 },
    );
  }
}
