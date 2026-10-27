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
  payload=dict(title='Synthetic Property Analyst '+suffix,division=division.pk,employer=job.company_id_id,openings=2,reason='Synthetic role for testing staffing approvals.',expected_version=1,action='draft')
  check(manager.post(new,payload).status_code==302,'manager saves Step 1 draft without JD or approval owners')
  req=Requisition.objects.get(title=payload['title']);detail=url('workspace-requisition-detail',req.pk);edit=url('workspace-requisition-edit',req.pk)
  check(req.status=='draft' and req.submitted_at is None and not req.job_id,'draft creates no vacancy or approval milestone')
  exports['requisition-draft']=manager.get(detail).content.decode()
  check(ceo.get(detail).status_code==404,'unassigned CEO cannot read another request')
  check(cs['other_director'].get(detail).status_code==404,'unassigned Director cannot read another request')
  response=manager.post(edit,dict(payload,action='submit',approver=people['ceo'].pk,assignment_director=people['director'].pk,confirm='on'))
  req.refresh_from_db();check(response.status_code==200 and req.status=='draft','submission blocked without JD and KPA')
  body='Responsibilities: prepare market analysis and support leasing decisions. Requirements: commercial analysis experience.'
  kpa='Produce accurate monthly market reports and maintain reviewed leasing forecasts on agreed dates.'
  good=dict(payload,action='submit',jd_text=body,kpa_text=kpa,approver=people['ceo'].pk,assignment_director=people['director'].pk,confirm='on')
  check(manager.post(edit,dict(good,approver=people['manager'].pk)).status_code==200,'requester cannot select self as CEO approver')
  check(manager.post(edit,dict(good,confirm='')).status_code==200,'review confirmation required before submission')
  check(manager.post(edit,good).status_code==302,'reviewed JD and KPA submitted to CEO')
  req.refresh_from_db();check(req.status=='pending' and req.submitted_at and req.version==2,'submission timestamp and revision recorded')
  check(manager.post(edit,dict(good,jd_text='changed')).status_code==403,'submitted package immutable to requester')
  check(director.post(url('workspace-requisition-assign',req.pk),{'ta_owner':people['ta'].pk,'expected_version':req.version,'confirm':'on'}).status_code==302,'premature assignment handled without write')
  req.refresh_from_db();check(req.ta_owner_id is None,'TA assignment blocked before CEO approval')
  check(ta.get(url('workspace-vacancy-new')+'?requisition='+str(req.pk)).status_code==404,'registration blocked before approval')
  dec=url('workspace-requisition-decide',req.pk)
  check(manager.post(dec,dict(decision='approved',confirm='yes',expected_version=req.version)).status_code==403,'requester cannot approve staffing need')
  ceo.post(dec,dict(decision='changes',confirm='yes',expected_version=req.version));req.refresh_from_db()
  check(req.status=='pending','return for changes requires reason')
  ceo.post(dec,dict(decision='changes',confirm='yes',expected_version=req.version,note='Clarify expected performance measures.'));req.refresh_from_db()
  check(req.status=='changes' and req.decided_at,'CEO can return package with timestamped rework reason')
  exports['requisition-rework']=manager.get(edit).content.decode()
  check(manager.post(edit,dict(good,expected_version=1)).status_code==200,'stale edit cannot overwrite returned package')
  manager.post(edit,dict(good,expected_version=req.version,kpa_text=kpa+' Report accuracy target to be confirmed with the manager.'));req.refresh_from_db()
  check(req.status=='pending' and not req.decided_at,'resubmission clears current decision while retaining history')
  exports['requisition-ceo']=ceo.get(detail).content.decode()
  ceo.post(dec,dict(decision='approved',confirm='yes',expected_version=1));req.refresh_from_db()
  check(req.status=='pending','stale CEO decision cannot progress requisition')
  ceo.post(dec,dict(decision='approved',confirm='yes',expected_version=req.version));req.refresh_from_db()
  check(req.status=='approved' and req.decided_at and not req.ta_owner_id,'CEO approval does not assign a TA or create vacancy')
  check(ta.get(url('workspace-vacancy-new')+'?requisition='+str(req.pk)).status_code==403,'CEO approval alone cannot bypass Director assignment')
  check(cs['other_director'].post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['ta'].pk,expected_version=req.version,confirm='on')).status_code==404,'other Director cannot assign unassigned requisition')
  exports['requisition-director']=director.get(detail).content.decode()
  director.post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['manager'].pk,expected_version=req.version,confirm='on'));req.refresh_from_db()
  check(not req.ta_owner_id,'manager cannot be forged into eligible HR TA choice')
  director.post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['ta'].pk,expected_version=req.version,confirm='on'));req.refresh_from_db()
  check(req.ta_owner_id==people['ta'].pk and req.assigned_by_id==people['director'].pk and req.assigned_at,'Director assigns one eligible TA with timestamp')
  check(cs['other_ta'].get(url('workspace-vacancy-new')+'?requisition='+str(req.pk)).status_code==403,'unassigned HR user cannot register another TA request')
  exports['requisition-ready']=ta.get(detail).content.decode()
  vacancy=url('workspace-vacancy-new')+'?requisition='+str(req.pk)
  response=ta.get(vacancy);check(response.status_code==200 and body.encode() in response.content,'Step 3 inherits approved JD')
  fields=dict(title='FORGED TITLE',company_id=job.company_id_id,open_positions=[position.pk],vacancy=99,description='<script>FORGED</script>',start_date=str(timezone.localdate()),end_date=str(timezone.localdate()+timedelta(days=30)))
  check(ta.post(vacancy,fields).status_code==302,'assigned TA registers approved need')
  req.refresh_from_db();check(req.job.title==req.title and req.job.vacancy==req.openings and req.job.company_id_id==req.employer_id and req.job.description==body,'forged title employer openings and JD ignored at registration')
  check(not req.job.is_published and req.registered_at,'registration records timestamp and draft publication state')
  count=Recruitment.objects.count();ta.post(vacancy,fields);check(Recruitment.objects.count()==count,'duplicate registration cannot create second vacancy')
  check(req.job.recruitment_managers.filter(pk=people['ta'].employee_get.pk).exists(),'assigned TA attached to resulting vacancy team')
  check(people['ta'].get_all_permissions()==User.objects.get(pk=people['ta'].pk).get_all_permissions(),'assignment does not grant additional role permissions')
  check(req.activity_events.filter(kind='requisition_decision').count()==2 and req.activity_events.filter(kind='requisition_assignment').exists() and req.activity_events.filter(kind='requisition_decision',detail__contains='Clarify expected performance').exists(),'rework approval and assignment history retained')
  check(not any(body in str(e.metadata) or kpa in str(e.metadata) for e in req.activity_events.all()),'JD and KPA bodies excluded from event metadata')
  exports['requisition-complete']=ta.get(detail).content.decode()
  # Real PDF path, protected download and uploaded-only package.
  import fitz
  pdf=fitz.open();pdf.new_page().insert_text((72,72),'Synthetic JD and KPA for staging only.');raw=pdf.tobytes();pdf.close()
  documents=dict(payload,title='Synthetic PDF package '+suffix,action='submit',approver=people['ceo'].pk,assignment_director=people['director'].pk,confirm='on',jd_document=SimpleUploadedFile('jd.pdf',raw,content_type='application/pdf'),kpa_document=SimpleUploadedFile('kpa.pdf',raw,content_type='application/pdf'))
  check(manager.post(new,documents).status_code==302,'reviewed PDF JD and KPA can be submitted instead of text')
  pdfreq=Requisition.objects.get(title=documents['title']);files.extend([pdfreq.jd_document.name,pdfreq.kpa_document.name])
  docurl=url('workspace-requisition-document',pdfreq.pk,'jd')
  check(ceo.get(docurl).status_code==200,'assigned CEO can download private JD attachment')
  check(cs['other_director'].get(docurl).status_code==404,'unassigned Director cannot download attachment')
  check(client().get(docurl).status_code==302,'anonymous attachment download requires staff login')
  check(b'<script>' not in ceo.get(url('workspace-requisition-detail',pdfreq.pk)).content,'attachment details cannot inject active markup')
  bad=dict(payload,title='Bad PDF '+suffix,jd_document=SimpleUploadedFile('bad.pdf',b'<script>fake</script>',content_type='application/pdf'))
  check(manager.post(new,bad).status_code==200 and not Requisition.objects.filter(title=bad['title']).exists(),'fake PDF rejected before storing requisition')
  # AI before vacancy, no external network. Shared quota remains across both parents.
  draft=Requisition.objects.create(title='Synthetic AI role '+suffix,division=division,employer=job.company_id,openings=1,reason='Testing pre-approval JD',requested_by=people['manager'])
  aiurl=url('workspace-requisition-jd',draft.pk)
  JDProviderConfig.objects.update_or_create(pk=1,defaults={'enabled':False,'encrypted_key':''})
  aipayload={'brief':'Analyze commercial requirements and produce monthly reports.','consent':'on','expected_version':draft.version}
  with patch('recruitment_experience.requisitions.generate') as api:
   check(manager.post(aiurl,aipayload).status_code==200 and not api.called,'disconnected AI sends no external request')
  JDProviderConfig.objects.filter(pk=1).update(enabled=True,encrypted_key=cipher().encrypt(b'synthetic-never-transmitted-key').decode())
  cache.delete('jd-draft:'+str(people['manager'].pk))
  with patch('recruitment_experience.requisitions.generate',return_value=(body,'mock-model')):
   check(manager.post(aiurl,aipayload).status_code==302,'AI draft can be generated before a vacancy exists')
  generated=JDDraft.objects.get(requisition=draft);check(generated.job_id is None and generated.status=='draft','AI output remains draft for requisition review')
  review=url('workspace-requisition-jd-review',draft.pk,generated.pk)
  exports['requisition-jd-review']=manager.get(review).content.decode()
  check(manager.post(review,dict(text=body,expected_version=draft.version,confirm='on')).status_code==302,'human can apply reviewed AI JD to editable requisition')
  draft.refresh_from_db();check(draft.jd_text==body and draft.status=='draft' and not draft.job_id,'AI cannot submit approve or publish staffing request')
  check(cs['director'].get(aiurl).status_code==404,'Director cannot draft unassigned request')
  for tab in ['plan','review','registration']:
   r=a.get(url('workspace-area','requisitions'),{'tab':tab});check(r.status_code==200 and r.content.count(b'class="wx-req-step ')==3,'three visible wizard steps on '+tab)
   exports['requisition-area-'+tab]=r.content.decode()
  exports['requisition-new']=manager.get(new).content.decode()
  Path('/tmp/requisition-staging-renders.json').write_text(json.dumps(exports))
  transaction.set_rollback(True)
finally:
 from django.core.files.storage import default_storage
 for file in files:default_storage.delete(file)
print('REQUISITION_WORKFLOW_STAGING_VERIFIED',len(checks),flush=True)
