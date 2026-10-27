"""Read-only presentation of the recruitment lifecycle; no stage rewrites."""
from collections import Counter
from django.db.models import Q
from django.urls import reverse
from .access import recruiter, scoped_jobs, scoped_candidates, reporting_jobs, leadership
from .models import Requisition, HiringRequest, Division, DivisionAccess
from .services import selected_jobs

PHASES = [
    dict(slug='plan', number=1, label='Plan & approve', short='Plan & approve', unit='requests', owner='Manager → HR → named approver', purpose='Agree the hiring need before a vacancy is prepared.', gate='A named approver has approved the current requisition. HR then prepares the vacancy.'),
    dict(slug='attract', number=2, label='Publish & attract', short='Publish & attract', unit='vacancies', owner='HR team', purpose='Prepare clear vacancies and attract applications through the careers site.', gate='HR checks the division, employer, job description, questions and publication checklist before publishing.'),
    dict(slug='screen', number=3, label='Screen & shortlist', short='Screen & shortlist', unit='applications', owner='HR · managers recommend', purpose='Review CVs and evidence, request recommendations and shortlist candidates.', gate='HR reviews the evidence and confirms the next stage. A manager recommendation does not move an application.'),
    dict(slug='interview', number=4, label='Interview & select', short='Interview & select', unit='applications', owner='HR coordinates · interviewers assess', purpose='Arrange assessments, collect feedback and decide whom to offer.', gate='The required assessments and feedback have been reviewed before HR confirms selection.'),
    dict(slug='offer', number=5, label='Offer & acceptance', short='Offer & acceptance', unit='applications', owner='HR · applicant responds', purpose='Record offer progress and the candidate’s confirmed response.', gate='Acceptance of the authorized offer is recorded with evidence. Sending an offer is not acceptance or joining.'),
    dict(slug='handover', number=6, label='Joining & HRMS handover', short='Joining & handover', unit='joiners', owner='HR / onboarding team', purpose='Prepare accepted candidates for joining and the receiving HR team.', gate='Confirm joining arrangements and record HRMS acknowledgement before closing the handover. Booking and HRMS connections are not configured yet.'),
]
BY_SLUG = {p['slug']: p for p in PHASES}


def candidate_phase(candidate):
    kind = candidate.stage_id.stage_type if candidate.stage_id else ''
    label = candidate.stage_id.stage.casefold() if candidate.stage_id else ''
    if candidate.canceled or kind == 'cancelled' or candidate.offer_letter_status == 'rejected':
        return 'closed'
    if candidate.offer_letter_status in ['accepted', 'joined']:
        return 'handover'
    if candidate.offer_letter_status == 'sent' or candidate.hired or kind == 'hired' or 'offer' in label:
        return 'offer'
    if kind == 'interview' or (kind == 'test' and 'screen' not in label):
        return 'interview'
    return 'screen'


def permitted_requisitions(user):
    if user.is_superuser:
        return Requisition.objects.all()
    if recruiter(user):
        divisions = Division.objects.filter(is_active=True)
        if DivisionAccess.objects.filter(user=user).exists():
            divisions = divisions.filter(divisionaccess__user=user).distinct()
        return Requisition.objects.filter(Q(division__in=divisions)|Q(requested_by=user,division__isnull=True))
    return Requisition.objects.filter(Q(requested_by=user) | Q(approver=user) | Q(assignment_director=user) | Q(ta_owner=user))


def phase_scope(request):
    """Use the same record boundaries as existing staff and leadership views."""
    manager_access = recruiter(request.user) or scoped_jobs(request.user).exists()
    aggregate = leadership(request.user) and not manager_access
    jobs = selected_jobs(request, reporting_jobs(request.user) if aggregate else scoped_jobs(request.user))
    available_jobs = jobs
    job_id = request.GET.get('job', '')
    if job_id:
        jobs = jobs.filter(pk=job_id) if job_id.isdigit() else jobs.none()
    if aggregate:
        from recruitment.models import Candidate
        candidates = Candidate.objects.filter(is_active=True, recruitment_id__in=jobs).select_related('recruitment_id', 'stage_id', 'job_position_id')
    else:
        candidates = scoped_candidates(request.user).filter(recruitment_id__in=jobs)
    requests = permitted_requisitions(request.user)
    additional = HiringRequest.objects.filter(job__in=reporting_jobs(request.user)) if leadership(request.user) else HiringRequest.objects.filter(requested_by=request.user)
    additional = additional.filter(job__in=jobs)
    division = request.GET.get('division', '')
    if division:
        requests = requests.none() if division == 'unassigned' else requests.filter(division_id=division) if division.isdigit() else requests.none()
    if job_id:
        requests = requests.filter(job__in=jobs)
    return dict(jobs=jobs, available_jobs=available_jobs, candidates=candidates, requisitions=requests, additional_requests=additional, aggregate=aggregate)


def navigation(request, active='', candidate=None):
    key = (request.GET.get('division', ''), request.GET.get('job', ''))
    cached = getattr(request, '_phase_navigation', None)
    if cached is None or cached[0] != key:
        scope = phase_scope(request)
        counts = Counter(candidate_phase(c) for c in scope['candidates'])
        counts['plan'] = scope['requisitions'].exclude(status='declined').filter(job__isnull=True).count()
        counts['attract'] = scope['jobs'].count()
        request._phase_navigation = (key, counts)
    else:
        counts = cached[1]
    phase = active if active in BY_SLUG else {'jobs':'attract', 'candidates':'screen', 'interviews':'interview', 'requests':'plan'}.get(active, '')
    if candidate:
        phase = candidate_phase(candidate)
    query = request.GET.copy()
    # Navigation preserves only scope, not stale queue, page or edit parameters.
    for name in list(query):
        if name not in ['division', 'job']:
            del query[name]
    suffix = '?' + query.urlencode() if query else ''
    return [dict(p, count=counts[p['slug']], url=reverse('workspace-phase', args=[p['slug']]) + suffix, current=p['slug']==phase) for p in PHASES]
