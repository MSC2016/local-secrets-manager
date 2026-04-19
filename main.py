import os

from app.main import create_app


HOST = os.environ.get("APP_HOST", "0.0.0.0")
PORT = int(os.environ.get("APP_PORT", "5000"))


def main():
    app = create_app()
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
