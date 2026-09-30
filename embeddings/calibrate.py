"""Evaluate the current checker against manually labeled submissions.

Usage: python -m embeddings.calibrate path/to/labeled_cases.csv
"""

import argparse
import csv
from pathlib import Path

from nlp.checker import run_plagiarism_check


LABELS = {"similar", "unrelated"}
REQUIRED_COLUMNS = {"title", "description", "file_path", "file_text", "label"}


def score_cases(csv_path: Path) -> list[tuple[float, str]]:
    cases = []
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
            raise ValueError(f"CSV needs these columns: {', '.join(sorted(REQUIRED_COLUMNS))}")

        for row_number, row in enumerate(reader, start=2):
            label = (row["label"] or "").strip().lower()
            if label not in LABELS:
                raise ValueError(f"Row {row_number}: label must be similar or unrelated")

            file_path = (row["file_path"] or "").strip()
            if file_path:
                document = (csv_path.parent / file_path).resolve()
                file_bytes = document.read_bytes()
                filename = document.name
            else:
                file_bytes = (row["file_text"] or "").encode("utf-8")
                filename = "submission.txt"

            result = run_plagiarism_check(
                row["title"] or "", row["description"] or "", file_bytes, filename
            )
            if "error" in result:
                raise ValueError(f"Row {row_number}: {result['error']}")
            score = float(result["plagiarism_percent"])
            cases.append((score, label))
            print(f"Row {row_number}: {label:9s} score={score:6.2f}")
    if not cases:
        raise ValueError("Add labeled submission rows before evaluating thresholds")
    return cases


def report_threshold(cases: list[tuple[float, str]], threshold: int) -> float:
    positives = [score for score, label in cases if label == "similar"]
    negatives = [score for score, label in cases if label == "unrelated"]
    if not positives or not negatives:
        raise ValueError("Include both similar and unrelated examples")
    true_positives = sum(score > threshold for score in positives)
    false_positives = sum(score > threshold for score in negatives)
    recall = true_positives / len(positives)
    specificity = 1 - false_positives / len(negatives)
    balanced_accuracy = (recall + specificity) / 2
    print(
        f"Threshold {threshold:3d}%: similar detected {true_positives}/{len(positives)}, "
        f"unrelated blocked {false_positives}/{len(negatives)}, "
        f"balanced accuracy {balanced_accuracy:.2f}"
    )
    return balanced_accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    cases = score_cases(args.csv_path)
    print("\nCurrent frontend cutoff:")
    report_threshold(cases, 30)
    if min(sum(label == kind for _, label in cases) for kind in LABELS) < 10:
        print("Collect at least 10 cases per label before considering a new cutoff.")
        return
    candidates = []
    for threshold in range(101):
        positives = [score for score, label in cases if label == "similar"]
        negatives = [score for score, label in cases if label == "unrelated"]
        recall = sum(score > threshold for score in positives) / len(positives)
        specificity = sum(score <= threshold for score in negatives) / len(negatives)
        candidates.append(((recall + specificity) / 2, threshold))
    best_accuracy = max(accuracy for accuracy, _ in candidates)
    best_thresholds = [threshold for accuracy, threshold in candidates if accuracy == best_accuracy]
    print(
        f"Exploratory cutoff range on this sample: "
        f"{min(best_thresholds)}-{max(best_thresholds)}% "
        f"(balanced accuracy {best_accuracy:.2f})."
    )
    print("Review errors on separate examples before changing the frontend cutoff.")


if __name__ == "__main__":
    main()
