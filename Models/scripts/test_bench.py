import numpy as np
import json
import os
from sentence_transformers import SentenceTransformer, util

# ── Paths ────────────────────────────────────────────────────────
base_dir = os.path.dirname(os.path.dirname(__file__))
data_dir = os.path.join(base_dir, 'data')
metadata_path = os.path.join(data_dir, 'db_metadata.json')
vectors_path = os.path.join(data_dir, 'db_vectors.npy')
ids_path = os.path.join(data_dir, 'db_ids.npy')

# ── Load Data & Model ────────────────────────────────────────────
with open(metadata_path, "r") as f:
    metadata = json.load(f)

db_vectors = np.load(vectors_path)   
db_ids     = np.load(ids_path)       

print("Loading Sentence Transformer for testing...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("Test Bench Ready ✓")

def quick_test(name, abstract="", threshold=0.60):
    query_text = f"{name}. {abstract if abstract else ''}"
    query_vec = model.encode(query_text)
    
    # Calculate similarity
    scores = util.cos_sim(query_vec, db_vectors)[0].numpy()
    best_idx = np.argmax(scores)
    
    score = scores[best_idx]
    proj_name = metadata.get(str(db_ids[best_idx]), "Unknown")

    print(f"\nTesting: '{name}'")
    if score >= threshold:
        print(f"  ✅ MATCH: {proj_name} ({score:.4f})")
    else:
        print(f"  🆕 UNIQUE: Closest was {proj_name} ({score:.4f})")

# ── YOUR TEST CASES ──────────────────────────────────────────────
if __name__ == "__main__":
    # Test 1: Should match a blockchain project
    quick_test("secure voting", "using ethereum and smart contracts for elections")

    # Test 2: Should be unique
    quick_test("space debris tracker", "monitoring satellite junk in low earth orbit")
