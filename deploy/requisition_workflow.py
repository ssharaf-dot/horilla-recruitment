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
  import uuid,re,html
  from recruitment_experience.requisition_wizard import SECTIONS,OUTLINE,SUGGESTIONS,missing
  def hidden(response,key):
   match=re.search('name="'+key+'"[^>]*value="([^"]*)"',response.content.decode());assert match,key
   return html.unescape(match[1])
  token=hidden(manager.get(new),'creation_token')
  check(manager.get(new).content.count(b'Level 3')==1,'new request has third-level section ribbon')
  check(b'STEP 1A' in manager.get(new).content,'first screen identifies Step 1A')
  payload=dict(title='Synthetic Property Analyst '+suffix,creation_token=token,section=1,expected_version=1,action='close')
  check(manager.post(new,payload).status_code==302,'role title alone saves a resumable partial draft')
  req=Requisition.objects.get(title=payload['title']);edit=url('workspace-requisition-edit',req.pk);detail=url('workspace-requisition-detail',req.pk)
  check(req.status=='draft' and req.division_id is None and req.openings is None,'partial draft does not invent employer headcount or approval')
  count=Requisition.objects.count();manager.post(new,payload);check(Requisition.objects.count()==count,'retried first checkpoint reuses its creation token')
  check(manager.get(edit).status_code==200,'requester can resume own incomplete draft')
  check(ceo.get(detail).status_code==404 and cs['other_director'].get(detail).status_code==404,'unassigned leaders cannot read private request')
  check(b'STEP 1A' in manager.get(edit,{'section':5}).content,'URL cannot skip unsaved wizard sections')
  base=dict(title=req.title,division=division.pk,employer=job.company_id_id,openings=2,reason='Synthetic need for commercial analysis and leasing support.',department='Commercial analysis',grade='Professional',work_location='Dubai',employment_type='full_time',hire_reason='new')
  def save(section,values,action='next',version=None):
   req.refresh_from_db();r=manager.post(edit,dict(values,section=section,expected_version=req.version if version is None else version,action=action));req.refresh_from_db();return r
  check(save(1,base,version=99).status_code==200 and req.wizard_step==1,'stale checkpoint preserves saved version')
  check(save(1,base).status_code==302 and req.resume_section==2,'Next saves role details and opens JD')
  check(b'STEP 1B' in manager.get(edit).content,'resume returns to last unfinished section')
  jdpage=manager.get(edit).content
  check(all(('data-template=' in jdpage.decode(),b'Insert suggested template' in jdpage,b'placeholder="We are seeking' in jdpage)),'visible JD placeholders and accessible template buttons available')
  check(all(label.encode() in jdpage for label in OUTLINE.values()),'structured JD covers responsibilities skills prerequisites and education')
  check(save(2,{},'next').status_code==200 and req.wizard_step==2,'blank JD cannot advance')
  check(save(2,{k:SUGGESTIONS[k] for k in OUTLINE},'build_jd').status_code==302,'template builds a draft preview')
  check(save(2,{'jd_text':req.jd_text,'jd_reviewed':'on'}).status_code==200 and req.wizard_step==2,'unresolved template prompts cannot pass checkpoint')
  body='Role summary\nPrepare commercial property analysis.\n\nResponsibilities\nProduce monthly market reports and support leasing decisions.\n\nRequired skills\nCommercial analysis and clear reporting.\n\nExperience and prerequisites\nPractical property research experience.\n\nEducation or equivalent experience\nRelevant qualification or equivalent professional experience.'
  check(save(2,{'jd_text':body,'jd_reviewed':'on'}).status_code==302 and req.jd_reviewed,'human-reviewed JD advances to success measures')
  kpa=dict(kpa_outcomes='Prepare accurate monthly market reports and leasing forecasts.',kpa_measures='Manager reviews accuracy and completeness each month.',kpa_timeframe='First report within 30 days; review at 90 days.')
  check(save(3,kpa).status_code==302 and req.resume_section==4,'structured outcomes measures and timeframe save together')
  budget=dict(salary_min='8000',salary_max='12000',salary_currency='AED',salary_period='month',salary_basis='gross',annual_budget='350000',budget_notes='Two openings, fixed allowances, employer costs and contingencies.',target_start_date=str(timezone.localdate()+timedelta(days=60)))
  check(save(4,dict(budget,salary_max='6000')).status_code==200,'inverted salary range blocked')
  check(save(4,dict(budget,annual_budget='12000')).status_code==200,'total budget must cover all openings across 12 months')
  check(save(4,budget).status_code==302 and req.resume_section==5,'internal salary and total budget save before review')
  owners=dict(approver=people['ceo'].pk,assignment_director=people['director'].pk,confirm='on')
  check(save(5,dict(owners,approver=people['manager'].pk),'submit').status_code==200,'requester cannot approve own need')
  check(save(5,dict(owners,confirm=''),'submit').status_code==200,'complete package requires explicit submission confirmation')
  check(save(5,owners,'submit').status_code==302 and req.status=='pending','saved package submits to named CEO')
  check(req.submitted_at and req.revisions.count()==1 and req.revisions.first().snapshot['jd_text']==body,'submitted version snapshot and timestamp retained')
  submitted=req.revisions.first();exports['wizard-ceo']=ceo.get(detail).content.decode()
  check(manager.post(edit,dict(base,section=1,expected_version=req.version)).status_code==403,'requester cannot edit while CEO owns review')
  check(director.post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['ta'].pk,expected_version=req.version,confirm='on')).status_code==302,'premature Director assignment handled safely')
  req.refresh_from_db();check(not req.ta_owner_id,'CEO decision required before assignment')
  dec=url('workspace-requisition-decide',req.pk);ceoedit=url('workspace-requisition-ceo-edit',req.pk)
  check(manager.get(ceoedit).status_code==403,'requester cannot use CEO editor')
  check(ceo.get(ceoedit).status_code==200,'named CEO can edit the hiring package')
  ceo.post(dec,dict(decision='changes',expected_version=req.version,confirm='yes'));req.refresh_from_db();check(req.status=='pending','return requires explanation')
  ceo.post(dec,dict(decision='declined',expected_version=req.version,confirm='yes'));req.refresh_from_db();check(req.status=='pending','rejection requires explanation')
  ceo.post(dec,dict(decision='changes',expected_version=req.version,confirm='yes',note='Clarify the 90-day outcomes.'));req.refresh_from_db()
  check(req.status=='changes' and req.resume_section==5 and req.revisions.count()==2,'return unlocks review with reason and retained submitted version')
  exports['wizard-returned']=manager.get(edit).content.decode()
  check(save(5,owners,'submit').status_code==302 and req.status=='pending','requester resubmits returned package')
  edited=dict({**base,**budget},jd_text=body+'\nCEO clarification: quarterly portfolio forecast.',jd_reviewed='on',title='Senior Property Analyst '+suffix,grade='Senior professional',salary_min='9000',salary_max='13000',annual_budget='380000',expected_version=req.version,decision='approved',confirm='yes',note='Adjusted scope and proposed budget.')
  check(ceo.post(ceoedit,dict(edited,expected_version=1)).status_code==200,'stale CEO editor cannot overwrite submitted package')
  check(ceo.post(ceoedit,edited).status_code==302,'CEO can edit and approve forward in one decision')
  req.refresh_from_db();check(req.status=='approved' and req.approved_version==req.version and req.title==edited['title'] and str(req.salary_max)=='13000.00','exact edited package approved without requester resubmission')
  check(submitted.snapshot['jd_text']==body and req.revisions.first().snapshot['jd_text']==edited['jd_text'],'before and after snapshots preserve CEO modifications')
  check(b'Before' in ceo.get(detail).content and b'After' in ceo.get(detail).content,'detail shows meaningful version comparison')
  check(ta.get(url('workspace-vacancy-new')+'?requisition='+str(req.pk)).status_code==403,'CEO approval alone cannot bypass named Director assignment')
  check(cs['other_director'].post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['ta'].pk,expected_version=req.version,confirm='on')).status_code==404,'other Director cannot assign request')
  exports['wizard-director']=director.get(detail).content.decode()
  director.post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['manager'].pk,expected_version=req.version,confirm='on'));req.refresh_from_db();check(not req.ta_owner_id,'assignment cannot promote manager into recruiter role')
  director.post(url('workspace-requisition-assign',req.pk),dict(ta_owner=people['ta'].pk,expected_version=req.version,confirm='on'));req.refresh_from_db()
  check(req.ta_owner_id==people['ta'].pk and req.assigned_at and req.assigned_by_id==people['director'].pk,'Director assigns one eligible TA with timestamp')
  check(cs['other_ta'].get(url('workspace-vacancy-new')+'?requisition='+str(req.pk)).status_code==403,'another TA cannot register request')
  vacancy=url('workspace-vacancy-new')+'?requisition='+str(req.pk)
  response=ta.get(vacancy);check(response.status_code==200 and b'3A' in response.content and b'3B' in response.content and b'wx-req-flow' in response.content,'registration stays in Work Area 1 with two visible sections')
  exports['wizard-registration']=response.content.decode()
  fields=dict(open_positions=[position.pk],start_date=str(timezone.localdate()),end_date=str(timezone.localdate()+timedelta(days=30)),expected_version=req.version,title='FORGED TITLE',vacancy=99,description='<script>FORGED</script>')
  count=Recruitment.objects.count()
  check(ta.post(vacancy+'&section=setup',fields).status_code==302,'TA saves registration setup first')
  req.refresh_from_db();check(req.vacancy_setup and not req.job_id and Recruitment.objects.count()==count,'setup checkpoint creates no vacancy')
  check(b'3B' in ta.get(vacancy).content,'return resumes registration review')
  check(ta.post(vacancy+'&section=review',dict(expected_version=req.version)).status_code==200,'registration creation requires explicit confirmation')
  check(ta.post(vacancy+'&section=review',dict(expected_version=req.version,confirm='yes')).status_code==302,'TA confirms creation after saved setup')
  req.refresh_from_db();check(req.job.title==edited['title'] and req.job.vacancy==2 and req.job.company_id_id==job.company_id_id,'registered role employer headcount inherit approved package')
  check('CEO clarification' in req.job.description and '<script>' not in req.job.description,'reviewed JD transfers safely instead of forged description')
  check(not req.job.is_published and not req.job.publish_in_linkedin and req.registered_at,'registration records milestone without automatic publication')
  ta.post(vacancy+'&section=review',dict(expected_version=req.version,confirm='yes'));check(Recruitment.objects.count()==count+1,'repeated create cannot duplicate vacancy')
  check(req.job.recruitment_managers.filter(pk=people['ta'].employee_get.pk).exists(),'assigned TA attached to vacancy team')
  exports['wizard-complete']=ta.get(detail).content.decode()
  check(req.activity_events.filter(kind='requisition_decision').count()==2 and req.activity_events.filter(kind='requisition_assignment').exists(),'rework approval assignment and registration history retained')
  check(not any(body in str(e.metadata) or '380000' in str(e.metadata) for e in req.activity_events.all()),'JD and salary bodies excluded from generic event metadata')
  # Distinct edited-return and terminal rejection paths use isolated copies.
  for decision_kind in ['edited_return','reject']:
   clone=Requisition.objects.get(pk=req.pk);clone.pk=None;clone.job=None;clone.creation_token=None;clone.ta_owner=None;clone.assigned_by=None;clone.assigned_at=None;clone.registered_at=None;clone.status='pending';clone.version=1;clone.approved_version=0;clone.save()
   if decision_kind=='edited_return':
    payload2=dict(edited,expected_version=1,decision='changes',note='Please clarify the responsibilities.',jd_text=edited['jd_text']+'\nClarify the reporting responsibility.')
    check(ceo.post(url('workspace-requisition-ceo-edit',clone.pk),payload2).status_code==302,'CEO can save JD edits while returning for clarification')
    clone.refresh_from_db();check(clone.status=='changes' and clone.resume_section==5 and 'Clarify the reporting responsibility.' in clone.jd_text,'edited return preserves changes and unlocks requester review')
   else:
    ceo.post(url('workspace-requisition-decide',clone.pk),dict(expected_version=1,confirm='yes',decision='declined',note='Synthetic hiring need not approved.'))
    clone.refresh_from_db();check(clone.status=='declined' and clone.revisions.first().note=='Synthetic hiring need not approved.','rejection closes request with recorded reason')
  # Private PDF extraction requires a reviewed canonical text; no uploaded-only shortcut.
  import fitz
  pdf=fitz.open();pdf.new_page().insert_text((72,72),'Synthetic JD: prepare monthly property reports and research commercial markets.');raw=pdf.tobytes();pdf.close()
  pdfreq=Requisition.objects.create(title='Synthetic PDF '+suffix,division=division,employer=job.company_id,openings=1,requested_by=people['manager'],wizard_step=2,resume_section=2)
  pe=url('workspace-requisition-edit',pdfreq.pk)
  check(manager.post(pe,dict(section=2,expected_version=pdfreq.version,action='upload_jd',jd_document=SimpleUploadedFile('jd.pdf',raw,content_type='application/pdf'))).status_code==302,'valid PDF saved and locally extracted')
  pdfreq.refresh_from_db();files.append(pdfreq.jd_document.name)
  check('monthly property reports' in pdfreq.jd_text and not pdfreq.jd_reviewed,'extracted text stays unreviewed until human confirms')
  docurl=url('workspace-requisition-document',pdfreq.pk,'jd')
  check(manager.get(docurl).status_code==200,'requester can retrieve private supporting PDF')
  check(cs['outsider'].get(docurl).status_code in [403,404],'unassigned user cannot download PDF')
  check(client().get(docurl).status_code==302,'anonymous PDF access requires staff login')
  check(manager.post(pe,dict(section=2,expected_version=pdfreq.version,action='next',jd_text=pdfreq.jd_text)).status_code==200,'PDF extraction does not bypass reviewed-text checkpoint')
  check(manager.post(pe,dict(section=2,expected_version=pdfreq.version,action='save',jd_document=SimpleUploadedFile('fake.pdf',b'<script>fake</script>',content_type='application/pdf'))).status_code==200,'fake PDF bytes rejected')
  # AI test stays offline. The optional provider assists the same saved JD.
  draft=Requisition.objects.create(title='Synthetic AI role '+suffix,division=division,employer=job.company_id,openings=1,reason='Testing pre-approval JD',requested_by=people['manager'],wizard_step=2,resume_section=2)
  aiurl=url('workspace-requisition-jd',draft.pk)
  JDProviderConfig.objects.update_or_create(pk=1,defaults={'enabled':False,'encrypted_key':''})
  aipayload={'brief':'Analyze commercial requirements and produce monthly reports.','consent':'on','expected_version':draft.version}
  with patch('recruitment_experience.requisitions.generate') as api:
   check(manager.post(aiurl,aipayload).status_code==200 and not api.called,'disconnected AI sends no external request')
  JDProviderConfig.objects.filter(pk=1).update(enabled=True,encrypted_key=cipher().encrypt(b'synthetic-never-transmitted-key').decode())
  cache.delete('jd-draft:'+str(people['manager'].pk))
  with patch('recruitment_experience.requisitions.generate',return_value=(body,'mock-model')):check(manager.post(aiurl,aipayload).status_code==302,'AI draft can assist requisition before vacancy exists')
  generated=JDDraft.objects.get(requisition=draft);review=url('workspace-requisition-jd-review',draft.pk,generated.pk)
  check(b'Level 3' in manager.get(review).content,'AI review remains in the same section hierarchy')
  check(manager.post(review,dict(text=body,expected_version=draft.version,confirm='on')).status_code==302,'human-reviewed AI draft saves to requisition')
  draft.refresh_from_db();check(draft.jd_reviewed and draft.status=='draft' and not draft.job_id,'AI does not submit approve or publish request')
  for tab in ['plan','review','registration','history']:
   r=a.get(url('workspace-area','requisitions'),{'tab':tab});check(r.status_code==200 and r.content.count(b'class="wx-req-step ')==3,'three visible workflow steps on '+tab)
   exports['wizard-area-'+tab]=r.content.decode()
  check(b'Vacancy registered' not in a.get(url('workspace-area','requisitions'),{'tab':'registration'}).content,'completed registration leaves active Step 3 queue')
  exports['wizard-new']=manager.get(new).content.decode()
  for section in range(1,6):
   req.status='draft';req.job=None;req.wizard_step=5;req.resume_section=section;req.save()
   r=manager.get(edit);check(r.status_code==200,'wizard section renders '+str(section));exports['wizard-section-'+str(section)]=r.content.decode()
  Path('/tmp/requisition-staging-renders.json').write_text(json.dumps(exports))
  transaction.set_rollback(True)
finally:
 from django.core.files.storage import default_storage
 for file in files:default_storage.delete(file)
print('REQUISITION_WORKFLOW_STAGING_VERIFIED',len(checks),flush=True)
