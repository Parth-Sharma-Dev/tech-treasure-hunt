import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import psycopg
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.signing import BadSignature, Signer
from django.db import connections, transaction
from django.db.models import F
from django.utils import timezone
from psycopg import sql

from competition.management.commands.backup_competition import pg_environment
from competition.models import Incident, Round, Team, TeamSession
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = "Restore into a new tth_recovery_* database and revoke restored team sessions."

    def add_arguments(self, parser):
        parser.add_argument("--backup", required=True)
        parser.add_argument("--database", required=True)
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        target = options["database"]
        config = connections["default"].settings_dict
        if target == config["NAME"] or not re.fullmatch(r"tth_recovery_[a-z0-9_]{1,40}", target):
            raise CommandError(
                "Use a new tth_recovery_* name. The current database cannot be overwritten."
            )
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Controller not found.")
        require_staff_permission(actor, "control_round")
        executable = shutil.which("pg_restore")
        if executable is None:
            raise CommandError("Add PostgreSQL client tools to PATH.")
        path = Path(options["backup"]).resolve()
        try:
            manifest = json.loads(
                path.with_suffix(path.suffix + ".manifest.json").read_text(encoding="utf-8")
            )
            payload = Signer(salt="competition.pg-backup.v1").unsign_object(
                manifest["signed_manifest"]
            )
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if (
                payload.get("format") != "competition-pg-backup-v1"
                or payload.get("sha256") != actual
            ):
                raise ValueError("Checksum mismatch")
        except (OSError, ValueError, KeyError, BadSignature):
            raise CommandError(
                "The backup manifest/signature/checksum is invalid; no database was changed."
            ) from None
        with psycopg.connect(
            host=config["HOST"],
            port=config["PORT"],
            dbname=config["NAME"],
            user=config["USER"],
            password=config["PASSWORD"],
            autocommit=True,
        ) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", [target]).fetchone():
                raise CommandError("That recovery database already exists; choose a new name.")
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        restored = subprocess.run(
            [
                executable,
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                "--dbname",
                target,
                str(path),
            ],
            env=pg_environment(config, target),
            capture_output=True,
            text=True,
            check=False,
        )
        if restored.returncode:
            raise CommandError(
                "Restore failed; inspect the separate recovery database. Source is unchanged."
            )
        alias = "competition_recovery"
        connections.databases[alias] = {**config, "NAME": target}
        try:
            with transaction.atomic(using=alias):
                now = timezone.now()
                restored_actor = (
                    get_user_model().objects.using(alias).filter(username=options["actor"]).first()
                )
                if restored_actor is None:
                    raise CommandError(
                        "The restored database does not contain the chosen controller."
                    )
                TeamSession.objects.using(alias).filter(revoked_at__isnull=True).update(
                    revoked_at=now
                )
                Team.objects.using(alias).update(session_version=F("session_version") + 1)
                for round in Round.objects.using(alias).exclude(state="DRAFT"):
                    Incident.objects.using(alias).create(
                        round=round,
                        owner=restored_actor,
                        category="RECOVERY",
                        opened_at=now,
                        material=True,
                        affected_scope={
                        "summary": "Restored checkpoint: reconcile retained evidence before use."
                        },
                        evidence_references=[str(path), actual],
                    )
        finally:
            connections[alias].close()
        self.stdout.write(
            f"Restored into {target}. Source unchanged; sessions revoked; recovery review required."
        )
