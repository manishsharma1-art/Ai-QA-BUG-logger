import time
import json
import numpy as np
from sentence_transformers import SentenceTransformer

def main():
    print("Loading data...")
    with open("training_examples.json", "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"Loaded {len(rows)} items.")
    
    texts = [
        f"Subject: {r['subject']}\nDescription: {r['description_raw']}"
        for r in rows
    ]
    
    print("Loading model...")
    t0 = time.time()
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    print(f"Model loaded in {time.time() - t0:.2f}s")
    
    print("Encoding...")
    t0 = time.time()
    embeddings = model.encode(texts, batch_size=32, normalize_embeddings=True)
    duration = time.time() - t0
    print(f"Encoded in {duration:.2f}s")
    print(f"Speed: {len(rows) / duration:.2f} items/s")

if __name__ == "__main__":
    main()
