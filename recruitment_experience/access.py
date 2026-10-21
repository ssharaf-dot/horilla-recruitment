"""All record access is scoped on the server, independently of visible navigation."""
from django.db.models import Q
from django.core.exceptions import PermissionDenied
from recruitment.models import Recruitment, Candidate, InterviewSchedule


def employee_for(user):
    return getattr(user, 'employee_get', None)


def scoped_jobs(user, manager=False):
    jobs = Recruitment.objects.filter(is_active=True)
    if user.is_superuser or (not manager and user.has_perm('recruitment.view_recruitment')):
        return jobs
    employee = employee_for(user)
    if employee is None:
        return jobs.none()
    return jobs.filter(Q(recruitment_managers=employee) | Q(stage_set__stage_managers=employee) | Q(candidate__candidate_interview__employee_id=employee)).distinct()


def scoped_candidates(user, manager=False):
    candidates = Candidate.objects.filter(is_active=True).select_related('recruitment_id', 'stage_id', 'job_position_id')
    if user.is_superuser or (not manager and user.has_perm('recruitment.view_candidate')):
        return candidates.filter(recruitment_id__in=scoped_jobs(user))
    employee = employee_for(user)
    if employee is None:
        return candidates.none()
    return candidates.filter(Q(recruitment_id__recruitment_managers=employee) | Q(stage_id__stage_managers=employee) | Q(candidate_interview__employee_id=employee)).distinct()


def can_coordinate(user, candidate):
    if user.has_perm('recruitment.change_candidate'):
        return True
    employee = employee_for(user)
    return employee is not None and (candidate.recruitment_id.recruitment_managers.filter(pk=employee.pk).exists() or (candidate.stage_id and candidate.stage_id.stage_managers.filter(pk=employee.pk).exists()))


def require_coordinate(user, candidate):
    if not can_coordinate(user, candidate):
        raise PermissionDenied('Only a coordinator for this application can change its next step.')


def scoped_interviews(user, manager=False):
    interviews = InterviewSchedule.objects.filter(candidate_id__in=scoped_candidates(user, manager)).select_related('candidate_id', 'candidate_id__recruitment_id').prefetch_related('employee_id')
    if user.is_superuser or (not manager and user.has_perm('recruitment.view_interviewschedule')):
        return interviews
    employee = employee_for(user)
    return interviews.filter(employee_id=employee).distinct() if employee else interviews.none()


def leadership(user):
    return user.has_perm('recruitment_experience.view_hiringoverview')
