"""Application package export.

Re-export the Flask app factory so WSGI servers and local tooling can import
``create_app`` from ``app`` if needed.
"""

from app.main import create_app

__all__ = ["create_app"]
