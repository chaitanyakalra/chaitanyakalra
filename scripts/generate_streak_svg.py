#!/usr/bin/env python3
"""Generate a static GitHub streak SVG for the profile README.

The script can read from GitHub's contribution calendar when a token is
available, or from a local git repository for local verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default=os.getenv("GITHUB_USERNAME", "chaitanyakalra"))
    parser.add_argument("--output", default="assets/streak.svg")
    parser.add_argument(
        "--source",
        choices=("github", "git", "auto"),
        default=os.getenv("STREAK_SOURCE", "auto"),
    )
    parser.add_argument(
        "--git-repo",
        default=os.getenv("STREAK_GIT_REPO", str(Path.home() / ".commit-mirror" / "mirror")),
    )
    parser.add_argument("--days", type=int, default=370)
    return parser.parse_args()


def today_ist() -> dt.date:
    return dt.datetime.now(IST).date()


def github_contributions(username: str, days: int) -> dict[dt.date, int]:
    token = os.getenv("GH_CONTRIB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GH_CONTRIB_TOKEN or GITHUB_TOKEN is required for GitHub source")

    end = today_ist()
    start = end - dt.timedelta(days=days - 1)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            weeks {
              contributionDays {
                date
                contributionCount
              }
            }
          }
        }
      }
    }
    """
    payload = json.dumps(
        {
            "query": query,
            "variables": {
                "login": username,
                "from": f"{start.isoformat()}T00:00:00+05:30",
                "to": f"{end.isoformat()}T23:59:59+05:30",
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "chaitanyakalra-streak-generator",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))

    if result.get("errors"):
        raise RuntimeError(result["errors"])
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user not found: {username}")

    counts: dict[dt.date, int] = {}
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    for week in weeks:
        for day in week["contributionDays"]:
            counts[dt.date.fromisoformat(day["date"])] = int(day["contributionCount"])
    return counts


def git_contributions(repo: str, days: int) -> dict[dt.date, int]:
    end = today_ist()
    start = end - dt.timedelta(days=days - 1)
    output = subprocess.check_output(
        [
            "git",
            "-C",
            repo,
            "log",
            "--since",
            f"{start.isoformat()} 00:00:00 +0530",
            "--pretty=%aI",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    counts: Counter[dt.date] = Counter()
    for line in output.splitlines():
        if not line.strip():
            continue
        stamp = dt.datetime.fromisoformat(line.strip().replace("Z", "+00:00"))
        counts[stamp.astimezone(IST).date()] += 1
    return dict(counts)


def complete_calendar(counts: dict[dt.date, int], days: int) -> dict[dt.date, int]:
    end = today_ist()
    start = end - dt.timedelta(days=days - 1)
    return {start + dt.timedelta(days=offset): counts.get(start + dt.timedelta(days=offset), 0) for offset in range(days)}


def streaks(counts: dict[dt.date, int]) -> tuple[int, int, int]:
    dates = sorted(counts)
    active = {day for day, count in counts.items() if count > 0}
    total = sum(counts.values())

    longest = 0
    run = 0
    for day in dates:
        if day in active:
            run += 1
            longest = max(longest, run)
        else:
            run = 0

    today = today_ist()
    cursor = today if counts.get(today, 0) > 0 else today - dt.timedelta(days=1)
    current = 0
    while cursor in active:
        current += 1
        cursor -= dt.timedelta(days=1)

    return current, longest, total


def weekly_heatmap(counts: dict[dt.date, int], weeks: int = 18) -> str:
    end = today_ist()
    start = end - dt.timedelta(days=(weeks * 7) - 1)
    start -= dt.timedelta(days=start.weekday() + 1 if start.weekday() != 6 else 0)
    max_count = max(counts.values() or [0])
    cells: list[str] = []
    colors = ["#1B1F2A", "#2D5A3D", "#3FB56A", "#4CC776", "#8FE9AB"]
    for week in range(weeks):
        for dow in range(7):
            day = start + dt.timedelta(days=(week * 7) + dow)
            count = counts.get(day, 0)
            if count == 0:
                color = colors[0]
            elif max_count <= 1:
                color = colors[2]
            else:
                color = colors[min(4, 1 + int((count / max_count) * 3))]
            x = 30 + week * 14
            y = 128 + dow * 14
            title = f"{day.isoformat()}: {count} contribution{'s' if count != 1 else ''}"
            cells.append(
                f'<rect x="{x}" y="{y}" width="10" height="10" rx="2" fill="{color}">'
                f"<title>{html.escape(title)}</title></rect>"
            )
    return "\n  ".join(cells)


def render_svg(username: str, counts: dict[dt.date, int]) -> str:
    current, longest, total = streaks(counts)
    generated = dt.datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    cells = weekly_heatmap(counts)
    width = 620
    height = 250
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="GitHub streak for {html.escape(username)}">
  <title>GitHub streak for {html.escape(username)}</title>
  <defs>
    <linearGradient id="card" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#16131F"/>
      <stop offset="100%" stop-color="#0D1117"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="16" fill="url(#card)"/>
  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="15" fill="none" stroke="#2B313C"/>
  <text x="30" y="42" fill="#F8FAFC" font-family="Verdana, Geneva, sans-serif" font-size="22" font-weight="700">GitHub streak</text>
  <text x="30" y="68" fill="#A7B0C0" font-family="Verdana, Geneva, sans-serif" font-size="12">Generated from contribution history • {html.escape(generated)}</text>

  <g font-family="Verdana, Geneva, sans-serif">
    <text x="42" y="102" fill="#FF5C8A" font-size="26" font-weight="700">{current}</text>
    <text x="42" y="121" fill="#CBD5E1" font-size="11">current streak</text>

    <text x="220" y="102" fill="#8FE9AB" font-size="26" font-weight="700">{longest}</text>
    <text x="220" y="121" fill="#CBD5E1" font-size="11">longest streak</text>

    <text x="408" y="102" fill="#6C63FF" font-size="26" font-weight="700">{total}</text>
    <text x="408" y="121" fill="#CBD5E1" font-size="11">contributions, last year</text>
  </g>

  {cells}

  <text x="30" y="232" fill="#6B7280" font-family="Verdana, Geneva, sans-serif" font-size="11">Static SVG generated in-repo. No third-party streak API.</text>
</svg>
"""


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    raw_counts: dict[dt.date, int] | None = None

    if args.source in ("github", "auto"):
        try:
            raw_counts = github_contributions(args.username, args.days)
        except Exception as exc:
            errors.append(f"github source failed: {exc}")
            if args.source == "github":
                print("\n".join(errors), file=sys.stderr)
                return 1

    if raw_counts is None:
        try:
            raw_counts = git_contributions(args.git_repo, args.days)
        except Exception as exc:
            errors.append(f"git source failed: {exc}")
            print("\n".join(errors), file=sys.stderr)
            return 1

    counts = complete_calendar(raw_counts, args.days)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_svg(args.username, counts), encoding="utf-8")

    current, longest, total = streaks(counts)
    print(f"wrote {output} (current={current}, longest={longest}, total={total})")
    if errors:
        print("; ".join(errors), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
