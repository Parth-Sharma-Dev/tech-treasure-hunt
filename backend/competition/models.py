import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q


def mission_token():
    return secrets.token_urlsafe(32)


def fallback_code():
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def staff_reference(**kwargs):
    return models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", **kwargs
    )


class ImmutableEvidence(models.Model):
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Evidence is immutable; append a new revision instead.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Original evidence cannot be deleted.")


class Round(models.Model):
    class State(models.TextChoices):
        DRAFT = "DRAFT"
        READY = "READY"
        LOBBY = "LOBBY"
        LIVE = "LIVE"
        FROZEN = "FROZEN"
        ENDED = "ENDED"
        PROVISIONAL = "PROVISIONAL"
        FINALIZED = "FINALIZED"

    class Delivery(models.TextChoices):
        ONLINE_HUNT = "ONLINE_HUNT", "Online treasure hunt"
        CODING = "CODING", "Supervised Python/C competition"
        EXTERNAL = "EXTERNAL", "Externally judged"
        BUZZER = "BUZZER", "Website buzzer with offline answers"

    class PlayMode(models.TextChoices):
        ONLINE = "ONLINE"
        PAPER = "PAPER"

    number = models.PositiveSmallIntegerField()
    attempt_no = models.PositiveSmallIntegerField(default=1)
    attempt_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=120)
    delivery_mode = models.CharField(max_length=20, choices=Delivery, blank=True)
    state = models.CharField(max_length=16, choices=State, default=State.DRAFT)
    play_mode = models.CharField(max_length=8, choices=PlayMode, default=PlayMode.ONLINE)
    rules_version = models.CharField(max_length=40, blank=True)
    rules = models.JSONField(default=dict, blank=True)
    rules_digest = models.CharField(max_length=64, blank=True, editable=False)
    rules_snapshot = models.JSONField(default=dict, editable=False)
    owners = models.JSONField(default=dict, blank=True)
    approved_by = staff_reference(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_digest = models.CharField(max_length=64, blank=True, editable=False)
    advancement_count = models.PositiveIntegerField(null=True, blank=True)
    active_budget_ms = models.PositiveBigIntegerField(default=90 * 60 * 1000)
    accumulated_active_ms = models.PositiveBigIntegerField(default=0)
    live_started_at = models.DateTimeField(null=True, blank=True)
    phase_started_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    control_version = models.PositiveIntegerField(default=0)
    is_demo = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["number", "attempt_no"], name="round_attempt_unique"),
            models.CheckConstraint(condition=Q(number__gte=1, number__lte=5), name="round_number"),
            models.CheckConstraint(condition=Q(attempt_no__gte=1), name="round_attempt_positive"),
            models.CheckConstraint(
                condition=Q(active_budget_ms__gt=0), name="round_budget_positive"
            ),
            models.CheckConstraint(
                condition=Q(advancement_count__isnull=True) | Q(advancement_count__gt=0),
                name="round_cut_positive",
            ),
        ]
        permissions = [
            ("prepare_content", "Prepare competition content"),
            ("control_round", "Control a live round"),
            ("adjudicate", "Propose score corrections"),
            ("verify_evidence", "Independently verify evidence"),
            ("publish_results", "Publish verified results"),
        ]

    def __str__(self):
        return f"Round {self.number} / attempt {self.attempt_no}: {self.title}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if not self._state.adding:
                previous = Round.objects.select_for_update().get(pk=self.pk)
                if previous.state != self.State.DRAFT:
                    frozen_fields = (
                        "number",
                        "attempt_no",
                        "attempt_id",
                        "title",
                        "delivery_mode",
                        "rules_version",
                        "rules",
                        "rules_digest",
                        "rules_snapshot",
                        "owners",
                        "approved_by_id",
                        "approved_at",
                        "approval_digest",
                        "advancement_count",
                        "is_demo",
                    )
                    if any(
                        getattr(self, field) != getattr(previous, field) for field in frozen_fields
                    ):
                        raise ValidationError("Round configuration is frozen after READY.")
                if (
                    previous.play_mode == self.PlayMode.PAPER
                    and self.play_mode != self.PlayMode.PAPER
                ):
                    raise ValidationError("Paper play cannot reopen online scoring.")
            return super().save(*args, **kwargs)


class RoundPhase(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    phase_type = models.CharField(max_length=8, choices=[("LIVE", "Live"), ("FROZEN", "Frozen")])
    play_mode = models.CharField(max_length=8, choices=Round.PlayMode)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    reason = models.TextField()
    actor = staff_reference()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(ended_at__gte=F("started_at")), name="phase_time_order"
            )
        ]


class BuzzerQuestion(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    public_id = models.CharField(max_length=40)
    stage = models.PositiveSmallIntegerField()
    version = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=200)
    private_content = models.JSONField(default=dict)
    prepared_by = staff_reference(null=True, blank=True)
    verified_by = staff_reference(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "public_id"], name="buzzer_question_unique"),
            models.CheckConstraint(
                condition=Q(stage__gte=1, stage__lte=5), name="buzzer_stage_range"
            ),
        ]

    def clean(self):
        from .buzzer_content import question_errors

        if errors := question_errors(self):
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            target = Round.objects.select_for_update().get(pk=self.round_id)
            previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            if target.state != "DRAFT" or previous and previous.round_id != self.round_id:
                raise ValidationError("Released buzzer questions cannot be edited or moved.")
            if previous and any(
                getattr(previous, field) != getattr(self, field)
                for field in [
                    "public_id",
                    "stage",
                    "version",
                    "source_reference",
                    "private_content",
                ]
            ):
                self.verified_by = None
                self.verified_at = None
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if Round.objects.select_for_update().get(pk=self.round_id).state != "DRAFT":
                raise ValidationError("Released buzzer questions cannot be deleted.")
            return super().delete(*args, **kwargs)


class BuzzerWindow(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    question = models.ForeignKey(BuzzerQuestion, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    round_version = models.PositiveIntegerField()
    opened_at = models.DateTimeField()
    actor = staff_reference()
    reason = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "version"], name="buzzer_window_version"),
        ]


class BuzzerClosure(ImmutableEvidence):
    window = models.OneToOneField(BuzzerWindow, on_delete=models.PROTECT)
    closed_at = models.DateTimeField()
    actor = staff_reference()
    reason = models.TextField()


class BuzzerPress(ImmutableEvidence):
    id = models.UUIDField(primary_key=True, editable=False)
    window = models.ForeignKey(BuzzerWindow, on_delete=models.PROTECT)
    team = models.ForeignKey("Team", on_delete=models.PROTECT)
    session = models.ForeignKey("TeamSession", on_delete=models.PROTECT)
    received_at = models.DateTimeField()
    admitted_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["window", "team", "received_at"], name="buzzer_team_time")]


class CodingTask(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    public_id = models.CharField(max_length=24)
    category = models.CharField(
        max_length=16,
        choices=[(key, key.title()) for key in ["OUTPUT", "DEBUG", "FILL", "SHORT", "LOGIC"]],
    )
    prompt = models.TextField(max_length=10000)
    starter_code = models.TextField(max_length=16000, blank=True)
    languages = models.JSONField(default=list)
    points = models.DecimalField(max_digits=7, decimal_places=3)
    version = models.CharField(max_length=40)
    private_rubric = models.JSONField(
        default=dict,
        help_text=(
            "Private lab judging rubric. SHORT tasks need test_cases "
            "with unique id/input/expected fields."
        ),
    )
    prepared_by = staff_reference(null=True, blank=True)
    verified_by = staff_reference(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "public_id"], name="coding_task_id_unique"),
            models.CheckConstraint(condition=Q(points__gt=0), name="coding_task_points_positive"),
        ]

    def __str__(self):
        return f"{self.public_id} ({self.category})"

    def clean(self):
        from .coding_content import task_errors

        errors = task_errors(self)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            round = Round.objects.select_for_update().get(pk=self.round_id)
            if round.state != "DRAFT":
                raise ValidationError("Coding tasks are frozen after READY.")
            if self.pk:
                old = CodingTask.objects.get(pk=self.pk)
                if old.round_id != self.round_id:
                    raise ValidationError(
                        "Create a new draft coding task instead of moving existing content."
                    )
                fields = [
                    "round_id",
                    "public_id",
                    "category",
                    "prompt",
                    "starter_code",
                    "languages",
                    "points",
                    "version",
                    "private_rubric",
                    "prepared_by_id",
                ]
                if any(getattr(old, key) != getattr(self, key) for key in fields):
                    self.verified_by = self.verified_at = None
                    if kwargs.get("update_fields"):
                        kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                            "verified_by",
                            "verified_at",
                        }
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if Round.objects.select_for_update().get(pk=self.round_id).state != "DRAFT":
                raise ValidationError("Released coding tasks cannot be deleted.")
            return super().delete(*args, **kwargs)


class CodingWorkstation(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    team = models.ForeignKey("Team", on_delete=models.PROTECT)
    session = models.ForeignKey("TeamSession", on_delete=models.PROTECT)
    label = models.CharField(max_length=100)
    supervisor = staff_reference()
    evidence_references = models.JSONField(default=list)
    assigned_at = models.DateTimeField()
    version = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "team"], name="coding_one_station_per_team"),
            models.UniqueConstraint(fields=["round", "label"], name="coding_station_unique"),
        ]


class CodingRevision(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    team = models.ForeignKey("Team", on_delete=models.PROTECT)
    task = models.ForeignKey(CodingTask, on_delete=models.PROTECT)
    action_id = models.UUIDField(unique=True)
    revision = models.PositiveIntegerField()
    language = models.CharField(max_length=16)
    body = models.TextField()
    source_hash = models.CharField(max_length=64)
    admitted_at = models.DateTimeField()
    active_elapsed_ms = models.PositiveBigIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "task", "revision"], name="coding_revision_unique"
            )
        ]


class CodingSubmission(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    team = models.ForeignKey("Team", on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    submitted_at = models.DateTimeField()
    active_elapsed_ms = models.PositiveBigIntegerField()
    manifest = models.JSONField(default=list)
    manifest_digest = models.CharField(max_length=64)
    workstation_evidence = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["round", "team"], name="coding_final_once")]


class CodingJudgmentProposal(ImmutableEvidence):
    submission = models.ForeignKey(CodingSubmission, on_delete=models.PROTECT)
    maker = staff_reference()
    payload = models.JSONField()
    reason = models.TextField()
    evidence_digest = models.CharField(max_length=64)


class CodingJudgment(ImmutableEvidence):
    proposal = models.OneToOneField(CodingJudgmentProposal, on_delete=models.PROTECT)
    submission = models.ForeignKey(CodingSubmission, on_delete=models.PROTECT)
    verifier = staff_reference()
    score = models.DecimalField(max_digits=7, decimal_places=3)
    fully_correct_tasks = models.PositiveSmallIntegerField()
    task_marks = models.JSONField(default=list)
    rejected = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(score__gte=0, score__lte=100), name="coding_score_bounds"
            )
        ]


class PublishedInformation(models.Model):
    prepared_by = staff_reference(null=True, blank=True)
    published_by = staff_reference(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_snapshot = models.JSONField(default=dict, editable=False)
    visible = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        publication_fields = ["published_by_id", "published_at", "published_snapshot"]
        with transaction.atomic():
            if self.pk and kwargs.get("update_fields") is None:
                previous = type(self).objects.select_for_update().filter(pk=self.pk).first()
                if previous:
                    for field in publication_fields:
                        setattr(self, field, getattr(previous, field))
            return super().save(*args, **kwargs)


class RoundInformation(PublishedInformation):
    round = models.OneToOneField(Round, on_delete=models.PROTECT)
    summary = models.TextField(max_length=1000, blank=True)
    instructions = models.TextField(
        max_length=10000,
        blank=True,
        help_text=(
            "General participant instructions. Keep clues, answers and interview questions private."
        ),
    )
    venue = models.CharField(max_length=200, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)
    contacts = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'Approved contacts: [{"name":"Name", "role":"Role", '
            '"location":"Desk", "channel":"Public contact"}]'
        ),
    )

    def clean(self):
        from .portal import validate_information

        validate_information(self)
        if (
            self.pk
            and self.published_snapshot
            and self.published_snapshot.get("round_id") != self.round_id
        ):
            raise ValidationError(
                "Create a new information record instead of moving a published one."
            )

    def __str__(self):
        return f"Information: {self.round}"


class EventAnnouncement(PublishedInformation):
    title = models.CharField(max_length=150)
    body = models.TextField(max_length=3000)
    is_demo = models.BooleanField(default=False)
    round = models.ForeignKey(Round, on_delete=models.PROTECT, null=True, blank=True)

    def clean(self):
        if self.round_id and self.round.is_demo != self.is_demo:
            raise ValidationError("Announcement and round must use the same demo/live cohort.")
        if (
            self.pk
            and self.published_snapshot
            and (
                self.published_snapshot.get("is_demo") != self.is_demo
                or self.published_snapshot.get("round_id") != self.round_id
            )
        ):
            raise ValidationError("Published announcements cannot move between cohorts or rounds.")

    def __str__(self):
        return self.title


class FacultyProfile(PublishedInformation):
    display_name = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    location = models.CharField(max_length=200, blank=True)
    contact_channel = models.CharField(max_length=200, blank=True)
    photo_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Approved HTTPS portrait URL; leave blank for an initials placeholder.",
    )
    consent_reference = models.CharField(max_length=200)
    is_demo = models.BooleanField(default=False)

    def clean(self):
        if self.photo_url and not self.photo_url.startswith("https://"):
            raise ValidationError("Use an approved HTTPS portrait URL.")
        if self.published_snapshot and self.published_snapshot.get("is_demo") != self.is_demo:
            raise ValidationError("Published faculty cannot move between cohorts.")

    def __str__(self):
        return self.display_name


class Team(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        WITHDRAWN = "WITHDRAWN"
        DISQUALIFIED = "DISQUALIFIED"

    code = models.CharField(max_length=24, unique=True)
    name = models.CharField(max_length=100)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    leader_name = models.CharField(max_length=100, blank=True)
    roster_reference = models.CharField(max_length=200, blank=True)
    roster_digest = models.CharField(max_length=64, blank=True)
    member_count = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE)
    session_version = models.PositiveIntegerField(default=1)
    is_demo = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(member_count__gte=3, member_count__lte=4), name="team_member_count"
            )
        ]

    def __str__(self):
        return f"{self.code}: {self.name}"


class TeamSession(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    session_key = models.CharField(max_length=40, unique=True)
    session_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "revoked_at", "expires_at"])]


class TeamLoginWindow(models.Model):
    team = models.OneToOneField(Team, on_delete=models.PROTECT)
    started_at = models.DateTimeField()
    failed_attempts = models.PositiveIntegerField(default=0)


class Mission(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    public_id = models.CharField(max_length=24)
    token = models.CharField(max_length=64, default=mission_token, unique=True, editable=False)
    fallback_code = models.CharField(
        max_length=12, default=fallback_code, unique=True, editable=False
    )
    hint = models.TextField()
    symbol = models.CharField(max_length=100, blank=True)
    qr_location = models.CharField(max_length=200)
    clue_location = models.CharField(max_length=200)
    difficulty = models.CharField(max_length=20, blank=True)
    points = models.PositiveSmallIntegerField(default=1)
    answer_verifiers = models.JSONField(default=list)
    keyword = models.CharField(max_length=100)
    volunteer_owner = staff_reference(null=True, blank=True)
    prepared_by = staff_reference(null=True, blank=True)
    available = models.BooleanField(default=True)
    is_void = models.BooleanField(default=False)
    is_practice = models.BooleanField(default=False)
    verified_by = staff_reference(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "public_id"], name="mission_public_id_unique"),
            models.CheckConstraint(condition=Q(points=1), name="mission_one_point"),
        ]

    def __str__(self):
        return f"{self.public_id} (round {self.round_id})"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            round = Round.objects.select_for_update().get(pk=self.round_id)
            if round.state != Round.State.DRAFT:
                raise ValidationError("Mission content is frozen after READY; use adjudication.")
            if not self._state.adding:
                previous = Mission.objects.get(pk=self.pk)
                if previous.round_id != self.round_id:
                    raise ValidationError("Move missions by creating a new draft mission instead.")
                content_fields = (
                    "public_id",
                    "hint",
                    "symbol",
                    "qr_location",
                    "clue_location",
                    "difficulty",
                    "points",
                    "answer_verifiers",
                    "keyword",
                    "volunteer_owner_id",
                    "prepared_by_id",
                    "is_practice",
                    "available",
                )
                if any(
                    getattr(previous, field) != getattr(self, field) for field in content_fields
                ):
                    self.verified_by = None
                    self.verified_at = None
                    if kwargs.get("update_fields") is not None:
                        kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                            "verified_by",
                            "verified_at",
                        }
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            round = Round.objects.select_for_update().get(pk=self.round_id)
            if round.state != Round.State.DRAFT:
                raise ValidationError("Released missions cannot be deleted.")
            return super().delete(*args, **kwargs)


class Visit(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    first_opened_at = models.DateTimeField()
    last_opened_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=1)
    access_method = models.CharField(
        max_length=12, choices=[("QR", "QR"), ("FALLBACK", "Fallback")]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "mission"], name="visit_team_mission_unique"),
            models.CheckConstraint(condition=Q(count__gte=1), name="visit_count_positive"),
            models.CheckConstraint(
                condition=Q(last_opened_at__gte=F("first_opened_at")), name="visit_time_order"
            ),
        ]


class AttemptState(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    evaluated_wrong_count = models.PositiveIntegerField(default=0)
    cooldown_until_active_ms = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "mission"], name="attempt_team_mission_unique")
        ]


class SubmissionDecision(ImmutableEvidence):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    request_fingerprint = models.CharField(max_length=64)
    answer_hmac = models.CharField(max_length=64, blank=True)
    ingress_at = models.DateTimeField()
    admitted_at = models.DateTimeField()
    active_elapsed_ms = models.PositiveBigIntegerField()
    rules_version = models.CharField(max_length=40)
    answer_key_version = models.CharField(max_length=40, blank=True)
    outcome = models.CharField(max_length=32)
    reason = models.CharField(max_length=200, blank=True)
    response_snapshot = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "round", "idempotency_key"], name="decision_key_unique"
            )
        ]
        indexes = [
            models.Index(fields=["team", "round", "admitted_at"]),
            models.Index(fields=["team", "round", "active_elapsed_ms"]),
            models.Index(fields=["round", "outcome", "admitted_at"]),
        ]

    def clean(self):
        if self.mission_id and self.round_id and self.mission.round_id != self.round_id:
            raise ValidationError("Mission does not belong to the decision's round.")


class Incident(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    category = models.CharField(max_length=40)
    affected_scope = models.JSONField(default=dict)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    evidence_references = models.JSONField(default=list)
    decision = models.TextField(blank=True)
    owner = staff_reference()
    material = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(closed_at__isnull=True) | Q(closed_at__gte=F("opened_at")),
                name="incident_time_order",
            )
        ]


class ResolutionProposal(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    correction_type = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    expected_version = models.PositiveIntegerField()
    evidence_digest = models.CharField(max_length=64)
    reason = models.TextField()
    maker = staff_reference()
    incident = models.ForeignKey(Incident, on_delete=models.PROTECT)


class MissionResolution(ImmutableEvidence):
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    correction_type = models.CharField(max_length=32)
    affected_scope = models.JSONField(default=dict)
    evidence_references = models.JSONField(default=list)
    source_decisions = models.JSONField(default=list)
    reason = models.TextField()
    maker = staff_reference()
    approver = staff_reference()
    incident = models.ForeignKey(Incident, on_delete=models.PROTECT)
    proposal = models.OneToOneField(
        ResolutionProposal, on_delete=models.PROTECT, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=~Q(maker=F("approver")), name="resolution_two_reviewers"
            )
        ]


class Completion(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    source_decision = models.ForeignKey(
        SubmissionDecision, on_delete=models.PROTECT, null=True, blank=True
    )
    source_resolution = models.ForeignKey(
        MissionResolution, on_delete=models.PROTECT, null=True, blank=True
    )
    effective_at = models.DateTimeField()
    effective_active_ms = models.PositiveBigIntegerField()
    revision = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "mission"], name="completion_unique"),
            models.CheckConstraint(
                condition=(
                    Q(source_decision__isnull=False, source_resolution__isnull=True)
                    | Q(source_decision__isnull=True, source_resolution__isnull=False)
                ),
                name="completion_one_source",
            ),
        ]

    def clean(self):
        if self.source_decision_id:
            source = self.source_decision
            if source.team_id != self.team_id or source.mission_id != self.mission_id:
                raise ValidationError("Completion source belongs to a different team or mission.")
            if source.outcome != "accepted":
                raise ValidationError("A direct completion requires an accepted decision.")
        if self.source_resolution_id and self.source_resolution.mission_id != self.mission_id:
            raise ValidationError("Completion resolution belongs to a different mission.")
        if self.mission_id and self.mission.is_practice:
            raise ValidationError("Practice missions cannot create competitive completions.")


class ImportBatch(models.Model):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    file_digest = models.CharField(max_length=64)
    schema_version = models.CharField(max_length=40)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    dry_run_errors = models.JSONField(default=list)
    preview = models.JSONField(default=list)
    source_rows = models.JSONField(default=list)
    evidence_digest = models.CharField(max_length=64, blank=True)
    reason = models.TextField(blank=True)
    maker = staff_reference()
    verifier = staff_reference(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            protected = [
                "round_id",
                "file_digest",
                "schema_version",
                "source_rows",
                "preview",
                "dry_run_errors",
                "maker_id",
                "reason",
                "evidence_digest",
            ]
            if any(getattr(self, field) != getattr(previous, field) for field in protected):
                raise ValidationError("Original score batch evidence cannot be rewritten.")
            if previous.committed_at and (
                self.verifier_id != previous.verifier_id
                or self.committed_at != previous.committed_at
            ):
                raise ValidationError("Committed source batch verification cannot be replaced.")
        return super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "file_digest"], name="import_file_unique"),
            models.CheckConstraint(
                condition=Q(verifier__isnull=True) | ~Q(maker=F("verifier")),
                name="import_two_reviewers",
            ),
            models.CheckConstraint(
                condition=Q(committed_at__isnull=True) | Q(verifier__isnull=False),
                name="import_commit_verified",
            ),
        ]


class ExternalVoidProposal(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    maker = staff_reference()
    question_id = models.CharField(max_length=40)
    source_reference = models.CharField(max_length=200)
    reason = models.TextField()
    evidence_digest = models.CharField(max_length=64)


class ExternalQuestionVoid(ImmutableEvidence):
    proposal = models.OneToOneField(ExternalVoidProposal, on_delete=models.PROTECT)
    verifier = staff_reference()


class RosterProposal(ImmutableEvidence):
    maker = staff_reference()
    payload = models.JSONField()
    evidence_digest = models.CharField(max_length=64)
    reason = models.TextField()


class ScoreRevision(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    score = models.DecimalField(max_digits=10, decimal_places=3)
    max_score = models.DecimalField(max_digits=10, decimal_places=3)
    tie_metrics = models.JSONField(default=dict)
    source_reference = models.CharField(max_length=200)
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, null=True, blank=True)
    reason = models.TextField()
    maker = staff_reference()
    verifier = staff_reference()
    supersedes = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(score__gte=0, max_score__gt=0, score__lte=F("max_score")),
                name="score_range",
            ),
            models.CheckConstraint(condition=~Q(maker=F("verifier")), name="score_two_reviewers"),
        ]

    def clean(self):
        if self.import_batch_id and self.import_batch.round_id != self.round_id:
            raise ValidationError("Import belongs to a different round.")
        if self.supersedes_id:
            previous = self.supersedes
            if previous.team_id != self.team_id or previous.round_id != self.round_id:
                raise ValidationError("A revision must supersede the same team and round.")


class ResultProposal(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    maker = staff_reference()
    target_status = models.CharField(
        max_length=12, choices=[("PROVISIONAL", "Provisional"), ("FINAL", "Final")]
    )
    expected_version = models.PositiveIntegerField()
    evidence_digest = models.CharField(max_length=64)
    payload = models.JSONField()
    reason = models.TextField()


class ResultSnapshot(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()
    status = models.CharField(
        max_length=12, choices=[("PROVISIONAL", "Provisional"), ("FINAL", "Final")]
    )
    ranked_entries = models.JSONField(default=list)
    qualifier_codes = models.JSONField(default=list)
    cut_count = models.PositiveIntegerField(null=True, blank=True)
    rules_digest = models.CharField(max_length=64)
    evidence_digest = models.CharField(max_length=64)
    maker = staff_reference()
    approver = staff_reference()
    appeal_deadline = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict)
    proposal = models.OneToOneField(
        ResultProposal, on_delete=models.PROTECT, null=True, blank=True, related_name="publication"
    )
    published_at = models.DateTimeField()
    supersedes = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["round", "revision"], name="snapshot_revision_unique"),
            models.CheckConstraint(
                condition=~Q(maker=F("approver")), name="snapshot_two_reviewers"
            ),
        ]

    def clean(self):
        if self.supersedes_id and self.supersedes.round_id != self.round_id:
            raise ValidationError("A result snapshot must supersede the same round.")


class PaperWindow(ImmutableEvidence):
    round = models.OneToOneField(Round, on_delete=models.PROTECT)
    incident = models.ForeignKey(Incident, on_delete=models.PROTECT)
    official_start = models.DateTimeField()
    official_end = models.DateTimeField()
    active_offset_ms = models.PositiveBigIntegerField()
    remaining_budget_ms = models.PositiveBigIntegerField()
    assigned_desks = models.JSONField()
    clock_evidence = models.JSONField()
    writer_isolation_evidence = models.JSONField()
    recorder = staff_reference()
    verifier = staff_reference()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(official_end__gte=F("official_start")), name="paper_time_order"
            ),
            models.CheckConstraint(
                condition=~Q(recorder=F("verifier")), name="paper_two_reviewers"
            ),
        ]


class PaperProposal(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16)
    payload = models.JSONField(default=dict)
    expected_version = models.PositiveIntegerField()
    evidence_digest = models.CharField(max_length=64)
    maker = staff_reference()
    reason = models.TextField()


class PaperSlip(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    proposal = models.OneToOneField(PaperProposal, on_delete=models.PROTECT)
    team = models.ForeignKey(Team, on_delete=models.PROTECT)
    mission = models.ForeignKey(Mission, on_delete=models.PROTECT)
    slip_number = models.CharField(max_length=64)
    desk = models.CharField(max_length=100)
    evaluated_at = models.DateTimeField()
    active_elapsed_ms = models.PositiveBigIntegerField()
    outcome = models.CharField(max_length=32)
    answer_hmac = models.CharField(max_length=64, blank=True)
    answer_key_version = models.CharField(max_length=40, blank=True)
    maker = staff_reference()
    verifier = staff_reference()
    evidence_references = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["round", "slip_number"], name="paper_slip_number_unique"
            ),
            models.CheckConstraint(
                condition=~Q(maker=F("verifier")), name="paper_slip_two_reviewers"
            ),
        ]


class RecoveryProposal(ImmutableEvidence):
    round = models.ForeignKey(Round, on_delete=models.PROTECT)
    maker = staff_reference()
    payload = models.JSONField(default=dict)
    reason = models.TextField()
    expected_version = models.PositiveIntegerField()
    evidence_digest = models.CharField(max_length=64)
    incident = models.ForeignKey(Incident, on_delete=models.PROTECT)


class AuditEvent(ImmutableEvidence):
    action_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor = staff_reference()
    action = models.CharField(max_length=80)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.TextField()
    incident = models.ForeignKey(Incident, on_delete=models.PROTECT, null=True, blank=True)
