# ANSWERS.md

## 1. How to run

No installs needed. Python 3.8+ is the only requirement (standard library only).

**Generate test data:**
```bash
python scripts/generate_logs.py -n 5000 -o test.log
```

**Run the analyzer:**
```bash
python analyze.py test.log
```

**Other options:**
```bash
python analyze.py server.log --json                  # JSON output
python analyze.py server.log --filter-status 500     # only 500s
python analyze.py server.log --filter-path /api/     # only /api/* paths
python analyze.py server.log --top-slow 20           # top 20 slowest
```

---

## 2. Stack choice

**Why Python, standard library only:**

Python was the right pick for two reasons. First, its `re`, `json`, `collections`, and `datetime` modules cover everything this task needs without any package management overhead — someone running this on a fresh machine just needs Python, nothing else. Second, Python's readability makes the parsing logic easy to audit and extend, which matters for a tool that's going to be trusted with production logs.

The deliberate choice to avoid external libraries (pandas, click, rich) was intentional: they add install friction and dependency drift. The report renders fine with plain `print()` and Unicode block characters.

**A worse choice: JavaScript/Node.js**

Node would have required either a bundler setup or careful management of ESM vs CommonJS for a CLI tool. Streaming large log files through Node is doable but the async API adds ceremony. The standard library for text parsing and date handling is weaker than Python's — you'd immediately reach for `moment.js` or `luxon` just to parse "15-Mar-2024 14:23:01", pulling in dependencies for a task Python handles natively.

Another bad choice: **Bash/awk**. Fine for a one-liner count of 500s, but adding JSON line parsing, multiple timestamp format support, response-time normalization, and a nicely formatted report in pure Bash would produce something unmaintainable.

---

## 3. One real edge case

**Two-token timestamps (e.g., `15-Mar-2024 14:23:01`)**

`analyze.py`, function `parse_timestamp`, lines ~55–75; and `parse_line`, lines ~175–185.

The human-readable timestamp format splits across two whitespace-separated tokens: the date (`15-Mar-2024`) and the time (`14:23:01`). A naive tokenize-then-match approach would hand the timestamp parser only the first token (`15-Mar-2024`), which matches none of the patterns, and the entire line would be classified as malformed.

The fix is in `parse_timestamp`: after failing all single-token patterns, it tries `token + " " + next_token` as a combined string. The caller (`parse_line`) checks the returned `tokens_consumed` value (1 or 2) and advances the index accordingly, so the rest of the line (IP, method, path, etc.) parses correctly.

Without this handling, every line with a human-readable timestamp would be silently skipped and counted as malformed. On a file where someone changed the logging config mid-deployment, that could mean losing 20–30% of entries with no obvious explanation — the report would just show a suspiciously high malformed count with no hint as to why.

---

## 4. AI usage

I used Claude (claude.ai) during development for one specific thing:

**What I asked:** "What's a clean way in Python to tokenize a log line that might have quoted strings containing spaces (e.g., user agent fields), without pulling in a CSV/shlex library?"

**What it gave me:** A character-by-character loop that tracks whether we're inside a quote and splits on whitespace otherwise — essentially what became the `_tokenize()` function.

**What I changed:** The AI's version used a single `quote_char = '"'` hardcoded. I changed it to capture the opening quote character dynamically (`quote_char = ch`) so it handles both `"double"` and `'single'` quoted strings. Some log formats (particularly Nginx with custom `log_format`) emit single-quoted user agent strings. Hardcoding double quotes would tokenize those incorrectly, splitting the user agent on internal spaces.

I also rewrote the error path — the AI returned `[]` on a parsing failure, which would silently produce a zero-length token list that the caller would mishandle. I kept it returning whatever was accumulated, which gives the caller enough to detect and count the malformed line correctly.

---

## 5. Honest gap

**The slowest-endpoints table isn't useful when paths contain IDs.**

Right now, `/api/users/1234` and `/api/users/5678` are treated as different endpoints. So the "top 10 slowest by average" table shows individual parameterized paths (each with 1 hit) rather than aggregated route patterns like `/api/users/:id`. A path that's consistently slow across all user IDs looks like hundreds of unrelated one-off slow requests instead of a single pattern worth investigating.

**What I'd do with another day:**

Add a path normalization step that collapses numeric segments to `:id` — a simple regex like `re.sub(r'/\d+', '/:id', path)` applied before aggregation. I'd also look at UUIDs and common slug patterns. This single change would make the slowest-endpoints section dramatically more actionable: instead of "these 10 specific product IDs were slow," you'd see "/api/products/:id averages 340ms across 892 requests," which is actually something you can act on.
