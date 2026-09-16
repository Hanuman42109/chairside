"""CLI: score one or more transcript fixtures against expected outcomes.

Usage:
    python -m app.eval.run_eval app/eval/fixtures/sample_new_booking.json
    python -m app.eval.run_eval app/eval/fixtures/*.json --write-db
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.eval.evaluator import EvalResult, evaluate_call


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


async def _write_to_db(call_id: str, result: EvalResult) -> None:
    from app.db import repository

    # NOTE: eval_scores.call_id is a foreign key to calls.id -- fixtures use
    # made-up ids, so --write-db only makes sense once pointed at a real call
    # UUID that already exists in the `calls` table.
    await repository.create_eval_score(
        call_id,
        slot_filling_accuracy=result.slot_filling_accuracy,
        hallucination_score=result.hallucination_score,
        escalation_correctness=result.escalation_correctness,
        overall_score=result.overall_score,
        notes="; ".join(result.notes),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Score call transcript fixtures.")
    parser.add_argument("fixtures", nargs="+", help="Path(s) to fixture JSON files.")
    parser.add_argument(
        "--write-db",
        action="store_true",
        help="Also write results to eval_scores (requires a real call UUID as call_id).",
    )
    args = parser.parse_args()

    for fixture_path in args.fixtures:
        path = Path(fixture_path)
        fixture = _load_fixture(path)
        result = evaluate_call(fixture)

        print(f"\n{path.name}")
        print(f"  call_id:                 {fixture.get('call_id')}")
        print(f"  slot_filling_accuracy:   {result.slot_filling_accuracy}")
        print(f"  hallucination_score:     {result.hallucination_score}")
        print(f"  escalation_correctness:  {result.escalation_correctness}")
        print(f"  overall_score:           {result.overall_score}")
        for note in result.notes:
            print(f"    - {note}")

        if args.write_db:
            asyncio.run(_write_to_db(fixture["call_id"], result))


if __name__ == "__main__":
    main()
