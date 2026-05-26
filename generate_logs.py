#!/usr/bin/env python3
"""
scripts/generate_logs.py — Generate a representative test log file.

Produces a file matching the assessment spec:
  - Primary format: ISO 8601 timestamp, IP, method, path, status, response_time
  - ~5–10% deviations: alt timestamps, alt time units, missing status,
    extra fields, blank lines, stack trace fragments, JSON lines

Usage:
    python scripts/generate_logs.py                  # 5000 lines → test.log
    python scripts/generate_logs.py -n 50000         # 50k lines
    python scripts/generate_logs.py -n 1000 -o x.log
"""

import random
import json
import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


PATHS = [
    "/api/users", "/api/users/{id}", "/api/login", "/api/logout",
    "/api/products", "/api/products/{id}", "/api/orders", "/api/orders/{id}",
    "/api/search", "/api/cart", "/api/checkout", "/api/payment",
    "/health", "/metrics", "/api/admin/users", "/api/admin/stats",
    "/static/app.js", "/static/style.css", "/favicon.ico",
]

METHODS = ["GET"] * 60 + ["POST"] * 20 + ["PUT"] * 10 + ["DELETE"] * 8 + ["PATCH"] * 2

STATUS_WEIGHTS = [
    (200, 50), (201, 8), (204, 4), (206, 2),
    (301, 3), (302, 4), (304, 5),
    (400, 4), (401, 5), (403, 3), (404, 7), (429, 2),
    (500, 2), (502, 1), (503, 1),
]
STATUSES, STATUS_PROBS = zip(*STATUS_WEIGHTS)
STATUS_TOTAL = sum(STATUS_PROBS)
STATUS_NORMALIZED = [p / STATUS_TOTAL for p in STATUS_PROBS]


IPS = [
    "192.168.1.{}".format(i) for i in range(1, 20)
] + [
    "10.0.0.{}".format(i) for i in range(1, 15)
] + ["172.16.0.1", "8.8.8.8", "1.1.1.1"]

USER_AGENTS = [
    '"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"',
    '"curl/7.79.1"',
    '"python-requests/2.28.0"',
    '"PostmanRuntime/7.29.0"',
    '"Go-http-client/2.0"',
]

REFERRERS = [
    '"https://example.com/dashboard"',
    '"https://app.example.com/"',
    '"-"',
]


def random_path():
    p = random.choice(PATHS)
    if "{id}" in p:
        p = p.replace("{id}", str(random.randint(1, 9999)))
    return p


def random_status():
    return random.choices(STATUSES, weights=STATUS_NORMALIZED)[0]


def random_ms(status):
    """Response time in ms — slower for errors and complex endpoints."""
    base = random.lognormvariate(4.5, 1.0)  # ~90ms median
    if status >= 500:
        base *= random.uniform(2, 8)
    return max(1.0, base)


def fmt_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def fmt_slash(dt):
    return dt.strftime("%Y/%m/%d %H:%M:%S")

def fmt_human(dt):
    return dt.strftime("%d-%b-%Y %H:%M:%S")

def fmt_epoch(dt):
    return str(int(dt.timestamp()))


def generate_log(n: int, outfile: str):
    start = datetime.now(tz=timezone.utc) - timedelta(hours=48)
    dt = start

    lines = []
    deviation_count = 0

    for i in range(n):
        # Advance time (Poisson-ish arrivals)
        dt += timedelta(seconds=random.expovariate(n / (48 * 3600)))

        path   = random_path()
        method = random.choice(METHODS)
        status = random_status()
        ms     = random_ms(status)
        ip     = random.choice(IPS)

        # Roll for deviation (target ~7%)
        roll = random.random()

        if roll < 0.01:
            # Blank line
            lines.append("")
            deviation_count += 1
            continue

        if roll < 0.02:
            # Stack trace fragment
            lines.append("  at com.example.Service.handleRequest(Service.java:142)")
            lines.append("  at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1089)")
            deviation_count += 2
            continue

        if roll < 0.03:
            # JSON line
            obj = {
                "timestamp": fmt_iso(dt),
                "ip": ip,
                "method": method,
                "path": path,
                "status": status,
                "response_time": f"{ms:.0f}ms",
            }
            lines.append(json.dumps(obj))
            deviation_count += 1
            continue

        # Choose timestamp format
        if roll < 0.045:
            ts = fmt_slash(dt)
            deviation_count += 1
        elif roll < 0.055:
            ts = fmt_human(dt)
            deviation_count += 1
        elif roll < 0.060:
            ts = fmt_epoch(dt)
            deviation_count += 1
        else:
            ts = fmt_iso(dt)

        # Choose response time format
        if roll < 0.062 and roll >= 0.060:
            rt = f"{ms/1000:.3f}s"   # seconds
            deviation_count += 1
        elif roll < 0.065 and roll >= 0.062:
            rt = str(int(ms))         # bare integer
            deviation_count += 1
        else:
            rt = f"{int(ms)}ms"

        # Missing status
        if roll < 0.067 and roll >= 0.065:
            status_str = "-"
            deviation_count += 1
        else:
            status_str = str(status)

        # Extra fields
        extra = ""
        if roll > 0.90:
            extra = " " + random.choice(USER_AGENTS)
        if roll > 0.95:
            extra += " " + random.choice(REFERRERS)

        line = f"{ts} {ip} {method} {path} {status_str} {rt}{extra}"
        lines.append(line)

    Path(outfile).write_text("\n".join(lines) + "\n", encoding="utf-8")
    total = len(lines)
    print(f"Generated {total:,} lines → {outfile}")
    print(f"  Deviations injected : ~{deviation_count:,} ({100*deviation_count/max(total,1):.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Generate a test log file.")
    parser.add_argument("-n", type=int, default=5000, help="Number of log entries to generate (default: 5000)")
    parser.add_argument("-o", "--output", default="test.log", help="Output file path (default: test.log)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    generate_log(args.n, args.output)


if __name__ == "__main__":
    main()
