# Latest query benchmark results

**Run date:** 2026-09-23. The main test is the final 100 requests/s run; a subsequent
2 requests/s check used the same application configuration.

## Summary

**Database connection handling remained stable under the tested load, but the application
has not demonstrated 100 successful answers per second.** The final run returned 115
cited answers from 2,000 requests. The other 1,885 received `503 query_provider_unavailable`,
matching the recorded count of rate-limited Mistral embeddings.

There were no database errors, HTTP 500s, or client timeouts in that run. This is a good
result for controlled overload handling, but a **5.75% answer success rate** is unsuitable
for serving that workload reliably.

## Workload and results

The local Docker Compose stack used four Uvicorn API workers, PostgreSQL/pgvector,
PgBouncer, Redis, and real Mistral providers. Each of 100 tenant administrators had an
activated copy of the same small PDF and asked the same question. Setup and login were
excluded from the timed load phase. The client scheduled requests independently of
response completion and enforced a 30-second total request deadline.

At 100 requests/s for 20 seconds, each user sent 20 requests, below the unchanged quota
of 30 queries per 60 seconds. Provider throttling is distinct from this API user quota.

| Measurement | Main run: 100 requests/s | Follow-up: 2 requests/s |
| --- | ---: | ---: |
| Load duration | 20s | 20s |
| Total requests | 2,000 | 40 |
| Successful, with source citations | 115 (5.75%) | 39 (97.5%) |
| Provider-unavailable responses | 1,885 | 1 |
| Database errors / HTTP 500s / client timeouts | 0 / 0 / 0 | 0 / 0 / 0 |
| API user-quota rejections (`429`) | 0 | 0 |
| Successful-answer median | 2.59s | 1.64s |
| Successful-answer p95 | 6.68s | 3.54s |
| Full client drain duration | 27.27s | 21.24s |
| Successful responses per drain second | 4.22 | 1.84 |

The last row describes these finite bursts, not sustained capacity. The main run's
all-outcome p95 was 1.99s because most requests failed quickly; it must not be presented
as successful-answer latency. Client scheduling-lag p99 was 2.07ms. Citation presence
was checked, but answer quality was not manually evaluated.

## Bottlenecks

### Observed: embedding-provider admission

The main run's stage counters record:

- **2,000** completed lexical retrieval stages.
- **115** successful embeddings, followed by successful reranking and generation.
- **1,885** rate-limited embeddings, matching the provider-unavailable HTTP responses.

The configured Mistral embedding service was the demonstrated throughput bottleneck.
Interactive query embeddings now make one attempt when the provider is rate-limited,
preventing the previous 35-second retry-sleep sequence from amplifying overload.
Background ingestion retains its bounded retry policy.

More API workers or database connections will not remove this provider quota. The
one provider-unavailable response in the lower-rate check also means that sample does
not establish an error-free sustainable rate.

### Database: no saturation failure in the final run

Authentication releases its transaction after materializing current authorization.
Query reads release their connections before external embedding, reranking, and generation
waits. Later database reads reapply the verified actor through the transaction-start RLS hook.

PgBouncer uses transaction pooling, 10 server connections per role, an 80-connection
per-database cap, and a five-second queue wait. Application pools allow 10 connections
plus 20 overflow per role per API worker, with a five-second checkout timeout.

Across five periodic samples during the main run, PostgreSQL client backends peaked at
**25**, idle-in-transaction connections peaked at **11**, and the oldest observed transaction
was **0.21 seconds**. These are sampled observations, not exhaustive maxima. The absence
of database failures supports the current connection handling at this workload; it does
not prove capacity for larger corpora or sustained full-pipeline traffic.

### Still unverified: downstream and application capacity

Only 115 requests passed the embedding stage. A provider with greater admission capacity
would send more traffic through vector retrieval, reranking, and generation, potentially
exposing another limit. CPU, memory, connection budgets, corpus size, and provider token
throughput all need validation at that higher completion rate.

## Expectations

- **Light usage:** response times are encouraging, but the 39/40 lower-rate sample is too
  small and short to claim production reliability.
- **100–200 successful queries/s:** remains an unverified target. With one embedding cohort,
  a normal successful query makes approximately three provider calls: embedding, reranking,
  and generation. Budget roughly 300–600 provider calls/s at those query rates, plus token
  headroom and any extra calls for retries or citation correction.
- **More API workers:** can help when API compute is limiting and extra resources are
  available. They do not automatically multiply capacity or increase shared provider and
  database limits.
- **Users per worker:** the [autoscaling guide](../docs/AUTOSCALING.md) proposes **25
  full-quota users per API worker**, scaling around **17–18 equivalent users per worker**.
  These correspond to 12.5 and 8.75 queries/s per worker respectively and remain sizing
  hypotheses, not benchmark findings.

The next useful capacity test is a sustained, realistic-corpus run with confirmed provider
headroom, comparing worker counts and increasing load. Target successful-answer p95 below
five seconds and fewer than 1% failures as provisional acceptance criteria. A separate test
with realistic simulated provider latency can isolate infrastructure capacity; a real-provider
run is still required to validate the complete service.

## Retained evidence and reproduction

Only compact evidence from the final configuration is retained:

- [Main results](latest/results.json) and [run metadata](latest/metadata.json).
- [Runtime settings](latest/runtime.json).
- [Stage metric deltas](latest/metrics-delta.json) and [connection summary](latest/connection-summary.json).
- [Lower-rate results](latest/low-rate-results.json) and [metadata](latest/low-rate-metadata.json).

Superseded runs, per-request logs, full metrics dumps, and connection samples were removed.
The run metadata includes a Git revision and dirty-tree flag; the revision alone cannot
reproduce the runtime. These results cover short local tests with one small document and
one repeated question, not a large-corpus, mixed-user, or answer-quality evaluation.

```bash
uv run python benchmark/load_test.py --users 100 --rps 100 --duration 20 \
  --output-dir benchmark/new-run --label 'record deployed settings here'
```

The 100-user default fits this 20-second burst. Sustained 100 requests/s requires at least
200 evenly paced users under the default quota; 200 requests/s requires at least 400.
See [benchmark methodology](README.md) for setup, quota checks, and measurement definitions.
