"""
Upload property comp JSON batches to Pinecone.

Usage:
    python upsert_comps.py path/to/batch1.json [batch2.json ...]
    python upsert_comps.py ../../assets/batch*.json
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone
import os

load_dotenv()

PINECONE_INDEX = "rag-properties-israel"
EMBED_MODEL    = "text-embedding-3-small"
EMBED_DIMS     = 512
BATCH_SIZE     = 100

METADATA_FIELDS = [
    "property_type", "city", "neighborhood", "location",
    "size_sqm", "num_rooms", "floor_number", "has_parking", "has_balcony",
    "building_year", "condition",
    "price_listed", "price_sold", "price_per_sqm", "days_on_market", "sale_date",
]


def upsert_batch(records: list, embeddings: OpenAIEmbeddings, index) -> int:
    texts  = [r["embed_text"] for r in records]
    vectors = embeddings.embed_documents(texts)

    upsert_data = [
        {
            "id":       r["id"],
            "values":   vec,
            "metadata": {k: r[k] for k in METADATA_FIELDS if k in r},
        }
        for r, vec in zip(records, vectors)
    ]
    index.upsert(vectors=upsert_data)
    return len(upsert_data)


def main():
    if len(sys.argv) < 2:
        print("Usage: python upsert_comps.py batch1.json [batch2.json ...]")
        sys.exit(1)

    embeddings = OpenAIEmbeddings(model=EMBED_MODEL, dimensions=EMBED_DIMS)
    index      = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index(PINECONE_INDEX)

    total = 0
    for path in sys.argv[1:]:
        records = json.loads(Path(path).read_text())
        print(f"{path}: {len(records)} records", end="", flush=True)

        for i in range(0, len(records), BATCH_SIZE):
            chunk = records[i : i + BATCH_SIZE]
            upserted = upsert_batch(chunk, embeddings, index)
            print(f"  +{upserted}", end="", flush=True)
            total += upserted

        print()

    print(f"\nDone — {total} vectors upserted to '{PINECONE_INDEX}'")


if __name__ == "__main__":
    main()
