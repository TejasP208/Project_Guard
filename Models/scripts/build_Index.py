import numpy as np
import json
import os
from sentence_transformers import SentenceTransformer
from sqlalchemy import select

from database import SessionLocal
from models import Project

# ── Paths ────────────────────────────────────────────────────────
# ── Paths ────────────────────────────────────────────────────────
base_dir = os.path.dirname(os.path.dirname(__file__))       # Models/
data_dir = os.path.join(base_dir, 'data')

vectors_path = os.path.join(data_dir, 'db_vectors.npy')
ids_path = os.path.join(data_dir, 'db_ids.npy')
metadata_path = os.path.join(data_dir, 'db_metadata.json')

os.makedirs(data_dir, exist_ok=True)

# ── Load Pre-trained Model ───────────────────────────────────────
print("Downloading/Loading Sentence Transformer...")
model = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded ✓")

# ── Load projects from PostgreSQL ─────────────────────────────────
with SessionLocal() as session:
    rows = session.scalars(select(Project).order_by(Project.id)).all()

embeddings = {}
metadata   = {}
for project in rows:
    id, name, abstract = project.id, project.project_name, project.project_abstract
    # Combine name and abstract into one clean string
    text = f"{name}. {abstract if abstract else ''}"
    
    # The transformer handles the tokenization, padding, and embedding instantly
    vector = model.encode(text) 
    
    embeddings[id] = vector
    metadata[str(id)] = name
    print(f"  [{id}] {name}")

# ── Save ─────────────────────────────────────────────────────────
ids     = list(embeddings.keys())
vectors = np.array([embeddings[i] for i in ids])

np.save(vectors_path, vectors)
np.save(ids_path, np.array(ids))

with open(metadata_path, "w") as f:
    json.dump(metadata, f, indent=2)

print(f"\nVector shape: {vectors.shape}")
print("Database Re-embedded successfully ✓")
