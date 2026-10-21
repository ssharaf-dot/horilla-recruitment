"""Create explicit demo personas, using credentials supplied outside Git.

Run with Django initialized. Set HORILLA_DEMO_ACCOUNTS_FILE to a mode-0600 JSON
file containing demo_hr, demo_manager, demo_ceo and applicant passwords. This
script is intentionally opt-in and never changes existing accounts/passwords.
"""
import os
import json
from datetime import timedelta, time
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from employee.models import Employee, EmployeeWorkInformation
from recruitment.models import Recruitment, Candidate, StageNote, InterviewSchedule
from recruitment_experience.models import ApplicantAccount, ApplicantApplication, ReviewRequest, HiringRequest
from recruitment_experience.access import scoped_jobs, scoped_candidates
from recruitment_portal.models import get_branding

assert os.environ.get('HORILLA_CREATE_DEMO_ACCOUNTS') == 'approved', 'Explicit demo provisioning required'
secrets_path = Path(os.environ['HORILLA_DEMO_ACCOUNTS_FILE'])
assert secrets_path.stat().st_mode & 0o077 == 0, 'Credentials file must be private'
passwords = json.loads(secrets_path.read_text())
assert all(len(passwords[k]) >= 16 for k in ['demo_hr', 'demo_manager', 'demo_ceo', 'applicant'])
assert not User.objects.filter(username__in=['demo_hr', 'demo_manager', 'demo_ceo']).exists(), 'Demo staff already exist; inspect instead of resetting them'
assert not ApplicantAccount.objects.filter(email='demo.applicant@example.invalid').exists(), 'Demo applicant already exists'
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
jobs = list(Recruitment.objects.filter(is_active=True, is_published=True, closed=False).order_by('pk'))
assert len(jobs) >= 2
preferred = [j for j in jobs if 'facilit' in j.title.lower() or 'property manager' in j.title.lower()]
assigned = (preferred + [j for j in jobs if j not in preferred])[:2]
job = assigned[0]
position = job.open_positions.first()
assert position
stage = job.stage_set.filter(stage_type='interview').first()
assert stage
initial_admin = User.objects.filter(username='demo_admin').values('id','password','is_active','is_superuser').first()
media_created = []
try:
 with transaction.atomic():
    users = {}
    for username, first, last in [('demo_hr','Demo','HR'),('demo_manager','Demo','Hiring Manager'),('demo_ceo','Demo','CEO')]:
        user = User.objects.create_user(username=username, email=username+'@example.invalid', password=passwords[username], first_name=first, last_name=last, is_staff=False, is_superuser=False)
        User.objects.filter(pk=user.pk).update(is_new_employee=False)
        user.refresh_from_db()
        employee = Employee.objects.create(employee_user_id=user, employee_first_name=first, employee_last_name=last, email=user.email, phone='0000000000')
        info, _ = EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
        EmployeeWorkInformation.objects.filter(pk=info.pk).update(company_id=job.company_id, department_id=position.department_id, job_position_id=position)
        users[username] = user
    hr_group, _ = Group.objects.get_or_create(name='Demo Recruitment HR')
    hr_group.permissions.set(Permission.objects.filter(content_type__app_label='recruitment', codename__regex=r'^(view|add|change)_'))
    users['demo_hr'].groups.add(hr_group)
    ceo_group, _ = Group.objects.get_or_create(name='Demo Recruitment Leadership')
    ceo_group.permissions.set(Permission.objects.filter(content_type__app_label='recruitment_experience', codename__in=['view_hiringoverview','approve_hiringrequest','view_hiringrequest']))
    users['demo_ceo'].groups.add(ceo_group)
    manager = users['demo_manager'].employee_get
    for assigned_job in assigned:
        assigned_job.recruitment_managers.add(manager)
        for candidate in Candidate.objects.filter(recruitment_id=assigned_job, stage_id__stage_type='initial')[:1]:
            ReviewRequest.objects.create(candidate=candidate, reviewer=manager, requested_by=users['demo_hr'])
    # Ensure useful reviews even if this installation uses a different screening stage type.
    review_candidates = Candidate.objects.filter(recruitment_id__in=assigned, hired=False, canceled=False).exclude(stage_id__stage_type__in=['hired','cancelled']).order_by('pk')[:2]
    for candidate in review_candidates:
        ReviewRequest.objects.get_or_create(candidate=candidate, reviewer=manager, defaults={'requested_by':users['demo_hr']})
    prior_interview = InterviewSchedule.objects.filter(candidate_id__recruitment_id__in=assigned, interview_date__lt=timezone.localdate(), completed=False).first()
    if prior_interview:
        prior_interview.employee_id.add(manager)
    account = ApplicantAccount.objects.create(email='demo.applicant@example.invalid', name='Alex Demo', password=make_password(passwords['applicant']))
    candidate = Candidate(name='Alex Demo', email=account.email, mobile='0000000000', recruitment_id=job, job_position_id=position, stage_id=stage, source='application', city='Dubai', country='United Arab Emirates')
    import fitz
    pdf = fitz.open(); page = pdf.new_page()
    page.insert_text((60,70), 'ALEX DEMO - FICTIONAL APPLICANT', fontsize=18)
    page.insert_text((60,110), 'Synthetic CV for recruitment platform demonstrations only.\n\nProperty operations and facilities coordination\n5 years of fictional relevant experience\nSample skills: tenant services, maintenance planning, project coordination\n\nNo real personal information is included.', fontsize=11)
    candidate.resume.save('alex-demo-cv.pdf', ContentFile(pdf.tobytes()), save=False)
    media_created.append(candidate.resume)
    candidate.save()
    ApplicantApplication.objects.create(account=account, candidate=candidate)
    StageNote.objects.create(candidate_id=candidate, stage_id=stage, description='Demo application reviewed. Your interview is the next step.', updated_by=users['demo_hr'].employee_get, candidate_can_view=True)
    StageNote.objects.create(candidate_id=candidate, stage_id=stage, description='DEMO INTERNAL NOTE: discuss examples of property operations experience. This note is private to the hiring team.', updated_by=users['demo_hr'].employee_get, candidate_can_view=False)
    appointment = InterviewSchedule.objects.create(candidate_id=candidate, interview_date=timezone.localdate()+timedelta(days=2), interview_time=time(10,0), description='Demo interview only. Review the role and prepare two examples of relevant experience. No real meeting invitation has been sent.')
    appointment.employee_id.add(manager)
    hiring_request = HiringRequest.objects.create(job=job, openings=1, reason='Demo approval request: one additional opening to support an upcoming property handover. This is fictional headcount for testing the CEO approval journey.', requested_by=users['demo_manager'])
    assert users['demo_manager'].has_perm('recruitment.view_candidate') is False
    assert users['demo_ceo'].has_perm('recruitment.view_candidate') is False
    assert scoped_jobs(users['demo_manager']).count() == len(assigned)
    assert scoped_candidates(users['demo_ceo']).count() == 0
    if initial_admin:
        assert User.objects.filter(username='demo_admin').values('id','password','is_active','is_superuser').first() == initial_admin
    receipt={'created_staff':list(users),'applicant_email':account.email,'applicant_candidate_id':candidate.pk,'assigned_jobs':[{'id':j.pk,'title':j.title} for j in assigned], 'pending_hiring_request_id':hiring_request.pk,'interview_date':str(appointment.interview_date),'time_zone':settings.TIME_ZONE}
    Path('/tmp/demo-role-receipt.json').write_text(json.dumps(receipt,indent=2))
 print('DEMO_ROLES_PROVISIONED_WITH_SCOPED_ACCESS',flush=True)
except Exception:
 for field in media_created:
    field.storage.delete(field.name)
 raise
