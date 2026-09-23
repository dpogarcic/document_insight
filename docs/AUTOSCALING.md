# API capacity and autoscaling guide

- **Status:** Draft sizing hypothesis
- **Date:** 2026-09-23
- **Scope:** Public API workers serving `POST /query`. An API worker means one Uvicorn
  process, not an RQ ingestion or evaluation worker.

## Initial estimate per API worker

Use **25 users continuously consuming their full query allowance per API worker** as
the initial capacity hypothesis. Plan to scale out at approximately **17–18 equivalent
full-quota users per worker**, or 70% of that hypothesized capacity.

These figures assume sufficient model-provider capacity, adequate CPU and memory, and
short database transactions. They are derived from a proposed 50 requests/s test target
for four workers. They are **not** measurements of a single worker or evidence that
capacity grows linearly with worker count.

| Planning measure | Per API worker |
| --- | ---: |
| Hypothesized sustained query capacity | 12.5 requests/s |
| Equivalent users continuously at the default quota | 25 |
| Proposed scale-out threshold, at 70% capacity | 8.75 requests/s |
| Equivalent full-quota users at that threshold | 17.5, approximately 17–18 |

Do not use these numbers as production limits until the validation below passes.

## Converting users into query traffic

The default per-user quota is **30 queries per 60 seconds**, equivalent to 0.5 queries/s
over sustained usage. Tenant/user quota state is shared through Redis across API workers.

```text
Sustained query rate = active users × average queries per user per minute / 60
Equivalent full-quota users = sustained query rate / 0.5
```

"Equivalent full-quota users" expresses workload, not a limit on registered users,
logged-in sessions, or open browser tabs. For example:

| Workload across 1,000 active users | Aggregate query rate |
| --- | ---: |
| One question per user every five minutes | 3.3 requests/s |
| One question per user per minute | 16.7 requests/s |
| Three questions per user per minute | 50 requests/s |
| Six questions per user per minute | 100 requests/s |
| Twelve questions per user per minute | 200 requests/s |

The quota does not pace requests evenly. A user can spend their allowance in a burst.
Provisioning headroom and bounded in-flight work are separate requirements; autoscaling
cannot respond instantly to a synchronized burst. This document does not implement a
global concurrency limit or an autoscaler.

## Illustrative worker counts

The following is arithmetic using the initial hypothesis, not measured scaling behavior.
It assumes sufficient additional compute resources and no shared downstream bottleneck.

| API workers | Hypothesized full-quota users | Hypothesized query capacity | Scale-out trigger at 70% |
| --- | ---: | ---: | ---: |
| 1 | 25 | 12.5 requests/s | 8.75 requests/s, or 17.5 equivalent users |
| 4 | 100 | 50 requests/s | 35 requests/s, or 70 equivalent users |
| 8 | 200 | 100 requests/s | 70 requests/s, or 140 equivalent users |
| 12 | 300 | 150 requests/s | 105 requests/s, or 210 equivalent users |

Twelve workers therefore do not imply a validated 200 requests/s capacity. Adding
processes to the same CPU-constrained host may provide little benefit or worsen latency.
Async workers already serve multiple requests concurrently; they are not limited to one
in-flight query each. Additional processes consume memory and maintain independent pools.

## Proposed scaling policy

1. **Validate capacity first.** On the intended production hardware, find the highest
   sustained full-pipeline rate that satisfies the proposed objectives: successful-answer
   p95 below five seconds and fewer than 1% unsuccessful requests. These objectives also
   remain provisional until accepted for the product. Provider failures and client
   timeouts count against end-to-end reliability; quick failures do not improve the
   successful-answer latency metric.
2. **Scale out around 70% of validated capacity**, sustained for one to two minutes.
   Use aggregate query arrival rate and ready API capacity, not registered-user counts.
   Replace the 12.5 requests/s per-worker hypothesis with measured values; validate each
   deployment size rather than assuming linear scaling. For a validated four-worker
   capacity of 50 requests/s, the initial trigger would be 35 requests/s.
3. **Watch API queueing and resource pressure.** Growing request queues, increasing
   latency, and CPU saturation can justify earlier scaling when API compute is the
   limiting resource. Investigate per-instance imbalance as well as fleet averages.
4. **Distinguish downstream saturation.** Provider throttling requires provider headroom
   or admission control. Database saturation requires database/pool investigation.
   Neither condition should trigger an unlimited increase in API workers.
5. **Scale in conservatively.** Use a sustained low-load window, retain capacity for
   bursts, and drain in-flight requests. Choose and validate the minimum replica count,
   cooldown, and shutdown grace period before enabling automatic scale-in.

In production, an autoscaler would normally add or remove API replicas with a defined
worker count and resource allocation. Changing `--workers` in Compose and restarting
the service is a manual capacity change. Platform selection and autoscaling implementation
remain deferred under the [architecture](ARCHITECTURE.md).

## Shared capacity constraints

The current development configuration allows up to 30 application connections per
database role per API worker: 10 pooled plus 20 overflow. Twelve workers could therefore
open up to **720 client connections to PgBouncer for authentication and query roles
alone**. Other roles and services add more against its 1,000-client limit. Pools are
opened on demand; this is a possible ceiling, not expected steady-state usage.

PgBouncer independently limits server connections to 10 per role and 80 per database.
Adding API workers does not increase PostgreSQL capacity. Review application pool sizes,
PgBouncer limits, database resources, and operational headroom together before scaling.

With one enabled embedding cohort and the normal successful path, each query requires
approximately one embedding, one reranking, and one generation call. At 100 queries/s,
budget approximately **300 provider calls/s**; at 200 queries/s, approximately **600**.
Additional embedding cohorts, retries, and citation correction can add calls. Provider
request quotas, token quotas, and latency must support the full pipeline.

## Evidence and validation gate

The [2026-09-23 benchmark report](../benchmark/results.md) records a final four-worker
run at 100 offered queries/s for 20 seconds:

- All 2,000 requests completed lexical retrieval.
- No database errors, HTTP 500s, or client timeouts occurred in that final run.
- PostgreSQL client backends peaked at 25 in the periodic samples.
- Only 115 requests returned answers; 1,885 embeddings were provider-rate-limited.
- Successful-answer p50 was 2.59 seconds and p95 was 6.68 seconds.

This supports the improvement in connection handling. It does **not** establish reliable
full-pipeline capacity at 50, 100, or 200 queries/s. The final lower-rate sample at
2 queries/s completed 39 of 40 requests, so it also does not establish a zero-error rate.

Before adopting a production users-per-worker figure:

- Compare 4, 8, and 12 workers on documented CPU/memory allocations, including API replicas
  if that is the intended deployment topology.
- Use representative corpus sizes, questions, tenant/department distributions, and provider
  latency. Ensure provider request and token quotas have sufficient headroom.
- Test increasing offered rates, including 25, 50, 100, and 200 queries/s, long enough to
  reach steady load, then test bursts and recovery. A proposed minimum is 15 minutes per
  sustained load point; longer runs are needed for production confidence.
- Preserve the user quota. Sustained 100 queries/s needs at least 200 evenly paced users;
  sustained 200 queries/s needs at least 400. The benchmark's default 100 users is suitable
  for its 20-second burst, not sustained 100 queries/s.
- Record success/error rates, successful-answer p95, queueing, CPU/memory, connection
  occupancy, provider throttling, and scheduler lag. Test scale-out and graceful scale-in.
- Use a separately labelled test with simulated provider latency to isolate infrastructure
  capacity, then confirm the result with real providers. Do not equate simulated and
  end-to-end capacity.

## References

- [Benchmark methodology](../benchmark/README.md)
- [Tenant isolation and shared per-user quota](adr/003-tenant-isolation.md)
- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/)
- [PgBouncer configuration](https://www.pgbouncer.org/config)
