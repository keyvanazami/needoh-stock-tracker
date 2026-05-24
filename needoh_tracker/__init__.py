"""NeeDoh Stock Tracker — a self-contained FastAPI app that hunts for NeeDoh
toys across retailers and Instagram, keeps a deduped watchlist, notifies you
(email + web push) on restocks, and can place automated phone calls to stores.

Runs independently of the Gemini paragraph-reader app under ``python_backend/``.
Start it with ``python -m needoh_tracker`` (default port 3100).
"""

__all__ = ["__version__"]
__version__ = "1.0.0"
