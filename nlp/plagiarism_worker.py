"""Run one plagiarism check in an isolated process so the API can enforce a hard deadline."""

import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

def main() -> int:
    if len(sys.argv) != 2:
        return 2
    request_path = Path(sys.argv[1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    file_path = Path(request["file_path"])
    file_bytes = file_path.read_bytes() if file_path.exists() else b""
    # stdout is the API's JSON transport. Keep dependency/checker diagnostics
    # off that channel, including messages emitted during imports.
    with redirect_stdout(sys.stderr):
        from nlp.checker import run_plagiarism_check
        result = run_plagiarism_check(
            request["title"], request["description"], file_bytes, request["filename"],
        )
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
