from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from competition.models import CodingTask, Round
from competition.rules import require_staff_permission


class Command(BaseCommand):
    help = (
        "Prepare five synthetic Round 3 coding drafts. Never verify content or grant qualification."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="DEMO-content")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Synthetic coding seeds require DEBUG.")
        actor = get_user_model().objects.filter(username=options["actor"]).first()
        if actor is None:
            raise CommandError("Content staff account not found.")
        require_staff_permission(actor, "prepare_content")
        round = Round.objects.filter(number=3, is_demo=True).order_by("-attempt_no").first()
        if round is None or round.state != "DRAFT":
            raise CommandError(
                "Use an existing demo Round 3 DRAFT; released attempts are preserved."
            )
        if CodingTask.objects.filter(round=round).exists():
            self.stdout.write(
                "Existing coding content preserved. Use Django admin to review/edit it."
            )
            return
        round.delivery_mode = "CODING"
        round.active_budget_ms = 2700000
        round.rules_version = "demo-coding-v1"
        round.rules = {
            **round.rules,
            "submission_policy": "locked_final_with_cutoff_autofinalize",
            "ranking_policy": "score_correct_tasks_final_time",
            "qualification_tie_policy": "block_exact_ties",
            "one_workstation_per_team": True,
            "score_precision": 3,
            "language_versions": {
                "PYTHON": "Synthetic demo: verify approved lab Python version",
                "C": "Synthetic demo: verify approved lab C version",
            },
        }
        round.approved_by = None
        round.approved_at = None
        round.approval_digest = ""
        round.save()
        fixtures = [
            (
                "OUTPUT",
                15,
                ["TEXT"],
                "Demo: predict the output of Python print(2 ** 3).",
                "",
                {"expected": "8"},
            ),
            (
                "DEBUG",
                25,
                ["C"],
                "Demo: repair the C source so it prints 4 and a newline.",
                '#include <stdio.h>\nint main(void) { printf("%d\\n", 2 + ); return 0; }',
                {"expected_output": "4\n", "requirement": "Correct compilable C source"},
            ),
            (
                "FILL",
                20,
                ["PYTHON"],
                "Demo: fill the missing Python expression in add(a,b).",
                "def add(a, b):\n    return ___",
                {"expected_fragment": "a + b"},
            ),
            (
                "SHORT",
                30,
                ["PYTHON", "C"],
                "Demo: read two integers and print their sum. Submit complete Python/C source.",
                "",
                {
                    "test_cases": [
                        {"id": "sum-positive", "input": "2 3\n", "expected": "5\n"},
                        {"id": "sum-zero", "input": "0 0\n", "expected": "0\n"},
                    ]
                },
            ),
            (
                "LOGIC",
                10,
                ["TEXT"],
                "Demo: order these steps by labels: B=display result; A=read inputs; C=add inputs.",
                "",
                {"expected_order": "A,C,B"},
            ),
        ]
        for category, points, languages, prompt, starter, rubric in fixtures:
            task = CodingTask(
                round=round,
                public_id=f"DEMO-{category}",
                category=category,
                points=points,
                languages=languages,
                prompt=prompt,
                starter_code=starter,
                private_rubric=rubric,
                version="demo-task-v1",
                prepared_by=actor,
            )
            task.full_clean()
            task.save()
        self.stdout.write(
            "Prepared five unverified demo tasks and a 45-minute native draft. "
            "Confirm lab versions, verify content and approve rules. "
            "No Round 2 qualification was created."
        )
