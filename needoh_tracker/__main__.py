"""Entry point so ``python -m needoh_tracker`` starts the tracker.

Reads PORT (default 3100) from the project ``.env`` via python-dotenv, then
runs the FastAPI app with uvicorn. Independent of the Gemini app on port 3000.
"""
from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    port = int(os.environ.get("PORT", "3100"))
    uvicorn.run(
        "needoh_tracker.server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
