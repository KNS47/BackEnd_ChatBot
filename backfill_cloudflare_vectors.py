"""Fill missing Cloudflare vectors for existing document text.

Preview by default. --apply --source SOURCE sends pending chunks from one
reviewed public PDF to Workers AI and saves the vectors in Supabase.
"""

import argparse
import asyncio

from ai import AI_PROVIDER, embed_text, gemini_lifespan
from database import supabase

TABLE = "documents"
COLUMN = "embedding_cloudflare"


def pending_rows(
    cursor: int | None, maximum: int, include_content: bool, source: str | None,
) -> list[dict]:
    fields = "id,content" if include_content else "id"
    query = supabase.table(TABLE).select(fields).is_(COLUMN, "null").order("id").limit(maximum)
    if source is not None:
        query = query.eq("source", source)
    if cursor is not None:
        query = query.gt("id", cursor)
    return query.execute().data or []


def save_vector(document_id: int, vector: list[float]) -> bool:
    response = (
        supabase.table(TABLE).update({COLUMN: vector}).eq("id", document_id)
        .is_(COLUMN, "null").execute()
    )
    return bool(response.data)


async def run(limit: int, apply_changes: bool, source: str | None = None) -> tuple[int, int]:
    if apply_changes and not source:
        raise ValueError("Select one reviewed public PDF source before applying")
    cursor = None
    checked = saved = 0
    async with gemini_lifespan(None):
        while checked < limit:
            rows = await asyncio.to_thread(
                pending_rows, cursor, min(limit - checked, 100), apply_changes, source,
            )
            if not rows:
                break
            for row in rows:
                cursor = row["id"]
                checked += 1
                if not apply_changes:
                    continue
                text = row.get("content")
                if isinstance(text, str) and text.strip():
                    vector = await embed_text(text)
                    if len(vector) != 1024:
                        raise RuntimeError("Cloudflare embedding must have 1024 dimensions")
                    saved += await asyncio.to_thread(save_vector, cursor, vector)
    return checked, saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Send existing text to Cloudflare and write vectors")
    parser.add_argument("--source", help="Exact documents.source value for one reviewed public PDF")
    parser.add_argument("--limit", default=100, type=int, help="Maximum pending document chunks to check")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        parser.error("--limit must be between 1 and 10000")
    if args.apply and AI_PROVIDER != "cloudflare":
        parser.error("--apply requires AI_PROVIDER=cloudflare")
    if args.apply and (not args.source or not args.source.strip()):
        parser.error("--apply requires --source for one reviewed public PDF")

    try:
        checked, saved = asyncio.run(run(args.limit, args.apply, args.source))
    except Exception as exc:
        raise SystemExit(
            f"Cloudflare backfill stopped ({type(exc).__name__}). "
            "Existing Cloudflare vectors are skipped when you rerun it."
        ) from None
    if args.apply:
        print(f"Checked {checked} pending chunks. Saved {saved} vectors.")
    else:
        print(f"Preview: found {checked} pending chunks (maximum {args.limit}). No writes or AI requests.")


if __name__ == "__main__":
    main()
