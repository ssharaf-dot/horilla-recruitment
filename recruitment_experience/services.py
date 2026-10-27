"""Shared display, scope and durable-event rules for the recruitment workspace."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone
from .models import InterviewPlan, NotificationDelivery, WorkflowEvent

WORKING_ZONE = ZoneInfo('Asia/Dubai')


def selected_jobs(request, jobs):
    division = request.GET.get('division', '')
    if division == 'unassigned':
        return jobs.filter(workspace_profile__division__isnull=True)
    if division:
        return jobs.filter(workspace_profile__division_id=division) if division.isdigit() else jobs.none()
    return jobs


def public_status(candidate):
    if candidate.canceled:
        event = candidate.workspace_events.filter(kind='withdrawn').first()
        return 'Withdrawn' if event else 'Not progressing'
    offer = candidate.offer_letter_status
    if offer == 'joined':
        return 'Joined'
    if offer == 'accepted':
        return 'Offer accepted'
    if offer == 'sent':
        return 'Offer'
    if candidate.hired:
        return 'Next steps with HR'
    kind = candidate.stage_id.stage_type if candidate.stage_id else 'applied'
    return {'applied': 'Received', 'interview': 'Interview', 'cancelled': 'Not progressing'}.get(kind, 'Under review')


def stage_age(candidate):
    event = candidate.workspace_events.filter(kind='stage').order_by('-created_at', '-pk').first()
    return (timezone.now() - event.created_at).days if event else None


def decorate_candidate(candidate):
    candidate.public_status = public_status(candidate)
    candidate.days_in_stage = stage_age(candidate)
    return candidate


def interview_time(appointment):
    try:
        starts = appointment.workspace_plan.starts_at
    except InterviewPlan.DoesNotExist:
        # Existing date/time fields were entered in the installation's original zone.
        zone = ZoneInfo(getattr(settings, 'RECRUITMENT_LEGACY_TIME_ZONE', settings.TIME_ZONE))
        starts = datetime.combine(appointment.interview_date, appointment.interview_time, tzinfo=zone)
    return starts.astimezone(WORKING_ZONE)


def decorate_interview(appointment):
    appointment.dubai_time = interview_time(appointment)
    try:
        appointment.plan = appointment.workspace_plan
    except InterviewPlan.DoesNotExist:
        appointment.plan = None
    appointment.cancelled = bool(appointment.plan and appointment.plan.status == 'cancelled')
    return appointment


def audit(candidate, user, kind, detail='', **metadata):
    from .activity import record_event
    return record_event(candidate=candidate, actor=user if getattr(user, 'is_authenticated', False) else None, kind=kind, detail=detail, metadata=metadata)


def notify(key, recipient, subject, body):
    if not recipient:
        return None
    return NotificationDelivery.objects.get_or_create(key=key, defaults={
        'recipient': recipient, 'subject': subject, 'body': body,
        'status': 'queued' if getattr(settings, 'RECRUITMENT_NOTIFICATIONS_ENABLED', False) else 'held',
    })[0]


def task_message(path, intro):
    base = getattr(settings, 'RECRUITMENT_PUBLIC_URL', '').rstrip('/')
    return intro + ('\n\nOpen your task: ' + base + path if base else '\n\nSign in to the recruitment workspace to view this task.')
