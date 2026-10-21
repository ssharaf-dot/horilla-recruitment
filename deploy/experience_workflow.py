"""End-to-end workflow and object-access checks. Refuses any database except staging."""
import os, secrets, json, gzip
from pathlib import Path
from datetime import timedelta
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
import django
django.setup()
from django.conf import settings
from django.contrib.auth.models import User, Permission
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from recruitment.models import Recruitment, Candidate, Stage, InterviewSchedule, StageNote, RecruitmentSurvey, RecruitmentSurveyAnswer
from employee.models import Employee, EmployeeWorkInformation
from recruitment_experience.models import ReviewRequest, InterviewFeedback, HiringRequest, ApplicantAccount, ApplicantApplication
from recruitment_experience.access import scoped_candidates, scoped_jobs

assert settings.DATABASES['default']['NAME'] == 'horilla_staging', 'STAGING ONLY'
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
suffix = secrets.token_hex(5)
media = []
checks = []

def check(value, label):
    assert value, label
    checks.append(label)
    print('PASS', label, flush=True)

def client(user=None, csrf=False):
    c = Client(HTTP_X_FORWARDED_PROTO='https', enforce_csrf_checks=csrf)
    if user:
        c.force_login(user)
    return c

def url(name, *args):
    return reverse(name, args=args)

exports = {}
try:
 with transaction.atomic():
    admin = User.objects.get(username='staging_admin')
    a = client(admin)
    job = Recruitment.objects.filter(is_active=True, closed=False, is_published=True).first()
    assert job and job.open_positions.exists()
    position = job.open_positions.first()
    stage_applied = job.stage_set.filter(stage_type='applied').first() or job.stage_set.first()
    stage_interview = job.stage_set.filter(stage_type='interview').first()
    assert stage_applied and stage_interview
    roles = {}
    for name in ['manager', 'outsider', 'leadership']:
        user = User.objects.create_user(username='ux_' + name + suffix, password=secrets.token_urlsafe(32))
        User.objects.filter(pk=user.pk).update(is_new_employee=False)
        user.refresh_from_db()
        employee = Employee.objects.create(employee_user_id=user, employee_first_name='Synthetic ' + name, email=name+suffix+'@example.invalid', phone='0500000000')
        info, _ = EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
        EmployeeWorkInformation.objects.filter(pk=info.pk).update(company_id=job.company_id, department_id=position.department_id, job_position_id=position)
        roles[name] = user
    job.recruitment_managers.add(roles['manager'].employee_get)
    otherjob = Recruitment.objects.exclude(pk=job.pk).first()
    manager = client(roles['manager']); outsider = client(roles['outsider'])
    roles['leadership'].user_permissions.add(Permission.objects.get(codename='view_hiringoverview'))
    leader = client(roles['leadership'])
    for route in ['workspace-today', 'workspace-jobs', 'workspace-candidates', 'workspace-interviews', 'workspace-manager', 'workspace-ceo', 'workspace-requests']:
        response = a.get(url(route))
        check(response.status_code == 200, 'admin render ' + route)
        exports[route] = response.content.decode()
    check(client().get(url('workspace-today')).status_code == 302, 'staff workspace requires login')
    check(outsider.get(url('workspace-today')).status_code == 403, 'unassigned staff cannot enter workspace')
    check(leader.get(url('workspace-ceo')).status_code == 200, 'delegated leadership aggregate access')
    check(manager.get(url('workspace-ceo')).status_code == 403, 'manager cannot enter leadership overview')
    check(manager.get(url('workspace-job', job.pk)).status_code == 200, 'assigned manager sees own job')
    if otherjob:
        check(manager.get(url('workspace-job', otherjob.pk)).status_code == 404, 'manager cannot open unassigned job')
    candidate = Candidate(name='Synthetic UX Applicant', email='ux-'+suffix+'@example.invalid', mobile='0500000033', recruitment_id=job, job_position_id=position, stage_id=stage_applied, source='application')
    import fitz
    pdf = fitz.open(); pdf.new_page().insert_text((72, 72), 'SYNTHETIC CV - WORKSPACE VERIFICATION')
    candidate.resume.save('ux-test.pdf', SimpleUploadedFile('ux.pdf', pdf.tobytes()), save=False)
    media.append(candidate.resume.name)
    candidate.save()
    for route in ['workspace-candidate', 'workspace-job', 'workspace-applicant-preview']:
        pk = job.pk if route == 'workspace-job' else candidate.pk
        response = a.get(url(route, pk))
        check(response.status_code == 200, 'render '+route)
        exports[route] = response.content.decode()
    check(a.post(url('workspace-candidate', candidate.pk), {'note': 'PRIVATE_INTERNAL_UX_TEST'}).status_code == 302, 'internal note saved')
    check(a.post(url('workspace-stage', candidate.pk), {'stage': stage_interview.pk}).status_code == 302, 'stage move saved')
    candidate.refresh_from_db(); check(candidate.stage_id_id == stage_interview.pk, 'stage move persisted')
    check(a.post(url('workspace-review', candidate.pk), {'reviewer': roles['manager'].employee_get.pk}).status_code == 302, 'manager review requested')
    review = ReviewRequest.objects.get(candidate=candidate, reviewer=roles['manager'].employee_get)
    check(manager.get(url('workspace-manager')).status_code == 200, 'review appears in manager workspace')
    check(manager.post(url('workspace-review-complete', review.pk), {'note': 'Recommend technical discussion based on relevant experience.'}).status_code == 302, 'manager recommendation submitted')
    review.refresh_from_db(); check(review.completed_at is not None, 'manager review completion persisted')
    future = timezone.localdate() + timedelta(days=2)
    response = a.post(url('workspace-schedule', candidate.pk), {'interview_date': future.isoformat(), 'interview_time': '10:00', 'interviewers': [roles['manager'].employee_get.pk], 'details': 'Synthetic interview location - demo only'})
    check(response.status_code == 302, 'interview scheduling saved')
    appointment = InterviewSchedule.objects.get(candidate_id=candidate)
    check(appointment.employee_id.filter(pk=roles['manager'].employee_get.pk).exists(), 'assigned interviewer persisted')
    check(manager.post(url('workspace-feedback', appointment.pk), {'technical': 4, 'communication': 4, 'evidence': 'Synthetic interview evidence.', 'recommendation': 'proceed'}).status_code == 200, 'future interview feedback blocked')
    appointment.interview_date = timezone.localdate() - timedelta(days=1)
    appointment.save(update_fields=['interview_date'])
    check(manager.post(url('workspace-feedback', appointment.pk), {'technical': 4, 'communication': 4, 'evidence': 'Synthetic interview evidence.', 'recommendation': 'proceed'}).status_code == 302, 'interviewer feedback submitted')
    check(InterviewFeedback.objects.filter(interview=appointment, author=roles['manager']).exists(), 'feedback persisted')
    appointment.refresh_from_db(); check(appointment.completed, 'interview completed after all interviewer feedback')
    headcount = job.vacancy or 0
    check(manager.post(url('workspace-requests'), {'job': job.pk, 'openings': 1, 'reason': 'Synthetic additional coverage for testing.'}).status_code == 302, 'hiring request submitted')
    hiring = HiringRequest.objects.get(job=job, requested_by=roles['manager'])
    check(manager.post(url('workspace-decide', hiring.pk), {'decision': 'approved'}).status_code == 403, 'manager cannot self-approve headcount')
    check(a.post(url('workspace-decide', hiring.pk), {'decision': 'approved'}).status_code == 302, 'leadership approval saved')
    job.refresh_from_db(); check(job.vacancy == headcount + 1, 'approved opening updates job headcount')
    a.post(url('workspace-decide', hiring.pk), {'decision': 'approved'})
    job.refresh_from_db(); check(job.vacancy == headcount + 1, 'repeated approval cannot double-add openings')
    account = ApplicantAccount.objects.create(email=candidate.email, name=candidate.name, password=make_password(secrets.token_urlsafe(32)))
    ApplicantApplication.objects.create(account=account, candidate=candidate)
    app = client(); session = app.session; session['applicant_account'] = account.pk; session.save()
    response = app.get(url('applicant-detail', candidate.pk))
    check(response.status_code == 200 and b'Synthetic interview location' in response.content, 'applicant sees own interview')
    check(b'PRIVATE_INTERNAL_UX_TEST' not in response.content and b'Synthetic interview evidence' not in response.content, 'applicant never sees internal notes or feedback')
    check(app.get(url('applicant-cv', candidate.pk)).status_code == 200, 'applicant can read own CV')
    check(client().get(url('applicant-detail', candidate.pk)).status_code == 404, 'anonymous candidate ID cannot read application')
    check(client().get(url('applicant-cv', candidate.pk)).status_code == 404, 'anonymous candidate ID cannot read CV')
    otheraccount = ApplicantAccount.objects.create(email='other-'+suffix+'@example.invalid', name='Other Synthetic Applicant', password=make_password(secrets.token_urlsafe(32)))
    otherapp = client(); session = otherapp.session; session['applicant_account'] = otheraccount.pk; session.save()
    check(otherapp.get(url('applicant-detail', candidate.pk)).status_code == 404, 'other applicant cannot open application')
    check(otherapp.get(url('applicant-cv', candidate.pk)).status_code == 404, 'other applicant cannot open CV')
    check(leader.get(url('workspace-cv', candidate.pk)).status_code == 404, 'aggregate leadership permission does not grant CV access')
    check(manager.get(url('workspace-applicant-preview', candidate.pk)).status_code == 403, 'applicant impersonation preview restricted to admin')
    secured = client(admin, csrf=True)
    check(secured.post(url('workspace-stage', candidate.pk), {'stage': stage_applied.pk}).status_code == 403, 'stage writes require CSRF')
    check(secured.post(url('workspace-decide', hiring.pk), {'decision': 'approved'}).status_code == 403, 'approval writes require CSRF')
    check(client(csrf=True).post(url('applicant-login'), {'email': account.email, 'password': 'nope'}).status_code == 403, 'applicant login requires CSRF')
    check(a.get(url('workspace-stage', candidate.pk)).status_code == 405, 'GET never changes stage')
    check(a.get('/payroll/').status_code == 403, 'recruitment-only boundary preserved')
    # Exercise the actual public application and questionnaire. No privileged fields accepted.
    public = client(); email = 'new-'+suffix+'@example.invalid'
    question_text = 'Synthetic UX screening ' + suffix
    question = RecruitmentSurvey.objects.create(question=question_text, type='text', is_mandatory=True)
    question.recruitment_ids.add(job)
    upload = SimpleUploadedFile('public-test.pdf', pdf.tobytes(), content_type='application/pdf')
    response = public.post(url('portal-apply', job.pk), {'name': 'Synthetic Public UX Applicant', 'email': email, 'mobile': '0500000044', 'job_position_id': position.pk, 'resume': upload, 'hired': 'on', 'stage_id': stage_interview.pk})
    check(response.status_code == 302, 'public CV application submitted')
    new = Candidate.objects.get(email=email); media.append(new.resume.name)
    check(not new.hired and new.stage_id_id == stage_applied.pk, 'public application cannot inject hired or stage')
    check(public.get(url('applicant-detail', new.pk)).status_code == 200, 'new public submission owned by its browser session')
    if 'candidate-survey' in response.url:
        check(public.get(response.url).status_code == 200, 'questionnaire still reachable after application')
        response = public.post(url('candidate-survey'), {'text_' + question_text: 'Synthetic relevant experience.'})
        check(response.status_code == 200 and RecruitmentSurveyAnswer.objects.filter(candidate_id=new).exists(), 'public questionnaire answers persisted')
    response = public.get(url('applicant-home'))
    check(response.status_code == 200, 'guest application tracking works')
    exports['applicant-home'] = response.content.decode()
    app_password = secrets.token_urlsafe(32)
    response = public.post(url('applicant-register'), {'email': email, 'name': 'Synthetic Public UX Applicant', 'password': app_password, 'confirm_password': app_password})
    check(response.status_code == 302, 'applicant account registration succeeds')
    new_account = ApplicantAccount.objects.get(email=email)
    check(ApplicantApplication.objects.filter(account=new_account, candidate=new).exists(), 'same-session application attached to applicant account')
    public.post(url('applicant-logout'))
    check(public.get(url('applicant-detail', new.pk)).status_code == 404, 'applicant sign-out clears session ownership')
    response = public.post(url('applicant-login'), {'email': email, 'password': app_password})
    check(response.status_code == 302 and public.get(url('applicant-detail', new.pk)).status_code == 200, 'returning applicant sign-in restores only own applications')
    check(public.get(url('applicant-detail', candidate.pk)).status_code == 404, 'returning applicant cannot read another account')
    unowned = Candidate.objects.exclude(pk__in=[new.pk, candidate.pk]).exclude(workspace_owner__isnull=False).first()
    if unowned:
        impostor = client()
        response = impostor.post(url('applicant-register'), {'email': unowned.email, 'name': 'Synthetic email ownership check', 'password': app_password, 'confirm_password': app_password})
        check(response.status_code == 302, 'fresh account may register without adopting existing applicant records')
        check(impostor.get(url('applicant-detail', unowned.pk)).status_code == 404, 'registering matching email never claims an old application')
    exports['applicant-detail'] = app.get(url('applicant-detail', candidate.pk)).content.decode()
    Path('/tmp/experience-review.json.gz').write_bytes(gzip.compress(json.dumps(exports).encode()))
    transaction.set_rollback(True)
finally:
 for name in media:
    from django.core.files.storage import default_storage
    default_storage.delete(name)
print('EXPERIENCE_WORKFLOW_PASSED', len(checks), 'checks; synthetic database changes rolled back', flush=True)
