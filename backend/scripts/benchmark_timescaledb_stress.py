import argparse
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg


def explain_ms(conn: psycopg.Connection, sql: str) -> float:
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
        payload = cur.fetchone()[0]
    return float(payload[0]["Execution Time"])


def run_query_bench(conn: psycopg.Connection, table: str, runs: int) -> dict:
    queries = {
        "q1_point_7d_top1000": f"SELECT * FROM {table} WHERE point_id=42 AND collected_at>=now()-interval '7 day' ORDER BY collected_at DESC LIMIT 1000",
        "q2_range_30d_count": f"SELECT count(*) FROM {table} WHERE collected_at>=now()-interval '30 day'",
        "q3_bucket_30d_avg": (
            f"SELECT date_bin(interval '1 hour', collected_at, timestamptz '2000-01-01') AS b, avg(value) "
            f"FROM {table} WHERE point_id=42 AND collected_at>=now()-interval '30 day' GROUP BY 1 ORDER BY 1"
        ),
    }
    result = {}
    for name, sql in queries.items():
        explain_ms(conn, sql)
        runs_ms = [explain_ms(conn, sql) for _ in range(runs)]
        result[name] = {
            "avg_ms": statistics.mean(runs_ms),
            "runs_ms": runs_ms,
        }
    return result


def worker_insert(dsn: str, table: str, rows: int, batch_rows: int, points: int, span_seconds: int, seed: int) -> int:
    conn = psycopg.connect(dsn)
    conn.autocommit = True
    inserted = 0
    try:
        while inserted < rows:
            n = min(batch_rows, rows - inserted)
            offset = seed + inserted
            sql = f"""
            INSERT INTO {table} (point_id, collected_at, value)
            SELECT ((g + {offset}) % {points}) + 1,
                   now() - (((g + {offset}) % {span_seconds}) * interval '1 second'),
                   (random() * 100)::double precision
            FROM generate_series(1, {n}) AS g;
            """
            with conn.cursor() as cur:
                cur.execute(sql)
            inserted += n
    finally:
        conn.close()
    return inserted


def parallel_insert(
    dsn: str, table: str, total_rows: int, workers: int, batch_rows: int, points: int, span_days: int
) -> tuple[float, int]:
    span_seconds = max(span_days, 1) * 24 * 3600
    base = total_rows // workers
    extra = total_rows % workers
    t0 = time.perf_counter()
    inserted_total = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for i in range(workers):
            rows = base + (1 if i < extra else 0)
            seed = i * 10_000_000
            futures.append(
                pool.submit(worker_insert, dsn, table, rows, batch_rows, points, span_seconds, seed)
            )
        for fut in as_completed(futures):
            inserted_total += fut.result()
    return time.perf_counter() - t0, inserted_total


def main():
    parser = argparse.ArgumentParser(description="Stress benchmark: PostgreSQL table vs Timescale hypertable.")
    parser.add_argument("--dsn", default="postgresql://fsu:fsu123456@127.0.0.1:5432/fsu")
    parser.add_argument("--rows", type=int, default=1200000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-rows", type=int, default=5000)
    parser.add_argument("--points", type=int, default=2000)
    parser.add_argument("--span-days", type=int, default=60)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    conn = psycopg.connect(args.dsn)
    conn.autocommit = True

    setup_sql = """
    DROP TABLE IF EXISTS bench_pg_stress;
    DROP TABLE IF EXISTS bench_ts_stress;

    CREATE TABLE bench_pg_stress (
      id BIGSERIAL PRIMARY KEY,
      point_id INTEGER NOT NULL,
      collected_at TIMESTAMPTZ NOT NULL,
      value DOUBLE PRECISION NOT NULL
    );
    CREATE INDEX ix_bench_pg_stress_point_collected_at ON bench_pg_stress (point_id, collected_at DESC);
    CREATE INDEX ix_bench_pg_stress_collected_at ON bench_pg_stress (collected_at DESC);

    CREATE TABLE bench_ts_stress (
      id BIGSERIAL,
      point_id INTEGER NOT NULL,
      collected_at TIMESTAMPTZ NOT NULL,
      value DOUBLE PRECISION NOT NULL,
      PRIMARY KEY (id, collected_at)
    );
    SELECT create_hypertable('bench_ts_stress', 'collected_at', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
    CREATE INDEX IF NOT EXISTS ix_bench_ts_stress_point_collected_at ON bench_ts_stress (point_id, collected_at DESC);
    CREATE INDEX IF NOT EXISTS ix_bench_ts_stress_collected_at ON bench_ts_stress (collected_at DESC);
    """
    with conn.cursor() as cur:
        cur.execute(setup_sql)

    pg_insert_sec, pg_rows = parallel_insert(
        args.dsn, "bench_pg_stress", args.rows, args.workers, args.batch_rows, args.points, args.span_days
    )
    ts_insert_sec, ts_rows = parallel_insert(
        args.dsn, "bench_ts_stress", args.rows, args.workers, args.batch_rows, args.points, args.span_days
    )

    with conn.cursor() as cur:
        cur.execute("ANALYZE bench_pg_stress;")
        cur.execute("ANALYZE bench_ts_stress;")

    pg_query = run_query_bench(conn, "bench_pg_stress", args.runs)
    ts_query_before = run_query_bench(conn, "bench_ts_stress", args.runs)

    with conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE bench_ts_stress SET (
              timescaledb.compress,
              timescaledb.compress_segmentby = 'point_id',
              timescaledb.compress_orderby = 'collected_at DESC'
            );
            """
        )
        cur.execute(
            """
            SELECT compress_chunk(c, if_not_compressed => TRUE)
            FROM show_chunks('bench_ts_stress', older_than => interval '7 day') AS c;
            """
        )
        cur.execute("ANALYZE bench_ts_stress;")

    ts_query_after = run_query_bench(conn, "bench_ts_stress", args.runs)

    print("STRESS_BENCHMARK_RESULT_START")
    print(
        f"rows={args.rows}, workers={args.workers}, batch_rows={args.batch_rows}, "
        f"points={args.points}, span_days={args.span_days}, runs={args.runs}"
    )
    print(f"insert_pg_sec={pg_insert_sec:.3f} rows={pg_rows}")
    print(f"insert_ts_sec={ts_insert_sec:.3f} rows={ts_rows}")

    for name in pg_query:
        print(name)
        print(f"  pg_avg_ms={pg_query[name]['avg_ms']:.3f}")
        print(f"  ts_before_compress_avg_ms={ts_query_before[name]['avg_ms']:.3f}")
        print(f"  ts_after_compress_avg_ms={ts_query_after[name]['avg_ms']:.3f}")
        print("  pg_runs_ms=" + ",".join(f"{x:.3f}" for x in pg_query[name]["runs_ms"]))
        print("  ts_before_runs_ms=" + ",".join(f"{x:.3f}" for x in ts_query_before[name]["runs_ms"]))
        print("  ts_after_runs_ms=" + ",".join(f"{x:.3f}" for x in ts_query_after[name]["runs_ms"]))

    print("STRESS_BENCHMARK_RESULT_END")
    conn.close()


if __name__ == "__main__":
    main()
