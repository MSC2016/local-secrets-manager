"""Local development entrypoint.

Use this file when running the app directly with Flask's built-in development
server, for example during local debugging or VS Code launches.

For the more production-like local/container runtime, Gunicorn uses the app
factory target ``app.main:create_app()`` instead.
"""

import os

from app.main import create_app


HOST = os.environ.get("APP_HOST", "0.0.0.0")
PORT = int(os.environ.get("APP_PORT", "5000"))


def main():
    app = create_app()

    # Flask's built-in server is intentionally kept for local debugging.
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
