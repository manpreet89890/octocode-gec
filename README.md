This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Scheduling engine

The framework-independent scheduling engine is in [`python/scheduler.py`](./python/scheduler.py).
It is intentionally separate from weather retrieval, agricultural rules, persistence, and
the UI. Member 3's assessment implementation is supplied as a callable so every candidate
window is assessed with the same rules:

```python
from python.scheduler import Assessment, generate_schedule

result = generate_schedule(tasks, normalized_forecast, assess_window, {
    "max_alternatives": 3,
})
response = result.to_dict()
```

For the backend plan payload (`plan_id`, `tasks`, `forecast_periods`, and `policy`),
use `generate_plan_schedule(payload)`. It returns the shared proposal shape with
`overall_status`, per-task `original_window`, `proposed_window`, `change_type`,
reasons, limiting factors, alternatives, summary counts, and unfeasible reasons.
Pass Member 3's evaluator as `assessment_evaluator` to apply the verified
activity-specific rules. The built-in fallback is conservative and is intended
only for integration tests; it does not replace the agricultural rule catalogue.

`tasks` and forecast points may be mappings or the engine's dataclasses. Task timestamps
and forecast timestamps must be timezone-aware. An assessment callable receives
`(task, candidate_start, candidate_end, forecast_points)` and must return
`suitable`, `unsuitable`, or `insufficient_data`. Only `suitable` candidates can be
scheduled. The result preserves task IDs and original task input, and includes the
proposed schedule, alternatives, changed and unchanged tasks, unscheduled tasks,
reasons, and limitations. The engine is a deterministic greedy scheduler; it does not
claim global optimality.

Run the scheduler tests from the repository root:

```bash
python -m unittest discover -s python -p "test_*.py" -v
```

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
