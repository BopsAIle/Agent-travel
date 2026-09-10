"""Live check: microservice HTTP + upstream APIs (RapidAPI, Tavily, Ticketmaster, Nominatim).

Run from repo root (containers must be up):

    python server/scripts/check_apis.py

If this process cannot resolve Docker DNS names, the script copies itself into
travel-orchestrator and re-runs there.

Options:

    python server/scripts/check_apis.py --quick
    python server/scripts/check_apis.py --skip-flight
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any, Optional


SERVICES = {
    "flight": os.getenv("FLIGHT_SERVICE_URL", "http://flight-service:8000"),
    "hotel": os.getenv("HOTEL_SERVICE_URL", "http://hotel-service:8001"),
    "activity": os.getenv("ACTIVITY_SERVICE_URL", "http://activity-service:8002"),
    "geocoding": os.getenv("GEOCODING_SERVICE_URL", "http://geocoding-service:8003"),
    "event": os.getenv("EVENT_SERVICE_URL", "http://event-service:8004"),
    "orchestrator": os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
}

ORCHESTRATOR_CONTAINER = os.getenv("ORCHESTRATOR_CONTAINER", "travel-orchestrator")


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str, elapsed_s: float = 0.0):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.elapsed_s = elapsed_s


def _summarize(parsed: Any) -> str:
    if isinstance(parsed, list):
        extra = f"items={len(parsed)}"
        if parsed and isinstance(parsed[0], dict):
            sample = {k: parsed[0].get(k) for k in list(parsed[0])[:3]}
            extra += f" sample={json.dumps(sample, ensure_ascii=False)[:160]}"
        return extra
    if isinstance(parsed, dict):
        return f"keys={list(parsed.keys())} sample={json.dumps(parsed, ensure_ascii=False)[:160]}"
    if isinstance(parsed, str):
        return f"str_len={len(parsed)} head={parsed[:100]!r}"
    return f"type={type(parsed).__name__}"


def request_json(
    method: str,
    url: str,
    payload: Optional[dict] = None,
    timeout: int = 20,
) -> tuple[int, Any, str]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = raw.decode("utf-8", errors="replace")[:200]
            return response.status, parsed, ""
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")[:240]
        return exc.code, parsed, str(exc.reason)
    except Exception as exc:
        return 0, None, f"{type(exc).__name__}: {exc}"


def hostname_resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def inside_docker_network() -> bool:
    return hostname_resolves("flight-service")


def reexec_inside_orchestrator() -> int:
    if not shutil.which("docker"):
        print("Cannot reach Docker DNS (flight-service) and docker CLI is missing.")
        print("Start the stack, then run this from a machine with Docker, or:")
        print("  docker exec travel-orchestrator python /app/scripts/check_apis.py")
        return 2

    dest = "/tmp/check_apis.py"
    print(
        f"Host cannot resolve flight-service; running inside {ORCHESTRATOR_CONTAINER}...",
        flush=True,
    )
    copy = subprocess.run(
        ["docker", "cp", os.path.abspath(__file__), f"{ORCHESTRATOR_CONTAINER}:{dest}"],
        capture_output=True,
        text=True,
    )
    if copy.returncode != 0:
        print(copy.stderr.strip() or copy.stdout.strip() or "docker cp failed")
        return copy.returncode

    extra = sys.argv[1:]
    cmd = [
        "docker",
        "exec",
        "-e",
        "CHECK_APIS_INSIDE=1",
        ORCHESTRATOR_CONTAINER,
        "python",
        dest,
        *extra,
    ]
    return subprocess.call(cmd)


def check_get(name: str, url: str, timeout: int = 8) -> CheckResult:
    started = time.time()
    status, parsed, err = request_json("GET", url, timeout=timeout)
    elapsed = time.time() - started
    if status == 200:
        return CheckResult(name, True, _summarize(parsed), elapsed)
    return CheckResult(name, False, f"HTTP {status} {err} {_summarize(parsed) if parsed else ''}".strip(), elapsed)


def check_post(
    name: str,
    url: str,
    payload: dict,
    timeout: int,
    ok_if: Any,
) -> CheckResult:
    started = time.time()
    status, parsed, err = request_json("POST", url, payload=payload, timeout=timeout)
    elapsed = time.time() - started
    if status != 200:
        return CheckResult(name, False, f"HTTP {status} {err} {_summarize(parsed) if parsed else ''}".strip(), elapsed)
    try:
        passed = bool(ok_if(parsed))
    except Exception as exc:
        return CheckResult(name, False, f"validator error: {exc}", elapsed)
    detail = _summarize(parsed)
    if not passed:
        return CheckResult(name, False, f"empty or unexpected payload; {detail}", elapsed)
    return CheckResult(name, True, detail, elapsed)


def trip_dates() -> tuple[str, str]:
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=3)
    return start.isoformat(), end.isoformat()


def run_checks(quick: bool, skip_flight: bool) -> list[CheckResult]:
    start_date, end_date = trip_dates()
    results: list[CheckResult] = []

    results.append(check_get("orchestrator /health", f"{SERVICES['orchestrator']}/health"))

    for name, base in SERVICES.items():
        if name == "orchestrator":
            continue
        results.append(check_get(f"{name} /metrics", f"{base}/metrics"))
        skills = check_get(f"{name} /agent/skills", f"{base}/agent/skills")
        results.append(skills)

    if quick:
        return results

    results.append(
        check_post(
            "geocoding Nominatim /geocode",
            f"{SERVICES['geocoding']}/geocode",
            {"query": "Eiffel Tower, Paris"},
            timeout=25,
            ok_if=lambda body: isinstance(body, dict) and body.get("latitude") is not None,
        )
    )
    results.append(
        check_post(
            "event Ticketmaster /search_events",
            f"{SERVICES['event']}/search_events",
            {"city": "New York", "start_date": start_date, "end_date": end_date},
            timeout=30,
            ok_if=lambda body: isinstance(body, list) and len(body) > 0,
        )
    )
    results.append(
        check_post(
            "activity Tavily /search_activities",
            f"{SERVICES['activity']}/search_activities",
            {"destination": "Paris", "interests": ["museums"]},
            timeout=45,
            ok_if=lambda body: isinstance(body, str) and len(body.strip()) > 40,
        )
    )
    results.append(
        check_post(
            "hotel RapidAPI /search",
            f"{SERVICES['hotel']}/search",
            {
                "destination": "Paris",
                "start_date": start_date,
                "end_date": end_date,
                "person": 1,
            },
            timeout=60,
            ok_if=lambda body: isinstance(body, list) and len(body) > 0,
        )
    )
    if not skip_flight:
        results.append(
            check_post(
                "flight RapidAPI /search",
                f"{SERVICES['flight']}/search",
                {
                    "origin": "London",
                    "destination": "Paris",
                    "start_date": start_date,
                    "end_date": end_date,
                    "person": 1,
                },
                timeout=90,
                ok_if=lambda body: isinstance(body, list) and len(body) > 0,
            )
        )
    return results


def print_report(results: list[CheckResult]) -> int:
    width = max(len(item.name) for item in results)
    failed = 0
    print()
    print(f"{'CHECK':<{width}}  {'STATUS':<7}  TIME   DETAIL")
    print("-" * (width + 60))
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        if not item.ok:
            failed += 1
        print(f"{item.name:<{width}}  {status:<7}  {item.elapsed_s:5.1f}s  {item.detail}")
    print("-" * (width + 60))
    print(f"{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check travel-agent service APIs.")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Only hit /health, /metrics, and /agent/skills (no paid upstream search).",
    )
    parser.add_argument(
        "--skip-flight",
        action="store_true",
        help="Skip the slow Booking.com round-trip search.",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Do not docker-exec into the orchestrator even if DNS fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inside = os.getenv("CHECK_APIS_INSIDE") == "1" or inside_docker_network()
    if not inside and not args.local:
        return reexec_inside_orchestrator()
    if not inside and args.local:
        print("Not on the Docker network; service hostnames will fail. Use without --local.")
        return 2
    return print_report(run_checks(quick=args.quick, skip_flight=args.skip_flight))


if __name__ == "__main__":
    sys.exit(main())
