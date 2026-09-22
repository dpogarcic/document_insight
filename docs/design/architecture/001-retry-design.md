# Retry design for asynchronous document processing

- **Status:** In Review
- **Date:** 2026-09-22
- **Decision owners:** Engineering

## Context

ADR 002 specifies that workers use bounded retries with exponential backoff for transient failures,
that attempts and timestamps are persisted, and that a reconciliation process finds stale `processing`
jobs and retries or fails them. This document defines the concrete retry behavior, failure classification,
and reconciliation mechanics for the ingestion worker.

## Principles

1. **Transient failures are retried.** Network timeouts, provider errors, and database contention are
   transient and should be retried with exponential backoff.
2. **Permanent failures are not retried automatically.** Parsing failures, unsupported media types,
   invalid profiles, and exhausted retry budgets are permanent and must be marked as such.
3. **Partial success is not success.** A job that has completed parsing but failed embedding is not
   ready. The job must either complete all stages or be marked failed.
4. **Retry state is durable.** Attempt counts, timestamps, and error categories are persisted in
   PostgreSQL so that restarts and reconciliation can make correct decisions.

## Failure classification

Every failure is classified into one of these categories, stored on the job row:

| Category | Description | Retryable? |
|----------|-------------|------------|
| `transient` | Network timeout, provider error, database contention | Yes, with backoff |
| `permanent` | Parsing failure, unsupported media, invalid profile, max attempts reached | No |
| `timeout` | Stage exceeded its time budget | Yes, once |
| `configuration` | Profile or provider misconfiguration | No |

## Retry policy

### Per-attempt backoff

```
backoff_seconds = min(60, 2 * 2^attempt) + jitter
```

where `attempt` is the zero-based attempt count, and jitter is a random value in `[-25%, +25%]`
of the calculated backoff.

| Attempt | Base backoff | Capped backoff |
|---------|--------------|----------------|
| 0 | 2s | 2s |
| 1 | 4s | 4s |
| 2 | 8s | 8s |
| 3 | 16s | 16s |
| 4 | 32s | 32s |
| 5+ | 64s | 60s |

### Maximum attempts

Default `max_attempts` is 5. When `attempt_count >= max_attempts`, the job is marked as a permanent
failure with reason `max_attempts_reached` and is not retried.

### Stale job detection

A job in `processing` status for more than the stale threshold (default 10 minutes) is considered
stale and is a candidate for reconciliation. The reconciliation query is:

```sql
DELETE FROM processing_jobs
WHERE status = 'processing'
  AND updated_at < now() - interval '10 minutes'
RETURNING job_id, attempt_count, error_category;
```

Stalled jobs are re-queued for retry if they have remaining attempts; otherwise they are marked failed.

## Worker behavior

### On transient failure during a stage

1. Increment `attempt_count`.
2. Set `error_category = 'transient'`.
3. Calculate `next_retry_at = now() + backoff(attempt_count)`.
4. Update the job row with the new state.
5. Log: `processing job {id} stalled for {delay}s (attempt {n}/{max}, next retry in {delay}s)`
6. Do not mark the job as failed; allow the reconciliation process or a scheduled retry to resume it.

The current implementation re-enqueues the job in RQ immediately with an `at` schedule set to `next_retry_at`, so the worker picks it up automatically after the backoff period without waiting for a separate reconciliation process.

### On permanent failure during a stage

1. Set `error_category = 'permanent'`.
2. Mark the job as failed with an appropriate reason.
3. Do not increment `attempt_count` for permanent failures (they are not retried).

### On max attempts reached

1. Set `error_category = 'permanent'`.
2. Mark the job as failed with reason `max_attempts_reached`.
3. Log the terminal failure.

## Reconciliation process

A periodic task (or ad-hoc trigger) performs stale job detection:

1. Find jobs in `processing` status older than the stale threshold.
2. For each stale job:
   - If `attempt_count < max_attempts` and `error_category` is retryable: re-queue for retry.
   - Otherwise: mark as failed with appropriate reason.

## Schema changes

### New columns on `processing_jobs`

| Column | Type | Description |
|--------|------|-------------|
| `attempt_count` | integer, default 0 | Number of processing attempts |
| `last_attempt_at` | timestamp | When the last attempt started |
| `next_retry_at` | timestamp | When the job is eligible for retry |
| `error_category` | varchar(20) | `transient`, `permanent`, `timeout`, `configuration` |
| `failure_reason` | varchar(100) | Machine-readable failure reason |

### Migration

A new Alembic migration adds these columns with backfill defaults for existing rows.

## Logging

On each retry decision, log a structured message:

```
processing job {job_id} stalled for {delay}s (attempt {attempt_count}/{max_attempts}, next retry in {delay}s)
```

On terminal failure:

```
processing job {job_id} marked failed: {reason} (attempt {attempt_count}/{max_attempts}, category {error_category})
```

## Observability

- `attempt_count` and `error_category` are exposed through `GET /jobs/{job_id}`.
- Metrics: count of retries by category, count of terminal failures by reason, P95 retry delay.

## Out of scope

- Per-tenant retry configuration (future work).
- Automatic retry of `ready` jobs (not needed; `ready` means complete).
- Retry of already-failed jobs via the API (future operator action).
