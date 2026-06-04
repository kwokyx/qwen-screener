"""Smoke test for built-in strategy performance.

Run after Docker services are up:
    docker compose exec -T backend python scripts/smoke_strategy_performance.py
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.database import SessionLocal
from app.services import strategy_selector


DEFAULT_LIMIT = 20
STRATEGIES = [
    "turtle_breakout",
    "ma_volume",
    "rps_breakout",
    "high_tight_flag",
    "limit_up_shakeout",
    "uptrend_limit_down",
]


def _run_strategy(strategy_id: str, limit: int) -> dict:
    db = SessionLocal()
    started = time.perf_counter()
    try:
        result = strategy_selector.run_strategy_selection(db, strategy_id, limit=limit)
    finally:
        db.close()
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    scope_note = next((note for note in result.notes if "回测" in note), "")
    return {
        "strategy_id": strategy_id,
        "trade_date": result.trade_date,
        "total": result.total,
        "returned": len(result.items),
        "elapsed_ms": elapsed_ms,
        "scope_note": scope_note,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run built-in strategy performance smoke.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    print("strategy_id\ttrade_date\ttotal\treturned\telapsed_ms\tscope_note", flush=True)
    for strategy_id in STRATEGIES:
        try:
            row = _run_strategy(strategy_id, args.limit)
        except Exception as exc:
            print(f"{strategy_id}\tERROR\t-\t-\t-\t{str(exc)[:160]}", flush=True)
            return 1
        print(
            f"{row['strategy_id']}\t{row['trade_date'] or '-'}\t{row['total']}\t"
            f"{row['returned']}\t{row['elapsed_ms']}\t{row['scope_note']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
