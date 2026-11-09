#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.request
from pathlib import Path


def request(url):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
            status = response.status
    except Exception as error:
        return {"status": 0, "seconds": time.perf_counter() - started, "error": str(error)}
    return {"status": status, "seconds": time.perf_counter() - started, "error": ""}


def percentile(values, fraction):
    values = sorted(values)
    return values[min(round((len(values) - 1) * fraction), len(values) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://omanskylight.com")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("artifacts/phase13-load.json"))
    args = parser.parse_args()
    urls = [f"{args.base_url}/health/", f"{args.base_url}/listings/"]
    work = [urls[index % len(urls)] for index in range(args.requests)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(request, work))
    elapsed = time.perf_counter() - started
    timings = [item["seconds"] for item in results]
    errors = [item for item in results if item["status"] != 200]
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(args.requests / elapsed, 2),
        "latency_ms": {
            "mean": round(statistics.mean(timings) * 1000, 2),
            "p50": round(percentile(timings, 0.50) * 1000, 2),
            "p95": round(percentile(timings, 0.95) * 1000, 2),
            "max": round(max(timings) * 1000, 2),
        },
        "errors": len(errors),
        "sample_errors": errors[:5],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    if errors or report["latency_ms"]["p95"] > 2000:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
