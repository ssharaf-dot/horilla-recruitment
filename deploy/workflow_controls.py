"""Staging-only integration tests; all synthetic database writes are rolled back."""
import os,secrets,json
from unittest.mock import patch
from datetime import timedelta
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','horilla.settings')
import django
django.setup()
from django.conf import settings
from django.contrib.auth.models import User,Permission
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from recruitment.models import Recruitment,Candidate,Stage
from employee.models import Employee,EmployeeWorkInformation
from recruitment_experience.models import OfferApproval,JoiningPlan,JoiningTask,WorkflowEvent,JDProviderConfig,JDDraft,ApplicantAccount,ApplicantApplication
from recruitment_experience.activity import current_request
from recruitment_experience.jd import generate,cipher,digest
from recruitment_experience.workflow import TASKS
assert settings.DATABASES['default']['NAME']=='horilla_staging','STAGING ONLY'
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
checks=[];exports={};suffix=secrets.token_hex(5)
def check(value,label):
 assert value,label
 checks.append(label);print('PASS',label,flush=True)
def client(user=None,csrf=False):
 c=Client(HTTP_X_FORWARDED_PROTO='https',enforce_csrf_checks=csrf)
 if user:c.force_login(user)
 return c
def url(name,*args):return reverse(name,args=args)
with transaction.atomic():
 admin=User.objects.get(username='staging_admin');a=client(admin)
 job=Recruitment.objects.filter(is_active=True,closed=False).first();position=job.open_positions.first()
 hired=job.stage_set.filter(stage_type='hired').first();applied=job.stage_set.filter(stage_type='applied').first()
 roles={}
 for role in ['hr','director','director2','manager','outsider','leader']:
  u=User.objects.create_user(username='flow_'+role+suffix,password=secrets.token_urlsafe(32))
  User.objects.filter(pk=u.pk).update(is_new_employee=False);u.refresh_from_db()
  employee=Employee.objects.create(employee_user_id=u,employee_first_name='Synthetic '+role,email=role+suffix+'@example.invalid',phone='0500000000')
  info,_=EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
  EmployeeWorkInformation.objects.filter(pk=info.pk).update(company_id=job.company_id,department_id=position.department_id,job_position_id=position)
  roles[role]=u
 roles['hr'].user_permissions.add(Permission.objects.get(codename='view_recruitment'))
 for role in ['director','director2']:roles[role].user_permissions.add(Permission.objects.get(codename='approve_offer'))
 roles['leader'].user_permissions.add(Permission.objects.get(codename='view_hiringoverview'))
 job.recruitment_managers.add(roles['manager'].employee_get)
 hr,director,otherdirector,manager,outsider,leader=(client(roles[x]) for x in ['hr','director','director2','manager','outsider','leader'])
 candidate=Candidate.objects.create(name='Synthetic Offer Applicant',email='offer-'+suffix+'@example.invalid',mobile='0500000000',recruitment_id=job,job_position_id=position,stage_id=hired,hired=True)
 other=Candidate.objects.create(name='Synthetic Unselected Applicant',email='other-'+suffix+'@example.invalid',mobile='0500000000',recruitment_id=job,job_position_id=position,stage_id=applied)
 prepare=url('workspace-prepare-offer',candidate.pk);outcome=url('workspace-offer',candidate.pk)
 values={'director':roles['director'].pk,'role_title':'Synthetic Property Manager','monthly_salary':'10000.00','currency':'AED','proposed_joining':str(timezone.localdate()+timedelta(days=14)),'terms':'Synthetic contract and allowance reference. No real offer.','confirm':'on'}
 sent={'outcome':'sent','date':str(timezone.localdate()),'evidence':'Synthetic issuance evidence','confirm':'on'}
 response=hr.post(outcome,sent);candidate.refresh_from_db()
 check(response.status_code==200 and candidate.offer_letter_status=='not_sent','offer send blocked without Director approval')
 check(manager.post(prepare,values).status_code==403,'manager cannot prepare offer terms')
 check(leader.get(prepare).status_code==404,'aggregate leader cannot read candidate terms')
 check(outsider.get(prepare).status_code==403,'outsider cannot enter offer preparation')
 check(hr.post(url('workspace-prepare-offer',other.pk),values).status_code==200 and not OfferApproval.objects.filter(candidate=other).exists(),'unselected candidate cannot receive approval request')
 selfvalues=dict(values,director=roles['hr'].pk)
 check(hr.post(prepare,selfvalues).status_code==200 and not candidate.offer_approvals.exists(),'preparer cannot select themselves as Director')
 response=hr.post(prepare,values);item=candidate.offer_approvals.get()
 check(response.status_code==302 and item.status=='pending','HR submits immutable offer terms for Director')
 check(hr.post(prepare,values).status_code==200 and candidate.offer_approvals.count()==1,'duplicate pending request blocked')
 decision=url('workspace-offer-approval',item.pk)
 exports['approval']=director.get(decision).content.decode()
 check(director.get(decision).status_code==200,'assigned Director reads offer package')
 check(otherdirector.get(decision).status_code==403,'another Director cannot read assigned terms')
 check(manager.get(decision).status_code==403,'manager cannot read compensation terms')
 check(director.get(url('workspace-candidate',candidate.pk)).status_code==404,'Director has no general candidate-profile access')
 check(director.get(url('recruitment-dashboard')).status_code==200,'Director landing opens assigned approvals')
 check(hr.post(decision,{'decision':'approved','note':'Synthetic','confirm':'on'}).status_code==200,'preparer cannot approve offer')
 check(director.post(decision,{'decision':'declined','note':'Synthetic salary revision needed','confirm':'on'}).status_code==302,'Director can request changes')
 item.refresh_from_db();check(item.status=='declined','changes-requested decision persisted')
 check(hr.post(outcome,sent).status_code==200,'declined request still blocks offer send')
 check(hr.post(prepare,values).status_code==302,'revised offer creates new approval request')
 item=candidate.offer_approvals.order_by('-pk').first();decision=url('workspace-offer-approval',item.pk)
 check(director.post(decision,{'decision':'approved','note':'Synthetic approved terms','confirm':'on'}).status_code==302,'assigned Director approves terms')
 item.refresh_from_db();check(item.decided_at is not None and item.status=='approved','approval has decision timestamp')
 check(director.post(decision,{'decision':'declined','note':'Stale second decision','confirm':'on'}).status_code==200,'stale second decision rejected')
 item.terms='Forged revision'
 try:item.save();mutable=True
 except ValidationError:mutable=False
 check(not mutable,'submitted offer terms cannot be edited even through model save')
 item.refresh_from_db()
 check(hr.post(outcome,sent).status_code==302,'HR can record sent after approval')
 candidate.refresh_from_db();check(candidate.offer_letter_status=='sent','sent outcome recorded separately')
 joinurl=url('workspace-joining',candidate.pk)
 check(hr.post(joinurl,{'confirm':'yes'}).status_code==200 and not JoiningPlan.objects.filter(candidate=candidate).exists(),'joining checklist blocked before acceptance')
 check(hr.post(outcome,dict(sent,outcome='accepted')).status_code==302,'HR records actual acceptance')
 check(hr.post(joinurl,{'confirm':'yes'}).status_code==302,'accepted candidate starts joining plan')
 plan=JoiningPlan.objects.get(candidate=candidate);check(plan.tasks.count()==len(TASKS),'joining creates one task per checklist template')
 check(hr.post(joinurl,{'confirm':'yes'}).status_code==302 and JoiningPlan.objects.filter(candidate=candidate).count()==1,'joining initialization is idempotent')
 check(hr.post(outcome,dict(sent,outcome='joined')).status_code==200,'joining blocked before required checklist tasks')
 task=plan.tasks.get(key='documents');taskurl=url('workspace-joining-task',task.pk)
 taskvalues={'assigned_to':roles['manager'].pk,'due_date':str(timezone.localdate()+timedelta(days=7)),'status':'done','evidence':'','expected_version':task.version}
 check(hr.post(taskurl,taskvalues).status_code==200,'completion without evidence rejected')
 taskvalues.update(status='in_progress',evidence='Synthetic document review started')
 check(hr.post(taskurl,taskvalues).status_code==302,'HR assigns checklist owner and due date')
 task.refresh_from_db();check(task.assigned_to_id==roles['manager'].pk and task.version==2,'checklist owner and version persisted')
 check(outsider.get(taskurl).status_code==403,'outsider cannot open task')
 taskvalues.update(expected_version=task.version,status='done',evidence='Synthetic documents verified')
 check(manager.post(taskurl,taskvalues).status_code==302,'assigned manager completes own task')
 task.refresh_from_db();check(task.completed_by_id==roles['manager'].pk and task.completed_at is not None,'task completion actor and timestamp recorded')
 check(manager.post(taskurl,dict(taskvalues,status='todo')).status_code==200,'stale task update rejected')
 other_task=plan.tasks.get(key='compliance')
 check(manager.post(url('workspace-joining-task',other_task.pk),{'status':'done','evidence':'Forged','expected_version':other_task.version}).status_code==403,'manager cannot change unassigned task')
 details=url('workspace-joining-details',candidate.pk)
 data={'appointment_date':str(timezone.localdate()+timedelta(days=10)),'appointment_time':'09:00','appointment_location':'Synthetic Dubai office','handover_reference':'SYNTHETIC-HRMS-REFERENCE','expected_version':plan.version}
 check(hr.post(details,data).status_code==302,'HR records agreed onboarding appointment and reference')
 check(hr.post(details,data).status_code==200,'stale onboarding details rejected')
 for task in plan.tasks.filter(required_for_joining=True).exclude(status='done'):
  check(hr.post(url('workspace-joining-task',task.pk),{'assigned_to':'','due_date':'','status':'not_applicable','evidence':'Synthetic checklist exception approved by HR','expected_version':task.version}).status_code==302,'required task resolved with explicit reason '+task.key)
 check(hr.post(outcome,dict(sent,outcome='joined')).status_code==302,'HR confirms actual joining after checklist gate')
 candidate.refresh_from_db();check(candidate.offer_letter_status=='joined' and candidate.joining_date==timezone.localdate(),'actual joined date persists')
 exports['joining']=hr.get(joinurl).content.decode()
 check(manager.post(joinurl,{'confirm':'yes'}).status_code==403,'manager cannot initialize joining plan')
 tracker=url('workspace-job-tracker',job.pk)
 exports['tracker']=hr.get(tracker).content.decode()
 check(b'Historical source' in exports['tracker'].encode(),'tracker includes labelled source history')
 check(WorkflowEvent.objects.filter(candidate=candidate,kind='offer_approval',actor=roles['director']).exists(),'Director actions attributed to named user')
 check(WorkflowEvent.objects.filter(candidate=candidate,kind='checklist',actor=roles['manager']).exists(),'manager task interactions attributed')
 check(WorkflowEvent.objects.filter(candidate=candidate,job=job).exists(),'candidate history rolls up to job')
 check(hr.get(tracker,{'kind':'views'}).status_code==200,'views tracker filter works')
 check(b'10000.00' not in manager.get(tracker).content,'job tracker excludes private offer compensation')
 check(leader.get(tracker).status_code==404,'aggregate CEO cannot read candidate activity')
 check(current_request.get() is None,'request actor context is cleared between requests')
 event=WorkflowEvent.objects.filter(candidate=candidate).first()
 try:event.detail='Tampered';event.save();blocked=False
 except ValidationError:blocked=True
 check(blocked,'activity entries reject model edits')
 aiurl=url('workspace-jd-settings')
 check(hr.get(aiurl).status_code==403,'HR cannot read or configure provider keys')
 check(manager.get(url('workspace-jd',job.pk)).status_code==403,'manager cannot send AI requests')
 check(leader.get(url('workspace-jd',job.pk)).status_code==403,'CEO cannot draft job descriptions')
 JDProviderConfig.objects.all().delete()
 check(b'Claude not connected' in hr.get(url('workspace-jd',job.pk)).content,'disconnected Claude status is explicit')
 fakekey='sk-ant-synthetic-test-only-'+suffix
 configdata={'api_key':fakekey,'model_name':'claude-sonnet-4-6','workspace_id':'','enabled':'on','confirm':'on'}
 check(a.post(aiurl,configdata).status_code==302,'admin can configure encrypted Anthropic key')
 cfg=JDProviderConfig.objects.get(pk=1)
 check(fakekey not in cfg.encrypted_key and cipher().decrypt(cfg.encrypted_key.encode()).decode()==fakekey,'provider key encrypted at rest')
 response=a.get(aiurl);check(fakekey.encode() not in response.content and b'password' in response.content,'key never echoed into settings HTML')
 check(a.post(aiurl,dict(configdata,api_key='')).status_code==302,'blank API field retains saved key')
 cfg.refresh_from_db();check(cipher().decrypt(cfg.encrypted_key.encode()).decode()==fakekey,'blank API input preserves encrypted key')
 class FakeResponse:
  def __enter__(self):return self
  def __exit__(self,*args):pass
  def read(self,*args):return json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':'Role summary\nSynthetic draft for review.\n\nResponsibilities\nMaintain properties.'}]}).encode()
 captured={}
 class FakeOpener:
  def open(self,request,timeout):captured.update(url=request.full_url,headers=request.headers,body=json.loads(request.data));return FakeResponse()
 with patch('urllib.request.build_opener',return_value=FakeOpener()):
  text,model=generate(job.title,'Synthetic role brief only')
 check(captured['url']=='https://api.anthropic.com/v1/messages','Claude uses fixed official API endpoint')
 check(captured['body']['max_tokens']==2400 and captured['body']['messages'][0]['content'].find('Synthetic role brief only')>=0,'provider receives bounded role brief')
 check(candidate.email not in json.dumps(captured['body']) and '10000.00' not in json.dumps(captured['body']),'AI request excludes candidate and salary records')
 check(captured['headers'].get('Authorization')=='Bearer '+fakekey,'Claude request uses configured key privately')
 before=job.description
 from django.core.cache import cache
 cache.delete('jd-draft:'+str(roles['hr'].pk))
 with patch('recruitment_experience.jd.generate',return_value=('Reviewed synthetic JD <script>alert(1)</script>','claude-sonnet-4-6')):
  response=hr.post(url('workspace-jd',job.pk),{'brief':'Synthetic brief','consent':'on'})
 check(response.status_code==302,'HR generates AI draft for review')
 draft=JDDraft.objects.filter(job=job).latest('pk');job.refresh_from_db()
 check(job.description==before,'generation alone does not alter published job')
 exports['jd-review']=hr.get(url('workspace-jd-review',draft.pk)).content.decode()
 data={'text':draft.text,'expected_version':draft.version,'confirm':'on'}
 check(hr.post(url('workspace-jd-review',draft.pk),dict(data,confirm='')).status_code==200,'JD application requires explicit human confirmation')
 check(hr.post(url('workspace-jd-review',draft.pk),data).status_code==302,'HR explicitly applies reviewed JD')
 job.refresh_from_db();check('<script>' not in job.description and '&lt;script&gt;' in job.description,'AI draft cannot inject active HTML')
 check(hr.post(url('workspace-jd-review',draft.pk),data).status_code==200,'applied draft cannot be replayed')
 stale=JDDraft.objects.create(job=job,author=roles['hr'],brief='Synthetic stale draft',text='Do not overwrite',source_description_sha256=digest('Old description'))
 check(hr.post(url('workspace-jd-review',stale.pk),{'text':'Overwrite','expected_version':1,'confirm':'on'}).status_code==200,'stale draft cannot overwrite another edit')
 response=a.post(aiurl,dict(configdata,api_key='',remove_key='on'))
 cfg.refresh_from_db();check(response.status_code==302 and not cfg.encrypted_key and not cfg.enabled,'admin can remove key and disable paid drafting')
 exports['jd']=hr.get(url('workspace-jd',job.pk)).content.decode();exports['ai-settings']=a.get(aiurl).content.decode()
 # Selection changes invalidate approved terms; a separate request must follow.
 other.stage_id=hired;other.hired=True;other.save()
 check(hr.post(url('workspace-prepare-offer',other.pk),values).status_code==302,'second selected application can request approval')
 extra=other.offer_approvals.get()
 check(director.post(url('workspace-offer-approval',extra.pk),{'decision':'approved','note':'Synthetic approval','confirm':'on'}).status_code==302,'Director approves second package')
 other.stage_id=applied;other.hired=False;other.save()
 extra.refresh_from_db();check(extra.status=='withdrawn','selection change invalidates old offer approval')
 check(a.post(reverse('candidate-stage-update',args=[candidate.pk]),{}).status_code==403,'legacy candidate writes cannot bypass audit and offer controls')
 check(a.post(reverse('generic-delete')+'?model=recruitment.Candidate',{}).status_code==403,'generic delete cannot bypass retained recruitment history')
 check(a.post(reverse('history-revert',args=[candidate.pk,1])+'?model=recruitment.Candidate',{}).status_code==403,'legacy history revert cannot bypass offer approval')
 setupurl=url('workspace-director-demo')
 check(hr.get(setupurl).status_code==403,'HR cannot provision Director accounts')
 if not User.objects.filter(username='demo_director').exists():
  # Real browser sessions normally have an active company, unlike the
  # original empty-session fixture. The automatic staff row starts unassigned.
  session=a.session;session['selected_company']=str(job.company_id_id);session.save()
  password=secrets.token_urlsafe(32)
  check(a.post(setupurl,{'employer':job.company_id_id,'password':password,'confirm_password':password,'confirm':'on'}).status_code==302,'administrator provisions dedicated Director account')
  demo=User.objects.get(username='demo_director')
  check(EmployeeWorkInformation._base_manager.filter(employee_id=demo.employee_get,company_id=job.company_id).count()==1,'company-filtered provisioning preserves one staff work record')
  check(demo.has_perm('recruitment_experience.approve_offer') and not demo.is_superuser and not demo.has_perm('recruitment.view_recruitment'),'demo Director has only bounded approval access')
  loginclient=client();check(loginclient.login(username='demo_director',password=password),'demo Director password authenticates')
  check(loginclient.get(url('recruitment-dashboard')).status_code==200,'new Director login lands on approvals')
  check(loginclient.get(url('workspace-candidate',candidate.pk)).status_code==404,'new Director cannot browse candidate profiles')
  check(a.post(setupurl,{'employer':job.company_id_id,'password':'changed','confirm_password':'changed','confirm':'on'}).status_code==200 and User.objects.get(pk=demo.pk).check_password(password),'existing Director account is never overwritten')
 session=a.session;session['selected_company']='all';session.save()
 # Real CSRF middleware must reject forged state-changing requests.
 check(client(roles['hr'],csrf=True).post(prepare,values).status_code==403,'offer requests enforce CSRF protection')
 check(client(admin,csrf=True).post(aiurl,configdata).status_code==403,'provider settings enforce CSRF protection')
 for name,args in [('workspace-job-tracker',[job.pk]),('workspace-candidate-tracker',[candidate.pk]),('workspace-offer-approvals',[]),('workspace-joining',[candidate.pk]),('workspace-jd',[job.pk]),('workspace-jd-settings',[])]:
  check(client().get(url(name,*args)).status_code==302,'anonymous blocked '+name)
  check(a.put(url(name,*args),data='').status_code==405,'unsupported method blocked '+name)
 Path('/tmp/workflow-controls-renders.json').write_text(json.dumps(exports))
 transaction.set_rollback(True)
print('WORKFLOW_CONTROLS_PASSED',len(checks),'checks; synthetic records rolled back; no real provider calls',flush=True)
