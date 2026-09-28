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

print("Loading Sentence Transformer...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded ✓")

# ── Main search function ─────────────────────────────────────────
def search(name, abstract="", threshold=0.50, top_k=3):
    # Combine query text
    query_text = f"{name}. {abstract if abstract else ''}"
    
    # Embed the query
    query_vec = model.encode(query_text)

    # Use the library's built-in, highly optimized cosine similarity
    # Returns a tensor of scores, we convert it to a 1D numpy array
    scores = util.cos_sim(query_vec, db_vectors)[0].numpy()

    # Combine scores with IDs and Names
    results = []
    for i, score in enumerate(scores):
        proj_id  = str(db_ids[i])
        proj_name = metadata.get(proj_id, "Unknown")
        results.append((float(score), proj_id, proj_name))

    # Sort high → low
    results.sort(reverse=True)

    best_score, best_id, best_name = results[0]
    exists = best_score >= threshold

    # ── Print result ─────────────────────────────────────────────
    print(f"\nQuery : '{name}'")
    if abstract:
        print(f"Info  : '{abstract[:60]}...'")
    print("─" * 55)

    if exists:
        print(f"✅ EXISTS — similar project found!")
        print(f"   Match : {best_name}")
        print(f"   Score : {best_score:.4f}")
    else:
        print(f"🆕 NEW — no similar project found")
        print(f"   Closest : {best_name}")
        print(f"   Score   : {best_score:.4f}")

    print(f"\nTop {top_k} matches:")
    for score, pid, pname in results[:top_k]:
        # Scale the bar visualization based on the new transformer scoring range
        filled = int(max(0, score) * 20) 
        bar    = "█" * filled + "░" * (20 - filled)
        label  = "✅" if score >= threshold else "  "
        print(f"  {label} [{score:.4f}] {bar} {pname}")

    print()

# ── Test it ──────────────────────────────────────────────────────
if __name__ == "__main__":
    search("AI crop disease detection", "detecting diseases in plant leaves using images")
    search("online exam portal", "web platform for conducting tests and auto grading")
    search("blockchain voting", "decentralized secure election system using blockchain")
    search("weather forecasting system", "predicts rain and temperature using sensors")
    search("recipe suggestion app", "recommend food recipes based on available ingredients")