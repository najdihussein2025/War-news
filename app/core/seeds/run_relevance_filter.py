import asyncio

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401
from app.core.database import SessionLocal
from app.news.services.pipeline_sweep_stages import sweep_relevance_filter


def main() -> None:
    db = SessionLocal()
    try:
        result = asyncio.run(sweep_relevance_filter(db))
        print("Relevance filter summary")
        print(f"processed: {result.processed}")
        print(f"succeeded: {result.succeeded}")
        print(f"failed: {result.failed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
