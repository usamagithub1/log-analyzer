# Log Analyzer

A robust CLI tool that analyzes web server log files and produces a clear, actionable summary report — designed to be useful for someone actually on call.

## Quick start

```bash
# No dependencies beyond Python 3.8+
python analyze.py path/to/server.log
```

That's it. No installs required.

## Generating test data

```bash
python scripts/generate_logs.py              # 5 000 lines → test.log
python scripts/generate_logs.py -n 50000     # 50 000 lines → test.log
python scripts/generate_logs.py -n 1000 -o sample.log
python scripts/generate_logs.py --seed 42    # reproducible output
```

The generator produces a file matching the assessment spec, including ~7% deviation lines: alternate timestamp formats, alternate time units, missing status codes, extra fields, blank lines, stack trace fragments, and JSON-formatted entries.

## Usage

```bash
python analyze.py <logfile> [options]

Options:
  --json              Output results as JSON instead of a text report
  --top-slow N        Show top N slowest endpoints (default: 10)
  --filter-status N   Only analyze lines with this status code
  --filter-path /x    Only analyze lines matching this path prefix
```

### Examples

```bash
python analyze.py server.log
python analyze.py server.log --json
python analyze.py server.log --filter-status 500
python analyze.py server.log --filter-path /api/users --top-slow 5
```

## What the report shows

1. **Parse summary** — total lines, parsed count, malformed count, breakdown of format anomalies, sample malformed lines.
2. **HTTP status codes** — grouped (2xx/3xx/4xx/5xx) with bar chart + individual code breakdown.
3. **HTTP methods** — distribution with bar chart.
4. **Top 10 most requested paths**.
5. **Top 10 slowest endpoints** — by average response time.
6. **Top 10 slowest individual requests** — absolute worst cases.
7. **Top 10 error-prone paths** — 4xx+5xx error rate per path (min 5 requests).
8. **Top 10 client IPs**.
9. **Traffic over time** — hourly request counts with bar chart (last 24 hours).

## What the tool handles

| Scenario | Handling |
|---|---|
| ISO 8601 timestamps | Primary format |
| `2024/03/15 14:23:01` timestamps | Parsed |
| `15-Mar-2024 14:23:01` timestamps | Parsed (including space-separated date + time) |
| Unix epoch timestamps | Parsed |
| Response time in `ms` | Primary unit |
| Response time in `s` | Converted to ms |
| Response time as bare integer | Treated as ms |
| Missing/`-` status code | Counted separately, not crashed on |
| Extra fields (user agent, referrer) | Captured in `extra`, not discarded |
| JSON-format lines | Parsed via `json.loads` with field name aliases |
| Stack trace fragments | Skipped, counted as malformed |
| Blank lines | Skipped, counted as malformed |
| Non-UTF-8 bytes | Replaced with `?`, never crashes |
| Unknown lines | Skipped with count, sample shown in report |

## Requirements

- Python 3.8 or newer
- Standard library only (no pip installs)

## Project structure

```
log-analyzer/
├── analyze.py              # main tool
├── scripts/
│   └── generate_logs.py    # test data generator
├── test.log                # sample file (generated)
├── README.md
└── ANSWERS.md
```
