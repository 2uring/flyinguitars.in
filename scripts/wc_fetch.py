#!/usr/bin/env python3
"""FIFA World Cup live data fetcher for flyinguitars.in.

Pulls fixtures, live scores and (when available) lineups from
football-data.org, normalises them into ``wc-data.json`` and — when the
meaningful content has changed — commits and pushes the file so the static
GitHub Pages site updates even while nobody is watching.

The script can run a single pass (``--once``) or loop forever with an
adaptive polling interval (default). It is intentionally dependency-light:
only the ``requests`` library plus the standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = REPO_ROOT / "wc-data.json"
TOKEN_FILE = REPO_ROOT / "scripts" / ".fd_token"
LOG_PREFIX = "[wc_fetch]"

API_BASE = "https://api.football-data.org/v4"
COMPETITION = os.environ.get("WC_COMPETITION", "WC")  # FIFA World Cup
IST = timezone(timedelta(hours=5, minutes=30))

LIVE_STATUSES = {"IN_PLAY", "PAUSED", "LIVE", "SUSPENDED"}
FINISHED_STATUSES = {"FINISHED", "AWARDED"}

# Polling cadence (seconds)
INTERVAL_LIVE = 60          # a match is in play
INTERVAL_SOON = 5 * 60      # a match kicks off within SOON_WINDOW
INTERVAL_IDLE = 30 * 60     # nothing happening
SOON_WINDOW = timedelta(hours=2)

# Respect football-data free tier (10 req/min). We cap detail lookups/cycle.
MAX_DETAIL_CALLS = 6


def log(msg: str) -> None:
    ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    print(f"{LOG_PREFIX} {ts}  {msg}", flush=True)


def get_token() -> str | None:
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if token:
        return token.strip()
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text().strip()
        if t:
            return t
    return None


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def _respect_rate_headers(headers) -> None:
    """football-data returns throttling hints; sleep proactively when the
    per-minute budget is nearly exhausted so we never trip the limiter."""
    try:
        remaining = headers.get("X-Requests-Available-Minute")
        reset = headers.get("X-RequestCounter-Reset")
        if remaining is None:
            return
        remaining = int(remaining)
        reset = int(reset) if reset is not None else 60
        if remaining <= 1:
            wait = max(1, min(reset, 65)) + 1
            log(f"rate budget low (remaining={remaining}); pausing {wait}s")
            time.sleep(wait)
    except (TypeError, ValueError):
        pass


def api_get(path: str, token: str, params: dict | None = None) -> dict | None:
    url = f"{API_BASE}{path}"
    try:
        r = requests.get(url, headers={"X-Auth-Token": token}, params=params, timeout=20)
    except requests.RequestException as exc:
        log(f"request error {path}: {exc}")
        return None
    if r.status_code == 429:
        retry = r.headers.get("X-RequestCounter-Reset") or "60"
        try:
            wait = int(retry) + 2
        except ValueError:
            wait = 62
        log(f"rate limited (429), backing off {wait}s")
        time.sleep(wait)
        return None
    if r.status_code == 403:
        log(f"403 forbidden for {path} (tier may not allow this resource)")
        return None
    if r.status_code != 200:
        log(f"{r.status_code} for {path}: {r.text[:160]}")
        return None
    _respect_rate_headers(r.headers)
    try:
        return r.json()
    except ValueError:
        log(f"bad JSON for {path}")
        return None


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
def to_ist(utc_str: str | None) -> dict:
    if not utc_str:
        return {"iso": None, "date": None, "time": None, "label": "TBD"}
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00")).astimezone(IST)
    except ValueError:
        return {"iso": utc_str, "date": None, "time": None, "label": utc_str}
    return {
        "iso": dt.isoformat(),
        "date": dt.strftime("%Y-%m-%d"),
        "dateLabel": dt.strftime("%a, %d %b"),
        "time": dt.strftime("%H:%M"),
        "label": dt.strftime("%a %d %b · %H:%M IST"),
    }


def team_obj(t: dict | None) -> dict:
    t = t or {}
    return {
        "id": t.get("id"),
        "name": t.get("name") or "TBD",
        "short": t.get("shortName") or t.get("tla") or t.get("name") or "TBD",
        "tla": t.get("tla"),
        "crest": t.get("crest"),
    }


def lineup_from_team(t: dict | None) -> dict:
    """Extract lineup/formation from a detailed team object if present."""
    t = t or {}
    formation = t.get("formation")
    lineup = t.get("lineup") or []
    bench = t.get("bench") or []
    coach = (t.get("coach") or {}).get("name")

    def player(p):
        return {
            "name": p.get("name"),
            "position": p.get("position"),
            "number": p.get("shirtNumber"),
        }

    return {
        "formation": formation,
        "coach": coach,
        "starting": [player(p) for p in lineup],
        "bench": [player(p) for p in bench],
    }


def normalise_match(m: dict, detail: dict | None = None) -> dict:
    score = m.get("score") or {}
    full = score.get("fullTime") or {}
    half = score.get("halfTime") or {}
    status = m.get("status")

    out = {
        "id": m.get("id"),
        "utcDate": m.get("utcDate"),
        "ist": to_ist(m.get("utcDate")),
        "status": status,
        "live": status in LIVE_STATUSES,
        "finished": status in FINISHED_STATUSES,
        "minute": m.get("minute"),
        "stage": (m.get("stage") or "").replace("_", " ").title() or None,
        "group": m.get("group"),
        "matchday": m.get("matchday"),
        "venue": m.get("venue"),
        "home": team_obj(m.get("homeTeam")),
        "away": team_obj(m.get("awayTeam")),
        "score": {
            "home": full.get("home"),
            "away": full.get("away"),
            "halfHome": half.get("home"),
            "halfAway": half.get("away"),
            "winner": score.get("winner"),
        },
        "lineups": None,
    }

    src = detail or {}
    home_d = src.get("homeTeam") or {}
    away_d = src.get("awayTeam") or {}
    if home_d.get("lineup") or away_d.get("lineup") or home_d.get("formation"):
        out["lineups"] = {
            "home": lineup_from_team(home_d),
            "away": lineup_from_team(away_d),
        }
    return out


def content_hash(matches: list[dict]) -> str:
    """Hash only the meaningful fields so we don't commit on every poll."""
    skinny = []
    for m in matches:
        skinny.append({
            "id": m["id"],
            "status": m["status"],
            "minute": m["minute"],
            "score": m["score"],
            "home": m["home"]["name"],
            "away": m["away"]["name"],
            "utc": m["utcDate"],
            "lineups": bool(m["lineups"]),
        })
    blob = json.dumps(skinny, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Git
# --------------------------------------------------------------------------
def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def push_data(no_push: bool) -> None:
    code, _ = git("add", "wc-data.json")
    if code != 0:
        log("git add failed")
        return
    code, out = git("commit", "-m", "chore(wc): update live World Cup data [auto]")
    if code != 0:
        if "nothing to commit" in out:
            return
        log(f"git commit issue: {out[:160]}")
        return
    log("committed wc-data.json")
    if no_push:
        return

    token_path = REPO_ROOT / "access_token"
    if not token_path.exists():
        log("no access_token file; skipping push")
        return
    gh_token = token_path.read_text().strip()
    push_url = f"https://x-access-token:{gh_token}@github.com/2uring/flyinguitars.in.git"
    code, out = git("push", push_url, "HEAD:main")
    if code != 0:
        log(f"push failed, trying rebase: {out[:160]}")
        git("pull", "--rebase", push_url, "main")
        code, out = git("push", push_url, "HEAD:main")
        if code != 0:
            log(f"push failed again: {out[:160]}")
            return
    log("pushed to origin/main")


# --------------------------------------------------------------------------
# Core cycle
# --------------------------------------------------------------------------
def build_dataset(token: str) -> tuple[list[dict], int]:
    data = api_get(f"/competitions/{COMPETITION}/matches", token)
    if not data:
        return [], INTERVAL_IDLE
    raw = data.get("matches") or []

    now = datetime.now(timezone.utc)
    live_ids, soon_ids = [], []
    for m in raw:
        st = m.get("status")
        if st in LIVE_STATUSES:
            live_ids.append(m.get("id"))
        elif st == "SCHEDULED" or st == "TIMED":
            try:
                kt = datetime.fromisoformat((m.get("utcDate") or "").replace("Z", "+00:00"))
                if timedelta(0) <= (kt - now) <= SOON_WINDOW:
                    soon_ids.append(m.get("id"))
            except ValueError:
                pass

    # Fetch detail (lineups + minute) for live first, then soon-to-start.
    want_detail = (live_ids + soon_ids)[:MAX_DETAIL_CALLS]
    details: dict[int, dict] = {}
    for mid in want_detail:
        d = api_get(f"/matches/{mid}", token)
        if d:
            details[mid] = d
        time.sleep(6.5)  # stay under 10 req/min

    matches = [normalise_match(m, details.get(m.get("id"))) for m in raw]
    matches.sort(key=lambda x: (x["utcDate"] or "9999"))

    if live_ids:
        interval = INTERVAL_LIVE
    elif soon_ids:
        interval = INTERVAL_SOON
    else:
        interval = INTERVAL_IDLE
    return matches, interval


def write_and_maybe_push(matches: list[dict], no_push: bool) -> None:
    new_hash = content_hash(matches)
    old_hash = None
    if DATA_FILE.exists():
        try:
            old = json.loads(DATA_FILE.read_text())
            old_hash = old.get("contentHash")
        except (ValueError, OSError):
            pass

    now_ist = datetime.now(IST)
    payload = {
        "updated": now_ist.isoformat(),
        "updatedLabel": now_ist.strftime("%d %b %Y · %H:%M IST"),
        "competition": "FIFA World Cup",
        "contentHash": new_hash,
        "count": len(matches),
        "matches": matches,
    }
    DATA_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    if new_hash != old_hash:
        log(f"content changed ({len(matches)} matches) -> commit/push")
        push_data(no_push)
    else:
        log(f"no content change ({len(matches)} matches)")


def run_once(token: str, no_push: bool) -> int:
    matches, interval = build_dataset(token)
    if not matches:
        log("no matches returned this cycle")
        return INTERVAL_IDLE
    write_and_maybe_push(matches, no_push)
    return interval


def main() -> int:
    ap = argparse.ArgumentParser(description="FIFA WC live data fetcher")
    ap.add_argument("--once", action="store_true", help="run a single pass and exit")
    ap.add_argument("--no-push", action="store_true", help="never git push (local only)")
    args = ap.parse_args()

    token = get_token()
    if not token:
        log("ERROR: no football-data.org token. Set FOOTBALL_DATA_TOKEN env or "
            f"write it to {TOKEN_FILE}")
        return 2

    log(f"starting (competition={COMPETITION}, push={'off' if args.no_push else 'on'})")
    if args.once:
        run_once(token, args.no_push)
        return 0

    while True:
        try:
            interval = run_once(token, args.no_push)
        except Exception as exc:  # keep the daemon alive no matter what
            log(f"unexpected error: {exc!r}")
            interval = INTERVAL_IDLE
        log(f"sleeping {interval}s")
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
