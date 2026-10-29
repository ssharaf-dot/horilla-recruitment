"""Staging-only workflow/authorization regression; all test rows roll back."""
import os,secrets,json
from pathlib import Path
from unittest.mock import patch
from datetime import timedelta
os.environ.setdefault('DJANGO_SETTINGS_MODULE','horilla.settings')
import django;django.setup()
from django.conf import settings
from django.contrib.auth.models import User,Permission
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from recruitment.models import Recruitment
from recruitment_experience.models import Requisition,Division,DivisionAccess,JDDraft,JDProviderConfig,WorkflowEvent
from recruitment_experience.jd import cipher
from employee.models import Employee,EmployeeWorkInformation
assert settings.DATABASES['default']['NAME']=='horilla_staging','STAGING ONLY'
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
checks=[];exports={};files=[];suffix=secrets.token_hex(5)
def check(v,label):
 assert v,label
 checks.append(label);print('PASS',label,flush=True)
def url(name,*args):return reverse(name,args=args)
def client(user=None,csrf=False):
 c=Client(HTTP_X_FORWARDED_PROTO='https',enforce_csrf_checks=csrf)
 if user:c.force_login(user)
 return c
try:
 with transaction.atomic():
  admin=User.objects.get(username='staging_admin');a=client(admin)
  job=Recruitment.objects.filter(is_active=True).first();position=job.open_positions.first();division=Division.objects.first()
  people={}
  for role in ['manager','ceo','director','ta','other_ta','other_director','outsider']:
   u=User.objects.create_user(username='req_'+role+suffix,password=secrets.token_urlsafe(32));User.objects.filter(pk=u.pk).update(is_new_employee=False)
   e=Employee.objects.create(employee_user_id=u,employee_first_name='Demo '+role,email=role+suffix+'@example.invalid',phone='0500000000')
   w,_=EmployeeWorkInformation.objects.get_or_create(employee_id=e);EmployeeWorkInformation.objects.filter(pk=w.pk).update(company_id=job.company_id,department_id=position.department_id,job_position_id=position)
   people[role]=u
  people['ceo'].user_permissions.add(Permission.objects.get(codename='approve_hiringrequest'),Permission.objects.get(codename='view_hiringoverview'))
  for role in ['director','other_director']:people[role].user_permissions.add(Permission.objects.get(codename='approve_offer'))
  for role in ['ta','other_ta']:people[role].user_permissions.add(Permission.objects.get(codename='view_recruitment'))
  job.recruitment_managers.add(people['manager'].employee_get)
  cs={role:client(u) for role,u in people.items()};manager=cs['manager'];ceo=cs['ceo'];director=cs['director'];ta=cs['ta']
  new=url('workspace-requisition-new')
  check(client().get(new).status_code==302,'anonymous cannot create requisition')
  check(cs['outsider'].get(new).status_code==403,'unassigned outsider cannot create requisition')
  check(cs['director'].get(new).status_code==403,'limited Director cannot create hiring package')
  check(client(people['manager'],True).post(new,{}).status_code==403,'CSRF rejects forged draft submission')
  from decimal import Decimal
  from django.utils import timezone
  from base.models import JobPosition,Company
  from recruitment_experience.models import VacancyProfile
  from recruitment_experience.requisition_wizard import revision
  from recruitment_experience.requisition_handoffs import approved_valid
  from recruitment_experience.requisition_registration import setup_current
  from recruitment_experience.requisitions import step_for,decorate_request
  req=Requisition.objects.create(title='Synthetic Handoff Analyst '+suffix,division=division,employer=job.company_id,openings=2,department='Commercial',grade='Professional',work_location='Dubai',employment_type='full_time',hire_reason='new',reason='Synthetic need for portfolio reporting.',jd_text='Prepare property reports, research commercial markets and present reviewed findings to the team.',kpa_text='Deliver accurate monthly reports, reviewed by the manager at the end of each month.',jd_reviewed=True,salary_min=Decimal('8000'),salary_max=Decimal('12000'),salary_basis='gross',annual_budget=Decimal('350000'),requested_by=people['manager'],approver=people['ceo'],assignment_director=people['director'],status='pending',submitted_at=timezone.now(),wizard_step=5,resume_section=5)
  revision(req,people['manager'],'submitted');detail=url('workspace-requisition-detail',req.pk);review=url('workspace-requisition-review',req.pk);assign=url('workspace-requisition-assignment',req.pk);correction=url('workspace-requisition-correction',req.pk);vacancy=url('workspace-vacancy-new')+'?requisition='+str(req.pk)
  check(b'Read-only status view' in manager.get(detail).content,'requester has observer status while CEO acts')
  check(b'Review package &amp; decide' in ceo.get(detail).content,'CEO status links to dedicated review')
  exports['handoff-review']=ceo.get(review).content.decode()
  exports['handoff-decision']=ceo.get(review+'?section=decision').content.decode()
  exports['handoff-ceo-edit']=ceo.get(url('workspace-requisition-ceo-edit',req.pk)).content.decode()
  check(ceo.get(review).status_code==200 and b'Prepare property reports' in ceo.get(review).content,'CEO sees package before the decision controls')
  check(manager.get(review).status_code==403,'requester cannot enter the CEO decision workspace')
  check(director.get(assign).status_code==302,'assignment cannot begin before CEO approval')
  bad=dict(expected_version=req.version,decision='changes',confirm='yes',note='')
  response=ceo.post(review+'?section=decision',bad);check(response.status_code==200 and b'Explain the reason' in response.content,'inline decision validation explains required return reason')
  check(ceo.post(review+'?section=decision',dict(bad,decision='approved',expected_version=0)).status_code==200,'stale CEO decision stays on screen without approval')
  check(ceo.post(review+'?section=decision',dict(bad,decision='approved')).status_code==302,'CEO approval hands to the Director')
  req.refresh_from_db();check(approved_valid(req),'recorded approval matches decimal values after database reload')
  check(b'Assign recruiter &amp; unlock Step 3' in director.get(detail).content,'Director receives a visible assignment action')
  check(director.get(assign).status_code==200 and b'eligible recruiter' in director.get(assign).content,'Director sees eligible staff and scoped assignment form')
  check(manager.post(assign,dict(expected_version=req.version,ta_owner=people['ta'].pk,confirm='on')).status_code==403,'requester cannot impersonate assignment Director')
  check(director.post(assign,dict(expected_version=req.version,ta_owner=people['ta'].pk,confirm='on')).status_code==302,'Director assigns the first TA')
  req.refresh_from_db();version=req.version
  check(director.post(assign,dict(expected_version=version,ta_owner=people['ta'].pk,confirm='on')).status_code==200,'no-op reassignment reports that ownership did not change')
  req.refresh_from_db();check(req.version==version,'no-op assignment does not create a new milestone')
  check(a.get(vacancy).status_code==403,'administrator cannot skip registration ownership as an unassigned TA')
  page=ta.get(vacancy);check(page.status_code==200 and b'multiple' not in page.content.split(b'name="open_positions"')[1].split(b'>')[0],'one approved role uses a single position selector')
  fields=dict(open_positions=position.pk,start_date=str(timezone.localdate()),end_date=str(timezone.localdate()+timedelta(days=30)),expected_version=req.version)
  check(ta.post(vacancy+'&section=setup',dict(fields,end_date=str(timezone.localdate()-timedelta(days=1)))).status_code==200,'expired recruitment closing date is blocked')
  foreign=Company.objects.create(company='Synthetic foreign employer '+suffix)
  foreign_position=JobPosition.objects.create(job_position='Foreign mapping '+suffix,department_id=position.department_id);foreign_position.company_id.add(foreign)
  check(ta.post(vacancy+'&section=setup',dict(fields,open_positions=foreign_position.pk)).status_code==200,'another employers explicit position mapping is rejected')
  check(ta.post(vacancy+'&section=setup',fields).status_code==302,'assigned TA saves the first setup')
  req.refresh_from_db();check(setup_current(req),'saved setup is bound to approval version recruiter and assignment')
  response=ta.get(vacancy);check(str(position).encode() in response.content and b'CV required' in response.content and b'Unpublished draft' in response.content,'review shows actual position CV requirement and publication outcome')
  exports['handoff-assignment']=director.get(assign).content.decode()
  exports['handoff-registration-review']=response.content.decode()
  newowner=people['other_ta'];newclient=cs['other_ta']
  check(director.post(assign,dict(expected_version=req.version,ta_owner=newowner.pk,confirm='on')).status_code==200,'changing an existing TA requires a reason')
  check(director.post(assign,dict(expected_version=req.version,ta_owner=newowner.pk,confirm='on',reason='Synthetic workload rebalance.')).status_code==302,'Director can reassign with a recorded reason')
  req.refresh_from_db();check(not setup_current(req) and req.vacancy_setup['open_positions']==[position.pk],'reassignment retains previous setup but invalidates its review')
  check(ta.get(vacancy).status_code==403,'previous TA cannot create a vacancy after reassignment')
  check(newclient.get(vacancy+'&section=review').status_code==302,'new TA must return to Step 3A instead of inheriting an unchecked review')
  check(b'earlier entries are shown' in newclient.get(vacancy).content,'new TA sees why the setup needs another review')
  fields['expected_version']=req.version;newclient.post(vacancy+'&section=setup',fields);req.refresh_from_db();check(setup_current(req),'new TA confirms the setup against their assignment')
  User.objects.filter(pk=newowner.pk).update(is_active=False);req.refresh_from_db()
  check(step_for(req)==2 and decorate_request(req,people['director']).viewer_acts,'unavailable TA returns the task to the Director for reassignment')
  User.objects.filter(pk=newowner.pk).update(is_active=True);req.refresh_from_db()
  original_jd=req.jd_text;req.jd_text+=' Unapproved change.';req.save(update_fields=['jd_text'])
  check(not approved_valid(req) and newclient.get(vacancy).status_code==403,'changed package cannot reuse an earlier approval for registration')
  req.jd_text=original_jd;req.save(update_fields=['jd_text'])
  check(manager.get(correction).status_code==403,'observer cannot invalidate an approval')
  response=newclient.post(correction,dict(expected_version=req.version,reason='Need to clarify the approved reporting responsibilities.',confirm='on'));check(response.status_code==302,'assigned TA can return incorrect approved content for correction')
  req.refresh_from_db();check(req.status=='changes' and not req.approved_version and not req.ta_owner_id and not req.assigned_at,'correction requires fresh approval and assignment')
  check(req.revisions.filter(kind='ceo_approved').exists() and req.revisions.filter(kind='correction_requested').exists(),'handback retains earlier approval and the correcting actors version')
  check(newclient.post(vacancy+'&section=review',dict(expected_version=req.version,confirm='yes')).status_code==403,'previous setup cannot create a vacancy during correction')
  check(b'Latest decision / correction instructions' in manager.get(detail).content,'correction instructions are not mislabelled as a CEO decision')
  # Resubmission is the requester action; repeat the existing verified Step 1E.
  response=manager.post(url('workspace-requisition-edit',req.pk),dict(section=5,expected_version=req.version,action='submit',approver=people['ceo'].pk,assignment_director=people['director'].pk,confirm='on'));check(response.status_code==302,'corrected package resubmits through Step 1E')
  req.refresh_from_db();ceo.post(review+'?section=decision',dict(expected_version=req.version,decision='approved',confirm='yes'));req.refresh_from_db()
  check(approved_valid(req),'fresh CEO approval authorizes the corrected version')
  director.post(assign,dict(expected_version=req.version,ta_owner=newowner.pk,confirm='on'));req.refresh_from_db()
  check(not setup_current(req),'new approval does not reuse the earlier setup confirmation')
  fields['expected_version']=req.version;newclient.post(vacancy+'&section=setup',fields);req.refresh_from_db()
  newclient.post(vacancy+'&section=review',dict(expected_version=req.version,confirm='yes'));req.refresh_from_db()
  check(req.job_id is not None and not req.job.is_published,'end-to-end rework creates exactly one unpublished vacancy')
  check(manager.get(url('workspace-job',req.job_id)).status_code==200,'original requester can follow the registered vacancy as its hiring manager')
  check(director.get(url('workspace-job',req.job_id)).status_code==404,'assignment Director gains no applicant access from assigning a recruiter')
  profile=VacancyProfile.objects.get(job=req.job);check(profile.location=='Dubai' and profile.work_type=='full_time','registration carries approved location and supported employment type')
  check(newclient.get(correction).status_code==403,'registered vacancies cannot be unlinked by the pre-registration correction route')
  editjob=url('workspace-vacancy-edit',req.job.pk)
  newclient.post(editjob,dict(title='FORGED TITLE',vacancy=99,description='FORGED JD',open_positions=position.pk,start_date=fields['start_date'],end_date=fields['end_date']))
  created=Recruitment.objects.get(pk=req.job_id);check(created.title==req.title and created.vacancy==req.openings and 'FORGED' not in created.description,'generic vacancy editor cannot bypass approved role JD or headcount')
  exports['handoff-complete']=newclient.get(detail).content.decode()
  Path('/tmp/handoff-staging-renders.json').write_text(json.dumps(exports))
  transaction.set_rollback(True)
finally:
 from django.core.files.storage import default_storage
 for file in files:default_storage.delete(file)
print('HANDOFF_WORKFLOW_STAGING_VERIFIED',len(checks),flush=True)
