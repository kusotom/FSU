import argparse
import statistics
import time

import psycopg


def timed_exec(conn: psycopg.Connection, sql: str) -> float:
    t0 = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql)
    return time.perf_counter() - t0


def explain_ms(conn: psycopg.Connection, sql: str) -> float:
    with conn.cursor() as cur:
        cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)
        row = cur.fetchone()[0]
    return float(row[0]["Execution Time"])


def main():
    parser = argparse.ArgumentParser(description="Compare PostgreSQL table vs TimescaleDB hypertable performance.")
    parser.add_argument("--dsn", default="postgresql://fsu:fsu123456@127.0.0.1:5432/fsu")
    parser.add_argument("--rows", type=int, default=800000)
    parser.add_argument("--points", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()

    conn = psycopg.connect(args.dsn)
    conn.autocommit = True

    setup_sql = f"""
    DROP TABLE IF EXISTS bench_pg;
    DROP TABLE IF EXISTS bench_ts;

    CREATE TABLE bench_pg (
      id BIGSERIAL PRIMARY KEY,
      point_id INTEGER NOT NULL,
      collected_at TIMESTAMPTZ NOT NULL,
      value DOUBLE PRECISION NOT NULL
    );
    CREATE INDEX ix_bench_pg_point_collected_at ON bench_pg (point_id, collected_at DESC);
    CREATE INDEX ix_bench_pg_collected_at ON bench_pg (collected_at DESC);

    CREATE TABLE bench_ts (
      id BIGSERIAL,
      point_id INTEGER NOT NULL,
      collected_at TIMESTAMPTZ NOT NULL,
      value DOUBLE PRECISION NOT NULL,
      PRIMARY KEY (id, collected_at)
    );
    SELECT create_hypertable('bench_ts', 'collected_at', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
    CREATE INDEX IF NOT EXISTS ix_bench_ts_point_collected_at ON bench_ts (point_id, collected_at DESC);
    CREATE INDEX IF NOT EXISTS ix_bench_ts_collected_at ON bench_ts (collected_at DESC);
    """

    with conn.cursor() as cur:
        cur.execute(setup_sql)

    insert_pg = f"""
    INSERT INTO bench_pg (point_id, collected_at, value)
    SELECT ((g - 1) % {args.points}) + 1,
           now() - (({args.rows} - g) * interval '1 second'),
           (random() * 100)::double precision
    FROM generate_series(1, {args.rows}) AS g;
    """
    insert_ts = f"""
    INSERT INTO bench_ts (point_id, collected_at, value)
    SELECT ((g - 1) % {args.points}) + 1,
           now() - (({args.rows} - g) * interval '1 second'),
           (random() * 100)::double precision
    FROM generate_series(1, {args.rows}) AS g;
    """

    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench_pg;")
    pg_insert_sec = timed_exec(conn, insert_pg)

    with conn.cursor() as cur:
        cur.execute("TRUNCATE bench_ts;")
    ts_insert_sec = timed_exec(conn, insert_ts)

    queries = {
        "q1_point_24h_top500": "SELECT * FROM {table} WHERE point_id = 42 AND collected_at >= now() - interval '24 hour' ORDER BY collected_at DESC LIMIT 500",
        "q2_range_30d_count": "SELECT count(*) FROM {table} WHERE collected_at >= now() - interval '30 day'",
        "q3_bucket_6h_avg": "SELECT date_bin(interval '5 minute', collected_at, timestamptz '2000-01-01') AS b, avg(value) FROM {table} WHERE point_id = 42 AND collected_at >= now() - interval '6 hour' GROUP BY 1 ORDER BY 1",
    }

    print("BENCHMARK_RESULT_START")
    print(f"rows={args.rows}, points={args.points}, runs={args.runs}")
    print(f"insert_pg_sec={pg_insert_sec:.3f}")
    print(f"insert_ts_sec={ts_insert_sec:.3f}")

    for name, tpl in queries.items():
        q_pg = tpl.format(table="bench_pg")
        q_ts = tpl.format(table="bench_ts")

        explain_ms(conn, q_pg)
        explain_ms(conn, q_ts)

        pg_runs = [explain_ms(conn, q_pg) for _ in range(args.runs)]
        ts_runs = [explain_ms(conn, q_ts) for _ in range(args.runs)]

        print(name)
        print(f"  pg_ms_avg={statistics.mean(pg_runs):.3f}")
        print(f"  ts_ms_avg={statistics.mean(ts_runs):.3f}")
        print(f"  pg_runs={','.join(f'{x:.3f}' for x in pg_runs)}")
        print(f"  ts_runs={','.join(f'{x:.3f}' for x in ts_runs)}")

    print("BENCHMARK_RESULT_END")
    conn.close()


if __name__ == "__main__":
    main()
