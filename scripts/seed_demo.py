from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.service import SecretsService


DEFAULT_PASSPHRASE = "demo-passphrase"
DEFAULT_DATA_DIR = Path("data") / "demo"


DEMO_DATA: dict[str, list[dict[str, object]]] = {
    "work": [
        {
            "name": "grafana-api-token",
            "value": "demo_grafana_token_12345",
            "metadata": {
                "owner": "platform-team",
                "environment": "staging",
                "rotation": "30d",
                "description": "Fake token for portfolio demo only",
            },
        },
        {
            "name": "postgres-readonly-url",
            "value": "postgresql://demo_reader:readonly@db.internal:5432/app",
            "metadata": {
                "owner": "data-team",
                "environment": "staging",
                "description": "Fake connection string for local demo",
            },
        },
    ],
    "personal": [
        {
            "name": "github-pat",
            "value": "ghp_demoPersonalTokenExample",
            "metadata": {
                "owner": "miguel",
                "purpose": "portfolio-testing",
                "description": "Fake PAT used only as sample data",
            },
        }
    ],
    "lab": [
        {
            "name": "k8s-bootstrap-token",
            "value": "demo.k8s.bootstrap.token",
            "metadata": {
                "cluster": "kind-dev",
                "environment": "local",
                "description": "Fake bootstrap token for container demo",
            },
        },
        {
            "name": "registry-password",
            "value": "demo-registry-password",
            "metadata": {
                "service": "registry.local",
                "environment": "lab",
                "description": "Fake registry credential for screenshots",
            },
        },
    ],
}


def build_service(data_dir: Path) -> SecretsService:
    db_path = data_dir / "secrets.db"
    config_path = data_dir / "config.json"
    return SecretsService(str(db_path), str(config_path))


def seed_demo_dataset(*, data_dir: Path, passphrase: str, clean: bool) -> None:
    if clean and data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    service = build_service(data_dir)
    service.initialize_database(passphrase)
    unlocked, message = service.unlock(passphrase)
    if not unlocked:
        raise RuntimeError(message)

    for vault_name, secrets in DEMO_DATA.items():
        service.create_vault(vault_name)
        for item in secrets:
            service.create_secret(
                vault_name,
                str(item["name"]),
                str(item["value"]),
                metadata=dict(item.get("metadata", {})),
            )

    service.lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a clean demo dataset for Local Secrets Manager."
    )
    parser.add_argument(
        "--passphrase",
        default=os.environ.get("DEMO_PASSPHRASE", DEFAULT_PASSPHRASE),
        help="Passphrase to use for the generated demo database.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("APP_DATA_DIR", str(DEFAULT_DATA_DIR)),
        help="Target data directory. Defaults to APP_DATA_DIR or data/demo.",
    )
    parser.add_argument(
        "--keep-existing-dir",
        action="store_true",
        help="Do not delete the target directory before seeding.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data_dir).resolve()
    seed_demo_dataset(
        data_dir=data_dir,
        passphrase=args.passphrase,
        clean=not args.keep_existing_dir,
    )

    print("Demo dataset created.")
    print(f"Data directory: {data_dir}")
    print(f"Database file: {data_dir / 'secrets.db'}")
    print(f"Config file: {data_dir / 'config.json'}")
    print(f"Passphrase: {args.passphrase}")
    print("Vaults: work, personal, lab")
    print("Run with APP_DATA_DIR pointing at that directory to use the demo data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
