"""Manually compare Qwen embeddings for related and unrelated project ideas.

Run from the repository root: python -m embeddings.compare_examples
"""

import math

from .cloudflare import CloudflareEmbeddingClient


EXAMPLES = {
    "reference": (
        "AI Crop Disease Detection. A mobile application identifies crop diseases "
        "from photographs of plant leaves and suggests treatment."
    ),
    "related": (
        "Plant Health Diagnosis. Farmers upload leaf photos to a machine learning "
        "system that recognizes plant infections and recommends remedies."
    ),
    "unrelated": (
        "Blockchain Voting System. A decentralized voting application records "
        "ballots on a blockchain and verifies election results."
    ),
}


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Vectors must have the same dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cannot compare a zero-length vector")
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def main() -> None:
    client = CloudflareEmbeddingClient()
    vectors = {name: client.embed(text) for name, text in EXAMPLES.items()}
    related = cosine_similarity(vectors["reference"], vectors["related"])
    unrelated = cosine_similarity(vectors["reference"], vectors["unrelated"])

    print(f"Reference vs related:   {related:.4f}")
    print(f"Reference vs unrelated: {unrelated:.4f}")
    print(f"Related ranks higher:   {related > unrelated}")


if __name__ == "__main__":
    main()
