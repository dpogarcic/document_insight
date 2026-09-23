# Query load benchmark

`load_test.py` provisions isolated throwaway tenants, uploads and activates the same
small sample PDF, then schedules authenticated `POST /query` requests at a fixed
open-loop rate. It uses real configured model providers. Run only against a disposable
or local development stack; it creates persistent users, documents, and provider traffic.

```bash
uv run python benchmark/load_test.py --users 100 --rps 100 --duration 20 \
  --output-dir benchmark/my-run --label 'describe the running configuration'
```

The default 100 users each send 20 requests during this 20-second burst, below the
30 requests per 60 seconds quota. Sustained 100 requests/s requires at least **200
users** under that quota. The script rejects a workload that would exceed its declared
quota unless `--allow-rate-limit` is explicitly supplied. `--quota-requests` and
`--quota-window` describe the server's configuration; they do not change the server.

Use `--user-pool /tmp/document-insight-benchmark-users.json` to save and reuse the same
provisioned users. The private manifest contains emails and tenant IDs, never bearer
tokens; reuse logs in again. Do not put it in version control. Wait at least one quota
window between repeated runs on the same pool. A failed/incomplete setup aborts rather
than silently using fewer users. Setup remains separate from the timed load phase.

## Measurements

- `results.json`: status counts, safe API error codes, distinct client exception types,
  successful-response and all-outcome latency distributions, scheduler lag, and number
  of responses containing source citations. Citation presence does not establish quality.
- `requests.json`: per-request duration, client dispatch time (monotonic), scheduling
  lag, status, safe error code, correlation ID, and citation presence. No question,
  answer, passage, password, or bearer token is saved.
- `metadata.json`: UTC report time, run label, Git revision/dirty flag, request deadline,
  declared quota, and hashes of the sample file and question. The label should record
  deployed settings; a dirty revision alone cannot reproduce the runtime.

`send_elapsed_s` and `achieved_send_rps` measure **client task scheduling**, not confirmed
server arrival. Scheduling lag measures the delay until each task starts its client
operation. HTTP connection limits allow up to rate × deadline concurrent connections;
client-side network waits still contribute to observed latency. `--timeout` (default
30 seconds) is a total per-request deadline, including client pool and network waits.
Timeout means the client stopped waiting; server work can continue afterwards.

`successful_rps` divides HTTP 200 completions by the entire client drain window. This
is a burst-completion statistic, not an estimate of sustained service capacity.
The test uses one small PDF and one repeated question, with tenant administrators.
It does not replace answer-quality, large-corpus, department-denial, or ingest-load tests.

See [results.md](results.md) for the latest results, bottlenecks, and capacity expectations.
The compact evidence is retained under [latest/](latest/): the final high-rate report,
run metadata, runtime settings, stage metric deltas, connection summary, and the lower-rate
follow-up report and metadata. Superseded runs, per-request logs, full metrics dumps, and
connection samples are not retained. The script still produces per-request records for
new investigations; keep them only while they are useful for diagnosis.

The API fails fast on a rate-limited query embedding request (`503` with
`query_provider_unavailable`); it does not spend 35 seconds retrying provider saturation.
Background ingestion still uses the existing embedding retry policy. A provider `429`
is distinct from the API's per-user `429` quota response.
