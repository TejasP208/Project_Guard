import sqlite3
import os
import sys
import numpy as np

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from .extractor    import extract_text
    from .preprocessor import preprocess, preprocess_batch
    from .tfidf_engine import compute_tfidf_similarity
    from .lda_engine   import train_lda, compute_lda_similarity, get_topic_labels
except ImportError:
    from nlp.extractor    import extract_text
    from nlp.preprocessor import preprocess, preprocess_batch
    from nlp.tfidf_engine import compute_tfidf_similarity
    from nlp.lda_engine   import train_lda, compute_lda_similarity, get_topic_labels

from Models.search import get_all_sbert_scores

DB_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'DB', 'training_data.db'
))

# Hybrid layer weights
WEIGHT_TFIDF = 0.35
WEIGHT_LDA   = 0.25
WEIGHT_SBERT = 0.40


def load_training_projects() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, year, group_no, project_name, project_abstract FROM projects"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def determine_risk(score: float) -> str:
    if score < 25:   return "Low"
    elif score < 55: return "Medium"
    else:            return "High"


def run_plagiarism_check(title: str, description: str, file_bytes: bytes, filename: str) -> dict:
    # Extract and combine all text
    file_text = extract_text(file_bytes, filename)
    full_text = f"{title} {description} {file_text}".strip()

    new_clean = preprocess(full_text)
    if not new_clean.strip():
        return {
            "error"             : "Could not extract meaningful text from the submission.",
            "plagiarism_percent": 0,
            "risk_level"        : "Unknown",
        }

    projects        = load_training_projects()
    if not projects:
        return {
            "plagiarism_percent": 0.0,
            "risk_level"        : "Low",
            "matched_project"   : "N/A",
            "matched_group"     : "N/A",
            "matched_year"      : "N/A",
            "error"             : "No projects in database to compare against."
        }

    abstracts_clean = preprocess_batch([p['project_abstract'] for p in projects])

    # Layer 1 — TF-IDF
    print("[Checker] Running TF-IDF layer...")
    tfidf_scores = compute_tfidf_similarity(new_clean, abstracts_clean)

    # Layer 2 — LDA
    print("[Checker] Running LDA layer...")
    lda_model, count_vec, existing_dists = train_lda(abstracts_clean)
    lda_scores = compute_lda_similarity(new_clean, lda_model, count_vec, existing_dists)

    # Layer 3 — SBERT
    print("[Checker] Running SBERT layer...")
    sbert_map    = get_all_sbert_scores(title, f"{description} {file_text}")
    sbert_scores = [sbert_map.get(str(p['id']), 0.0) for p in projects]

    # Blend all 3 layers
    combined = [
        (WEIGHT_TFIDF * t) + (WEIGHT_LDA * l) + (WEIGHT_SBERT * s)
        for t, l, s in zip(tfidf_scores, lda_scores, sbert_scores)
    ]

    best_i    = int(np.argmax(combined))
    best      = projects[best_i]
    final_pct = round(combined[best_i] * 100, 2)

    top3_idx = sorted(range(len(combined)), key=lambda i: combined[i], reverse=True)[:3]
    top3 = [
        {
            "rank"          : rank + 1,
            "project_name"  : projects[i]['project_name'],
            "group_no"      : projects[i]['group_no'],
            "year"          : projects[i]['year'],
            "combined_score": round(combined[i]     * 100, 2),
            "tfidf_score"   : round(tfidf_scores[i] * 100, 2),
            "lda_score"     : round(lda_scores[i]   * 100, 2),
            "sbert_score"   : round(sbert_scores[i] * 100, 2),
        }
        for rank, i in enumerate(top3_idx)
    ]

    topics = get_topic_labels(lda_model, count_vec)

    return {
        "plagiarism_percent": final_pct,
        "risk_level"        : determine_risk(final_pct),
        "matched_project"   : best['project_name'],
        "matched_group"     : best['group_no'],
        "matched_year"      : best['year'],
        "tfidf_score"       : round(tfidf_scores[best_i]  * 100, 2),
        "lda_score"         : round(lda_scores[best_i]    * 100, 2),
        "sbert_score"       : round(sbert_scores[best_i]  * 100, 2),
        "weights"           : {"tfidf": WEIGHT_TFIDF, "lda": WEIGHT_LDA, "sbert": WEIGHT_SBERT},
        "top_3_matches"     : top3,
        "topics_discovered" : [t['label'] for t in topics],
    }


if __name__ == "__main__":
    print("=" * 55)
    print(f"  3-Layer Check  |  TF-IDF={WEIGHT_TFIDF}  LDA={WEIGHT_LDA}  SBERT={WEIGHT_SBERT}")
    print("=" * 55)

    tests = [
        ("Real-time Sign Language Translator", "Uses computer vision to translate hand gestures to text",
         b"A system using webcam and deep learning to detect sign language gestures and convert them to spoken audio in real time."),
        ("AI Crop Disease Detection", "Detects plant diseases from leaf images using CNN",
         b"A mobile app that takes a photo of a plant leaf and uses a trained CNN to identify the disease and suggest treatment."),
        ("Blockchain-based Voting System", "Secure decentralized election using Ethereum smart contracts",
         b"Students cast votes through a web interface. All votes are recorded on a blockchain ensuring tamper-proof results."),
    ]

    for title, desc, text in tests:
        print(f"\n── '{title}' ──")
        result = run_plagiarism_check(title, desc, text, "test.txt")
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            continue
        print(f"  Score : {result['plagiarism_percent']}%  |  Risk: {result['risk_level']}")
        print(f"  Match : {result['matched_project']} (G{result['matched_group']}, {result['matched_year']})")
        print(f"  Layers: TF-IDF={result['tfidf_score']}%  LDA={result['lda_score']}%  SBERT={result['sbert_score']}%")
        print(f"  Top 3:")
        for m in result['top_3_matches']:
            print(f"    #{m['rank']} {m['project_name']} — {m['combined_score']}%")

    print("\n" + "=" * 55)
