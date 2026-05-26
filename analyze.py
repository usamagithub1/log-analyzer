#!/usr/bin/env python3
"""
Log Analyzer — Dev Weekends Fellowship 2026 Assessment
A robust CLI tool for analyzing web server log files.
"""

import sys
import re
import json
import argparse
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


# ---------------------------------------------------------------------------
# Data Model
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    raw: str
    timestamp: Optional[datetime] = None
    ip: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status: Optional[int] = None
    response_ms: Optional[float] = None
    extra: str = ""


@dataclass
class ParseStats:
    total: int = 0
    parsed: int = 0
    malformed: int = 0
    json_lines: int = 0
    missing_status: int = 0
    alt_timestamp: int = 0
    alt_time_unit: int = 0
    malformed_examples: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Timestamp parsing — handles 4 formats
# ---------------------------------------------------------------------------

_TS_PATTERNS = [
    # ISO 8601: 2024-03-15T14:23:01Z  (primary format)
    (re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)'), lambda m: datetime.fromisoformat(m.replace("Z", "+00:00"))),
    # Slash format: 2024/03/15 14:23:01
    (re.compile(r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})'), lambda m: datetime.strptime(m, "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)),
    # Human format: 15-Mar-2024 14:23:01  OR  24-May-2026 07:55:16
    (re.compile(r'^(\d{2}-[A-Za-z]{3,9}-\d{4} \d{2}:\d{2}:\d{2})'), lambda m: datetime.strptime(m, "%d-%b-%Y %H:%M:%S").replace(tzinfo=timezone.utc)),
    # Unix epoch: 1710512581
    (re.compile(r'^(\d{10})(?:\s|$)'), lambda m: datetime.fromtimestamp(int(m), tz=timezone.utc)),
]


def parse_timestamp(token: str, next_token: str = ""):
    """Try each known timestamp pattern. Returns (datetime, format_name, tokens_consumed) or (None, None, 1)."""
    # Try single-token forms first
    for pattern, converter in _TS_PATTERNS:
        m = pattern.match(token)
        if m:
            try:
                dt = converter(m.group(1))
                fmt = "iso8601" if "T" in token else ("slash" if "/" in token else ("human" if "-" in token[2:6] else "epoch"))
                return dt, fmt, 1
            except (ValueError, OSError):
                continue
    # Try two-token form for space-separated date+time: "15-Mar-2024" "14:23:01"
    combined = token + " " + next_token
    for pattern, converter in _TS_PATTERNS:
        m = pattern.match(combined)
        if m:
            try:
                dt = converter(m.group(1))
                fmt = "iso8601" if "T" in combined else ("slash" if "/" in combined else ("human" if "-" in combined[2:6] else "epoch"))
                return dt, fmt, 2
            except (ValueError, OSError):
                continue
    return None, None, 1


# ---------------------------------------------------------------------------
# Response-time parsing — ms, s, or bare integer
# ---------------------------------------------------------------------------

_RT_MS   = re.compile(r'^(\d+(?:\.\d+)?)ms$')
_RT_S    = re.compile(r'^(\d+(?:\.\d+)?)s$')
_RT_BARE = re.compile(r'^(\d+(?:\.\d+)?)$')


def parse_response_time(token: str):
    """Return response time in milliseconds (float) or None. Also returns unit used."""
    m = _RT_MS.match(token)
    if m:
        return float(m.group(1)), "ms"
    m = _RT_S.match(token)
    if m:
        return float(m.group(1)) * 1000, "s"
    m = _RT_BARE.match(token)
    if m:
        return float(m.group(1)), "bare"
    return None, None


# ---------------------------------------------------------------------------
# Line parser
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}
_IP_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')


def parse_line(raw: str, stats: ParseStats) -> Optional[LogEntry]:
    """
    Parse a single log line. Returns a LogEntry on (partial) success,
    None for lines that are truly unparseable (blank, stack-trace fragments, etc.)
    """
    stats.total += 1
    line = raw.strip()

    # --- skip blanks ---
    if not line:
        stats.malformed += 1
        return None

    # --- attempt JSON lines ---
    if line.startswith("{"):
        try:
            obj = json.loads(line)
            stats.json_lines += 1
            stats.parsed += 1
            entry = LogEntry(raw=raw)
            # best-effort field extraction from JSON
            entry.ip     = obj.get("ip") or obj.get("remote_addr") or obj.get("client")
            entry.method = obj.get("method") or obj.get("verb")
            entry.path   = obj.get("path") or obj.get("url") or obj.get("uri")
            raw_status   = obj.get("status") or obj.get("status_code") or obj.get("code")
            if raw_status is not None:
                try:
                    entry.status = int(raw_status)
                except (ValueError, TypeError):
                    pass
            raw_time = obj.get("response_time") or obj.get("duration") or obj.get("latency")
            if raw_time is not None:
                rt, _ = parse_response_time(str(raw_time))
                entry.response_ms = rt
            ts_raw = obj.get("timestamp") or obj.get("time") or obj.get("ts") or ""
            if ts_raw:
                entry.timestamp, _, _ = parse_timestamp(str(ts_raw))
            return entry
        except json.JSONDecodeError:
            pass  # fall through to standard parsing

    # --- tokenise carefully to handle quoted extra fields ---
    # Split on whitespace but keep quoted strings together
    tokens = _tokenize(line)

    if len(tokens) < 2:
        stats.malformed += 1
        if len(stats.malformed_examples) < 5:
            stats.malformed_examples.append(line[:120])
        return None

    entry = LogEntry(raw=raw)
    idx = 0

    # --- timestamp (first token) ---
    next_tok = tokens[idx + 1] if idx + 1 < len(tokens) else ""
    ts, ts_fmt, ts_consumed = parse_timestamp(tokens[idx], next_tok)
    if ts:
        entry.timestamp = ts
        if ts_fmt != "iso8601":
            stats.alt_timestamp += 1
        idx += ts_consumed
    # If no timestamp found, try skipping the first token (some formats differ)

    # --- IP address ---
    if idx < len(tokens) and _IP_RE.match(tokens[idx]):
        entry.ip = tokens[idx]
        idx += 1

    # --- HTTP method ---
    if idx < len(tokens) and tokens[idx].upper() in _HTTP_METHODS:
        entry.method = tokens[idx].upper()
        idx += 1

    # --- path ---
    if idx < len(tokens) and tokens[idx].startswith("/"):
        entry.path = tokens[idx]
        idx += 1

    # --- status code ---
    if idx < len(tokens):
        tok = tokens[idx]
        if tok == "-":
            entry.status = None
            stats.missing_status += 1
            idx += 1
        elif tok.isdigit() and 100 <= int(tok) <= 599:
            entry.status = int(tok)
            idx += 1

    # --- response time ---
    if idx < len(tokens):
        rt, unit = parse_response_time(tokens[idx])
        if rt is not None:
            entry.response_ms = rt
            if unit != "ms":
                stats.alt_time_unit += 1
            idx += 1

    # --- extra fields (user agent, referrer, etc.) ---
    entry.extra = " ".join(tokens[idx:])

    # Require at least method + path to count as parsed
    if entry.method and entry.path:
        stats.parsed += 1
        return entry
    else:
        stats.malformed += 1
        if len(stats.malformed_examples) < 5:
            stats.malformed_examples.append(line[:120])
        return None


def _tokenize(line: str) -> list:
    """Split line on whitespace, keeping quoted strings as single tokens."""
    tokens = []
    current = []
    in_quote = False
    quote_char = None
    for ch in line:
        if in_quote:
            current.append(ch)
            if ch == quote_char:
                in_quote = False
        elif ch in ('"', "'"):
            in_quote = True
            quote_char = ch
            current.append(ch)
        elif ch in (' ', '\t'):
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze(entries: list, stats: ParseStats) -> dict:
    """Crunch parsed entries into summary statistics."""
    status_counts    = Counter()
    method_counts    = Counter()
    path_counts      = Counter()
    path_times       = defaultdict(list)   # path -> [ms, ...]
    ip_counts        = Counter()
    error_paths      = Counter()           # 4xx/5xx per path
    hourly_requests  = Counter()           # hour -> count
    slow_entries     = []                  # (ms, path, method, status, ts)

    for e in entries:
        if e.status is not None:
            status_counts[e.status] += 1
            if e.status >= 400:
                error_paths[e.path or "unknown"] += 1

        if e.method:
            method_counts[e.method] += 1

        if e.path:
            path_counts[e.path] += 1

        if e.ip:
            ip_counts[e.ip] += 1

        if e.response_ms is not None and e.path:
            path_times[e.path].append(e.response_ms)
            slow_entries.append((e.response_ms, e.path, e.method or "", e.status or 0, e.timestamp))

        if e.timestamp:
            hourly_requests[e.timestamp.strftime("%Y-%m-%d %H:00")] += 1

    # Slowest endpoints (by average response time, min 3 requests)
    avg_times = {}
    for path, times in path_times.items():
        if len(times) >= 1:
            avg_times[path] = (sum(times) / len(times), max(times), len(times))

    top_slow_avg = sorted(avg_times.items(), key=lambda x: x[1][0], reverse=True)[:10]

    # Absolute slowest individual requests
    slow_entries.sort(reverse=True)
    top_slow_abs = slow_entries[:10]

    # Error rate per path (min 5 requests)
    error_rate = {}
    for path, err_count in error_paths.items():
        total = path_counts.get(path, err_count)
        if total >= 5:
            error_rate[path] = (err_count, total, round(100 * err_count / total, 1))

    top_error_paths = sorted(error_rate.items(), key=lambda x: x[1][2], reverse=True)[:10]

    # Status code groups
    status_2xx = sum(v for k, v in status_counts.items() if 200 <= k < 300)
    status_3xx = sum(v for k, v in status_counts.items() if 300 <= k < 400)
    status_4xx = sum(v for k, v in status_counts.items() if 400 <= k < 500)
    status_5xx = sum(v for k, v in status_counts.items() if k >= 500)

    return {
        "status_counts":    dict(sorted(status_counts.items())),
        "status_groups":    {"2xx": status_2xx, "3xx": status_3xx, "4xx": status_4xx, "5xx": status_5xx},
        "method_counts":    dict(method_counts.most_common()),
        "top_paths":        path_counts.most_common(10),
        "top_ips":          ip_counts.most_common(10),
        "top_slow_avg":     top_slow_avg,
        "top_slow_abs":     top_slow_abs,
        "top_error_paths":  top_error_paths,
        "hourly_requests":  dict(sorted(hourly_requests.items())[-48:]),  # last 48 hours
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def _bar(value: int, total: int, width: int = 30) -> str:
    if total == 0:
        return " " * width
    filled = round(width * value / total)
    return "█" * filled + "░" * (width - filled)


def print_report(stats: ParseStats, result: dict, file: str):
    total_parsed = stats.parsed
    total_lines  = stats.total

    w = 72  # report width
    sep = "─" * w

    def header(title):
        print(f"\n{'━' * w}")
        print(f"  {title}")
        print(f"{'━' * w}")

    def section(title):
        print(f"\n  {title}")
        print(f"  {'─' * (w - 4)}")

    print(f"\n{'═' * w}")
    print(f"  LOG ANALYZER  ·  {Path(file).name}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * w}")

    # Parse stats
    section("PARSE SUMMARY")
    print(f"  Total lines read  : {total_lines:>10,}")
    print(f"  Successfully parsed: {stats.parsed:>10,}  ({100*stats.parsed/max(total_lines,1):.1f}%)")
    print(f"  Malformed / skipped: {stats.malformed:>10,}  ({100*stats.malformed/max(total_lines,1):.1f}%)")
    print(f"  JSON-format lines  : {stats.json_lines:>10,}")
    print(f"  Alt timestamp fmt  : {stats.alt_timestamp:>10,}")
    print(f"  Alt time unit (s)  : {stats.alt_time_unit:>10,}")
    print(f"  Missing status (-)  : {stats.missing_status:>10,}")
    if stats.malformed_examples:
        print(f"\n  Sample malformed lines:")
        for ex in stats.malformed_examples:
            print(f"    · {ex}")

    # Status codes
    header("HTTP STATUS CODES")
    sg = result["status_groups"]
    total_req = sum(sg.values())
    for grp, count in sg.items():
        bar = _bar(count, total_req)
        print(f"  {grp}   {bar} {count:>8,}  ({100*count/max(total_req,1):5.1f}%)")

    print()
    sc = result["status_counts"]
    for code, count in sorted(sc.items()):
        label = _status_label(code)
        print(f"    {code} {label:<25} {count:>8,}")

    # Methods
    header("HTTP METHODS")
    total_m = sum(result["method_counts"].values())
    for method, count in result["method_counts"].items():
        bar = _bar(count, total_m, 20)
        print(f"  {method:<8} {bar} {count:>8,}")

    # Top paths
    header("TOP 10 MOST REQUESTED PATHS")
    total_p = sum(c for _, c in result["top_paths"])
    for i, (path, count) in enumerate(result["top_paths"], 1):
        bar = _bar(count, total_p, 20)
        print(f"  {i:>2}. {bar} {count:>7,}  {path}")

    # Slowest endpoints (by avg)
    header("TOP 10 SLOWEST ENDPOINTS  (by avg response time)")
    if result["top_slow_avg"]:
        print(f"  {'Path':<40} {'Avg':>8}  {'Max':>8}  {'Hits':>6}")
        print(f"  {'─'*40}  {'─'*8}  {'─'*8}  {'─'*6}")
        for path, (avg, mx, hits) in result["top_slow_avg"]:
            print(f"  {path[:40]:<40} {avg:>7.0f}ms  {mx:>7.0f}ms  {hits:>6,}")
    else:
        print("  No response time data available.")

    # Absolute slowest requests
    header("TOP 10 SLOWEST INDIVIDUAL REQUESTS")
    if result["top_slow_abs"]:
        print(f"  {'ms':>8}  {'Method':<7}  {'Status'}  Path")
        print(f"  {'─'*8}  {'─'*7}  {'─'*6}  {'─'*40}")
        for ms, path, method, status, ts in result["top_slow_abs"]:
            method_str = method or "?"
            status_str = str(status) if status else " -  "
            print(f"  {ms:>7.0f}ms  {method_str:<7}  {status_str:<6}  {(path or '')[:50]}")
    else:
        print("  No response time data available.")

    # Error paths
    header("TOP 10 ERROR-PRONE PATHS  (4xx + 5xx, min 5 requests)")
    if result["top_error_paths"]:
        print(f"  {'Path':<40} {'Errors':>7}  {'Total':>7}  {'Rate':>6}")
        print(f"  {'─'*40}  {'─'*7}  {'─'*7}  {'─'*6}")
        for path, (errs, total, rate) in result["top_error_paths"]:
            print(f"  {path[:40]:<40} {errs:>7,}  {total:>7,}  {rate:>5.1f}%")
    else:
        print("  No error paths found (or fewer than 5 requests per path).")

    # Top IPs
    header("TOP 10 CLIENT IPs")
    for i, (ip, count) in enumerate(result["top_ips"], 1):
        print(f"  {i:>2}. {ip:<18}  {count:>8,} requests")

    # Traffic over time
    hourly = result["hourly_requests"]
    if hourly:
        header("TRAFFIC OVER TIME  (hourly)")
        max_h = max(hourly.values())
        for hour, count in list(hourly.items())[-24:]:  # last 24 hours shown
            bar = _bar(count, max_h, 35)
            print(f"  {hour}  {bar}  {count:>6,}")

    print(f"\n{'═' * w}\n")


def _status_label(code: int) -> str:
    labels = {
        200: "OK", 201: "Created", 204: "No Content", 206: "Partial Content",
        301: "Moved Permanently", 302: "Found", 304: "Not Modified",
        400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
        404: "Not Found", 405: "Method Not Allowed", 408: "Request Timeout",
        409: "Conflict", 422: "Unprocessable Entity", 429: "Too Many Requests",
        500: "Internal Server Error", 502: "Bad Gateway",
        503: "Service Unavailable", 504: "Gateway Timeout",
    }
    return labels.get(code, "")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze a web server log file and produce a summary report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze.py server.log
  python analyze.py server.log --json
  python analyze.py server.log --top-slow 20
  python analyze.py server.log --filter-status 500
        """
    )
    parser.add_argument("logfile", help="Path to the log file to analyze")
    parser.add_argument("--json", action="store_true", help="Output results as JSON instead of a text report")
    parser.add_argument("--top-slow", type=int, default=10, metavar="N", help="Show top N slowest endpoints (default: 10)")
    parser.add_argument("--filter-status", type=int, metavar="CODE", help="Show only lines with this status code")
    parser.add_argument("--filter-path", type=str, metavar="PREFIX", help="Show only lines matching this path prefix")
    args = parser.parse_args()

    path = Path(args.logfile)
    if not path.exists():
        print(f"Error: file not found: {args.logfile}", file=sys.stderr)
        sys.exit(1)
    if not path.is_file():
        print(f"Error: not a file: {args.logfile}", file=sys.stderr)
        sys.exit(1)

    stats   = ParseStats()
    entries = []

    # Read file — handle encoding issues gracefully
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                entry = parse_line(raw_line, stats)
                if entry is None:
                    continue
                # Apply filters
                if args.filter_status and entry.status != args.filter_status:
                    continue
                if args.filter_path and entry.path and not entry.path.startswith(args.filter_path):
                    continue
                entries.append(entry)
    except OSError as e:
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    if stats.parsed == 0:
        print("Warning: no parseable log entries found.", file=sys.stderr)
        if stats.malformed > 0:
            print(f"  {stats.malformed} malformed lines were skipped.", file=sys.stderr)
        sys.exit(0)

    result = analyze(entries, stats)

    if args.json:
        # Serialize — convert tuples/datetimes
        def _serial(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, tuple):
                return list(obj)
            raise TypeError(f"Not serializable: {type(obj)}")
        print(json.dumps({"stats": vars(stats), "report": result}, default=_serial, indent=2))
    else:
        print_report(stats, result, args.logfile)


if __name__ == "__main__":
    main()
