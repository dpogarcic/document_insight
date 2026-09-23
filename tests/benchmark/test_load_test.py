"""Benchmark quota validation, deadlines, and safe error reporting."""

import argparse
import asyncio

import httpx
import pytest

from benchmark.load_test import (
    LoadPhaseTiming,
    ProvisionedUser,
    RequestResult,
    _send_query,
    _summarize,
    _validate_workload,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def workload(users: int, duration: float) -> argparse.Namespace:
    return argparse.Namespace(
        users=users,
        rps=100,
        duration=duration,
        setup_concurrency=5,
        timeout=30,
        ready_timeout=60,
        quota_requests=30,
        quota_window=60,
        allow_rate_limit=False,
    )


def test_quota_validation_distinguishes_burst_from_sustained_load() -> None:
    _validate_workload(workload(100, 20))
    _validate_workload(workload(200, 120))
    with pytest.raises(SystemExit, match="Increase --users"):
        _validate_workload(workload(100, 60))
    with pytest.raises(SystemExit, match="Increase --users"):
        _validate_workload(workload(20, 20))


@pytest.mark.anyio
async def test_request_deadline_includes_entire_client_operation() -> None:
    async def delayed(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        return httpx.Response(200)

    results: list[RequestResult] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(delayed)) as client:
        await _send_query(
            client, "http://test", ProvisionedUser(0, "", "", ""), "question", results, 0.0, 0.01
        )
    assert results[0].error == "TimeoutError"
    assert results[0].status_code == -1


@pytest.mark.anyio
async def test_safe_error_code_and_correlation_id_are_preserved() -> None:
    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"detail": {"code": "database_unavailable"}},
            headers={"X-Correlation-ID": "example"},
        )

    results: list[RequestResult] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        await _send_query(
            client, "http://test", ProvisionedUser(0, "", "", ""), "question", results, 0.0, 1.0
        )
    assert results[0].error == "database_unavailable"
    assert results[0].correlation_id == "example"
    report = _summarize(results, LoadPhaseTiming(1, 2), 1, 1, 1)
    assert report.error_counts == {"database_unavailable": 1}
    assert report.latency_ms == {}
    assert report.all_latency_ms


@pytest.mark.anyio
async def test_success_counts_source_citations_without_saving_content() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sources": [{"quote": "private content"}]})

    results: list[RequestResult] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(answer)) as client:
        await _send_query(
            client, "http://test", ProvisionedUser(0, "", "", ""), "question", results, 0.0, 1.0
        )
    assert results[0].cited_answer
    assert "private content" not in repr(results)
