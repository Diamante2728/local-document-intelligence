"""CLI: python -m src.qa.ask "your question here" [--json] [--no-llm-router]"""
import argparse
import json
import sys
import time


def format_citation(c):
    parts = [str(c.get("doc", "?"))]
    if c.get("page") is not None:
        parts.append(f'p{c["page"]}')
    if c.get("table_id"):
        parts.append(str(c["table_id"]))
    if c.get("cell"):
        parts.append(f'r{c["cell"]["row"]}c{c["cell"]["col"]}')
    if c.get("unit"):
        parts.append(f'[{c["unit"]}]')
    return " ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Ask a question over the local document corpus.")
    parser.add_argument("question", help="the question to answer")
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    parser.add_argument("--no-llm-router", action="store_true",
                        help="rules-only routing (deterministic; used for the Phase 5 ladder)")
    args = parser.parse_args()

    from .answer import answer

    t0 = time.perf_counter()
    result = answer(args.question, use_llm_router=not args.no_llm_router)
    elapsed = time.perf_counter() - t0

    if args.json:
        result["elapsed_s"] = round(elapsed, 3)
        json.dump(result, sys.stdout, indent=2, default=str)
        print()
        return

    print(f"\nQ: {args.question}")
    print(f"\nA: {result['answer']}")
    if result.get("operation"):
        print(f"   (computed in Python: operation={result['operation']})")
    print(f"\npath: {result['path_taken']}  |  confidence: {result['confidence']}  "
          f"|  {elapsed:.2f}s")
    routing = result.get("routing", {})
    if routing:
        print(f"router: {routing.get('method')} — {routing.get('reason')}")

    print("\ncitations:")
    if not result["citations"]:
        print("  (none)")
    for c in result["citations"]:
        print(f"  - {format_citation(c)}")

    if result.get("notes"):
        print("\nnotes:")
        for n in result["notes"]:
            print(f"  - {n}")
    print()


if __name__ == "__main__":
    main()
