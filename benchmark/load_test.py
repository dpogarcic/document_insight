"""Open-loop POST /query benchmark with quota-aware user counts.

The default 100 users at 100 req/s for 20 seconds send 20 requests per user,
within the default 30/60s quota. Sustained 100 req/s needs at least 200 users.
Use --allow-rate-limit for deliberate quota tests. Scheduling timestamps are
client dispatch times, not proof of server arrival. Every request has a total
deadline, and reports retain safe error codes, scheduling lag, and correlations.

Example: python benchmark/load_test.py --users 100 --rps 100 --duration 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
SAMPLE_DOCUMENT = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "pdf"
    / "Cedarbridge_Labs_Employee_Leave_Policy_2025.pdf"
)
DEFAULT_QUESTION = "What is the annual leave policy for the company?"
PASSWORD = "Benchmark-Load-Test-123!"


@dataclass(frozen=True, slots=True)
class ProvisionedUser:
    """One throwaway tenant admin with an activated document ready to query."""

    index: int
    email: str
    token: str
    tenant_id: str


@dataclass(slots=True)
class RequestResult:
    """One /query attempt's outcome."""

    sent_at: float
    latency_s: float
    status_code: int
    error: str | None = None
    schedule_lag_s: float = 0.0
    correlation_id: str | None = None
    cited_answer: bool = False


@dataclass(slots=True)
class Report:
    """Aggregated load-phase results, serialized for the results file."""

    target_rps: float
    duration_s: float
    user_count: int
    total_sent: int
    send_elapsed_s: float
    total_elapsed_s: float
    status_counts: dict[str, int]
    latency_ms: dict[str, float] = field(default_factory=dict)
    achieved_send_rps: float = 0.0
    successful_rps: float = 0.0
    error_counts: dict[str, int] = field(default_factory=dict)
    all_latency_ms: dict[str, float] = field(default_factory=dict)
    schedule_lag_ms: dict[str, float] = field(default_factory=dict)
    cited_answers: int = 0


async def _provision_user(
    client: httpx.AsyncClient, base_url: str, index: int, ready_timeout_s: float
) -> ProvisionedUser | None:
    """Register a tenant admin, ingest the sample document, and activate it."""
    email = f"benchmark-{index}-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        f"{base_url}/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": f"Benchmark User {index}",
            "tenant_name": f"Benchmark Tenant {index}",
        },
    )
    if register.status_code != 201:
        print(f"[user {index}] registration failed: {register.status_code} {register.text[:200]}")
        return None
    tenant_id = register.json()["tenant_id"]

    login = await client.post(f"{base_url}/auth/login", json={"email": email, "password": PASSWORD})
    if login.status_code != 200:
        print(f"[user {index}] login failed: {login.status_code}")
        return None
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with SAMPLE_DOCUMENT.open("rb") as handle:
        ingest = await client.post(
            f"{base_url}/ingest",
            headers=headers,
            files={"file": (SAMPLE_DOCUMENT.name, handle, "application/pdf")},
        )
    if ingest.status_code != 202:
        print(f"[user {index}] ingest failed: {ingest.status_code} {ingest.text[:200]}")
        return None
    stored = ingest.json()
    job_id, document_id, version_id = (
        stored["job_id"],
        stored["document_id"],
        stored["document_version_id"],
    )

    deadline = time.monotonic() + ready_timeout_s
    status = "queued"
    while time.monotonic() < deadline:
        job = await client.get(f"{base_url}/jobs/{job_id}", headers=headers)
        status = job.json()["status"]
        if status == "ready":
            break
        if status in ("failed", "cancelled"):
            print(f"[user {index}] processing {status}")
            return None
        await asyncio.sleep(1.0)
    if status != "ready":
        print(f"[user {index}] processing did not become ready within {ready_timeout_s}s")
        return None

    activate = await client.post(
        f"{base_url}/documents/{document_id}/activate",
        headers=headers,
        json={"document_version_id": version_id},
    )
    if activate.status_code != 200:
        print(f"[user {index}] activation failed: {activate.status_code} {activate.text[:200]}")
        return None

    return ProvisionedUser(index=index, email=email, token=token, tenant_id=tenant_id)


async def _provision_pool(
    base_url: str, count: int, ready_timeout_s: float, concurrency: int
) -> list[ProvisionedUser]:
    """Register and warm up `count` throwaway tenants, bounded by `concurrency`."""
    semaphore = asyncio.Semaphore(concurrency)

    async def _bounded(client: httpx.AsyncClient, index: int) -> ProvisionedUser | None:
        async with semaphore:
            return await _provision_user(client, base_url, index, ready_timeout_s)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        results = await asyncio.gather(*(_bounded(client, i) for i in range(count)))
    return [user for user in results if user is not None]


async def _send_query(
    client: httpx.AsyncClient,
    base_url: str,
    user: ProvisionedUser,
    question: str,
    results: list[RequestResult],
    scheduled_at: float,
    timeout_s: float,
) -> None:
    """Issue one query and record its outcome without raising."""
    start = time.monotonic()
    result = RequestResult(start, 0.0, -1, schedule_lag_s=start - scheduled_at)
    try:
        async with asyncio.timeout(timeout_s):
            response = await client.post(
                f"{base_url}/query",
                headers={"Authorization": f"Bearer {user.token}"},
                json={"question": question, "top_k": 5},
            )
        result.status_code = response.status_code
        result.correlation_id = response.headers.get("x-correlation-id")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            result.cited_answer = response.status_code == 200 and bool(payload.get("sources"))
            error = payload.get("detail")
            if isinstance(error, dict) and isinstance(error.get("code"), str):
                result.error = error["code"]
    except (httpx.HTTPError, TimeoutError) as error:
        # Persist only the exception class; raw messages may contain request data.
        result.error = type(error).__name__
    finally:
        result.latency_s = time.monotonic() - start
        results.append(result)


@dataclass(slots=True)
class LoadPhaseTiming:
    """Send-schedule duration versus full drain duration, kept separate.

    ``send_elapsed_s`` measures only how long it took to schedule every request on
    schedule; it should track the target rate closely regardless of response
    latency. ``total_elapsed_s`` additionally waits for every in-flight response
    to finish, so it is the right denominator for effective throughput once
    responses are slower than the send interval.
    """

    send_elapsed_s: float
    total_elapsed_s: float


async def _run_load_phase(
    base_url: str,
    users: list[ProvisionedUser],
    target_rps: float,
    duration_s: float,
    question: str,
    timeout_s: float = 30.0,
) -> tuple[list[RequestResult], LoadPhaseTiming]:
    """Fire requests on a fixed open-loop schedule, round-robined across users."""
    total_requests = max(1, round(target_rps * duration_s))
    results: list[RequestResult] = []
    limits = httpx.Limits(
        max_connections=max(200, ceil(target_rps * timeout_s)), max_keepalive_connections=100
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s), limits=limits) as client:
        phase_start = time.monotonic()
        tasks = []
        for i in range(total_requests):
            scheduled_at = phase_start + i / target_rps
            now = time.monotonic()
            if scheduled_at > now:
                await asyncio.sleep(scheduled_at - now)
            user = users[i % len(users)]
            tasks.append(
                asyncio.create_task(
                    _send_query(client, base_url, user, question, results, scheduled_at, timeout_s)
                )
            )
        send_elapsed = time.monotonic() - phase_start
        await asyncio.gather(*tasks)
        total_elapsed = time.monotonic() - phase_start
    return results, LoadPhaseTiming(send_elapsed, total_elapsed)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def _summarize(
    results: list[RequestResult],
    timing: LoadPhaseTiming,
    target_rps: float,
    duration_s: float,
    user_count: int,
) -> Report:
    error_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for item in results:
        label = str(item.status_code) if item.status_code > 0 else "connection_error"
        status_counts[label] = status_counts.get(label, 0) + 1
        if item.error:
            error_counts[item.error] = error_counts.get(item.error, 0) + 1

    ok_latencies_ms = [item.latency_s * 1000 for item in results if item.status_code == 200]
    latency_ms = (
        {
            "min": min(ok_latencies_ms),
            "p50": _percentile(ok_latencies_ms, 50),
            "p90": _percentile(ok_latencies_ms, 90),
            "p95": _percentile(ok_latencies_ms, 95),
            "p99": _percentile(ok_latencies_ms, 99),
            "max": max(ok_latencies_ms),
            "mean": statistics.fmean(ok_latencies_ms),
        }
        if ok_latencies_ms
        else {}
    )

    return Report(
        target_rps=target_rps,
        duration_s=duration_s,
        user_count=user_count,
        total_sent=len(results),
        send_elapsed_s=timing.send_elapsed_s,
        total_elapsed_s=timing.total_elapsed_s,
        status_counts=status_counts,
        latency_ms=latency_ms,
        error_counts=error_counts,
        all_latency_ms=_distribution([r.latency_s * 1000 for r in results]),
        schedule_lag_ms=_distribution([r.schedule_lag_s * 1000 for r in results]),
        cited_answers=sum(r.cited_answer for r in results),
        achieved_send_rps=len(results) / timing.send_elapsed_s if timing.send_elapsed_s else 0.0,
        successful_rps=status_counts.get("200", 0) / timing.total_elapsed_s
        if timing.total_elapsed_s
        else 0.0,
    )


def _print_report(report: Report) -> None:
    print("\n=== Load test results ===")
    print(f"Offered rate:        {report.target_rps:.0f} req/s for {report.duration_s:.0f}s")
    print(f"User pool:           {report.user_count} throwaway tenants")
    print(
        f"Requests sent:       {report.total_sent} in {report.send_elapsed_s:.1f}s "
        f"({report.achieved_send_rps:.1f} tasks/s scheduled)"
    )
    print(
        f"Full drain:          {report.total_elapsed_s:.1f}s until every client attempt completed"
    )
    print(
        f"Successful (200):    {report.status_counts.get('200', 0)} "
        f"({report.successful_rps:.1f} req/s effective, over the full drain window)"
    )
    print(f"Rate-limited (429):  {report.status_counts.get('429', 0)}")
    other = {k: v for k, v in report.status_counts.items() if k not in ("200", "429")}
    if other:
        print(f"Other statuses:      {other}")
    if report.latency_ms:
        lat = report.latency_ms
        print(
            "Latency (200s, ms):  "
            f"min={lat['min']:.0f} p50={lat['p50']:.0f} p90={lat['p90']:.0f} "
            f"p95={lat['p95']:.0f} p99={lat['p99']:.0f} max={lat['max']:.0f} mean={lat['mean']:.0f}"
        )


def _distribution(values: list[float]) -> dict[str, float]:
    """Describe latencies or scheduling lag, including failed requests."""
    if not values:
        return {}
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": max(values),
    }


def _write_results_json(report: Report, path: Path) -> None:
    path.write_text(json.dumps(asdict(report), indent=2) + "\n")


def _validate_workload(args: argparse.Namespace) -> None:
    """Reject accidental quota tests and invalid scheduler inputs."""
    for name in (
        "users",
        "rps",
        "duration",
        "setup_concurrency",
        "timeout",
        "ready_timeout",
        "quota_requests",
        "quota_window",
    ):
        if getattr(args, name) <= 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be positive")
    expected = ceil(args.rps * min(args.duration, args.quota_window) / args.users)
    if expected > args.quota_requests and not args.allow_rate_limit:
        raise SystemExit(
            f"Workload needs approximately {expected} requests/user/window; quota is "
            f"{args.quota_requests}. Increase --users or explicitly use --allow-rate-limit."
        )


async def _reuse_pool(base_url: str, path: Path, count: int) -> list[ProvisionedUser]:
    """Refresh logins for a private pool manifest containing benchmark emails only."""
    entries = json.loads(path.read_text())
    users = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for entry in entries[:count]:
            response = await client.post(
                f"{base_url}/auth/login", json={"email": entry["email"], "password": PASSWORD}
            )
            response.raise_for_status()
            users.append(
                ProvisionedUser(
                    entry["index"],
                    entry["email"],
                    response.json()["access_token"],
                    entry["tenant_id"],
                )
            )
    if len(users) != count:
        raise SystemExit("Pool manifest has fewer users than requested")
    return users


async def main_async(args: argparse.Namespace) -> None:
    _validate_workload(args)
    if not SAMPLE_DOCUMENT.exists():
        raise SystemExit(f"Sample document not found: {SAMPLE_DOCUMENT}")

    print(
        f"Provisioning {args.users} throwaway tenants (register, ingest, wait for ready, activate)..."
    )
    setup_start = time.monotonic()
    if args.user_pool and args.user_pool.exists():
        users = await _reuse_pool(args.base_url, args.user_pool, args.users)
    else:
        users = await _provision_pool(
            args.base_url, args.users, args.ready_timeout, args.setup_concurrency
        )
        if args.user_pool:
            with args.user_pool.open("x") as handle:
                args.user_pool.chmod(0o600)
                json.dump(
                    [{"index": u.index, "email": u.email, "tenant_id": u.tenant_id} for u in users],
                    handle,
                )

    setup_elapsed = time.monotonic() - setup_start
    if not users:
        raise SystemExit("No users were successfully provisioned; aborting load test.")
    print(f"Provisioned {len(users)}/{args.users} users in {setup_elapsed:.1f}s.")
    if len(users) < args.users:
        raise SystemExit("Incomplete user pool; refusing to change the workload silently.")

    print(f"\nRunning load phase: target {args.rps:.0f} req/s for {args.duration:.0f}s ...")
    load_started_at = datetime.now(UTC).isoformat()
    results, timing = await _run_load_phase(
        args.base_url, users, args.rps, args.duration, args.question, args.timeout
    )
    report = _summarize(results, timing, args.rps, args.duration, len(users))
    _print_report(report)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_results_json(report, output_dir / "results.json")
    metadata = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "load_started_at": load_started_at,
        "label": args.label,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "timeout_s": args.timeout,
        "quota_requests": args.quota_requests,
        "quota_window_s": args.quota_window,
        "sample_sha256": sha256(SAMPLE_DOCUMENT.read_bytes()).hexdigest(),
        "question_sha256": sha256(args.question.encode()).hexdigest(),
    }
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (output_dir / "requests.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2) + "\n"
    )
    print(f"Errors: {report.error_counts}; cited answers: {report.cited_answers}")
    print(f"Schedule lag (ms): {report.schedule_lag_ms}")
    print(f"\nWrote {output_dir / 'results.json'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="API base URL")
    parser.add_argument(
        "--users", type=int, default=100, help="Number of throwaway tenants in the pool"
    )
    parser.add_argument(
        "--rps", type=float, default=100.0, help="Target aggregate requests per second"
    )
    parser.add_argument(
        "--duration", type=float, default=20.0, help="Load phase duration in seconds"
    )
    parser.add_argument(
        "--setup-concurrency", type=int, default=5, help="Max concurrent provisioning requests"
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for each document to become ready",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Total request deadline")
    parser.add_argument("--quota-requests", type=int, default=30)
    parser.add_argument("--quota-window", type=float, default=60.0)
    parser.add_argument("--allow-rate-limit", action="store_true")
    parser.add_argument(
        "--user-pool", type=Path, help="Private reusable email manifest, outside git"
    )
    parser.add_argument("--label", default="", help="Describe runtime configuration for this run")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Question sent by every query")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).resolve().parent),
        help="Where to write results.json",
    )
    return parser.parse_args()


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
