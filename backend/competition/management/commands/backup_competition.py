import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.signing import Signer
from django.db import connections


def pg_environment(config, database=None):
    return {
        **os.environ,
        "PGHOST": config["HOST"],
        "PGPORT": str(config["PORT"]),
        "PGUSER": config["USER"],
        "PGPASSWORD": config["PASSWORD"],
        "PGDATABASE": database or config["NAME"],
    }


class Command(BaseCommand):
    help = "Create a private pg_dump archive and signed manifest without overwriting files."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True)

    def handle(self, *args, **options):
        executable = shutil.which("pg_dump")
        if executable is None:
            raise CommandError(
                "Install PostgreSQL client tools and add their bin directory to PATH."
            )
        path = Path(options["output"]).resolve()
        manifest = path.with_suffix(path.suffix + ".manifest.json")
        if path.exists() or manifest.exists():
            raise CommandError(
                "Choose new backup and manifest paths; existing files are preserved."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        config = connections["default"].settings_dict
        result = subprocess.run(
            [executable, "--format=custom", "--no-owner", "--file", str(path)],
            env=pg_environment(config),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise CommandError(
                "pg_dump failed. Check the connection/client version; a partial archive may remain."
            )
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        payload = {
            "format": "competition-pg-backup-v1",
            "sha256": checksum,
            "source_database": config["NAME"],
            "client": subprocess.run(
                [executable, "--version"], capture_output=True, text=True, check=True
            ).stdout.strip(),
        }
        with manifest.open("x", encoding="utf-8") as stream:
            json.dump(
                {"signed_manifest": Signer(salt="competition.pg-backup.v1").sign_object(payload)},
                stream,
                indent=2,
            )
        self.stdout.write(
            f"Backup saved to {path}; keep its manifest and original signing keys privately."
        )
