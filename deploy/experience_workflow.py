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
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from recruitment.models import Recruitment, Candidate, Stage, InterviewSchedule, StageNote, RecruitmentSurvey, RecruitmentSurveyAnswer
from employee.models import Employee, EmployeeWorkInformation
from recruitment_experience.models import ReviewRequest, InterviewFeedback, HiringRequest, ApplicantAccount, ApplicantApplication, ApplicationDraft, InterviewPlan, Division, DivisionAccess, VacancyProfile, NotificationDelivery, WorkflowEvent, Requisition
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
    check(a.post(url('workspace-stage', candidate.pk), {'stage': stage_interview.pk}).status_code == 200, 'stage preview before save')
    check(manager.post(url('workspace-stage', candidate.pk), {'stage': stage_interview.pk,'confirm':'yes','expected_stage':stage_applied.pk}).status_code == 403, 'manager cannot change stage')
    check(a.post(url('workspace-stage', candidate.pk), {'stage': stage_interview.pk,'confirm':'yes','expected_stage':stage_applied.pk}).status_code == 302, 'stage move saved')
    check(a.post(url('workspace-stage', candidate.pk), {'stage': stage_applied.pk,'confirm':'yes','expected_stage':stage_applied.pk}).status_code == 302, 'stale stage request redirected')
    check(WorkflowEvent.objects.filter(candidate=candidate,kind='stage').count()==1,'stale request does not write again')
    candidate.refresh_from_db(); check(candidate.stage_id_id == stage_interview.pk, 'stage move persisted')
    check(a.post(url('workspace-review', candidate.pk), {'reviewer': roles['manager'].employee_get.pk}).status_code == 302, 'manager review requested')
    review = ReviewRequest.objects.get(candidate=candidate, reviewer=roles['manager'].employee_get)
    check(manager.get(url('workspace-manager')).status_code == 200, 'review appears in manager workspace')
    check(manager.post(url('workspace-review-complete', review.pk), {'recommendation':'advance', 'note': 'Recommend technical discussion based on relevant experience.'}).status_code == 302, 'manager recommendation submitted')
    review.refresh_from_db(); check(review.completed_at is not None, 'manager review completion persisted')
    future = timezone.localdate() + timedelta(days=2)
    response = a.post(url('workspace-schedule', candidate.pk), {'date': future.isoformat(), 'time': '10:00', 'duration_minutes':45,'format':'in_person','location':'Synthetic office', 'interviewers': [roles['manager'].employee_get.pk], 'details': 'Synthetic interview location - demo only'})
    check(response.status_code == 302, 'interview scheduling saved')
    appointment = InterviewSchedule.objects.get(candidate_id=candidate)
    check(appointment.employee_id.filter(pk=roles['manager'].employee_get.pk).exists(), 'assigned interviewer persisted')
    check(manager.post(url('workspace-feedback', appointment.pk), {'technical': 4, 'communication': 4, 'evidence': 'Synthetic interview evidence.', 'recommendation': 'proceed'}).status_code == 200, 'future interview feedback blocked')
    InterviewPlan.objects.filter(interview=appointment).update(starts_at=timezone.now()-timedelta(days=1))
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
    attachment_question=RecruitmentSurvey.objects.create(question='Synthetic attachment '+suffix,type='file',is_mandatory=True)
    attachment_question.recruitment_ids.add(job)
    upload = SimpleUploadedFile('public-test.pdf', pdf.tobytes(), content_type='application/pdf')
    Recruitment.objects.filter(pk=job.pk).update(optional_profile_image=True)
    response=public.get(url('portal-apply',job.pk))
    check(response.status_code==302,'application starts an owned draft')
    draft=ApplicationDraft.objects.get(job=job,owner_key=public.session['application_draft_owner'])
    draft_url=url('portal-apply-draft',job.pk,draft.pk)
    check(client().get(draft_url).status_code==404,'another browser cannot resume draft')
    response=public.post(draft_url+'?step=1',{'name':'Synthetic Public UX Applicant','email':email,'mobile':'+971500000044','job_position_id':position.pk,'hired':'on','stage_id':stage_interview.pk})
    check(response.status_code==302,'draft details saved')
    response=public.post(draft_url+'?step=2',{'resume':upload})
    draft.refresh_from_db();media.append(draft.resume.name)
    check(response.status_code==302,'draft CV saved')
    check(not Candidate.objects.filter(email=email).exists(),'incomplete application stays out of HR queue')
    values={}
    for item in draft.questions:
        key='q'+str(item['id'])
        if item['type']=='text' or item['type']=='textarea':values[key]='Synthetic relevant experience.'
        elif item['type'] in ['options','multiple']: values[key]=[(item['options'] or '').split(',')[0].strip()] if item['type']=='multiple' else (item['options'] or '').split(',')[0].strip()
        elif item['type']=='checkbox': values[key]='yes'
        elif item['type']=='date':values[key]=str(timezone.localdate())
        elif item['type'] in ['number','percentage','rating']:values[key]='3'
        elif item['type']=='file':values[key]=SimpleUploadedFile('test.txt',b'Synthetic evidence')
    check(public.post(draft_url+'?step=3',{}).status_code==200,'required question blocks progress')
    check(public.post(draft_url+'?step=3',values).status_code==302,'required questionnaire saved before candidate exists')
    draft.refresh_from_db();media.extend(v for k,v in draft.attachments.items())
    response=public.post(draft_url+'?step=4',{'confirm':'on'})
    check(response.status_code==302,'reviewed application submitted')
    new=Candidate.objects.get(email=email)
    check(not new.hired and new.stage_id_id==stage_applied.pk,'public application cannot inject hired or stage')
    public.post(draft_url+'?step=4',{'confirm':'on'})
    check(Candidate.objects.filter(email=email).count()==1,'repeated final submit creates one candidate')
    check(RecruitmentSurveyAnswer.objects.filter(candidate_id=new).exists(),'questions and application submitted together')
    check(a.get(url('workspace-attachment',new.pk,'q'+str(attachment_question.pk))).status_code==200,'HR can download protected screening attachment')
    check(leader.get(url('workspace-attachment',new.pk,'q'+str(attachment_question.pk))).status_code==404,'leadership cannot download screening attachment')
    check(public.get(url('applicant-detail',new.pk)).status_code==200,'new submission belongs to browser session')
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
    exports['careers']=a.get(url('portal-careers')).content.decode()
    exports['settings']=a.get(url('workspace-settings')).content.decode()
    exports['requisitions']=a.get(url('workspace-requisitions')).content.decode()
    exports['wizard']=public.get(draft_url+'?step=4').content.decode()
    Path('/tmp/experience-review.json.gz').write_bytes(gzip.compress(json.dumps(exports).encode()))
    check(a.get(url('workspace-document-page',candidate.pk,1)).status_code==200,'protected CV renders as an image')
    check(leader.get(url('workspace-document',candidate.pk)).status_code==404,'leadership cannot preview CV')
    check(manager.post(url('workspace-schedule',candidate.pk),{}).status_code==403,'manager cannot schedule interview')
    for name in ['workspace-settings','workspace-requisitions','workspace-vacancy-new']:
        check(a.get(url(name)).status_code==200,'new HR screen '+name)
    for name in ['workspace-job-settings','workspace-vacancy-edit','workspace-job-team','workspace-questions','workspace-publish']:
        check(a.get(url(name,job.pk)).status_code==200,'vacancy configuration '+name)
    from recruitment_experience.services import interview_time
    legacy=InterviewSchedule.objects.create(candidate_id=candidate,interview_date=future,interview_time='10:00')
    legacy.refresh_from_db()
    with override_settings(RECRUITMENT_LEGACY_TIME_ZONE='Asia/Singapore'):
        check(interview_time(legacy).hour==6,'legacy Singapore instant is preserved as 06 Dubai')
    cal=a.get(url('workspace-calendar',legacy.pk)).content
    response=a.post(url('workspace-interview-cancel',legacy.pk),{'reason':'Synthetic cancellation','confirm':'on'})
    check(response.status_code==302,'interview cancellation confirmed')
    cal2=a.get(url('workspace-calendar',legacy.pk)).content
    check(next(x for x in cal.splitlines() if x.startswith(b'UID:'))==next(x for x in cal2.splitlines() if x.startswith(b'UID:')),'calendar UID stable across cancellation')
    check(b'STATUS:CANCELLED' in cal2,'cancelled calendar carries cancellation status')
    peer=InterviewSchedule.objects.create(candidate_id=candidate,interview_date=timezone.localdate()-timedelta(days=1),interview_time='09:00')
    peer.employee_id.set([roles['manager'].employee_get,roles['outsider'].employee_get])
    InterviewFeedback.objects.create(interview=peer,author=roles['outsider'],technical=3,communication=3,evidence='PRIVATE_PEER_SCORE_BEFORE_OWN_SUBMISSION',recommendation='more_information')
    check(b'PRIVATE_PEER_SCORE_BEFORE_OWN_SUBMISSION' not in manager.get(url('workspace-candidate',candidate.pk)).content,'peer assessment hidden until own submission')
    manager.post(url('workspace-feedback',peer.pk),{'technical':4,'communication':4,'evidence':'Independent synthetic assessment','recommendation':'proceed'})
    check(b'PRIVATE_PEER_SCORE_BEFORE_OWN_SUBMISSION' in manager.get(url('workspace-candidate',candidate.pk)).content,'peer assessment visible after own submission')
    check(public.post(url('applicant-action',new.pk,'contact'),{'details':'+971500000055','confirm':'on'}).status_code==302,'applicant can update own phone')
    check(otherapp.get(url('applicant-action',new.pk,'withdraw')).status_code==404,'other applicant cannot withdraw application')
    check(public.post(url('applicant-action',new.pk,'withdraw'),{'confirm':'on','details':'Synthetic test withdrawal'}).status_code==302,'applicant can confirm own withdrawal')
    new.refresh_from_db();check(new.canceled and new.workspace_events.filter(kind='withdrawn').exists(),'withdrawal recorded without deleting application')
    division=Division.objects.first();otherdivision=Division.objects.exclude(pk=division.pk).first()
    VacancyProfile.objects.update_or_create(job=job,defaults={'division':division})
    if otherjob:
        VacancyProfile.objects.update_or_create(job=otherjob,defaults={'division':otherdivision})
    original_jobs=Recruitment.objects.count()
    import uuid
    from recruitment_experience.requisition_wizard import SECTIONS
    newdata={'title':'Synthetic approved vacancy','division':division.pk,'employer':job.company_id_id,'openings':2,'reason':'Synthetic vacancy approval scenario','department':'Analysis','work_location':'Dubai','employment_type':'full_time','hire_reason':'new','approver':admin.pk,'assignment_director':admin.pk,'jd_text':'A synthetic vacancy with clear responsibilities and requirements.','jd_reviewed':'on','kpa_outcomes':'Deliver documented outcomes and maintain accurate reviewed reports.','kpa_measures':'Monthly report reviewed by the manager','kpa_timeframe':'Within the first 90 days','salary_min':'8000','salary_max':'12000','salary_currency':'AED','salary_period':'month','salary_basis':'gross','annual_budget':'350000','budget_notes':'Synthetic total for two openings','confirm':'on','creation_token':str(uuid.uuid4())}
    req=None
    for section in range(1,6):
        values={k:v for k,v in newdata.items() if k in SECTIONS[section]}
        values.update(section=section,expected_version=req.version if req else 1,creation_token=newdata['creation_token'],action='submit' if section==5 else 'next')
        response=manager.post(url('workspace-requisition-edit',req.pk) if req else url('workspace-requisition-new'),values)
        assert response.status_code==302,(section,response.status_code,response.content.decode()[:100])
        req=Requisition.objects.get(title=newdata['title'])
    check(response.status_code==302 and req.status=='pending','new vacancy requisition submitted through saved wizard')
    check(manager.post(url('workspace-requisition-decide',req.pk),{'decision':'approved','confirm':'yes'}).status_code==403,'requester cannot approve requisition')
    check(a.post(url('workspace-requisition-decide',req.pk),{'decision':'approved','confirm':'yes','expected_version':req.version}).status_code==302,'named approver confirms requisition')
    check(Recruitment.objects.count()==original_jobs,'approval alone does not publish or create a job')
    req.refresh_from_db()
    check(a.post(url('workspace-requisition-assign',req.pk),{'ta_owner':admin.pk,'expected_version':req.version,'confirm':'on'}).status_code==302,'Director assigns one TA after CEO approval')
    payload={'title':'Synthetic approved vacancy','company_id':job.company_id_id,'open_positions':[position.pk],'vacancy':99,'description':'A synthetic vacancy with clear responsibilities.','start_date':str(timezone.localdate()),'end_date':str(timezone.localdate()+timedelta(days=40)),'optional_resume':''}
    req.refresh_from_db();payload['expected_version']=req.version
    response=a.post(url('workspace-vacancy-new')+'?requisition='+str(req.pk)+'&section=setup',payload)
    assert response.status_code==302
    req.refresh_from_db()
    response=a.post(url('workspace-vacancy-new')+'?requisition='+str(req.pk)+'&section=review',{'expected_version':req.version,'confirm':'yes'})
    check(response.status_code==302,'approved requisition becomes a draft vacancy')
    req.refresh_from_db();created=req.job
    check(created and created.vacancy==2 and not created.is_published,'approved headcount used and new job remains unpublished')
    a.post(url('workspace-vacancy-new')+'?requisition='+str(req.pk),payload)
    check(Recruitment.objects.count()==original_jobs+1,'repeated prepare cannot duplicate vacancy')
    response=a.post(url('workspace-publish',created.pk),{'action':'publish','confirm':'on'})
    check(response.status_code==302 and Recruitment.objects.get(pk=created.pk).is_published,'completed publication checklist publishes approved vacancy')
    check(a.get(url('workspace-offer',candidate.pk)).status_code==200,'offer outcome screen renders')
    check(a.post(url('workspace-offer',candidate.pk),{'outcome':'joined','date':str(timezone.localdate()),'evidence':'Synthetic invalid jump','confirm':'on'}).status_code==200,'offer cannot skip to joined')
    scoped=roles['outsider'];DivisionAccess.objects.create(user=scoped,division=division,role='recruiter')
    restricted=client(scoped)
    check(restricted.get(url('workspace-candidate',candidate.pk)).status_code==200,'division recruiter can open permitted application')
    if otherjob:check(restricted.get(url('workspace-job',otherjob.pk)).status_code==404,'division recruiter denied another division direct job')
    check(restricted.get(url('recruitment-view')).status_code==403,'division restriction cannot bypass through legacy tools')
    check(not NotificationDelivery.objects.filter(status='sent').exists(),'unconnected delivery never claims sent')
    check(manager.post(url('workspace-offer',candidate.pk),{}).status_code==403,'manager cannot record offer outcomes')
    check(Recruitment.objects.get(pk=job.pk).company_id_id==job.company_id_id,'existing legal employer preserved')
    transaction.set_rollback(True)
finally:
 for name in media:
    from django.core.files.storage import default_storage
    default_storage.delete(name)
print('EXPERIENCE_WORKFLOW_PASSED', len(checks), 'checks; synthetic database changes rolled back', flush=True)
