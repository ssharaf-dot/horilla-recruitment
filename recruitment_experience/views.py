import json
from datetime import timedelta
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache
from recruitment.models import Recruitment, Candidate, Stage, StageNote, InterviewSchedule, RecruitmentSurveyAnswer
from employee.models import Employee
from .models import ReviewRequest, InterviewFeedback, HiringRequest, ApplicantAccount, ApplicantApplication
from .forms import NoteForm, ScheduleForm, FeedbackForm, HiringRequestForm, ApplicantAccessForm, ApplicantRegistrationForm
from .access import scoped_jobs, scoped_candidates, scoped_interviews, employee_for, can_coordinate, require_coordinate, leadership


def enabled():
    if not settings.RECRUITMENT_ONLY:
        raise Http404()


def workspace(view):
    @login_required(login_url='login')
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        enabled()
        if not (request.user.is_superuser or scoped_jobs(request.user).exists() or leadership(request.user)):
            raise PermissionDenied('Ask your administrator for access to recruitment.')
        response = view(request, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response
    return wrapped


def context(request, **values):
    return dict(can_hr=request.user.has_perm('recruitment.view_recruitment'), can_hire=scoped_jobs(request.user).exists(), can_lead=leadership(request.user), can_approve=request.user.has_perm('recruitment_experience.approve_hiringrequest'), can_create=request.user.has_perm('recruitment.add_recruitment'), **values)


def annotated_jobs(jobs):
    return jobs.annotate(applications=Count('candidate', filter=Q(candidate__is_active=True), distinct=True), hires=Count('candidate', filter=Q(candidate__is_active=True, candidate__stage_id__stage_type='hired'), distinct=True)).order_by('-created_at')


def enrich_jobs(jobs):
    rows = list(annotated_jobs(jobs))
    for job in rows:
        job.remaining = max((job.vacancy or 0) - job.hires, 0)
        job.days_open = max((timezone.localdate() - job.start_date).days, 0)
    return rows


def pending_reviews(user, candidates):
    reviews = ReviewRequest.objects.filter(candidate__in=candidates, completed_at__isnull=True).select_related('candidate', 'candidate__recruitment_id', 'reviewer')
    if not user.is_superuser and not user.has_perm('recruitment.change_candidate'):
        reviews = reviews.filter(reviewer=employee_for(user))
    return reviews.order_by('created_at')


def overdue_feedback(user, manager=False):
    employee = employee_for(user)
    qs = scoped_interviews(user, manager).filter(interview_date__lt=timezone.localdate(), completed=False)
    if employee:
        qs = qs.exclude(workspace_feedback__author=user)
    return qs.order_by('interview_date', 'interview_time')


@workspace
@require_http_methods(['GET', 'HEAD'])
def today(request):
    candidates = scoped_candidates(request.user)
    reviews = pending_reviews(request.user, candidates)
    overdue = overdue_feedback(request.user)
    interviews = scoped_interviews(request.user).filter(interview_date=timezone.localdate(), completed=False).order_by('interview_time')
    applied = candidates.filter(stage_id__stage_type='applied').order_by('created_at')
    return render(request, 'experience/today.html', context(request, active='today', title='Today', new_count=applied.count(), review_count=reviews.count(), overdue_count=overdue.count(), today_count=interviews.count(), applied=applied[:3], reviews=reviews[:3], overdue=overdue[:3], interviews=interviews[:5], jobs=enrich_jobs(scoped_jobs(request.user).filter(closed=False))[:5]))


@workspace
@require_http_methods(['GET', 'HEAD'])
def jobs(request):
    qs = scoped_jobs(request.user)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(open_positions__job_position__icontains=query)).distinct()
    return render(request, 'experience/jobs.html', context(request, active='jobs', title='Jobs', jobs=enrich_jobs(qs), query=query))


@workspace
@require_http_methods(['GET', 'HEAD'])
def job(request, pk):
    record = get_object_or_404(scoped_jobs(request.user), pk=pk)
    candidates = scoped_candidates(request.user).filter(recruitment_id=record)
    columns = []
    for stage in record.stage_set.filter(is_active=True).order_by('sequence', 'pk'):
        columns.append({'stage': stage, 'candidates': list(candidates.filter(stage_id=stage).order_by('created_at'))})
    record = enrich_jobs(scoped_jobs(request.user).filter(pk=pk))[0]
    return render(request, 'experience/job.html', context(request, active='jobs', title=record.title, job=record, columns=columns, managers=record.recruitment_managers.all(), review_count=ReviewRequest.objects.filter(candidate__in=candidates, completed_at__isnull=True).count()))


@workspace
@require_http_methods(['GET', 'HEAD'])
def candidates(request):
    qs = scoped_candidates(request.user)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(email__icontains=query) | Q(recruitment_id__title__icontains=query))
    from django.core.paginator import Paginator
    return render(request, 'experience/candidates.html', context(request, active='candidates', title='Candidates', candidates=Paginator(qs.order_by('-created_at'), 30).get_page(request.GET.get('page')), query=query))


@workspace
@require_http_methods(['GET', 'POST', 'HEAD'])
def candidate(request, pk):
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    note = NoteForm(request.POST or None)
    if request.method == 'POST':
        require_coordinate(request.user, record)
        if note.is_valid():
            StageNote.objects.create(candidate_id=record, stage_id=record.stage_id, description=note.cleaned_data['note'], updated_by=employee_for(request.user), candidate_can_view=False)
            messages.success(request, 'Internal note saved. Applicants cannot see this note.')
            return redirect('workspace-candidate', pk=pk)
    answers = []
    for answer in RecruitmentSurveyAnswer.objects.filter(candidate_id=record):
        data = answer.answer_json
        try:
            data = json.loads(data) if isinstance(data, str) else data
        except (ValueError, TypeError):
            data = {}
        if isinstance(data, dict):
            answers.extend((str(k), ', '.join(map(str, v)) if isinstance(v, list) else str(v)) for k, v in data.items() if k != 'csrfmiddlewaretoken')
    return render(request, 'experience/candidate.html', context(request, active='candidates', title=record.name, candidate=record, note_form=note, can_coordinate=can_coordinate(request.user, record), stages=record.recruitment_id.stage_set.filter(is_active=True).order_by('sequence'), notes=StageNote.objects.filter(candidate_id=record).select_related('updated_by').order_by('-created_at')[:20], answers=answers, interviews=scoped_interviews(request.user).filter(candidate_id=record).order_by('-interview_date'), reviews=record.workspace_reviews.select_related('reviewer').all(), feedback=InterviewFeedback.objects.filter(interview__candidate_id=record).select_related('author', 'interview'), reviewers=record.recruitment_id.recruitment_managers.filter(is_active=True)))


@workspace
@require_http_methods(['POST'])
def stage(request, pk):
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    require_coordinate(request.user, record)
    stage_id = request.POST.get('stage', '')
    if not stage_id.isdigit():
        raise Http404()
    target = get_object_or_404(record.recruitment_id.stage_set.filter(is_active=True), pk=stage_id)
    with transaction.atomic():
        record = Candidate.objects.select_for_update().get(pk=pk)
        previous = str(record.stage_id.stage) if record.stage_id else 'Unassigned'
        record.stage_id = target
        record.canceled = target.stage_type == 'cancelled'
        record.hired = target.stage_type == 'hired'
        record.save()
        StageNote.objects.create(candidate_id=record, stage_id=target, description=f'Stage changed from {previous} to {target.stage}.', updated_by=employee_for(request.user), candidate_can_view=True)
    messages.success(request, 'Application stage updated.')
    return redirect('workspace-candidate', pk=pk)


@workspace
@require_http_methods(['POST'])
def review(request, pk):
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    require_coordinate(request.user, record)
    reviewer_id = request.POST.get('reviewer', '')
    if not reviewer_id.isdigit():
        raise Http404()
    reviewer = get_object_or_404(record.recruitment_id.recruitment_managers.filter(is_active=True), pk=reviewer_id)
    if not reviewer.employee_user_id or not reviewer.employee_user_id.is_active:
        messages.error(request, 'Choose a manager with an active staff account.')
        return redirect('workspace-candidate', pk=pk)
    item, created = ReviewRequest.objects.get_or_create(candidate=record, reviewer=reviewer, defaults={'requested_by': request.user})
    if not created and item.completed_at:
        item.completed_at = None
        item.requested_by = request.user
        item.created_at = timezone.now()
        item.save()
    messages.success(request, 'Manager review requested. It is now in their review queue; no email was sent.')
    return redirect('workspace-candidate', pk=pk)


@workspace
@require_http_methods(['POST'])
def review_complete(request, pk):
    item = get_object_or_404(ReviewRequest.objects.filter(candidate__in=scoped_candidates(request.user)), pk=pk)
    if not request.user.is_superuser and item.reviewer != employee_for(request.user):
        raise PermissionDenied()
    form = NoteForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            StageNote.objects.create(candidate_id=item.candidate, stage_id=item.candidate.stage_id, description='Manager recommendation: ' + form.cleaned_data['note'], updated_by=employee_for(request.user), candidate_can_view=False)
            item.completed_at = timezone.now()
            item.save(update_fields=['completed_at'])
        messages.success(request, 'Your recommendation was saved and the review is complete.')
    else:
        messages.error(request, 'Add a recommendation before completing the review.')
    return redirect('workspace-candidate', pk=item.candidate_id)


@workspace
@require_http_methods(['GET', 'POST', 'HEAD'])
def schedule(request, pk):
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    require_coordinate(request.user, record)
    if not request.user.has_perm('recruitment.add_interviewschedule') and not record.recruitment_id.recruitment_managers.filter(pk=getattr(employee_for(request.user), 'pk', None)).exists():
        raise PermissionDenied()
    form = ScheduleForm(request.POST or None, employees=Employee.objects.filter(is_active=True, employee_user_id__is_active=True))
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            appointment = InterviewSchedule.objects.create(candidate_id=record, interview_date=form.cleaned_data['interview_date'], interview_time=form.cleaned_data['interview_time'], description=form.cleaned_data['details'])
            appointment.employee_id.set(form.cleaned_data['interviewers'])
            StageNote.objects.create(candidate_id=record, stage_id=record.stage_id, description='Interview scheduled. Check your application for appointment details.', updated_by=employee_for(request.user), candidate_can_view=True)
        messages.success(request, 'Interview saved and visible in the applicant portal. No email or calendar invitation was sent.')
        return redirect('workspace-candidate', pk=pk)
    return render(request, 'experience/form.html', context(request, active='interviews', title='Schedule interview', intro=record.name + ' · ' + str(record.recruitment_id), form=form, submit_label='Save interview', cancel_url=reverse('workspace-candidate', args=[pk])))


@workspace
@require_http_methods(['GET', 'HEAD'])
def interviews(request):
    return render(request, 'experience/interviews.html', context(request, active='interviews', title='Interviews', interviews=scoped_interviews(request.user).order_by('-interview_date', 'interview_time'), today=timezone.localdate()))


@workspace
@require_http_methods(['GET', 'POST', 'HEAD'])
def feedback(request, pk):
    appointment = get_object_or_404(scoped_interviews(request.user), pk=pk)
    if not request.user.is_superuser and not appointment.employee_id.filter(pk=getattr(employee_for(request.user), 'pk', None)).exists():
        raise PermissionDenied('Only an assigned interviewer can submit feedback.')
    existing = InterviewFeedback.objects.filter(interview=appointment, author=request.user).first()
    form = FeedbackForm(request.POST or None, instance=existing)
    if request.method == 'POST' and form.is_valid():
        if appointment.interview_date > timezone.localdate():
            form.add_error(None, 'Feedback can be submitted on or after the interview date.')
        else:
            with transaction.atomic():
                item = form.save(commit=False)
                item.interview = appointment
                item.author = request.user
                item.save()
                # Completion is a team outcome: every assigned interviewer must submit.
                expected = set(appointment.employee_id.exclude(employee_user_id=None).values_list('employee_user_id', flat=True))
                received = set(appointment.workspace_feedback.values_list('author_id', flat=True))
                if expected and expected.issubset(received):
                    appointment.completed = True
                    appointment.save(update_fields=['completed'])
            messages.success(request, 'Interview feedback saved. It remains private to the hiring team.')
            return redirect('workspace-candidate', pk=appointment.candidate_id_id)
    return render(request, 'experience/form.html', context(request, active='manager', title='Interview feedback', intro=str(appointment.candidate_id), form=form, submit_label='Submit feedback', cancel_url=reverse('workspace-candidate', args=[appointment.candidate_id_id])))


@workspace
@require_http_methods(['GET', 'HEAD'])
def manager(request):
    candidates = scoped_candidates(request.user, manager=True)
    jobs = enrich_jobs(scoped_jobs(request.user, manager=True).filter(closed=False))
    reviews = pending_reviews(request.user, candidates)
    interviews = scoped_interviews(request.user, manager=True).filter(completed=False, interview_date__gte=timezone.localdate()).order_by('interview_date', 'interview_time')
    return render(request, 'experience/manager.html', context(request, active='manager', title='Hiring manager', jobs=jobs, reviews=reviews, overdue=overdue_feedback(request.user, True), next_interview=interviews.first(), remaining=sum(job.remaining for job in jobs)))


@workspace
@require_http_methods(['GET', 'HEAD'])
def ceo(request):
    if not leadership(request.user):
        raise PermissionDenied('Leadership overview permission is required.')
    jobs = enrich_jobs(Recruitment.objects.filter(is_active=True, closed=False))
    total = sum(job.vacancy or 0 for job in jobs)
    hires = sum(job.hires for job in jobs)
    groups = {}
    for job in jobs:
        positions = list(job.open_positions.select_related('department_id'))
        label = str(positions[0].department_id) if positions and positions[0].department_id else 'Other departments'
        row = groups.setdefault(label, {'name': label, 'total': 0, 'hires': 0})
        row['total'] += job.vacancy or 0
        row['hires'] += job.hires
    for row in groups.values():
        row['percent'] = min(round(100 * row['hires'] / row['total']), 100) if row['total'] else 0
    candidates = Candidate.objects.filter(is_active=True, recruitment_id__in=[j.pk for j in jobs])
    critical = [j for j in jobs if j.remaining and j.days_open >= 30]
    return render(request, 'experience/ceo.html', context(request, active='ceo', title='Leadership overview', jobs=jobs, openings=total, hires=hires, remaining=sum(j.remaining for j in jobs), critical=critical, departments=list(groups.values()), pending=HiringRequest.objects.filter(status='pending').select_related('job', 'requested_by'), applications=candidates.count(), in_progress=candidates.exclude(stage_id__stage_type__in=['hired', 'cancelled']).count(), rejected=candidates.filter(stage_id__stage_type='cancelled').count()))


@workspace
@require_http_methods(['GET', 'POST', 'HEAD'])
def hiring_request(request):
    form = HiringRequestForm(request.POST or None, jobs=scoped_jobs(request.user), initial={'job': request.GET.get('job')})
    if request.method == 'POST' and form.is_valid():
        job = form.cleaned_data['job']
        employee = employee_for(request.user)
        if not request.user.has_perm('recruitment.change_recruitment') and not job.recruitment_managers.filter(pk=getattr(employee, 'pk', None)).exists():
            raise PermissionDenied()
        item = form.save(commit=False)
        item.requested_by = request.user
        item.save()
        messages.success(request, 'Hiring request submitted to leadership. Openings change only after approval.')
        return redirect('workspace-requests')
    items = HiringRequest.objects.all() if leadership(request.user) else HiringRequest.objects.filter(requested_by=request.user)
    return render(request, 'experience/requests.html', context(request, active='requests', title='Hiring requests', form=form, requests=items.select_related('job', 'requested_by', 'decided_by').order_by('-created_at')))


@workspace
@require_http_methods(['POST'])
def decide(request, pk):
    if not request.user.has_perm('recruitment_experience.approve_hiringrequest'):
        raise PermissionDenied()
    decision = request.POST.get('decision')
    if decision not in {'approved', 'declined'}:
        raise Http404()
    with transaction.atomic():
        item = get_object_or_404(HiringRequest.objects.select_for_update(), pk=pk)
        if item.status != 'pending':
            messages.error(request, 'This request already has a decision. Its openings were not changed again.')
        else:
            if decision == 'approved':
                job = Recruitment.objects.select_for_update().get(pk=item.job_id)
                if job.closed:
                    messages.error(request, 'Reopen the job before approving additional openings.')
                    return redirect('workspace-requests')
                job.vacancy = (job.vacancy or 0) + item.openings
                # Avoid Recruitment.save() LinkedIn publication hooks for headcount only.
                Recruitment.objects.filter(pk=job.pk).update(vacancy=job.vacancy)
            item.status = decision
            item.decided_by = request.user
            item.decided_at = timezone.now()
            item.decision_note = request.POST.get('decision_note', '').strip()[:2000]
            item.save()
            messages.success(request, 'Hiring request ' + decision + '. The decision has been recorded.')
    return redirect('workspace-requests')


@workspace
@require_http_methods(['GET', 'HEAD'])
def candidate_cv(request, pk):
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    return serve_cv(record)


def serve_cv(record):
    if not record.resume:
        raise Http404()
    try:
        result = FileResponse(record.resume.open('rb'), content_type='application/pdf', filename='application-cv.pdf')
    except (FileNotFoundError, OSError):
        raise Http404()
    result['Cache-Control'] = 'private, no-store'
    result['X-Content-Type-Options'] = 'nosniff'
    result['X-Frame-Options'] = 'SAMEORIGIN'
    return result


def applicant_account(request):
    account = ApplicantAccount.objects.filter(pk=request.session.get('applicant_account')).first()
    # An explicit session generation protects against stale ownership after login changes.
    return account


def attach_application(request, candidate):
    """Called only immediately after a successful public application in this session."""
    account = applicant_account(request)
    if account and candidate.email.strip().lower() == account.email:
        ApplicantApplication.objects.get_or_create(candidate=candidate, defaults={'account': account})
    else:
        owned = request.session.get('applicant_guest_ids', [])
        request.session['applicant_guest_ids'] = list(dict.fromkeys(owned + [candidate.pk]))[-20:]


def owned_candidates(request):
    account = applicant_account(request)
    ids = list(account.applications.values_list('candidate_id', flat=True)) if account else []
    ids += request.session.get('applicant_guest_ids', [])
    return Candidate.objects.filter(pk__in=ids).select_related('recruitment_id', 'stage_id')


@require_http_methods(['GET', 'POST', 'HEAD'])
@never_cache
def applicant_login(request):
    enabled()
    form = ApplicantAccessForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        # Rate limit both account and network; never log raw credentials.
        import hashlib
        email = form.cleaned_data['email'].strip().lower()
        keys = ['applicant-login-' + hashlib.sha256(value.encode()).hexdigest() for value in [email, request.META.get('REMOTE_ADDR', '')]]
        blocked = any(cache.get(key, 0) >= 10 for key in keys)
        account = ApplicantAccount.objects.filter(email=email).first()
        valid = check_password(form.cleaned_data['password'], account.password if account else make_password(None))
        if valid and not blocked:
            request.session.cycle_key()
            request.session['applicant_account'] = account.pk
            for key in keys:
                cache.delete(key)
            return redirect('applicant-home')
        for key in keys:
            cache.set(key, cache.get(key, 0) + 1, 900)
        form.add_error(None, 'Sign-in failed. Check your details, or try again later after repeated attempts.')
    return render(request, 'experience/applicant_access.html', {'form': form, 'register': False})


@require_http_methods(['GET', 'POST', 'HEAD'])
@never_cache
def applicant_register(request):
    enabled()
    form = ApplicantRegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                account = ApplicantAccount.objects.create(email=form.cleaned_data['email'], name=form.cleaned_data['name'], password=make_password(form.cleaned_data['password']))
                # Only submissions made in this browser session may be attached.
                for candidate in owned_candidates(request).filter(email__iexact=account.email):
                    ApplicantApplication.objects.get_or_create(candidate=candidate, defaults={'account': account})
            request.session.cycle_key()
            request.session['applicant_account'] = account.pk
            return redirect('applicant-home')
        except IntegrityError:
            form.add_error(None, 'Unable to create this account. If it already exists, sign in.')
    return render(request, 'experience/applicant_access.html', {'form': form, 'register': True})


@require_http_methods(['POST'])
@never_cache
def applicant_logout(request):
    enabled()
    request.session.pop('applicant_account', None)
    request.session.pop('applicant_guest_ids', None)
    request.session.cycle_key()
    return redirect('applicant-login')


@require_http_methods(['GET', 'HEAD'])
@never_cache
def applicant_home(request):
    enabled()
    account = applicant_account(request)
    records = owned_candidates(request)
    if not account and not records.exists():
        return redirect('applicant-login')
    return render(request, 'experience/applicant_home.html', {'account': account, 'applications': records.order_by('-created_at')})


def applicant_context(candidate):
    return {'candidate': candidate, 'stages': candidate.recruitment_id.stage_set.filter(is_active=True).exclude(stage_type='cancelled').order_by('sequence'), 'time_zone': timezone.get_current_timezone_name(), 'interviews': InterviewSchedule.objects.filter(candidate_id=candidate).prefetch_related('employee_id').order_by('-interview_date', '-interview_time'), 'updates': StageNote.objects.filter(candidate_id=candidate, candidate_can_view=True).order_by('-created_at')[:20], 'questionnaire_complete': RecruitmentSurveyAnswer.objects.filter(candidate_id=candidate).exists(), 'has_questions': candidate.recruitment_id.recruitmentsurvey_set.exists()}


@require_http_methods(['GET', 'HEAD'])
@never_cache
def applicant_detail(request, pk):
    enabled()
    record = get_object_or_404(owned_candidates(request), pk=pk)
    return render(request, 'experience/applicant_detail.html', applicant_context(record))


@require_http_methods(['GET', 'HEAD'])
@never_cache
def applicant_cv(request, pk):
    enabled()
    return serve_cv(get_object_or_404(owned_candidates(request), pk=pk))


@workspace
@require_http_methods(['GET', 'HEAD'])
def applicant_preview(request, pk):
    if not request.user.is_superuser:
        raise PermissionDenied()
    record = get_object_or_404(scoped_candidates(request.user), pk=pk)
    return render(request, 'experience/applicant_detail.html', dict(applicant_context(record), preview=True))


@require_http_methods(['POST'])
@never_cache
def applicant_questionnaire(request, pk):
    enabled()
    record = get_object_or_404(owned_candidates(request), pk=pk)
    from django.core import serializers
    if RecruitmentSurveyAnswer.objects.filter(candidate_id=record).exists():
        return redirect('applicant-detail', pk=pk)
    request.session['candidate'] = serializers.serialize('json', [record])
    return redirect('candidate-survey')
