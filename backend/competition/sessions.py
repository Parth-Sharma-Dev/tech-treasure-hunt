import math
import re
import uuid
from datetime import timedelta

from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.db import IntegrityError, transaction
from django.middleware.csrf import rotate_token
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from .api import ApiProblem
from .models import AuditEvent, Team, TeamLoginWindow, TeamSession
from .rules import require_staff_permission

MAX_TEAM_SESSIONS = 4
LOGIN_FAILURE_LIMIT = 5
LOGIN_WINDOW_SECONDS = 60


def safe_return_path(value):
    if isinstance(value, str) and (
        value in ("/", "/lobby")
        or re.fullmatch(r"/missions/[A-Za-z0-9_-]{20,64}", value)
        or re.fullmatch(r"/rounds/[1-9][0-9]{0,9}/results", value)
        or re.fullmatch(r"/rounds/[1-9][0-9]{0,9}", value)
        or re.fullmatch(r'/rounds/[1-9][0-9]{0,9}/coding', value)
    ):
        return value
    return "/lobby"


def active_sessions(team, now=None):
    return TeamSession.objects.filter(
        team=team,
        revoked_at__isnull=True,
        expires_at__gt=now or timezone.now(),
        session_version=team.session_version,
    )


@transaction.atomic
@sensitive_variables()
def login_team(request, code, password):
    # Return failures normally so failed-login counters commit instead of rolling back.
    team = (
        Team.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(code=code)
        .first()
    )
    if (
        team is None
        or not team.user.is_active
        or team.user.is_staff
        or team.status != Team.Status.ACTIVE
    ):
        return ApiProblem("invalid_credentials", "Check your team code and password.", 401)
    now = timezone.now()
    window, _ = TeamLoginWindow.objects.get_or_create(team=team, defaults={"started_at": now})
    if now >= window.started_at + timedelta(seconds=LOGIN_WINDOW_SECONDS):
        window.started_at = now
        window.failed_attempts = 0
    if window.failed_attempts >= LOGIN_FAILURE_LIMIT:
        retry_after = max(
            1, math.ceil(LOGIN_WINDOW_SECONDS - (now - window.started_at).total_seconds())
        )
        return ApiProblem(
            "login_rate_limited", "Too many login attempts. Try again shortly.", 429, retry_after
        )
    if not team.user.check_password(password):
        window.failed_attempts += 1
        window.save()
        return ApiProblem("invalid_credentials", "Check your team code and password.", 401)
    window.failed_attempts = 0
    window.save()
    if request.user.is_authenticated and request.user.pk != team.user_id:
        return ApiProblem("account_conflict", "Sign out before changing accounts.", 409)
    previous_key = request.session.session_key
    current = active_sessions(team, now).filter(session_key=previous_key).first()
    if current and request.user.is_authenticated:
        rotate_token(request)
        return team
    if active_sessions(team, now).count() >= MAX_TEAM_SESSIONS:
        return ApiProblem(
            "session_limit",
            "Four browsers are already signed in. Ask event staff to remove a stale session.",
            409,
        )
    # Never revive the key of a revoked session, including on a same-account re-login.
    request.session.cycle_key()
    login(request, team.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.save()
    TeamSession.objects.create(
        team=team,
        session_key=request.session.session_key,
        session_version=team.session_version,
        expires_at=request.session.get_expiry_date(),
        last_seen_at=now,
    )
    return team


def require_team(request, *, allow_inactive=False, touch=True):
    if not request.user.is_authenticated or not request.user.is_active or request.user.is_staff:
        raise ApiProblem("authentication_required", "Sign in with your team credentials.", 401)
    record = (
        TeamSession.objects.select_related("team")
        .filter(
            session_key=request.session.session_key,
            team__user=request.user,
            team__user__is_active=True,
            team__user__is_staff=False,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )
        .first()
    )
    if record is None or record.session_version != record.team.session_version:
        raise ApiProblem(
            "session_revoked", "This session has ended. Sign in again or contact event staff.", 401
        )
    if not allow_inactive and record.team.status != Team.Status.ACTIVE:
        raise ApiProblem("team_inactive", "This team cannot submit. Contact event staff.", 403)
    if touch:
        TeamSession.objects.filter(pk=record.pk, revoked_at__isnull=True).update(
            last_seen_at=timezone.now()
        )
    request.team_session = record
    return record.team


@transaction.atomic
def logout_team(request):
    if request.user.is_authenticated:
        team = Team.objects.select_for_update().filter(user=request.user).first()
        if team:
            TeamSession.objects.filter(
                team=team, session_key=request.session.session_key, revoked_at__isnull=True
            ).update(revoked_at=timezone.now())
    logout(request)
    rotate_token(request)


@transaction.atomic
def revoke_session(team_id, session_id, actor, action_id, reason):
    require_staff_permission(actor, "control_round")
    try:
        action_id = uuid.UUID(action_id)
    except (ValueError, TypeError, AttributeError):
        raise ApiProblem("invalid_request", "A valid action UUID is required.") from None
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ApiProblem("invalid_request", "Give a reason for revoking the session.")
    team = Team.objects.select_for_update().filter(pk=team_id).first()
    if team is None:
        raise ApiProblem("not_found", "Team not found.", 404)
    fingerprint = {"team_id": team_id, "session_id": session_id, "reason": reason}
    previous = AuditEvent.objects.filter(action_id=action_id).first()
    if previous:
        if previous.action != "revoke_team_session" or previous.after.get("request") != fingerprint:
            raise ApiProblem(
                "action_conflict", "This action key was used for a different request.", 409
            )
        return previous.after["response"]
    record = TeamSession.objects.filter(pk=session_id, team=team).first()
    if record is None:
        raise ApiProblem("not_found", "Session not found for this team.", 404)
    before = {"revoked_at": record.revoked_at.isoformat() if record.revoked_at else None}
    if record.revoked_at is None:
        record.revoked_at = timezone.now()
        record.save(update_fields=["revoked_at"])
    Session.objects.filter(session_key=record.session_key).delete()
    response = {"session_id": record.pk, "revoked_at": record.revoked_at.isoformat()}
    try:
        with transaction.atomic():
            AuditEvent.objects.create(
                action_id=action_id,
                actor=actor,
                action="revoke_team_session",
                reason=reason,
                before=before,
                after={"request": fingerprint, "response": response},
            )
    except IntegrityError:
        # Roll back the entire revocation if another team used the same global action UUID.
        raise ApiProblem("action_conflict", "This action key was already used.", 409) from None
    return response
