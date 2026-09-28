import numpy as np
import json
import os
from sentence_transformers import SentenceTransformer, util

_base_dir = os.path.dirname(os.path.abspath(__file__))
_data_dir = os.path.join(_base_dir, 'data')

_metadata_path = os.path.join(_data_dir, 'db_metadata.json')
_vectors_path  = os.path.join(_data_dir, 'db_vectors.npy')
_ids_path      = os.path.join(_data_dir, 'db_ids.npy')

_model = None

def get_model():
    global _model
    if _model is None:
        print("[SBERT] Loading model (one-time)...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        print("[SBERT] Model loaded ✓")
    return _model


def get_all_sbert_scores(title: str, abstract: str = "") -> dict:
    """Returns {str(project_id): similarity_score} for all projects in the index."""
    db_vectors = np.load(_vectors_path)
    db_ids     = np.load(_ids_path)

    query_text = f"{title}. {abstract}".strip() if abstract else title
    query_vec  = get_model().encode(query_text)

    scores = util.cos_sim(query_vec, db_vectors)[0].numpy()

    return {str(int(db_ids[i])): float(scores[i]) for i in range(len(db_ids))}


def semantic_search(name: str, abstract: str = "", threshold: float = 0.60, top_k: int = 3) -> dict:
    """Standalone search — returns best match info. Used by scripts/tests."""
    with open(_metadata_path, "r") as f:
        metadata = json.load(f)

    score_map = get_all_sbert_scores(name, abstract)
    results = [
        {"name": metadata.get(pid, "Unknown"), "score": score}
        for pid, score in score_map.items()
    ]
    results.sort(key=lambda x: x["score"], reverse=True)

    best = results[0]
    return {
        "exists"    : best["score"] >= threshold,
        "best_match": best,
        "top_k"     : results[:top_k],
    }


if __name__ == "__main__":
    tests = [
        ("AI crop disease detection", "detecting plant diseases using CNN"),
        ("blockchain voting system",  "decentralized election using smart contracts"),
        ("space debris tracker",      "monitoring satellite junk in low earth orbit"),
    ]
    for name, abstract in tests:
        r = semantic_search(name, abstract)
        tag = "✅ EXISTS" if r["exists"] else "🆕 NEW"
        print(f"\n{tag}  '{name}'")
        for m in r["top_k"]:
            bar = "█" * int(m["score"] * 20) + "░" * (20 - int(m["score"] * 20))
            print(f"  [{m['score']:.4f}] {bar} {m['name']}")
