"""Staging-only integration checks: lifecycle presentation, scoped profiles and CV review."""
import os,secrets,re,html,json,gzip,hashlib
from pathlib import Path
os.environ.setdefault('DJANGO_SETTINGS_MODULE','horilla.settings')
import django
django.setup()
from django.conf import settings
from django.test import Client, RequestFactory
from django.contrib.auth.models import User,Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import reverse
from employee.models import Employee, EmployeeWorkInformation
from recruitment.models import Recruitment,Candidate,Stage
from recruitment_experience.models import CandidateProfile,HiringRequest,WorkflowEvent,ApplicantAccount,ApplicantApplication,Division,DivisionAccess
from recruitment_experience.phase_data import PHASES,candidate_phase,navigation,phase_scope
from recruitment_experience.cv_profile import suggest_from_text,extract_resume
from recruitment_experience.access import scoped_candidates
from recruitment_experience.services import WORKING_ZONE
from django.utils import timezone
assert settings.DATABASES['default']['NAME']=='horilla_staging','STAGING ONLY'
checks=[];exports={};media=[];suffix=secrets.token_hex(5)
def check(value,label):
 assert value,label
 checks.append(label);print('PASS',label,flush=True)
def client(user=None,csrf=False):
 c=Client(HTTP_HOST='staging.test',HTTP_X_FORWARDED_PROTO='https',enforce_csrf_checks=csrf)
 if user:c.force_login(user)
 return c
def hidden(response,name):
 pattern=r'name="'+name+r'"[^>]*value="([^"]*)"'
 match=re.search(pattern,response.content.decode());assert match,name
 return html.unescape(match[1])
def phase(c,slug,**query):return c.get(reverse('workspace-phase',args=[slug]),query)
try:
 with transaction.atomic(), timezone.override(WORKING_ZONE):
  admin=User.objects.get(username='staging_admin');a=client(admin)
  job=Recruitment.objects.filter(is_active=True,closed=False,is_published=True).first();assert job
  position=job.open_positions.first();assert position
  applied=job.stage_set.filter(stage_type='applied').first();interview=job.stage_set.filter(stage_type='interview').first();hired=job.stage_set.filter(stage_type='hired').first()
  roles={}
  for role in ['manager','outsider','leader']:
   user=User.objects.create_user(username='phase_'+role+suffix,password=secrets.token_urlsafe(32))
   User.objects.filter(pk=user.pk).update(is_new_employee=False)
   employee=Employee.objects.create(employee_user_id=user,employee_first_name='Phase '+role,email=role+suffix+'@example.invalid',phone='0500000000')
   info,_=EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
   EmployeeWorkInformation.objects.filter(pk=info.pk).update(company_id=job.company_id,department_id=position.department_id,job_position_id=position)
   roles[role]=user
  job.recruitment_managers.add(roles['manager'].employee_get)
  roles['leader'].user_permissions.add(Permission.objects.get(codename='view_hiringoverview'))
  manager,outsider,leader=(client(roles[r]) for r in ['manager','outsider','leader'])
  additional=HiringRequest.objects.create(job=job,openings=1,reason='Synthetic phase approval check',requested_by=admin)
  check(('Opening request #'+str(additional.pk)).encode() in phase(a,'plan').content,'approval board includes additional openings')
  check(('Opening request #'+str(additional.pk)).encode() not in phase(manager,'plan').content,'manager approval board excludes another requester opening')
  import fitz
  pdf=fitz.open();page=pdf.new_page();page.insert_text((72,72),'Name: Sam Demo\nEmail: sam.demo@example.invalid\nPhone: +971501234567\nProfessional Summary\nFacilities specialist with property operations experience.\nWork Experience\nFacilities Coordinator - Demo Estates\n2022 - 2025\nEducation\nDiploma in Facilities Management\nSkills\nMaintenance planning, Vendor coordination, Reporting')
  raw=pdf.tobytes();pdf.close()
  candidate=Candidate(name='Phase Synthetic Applicant',email='phase-'+suffix+'@example.invalid',mobile='+971501234567',recruitment_id=job,job_position_id=position,stage_id=applied,source='application')
  candidate.resume.save('phase-cv.pdf',SimpleUploadedFile('phase-cv.pdf',raw),save=False);media.append(candidate.resume.name);candidate.save()
  otherjob=Recruitment.objects.exclude(pk=job.pk).first()
  other=Candidate.objects.filter(recruitment_id=otherjob,is_active=True).first() if otherjob else None
  for who,c in [('HR',a),('manager',manager),('leadership',leader)]:
   for spec in PHASES:
    response=phase(c,spec['slug']);check(response.status_code==200,who+' opens phase '+spec['slug'])
    check(b'aria-label="Recruitment phases"' in response.content,who+' has phase navigation '+spec['slug'])
    if who=='HR':exports['phase-'+spec['slug']]=response.content.decode()
    if who=='leadership' and spec['slug'] not in ['plan','attract']:
     check(candidate.name.encode() not in response.content,'leadership phase does not expose applicant '+spec['slug'])
   if who=='manager' and other:check(other.email.encode() not in phase(c,'screen').content,'manager phase excludes unassigned applicant')
  check(phase(client(),'screen').status_code==302,'phase requires authentication')
  check(phase(outsider,'screen').status_code==403,'unassigned employee cannot open phases')
  check(phase(a,'invalid').status_code==404,'unknown phase rejected')
  check(candidate.name.encode() not in phase(manager,'screen',job=otherjob.pk).content if otherjob else True,'forged job filter cannot reveal applicants')
  check(phase(a,'screen',division='not-a-number').status_code==200,'invalid division handled without error')
  rf=RequestFactory().get('/recruitment/workspace/');rf.user=admin
  nav=navigation(rf);scope=phase_scope(rf);all_rows=list(scope['candidates'])
  check(nav[0]['count']==scope['requisitions'].count()+scope['additional_requests'].count(),'approval navigation counts requisitions and additional openings')
  total=sum(item['count'] for item in nav if item['slug'] in ['screen','interview','offer','handover'])+sum(candidate_phase(c)=='closed' for c in all_rows)
  check(total==len(all_rows),'phase counts reconcile every scoped application once')
  for changes,wanted in [({},'screen'),({'stage_id':interview},'interview'),({'stage_id':hired},'offer'),({'offer_letter_status':'sent'},'offer'),({'offer_letter_status':'accepted'},'handover'),({'offer_letter_status':'joined'},'handover'),({'canceled':True},'closed')]:
   fresh=Candidate.objects.get(pk=candidate.pk)
   for k,v in changes.items():setattr(fresh,k,v)
   check(candidate_phase(fresh)==wanted,'classification '+repr(changes))
  review_url=reverse('workspace-profile-edit',args=[candidate.pk])
  before=(candidate.stage_id_id,candidate.offer_letter_status,candidate.resume.name)
  response=a.get(review_url,{'extract':'1'});check(response.status_code==200,'HR extracts CV suggestions')
  check(CandidateProfile.objects.filter(candidate=candidate).count()==0,'extracting CV writes no profile')
  check(b'sam.demo@example.invalid' in response.content and b'Facilities Coordinator' in response.content,'local PDF contact and experience suggestions rendered')
  check(b'Use in draft' in response.content and b'Save reviewed profile' in response.content,'suggestions require selection then explicit save')
  check(hidden(response,'version')=='0','new profile begins with no reviewed version')
  data={'name':candidate.name,'email':candidate.email,'mobile':candidate.mobile,'city':'Dubai','country':'United Arab Emirates','portfolio':'https://example.invalid','headline':'Facilities professional','about':'HR reviewed professional summary','experience':'Facilities Coordinator · Demo Estates\n2022–2025','education':'Diploma in Facilities Management','skills':'Maintenance planning, Vendor coordination','version':0,'confirm':'on','contact_token':hidden(response,'contact_token'),'resume_token':hidden(response,'resume_token')}
  check(manager.get(review_url,{'extract':'1'}).status_code==403,'manager cannot extract/edit profile')
  check(manager.post(review_url,data).status_code==403,'manager profile write denied')
  check(leader.get(review_url).status_code==404,'leadership cannot read profile editor')
  check(outsider.get(review_url).status_code in [403,404],'outsider profile editor denied')
  check(client().get(review_url).status_code==302,'unauthenticated profile editor denied')
  if other:check(manager.get(reverse('workspace-profile-edit',args=[other.pk])).status_code==404,'manager cannot read another job profile')
  check(client(admin,True).post(review_url,data).status_code==403,'profile writes enforce CSRF')
  no_confirm=dict(data);no_confirm.pop('confirm')
  check(a.post(review_url,no_confirm).status_code==200 and not CandidateProfile.objects.filter(candidate=candidate).exists(),'profile save requires HR confirmation')
  check(a.post(review_url,data).status_code==302,'reviewed profile saves')
  profile=CandidateProfile.objects.get(candidate=candidate);candidate.refresh_from_db()
  check(profile.headline==data['headline'] and profile.experience==data['experience'],'reviewed fields persisted')
  check(profile.source_resume_sha256==hashlib.sha256(raw).hexdigest(),'review linked to original CV digest')
  check((candidate.stage_id_id,candidate.offer_letter_status,candidate.resume.name)==before,'profile save preserves recruitment stage/outcome/CV')
  with candidate.resume.open('rb') as file:check(file.read()==raw,'original CV is byte-identical after review')
  check(WorkflowEvent.objects.filter(candidate=candidate,kind='profile_review').count()==1,'profile review audit recorded once')
  check(a.post(review_url,data).status_code==200 and CandidateProfile.objects.get(pk=profile.pk).version==profile.version,'stale profile submission cannot overwrite')
  latest=a.get(review_url);newdata=dict(data,version=profile.version,contact_token=hidden(latest,'contact_token'),resume_token='')
  Candidate.objects.filter(pk=candidate.pk).update(mobile='+971501111111')
  check(a.post(review_url,newdata).status_code==200 and Candidate.objects.get(pk=candidate.pk).mobile=='+971501111111','concurrent contact update preserved')
  Candidate.objects.filter(pk=candidate.pk).update(mobile=data['mobile'])
  escaped=a.get(review_url);bad=dict(newdata,contact_token=hidden(escaped,'contact_token'),about='<script>alert(1)</script>',portfolio='javascript:alert(1)')
  check(a.post(review_url,bad).status_code==200 and CandidateProfile.objects.get(pk=profile.pk).about!=bad['about'],'unsafe website scheme rejected')
  safe=dict(bad,portfolio='https://example.invalid');check(a.post(review_url,safe).status_code==302,'ordinary profile text can be recorded')
  display=a.get(reverse('workspace-candidate',args=[candidate.pk]));check(b'&lt;script&gt;' in display.content and b'<script>alert(1)</script>' not in display.content,'profile text escaped in rendered page')
  CandidateProfile.objects.filter(pk=profile.pk).update(about=data['about'])
  display=a.get(reverse('workspace-candidate',args=[candidate.pk]));exports['profile']=display.content.decode()
  exports['profile-edit']=a.get(review_url,{'extract':'1'}).content.decode()
  for name,c in [('overview',a),('manager',manager),('leadership',leader)]:
   route={'overview':'workspace-today','manager':'workspace-manager','leadership':'workspace-ceo'}[name]
   r=c.get(reverse(route));check(r.status_code==200,name+' landing renders');exports[name]=r.content.decode()
  check(b'Experience' in display.content and b'Education' in display.content and b'Skills' in display.content,'profile sections available')
  account=ApplicantAccount.objects.create(email='phase-applicant-'+suffix+'@example.invalid',name='Sam Demo',password='not-a-login-credential')
  ApplicantApplication.objects.create(account=account,candidate=candidate)
  applicant=client();session=applicant.session;session['applicant_account']=account.pk;session.save()
  r=applicant.get(reverse('applicant-detail',args=[candidate.pk]));check(r.status_code==200,'owned applicant journey renders');exports['applicant']=r.content.decode()
  check(b'HR reviewed professional summary' not in r.content and b'profile_review' not in r.content,'private profile review is not disclosed to applicant')
  check(applicant.get(review_url).status_code==302,'applicant identity cannot access staff profile')
  extracted=suggest_from_text('Name: Demo Person\nEmail: demo@example.invalid\nDOB: 1990-01-01\nWork Experience\nCoordinator\nEducation\nDiploma\nSkills\nExcel, Scheduling')
  check(extracted.get('name')=='Demo Person' and 'experience' in extracted and 'dob' not in extracted,'extract only explicitly supported fields')
  check('mobile' not in suggest_from_text('Education\n2010 - 2014\nID: 12345678901'),'dates and IDs are not guessed as phone numbers')
  check('name' not in suggest_from_text('CURRICULUM VITAE\nRandom Text'),'no name inferred from arbitrary first line')
  check(len(suggest_from_text('Experience\n'+'x'*10000)['experience'])==6000,'extracted sections bounded')
  candidate.resume.name='does-not-exist.pdf';check(bool(extract_resume(candidate)[2]),'missing file handled without failure')
  # Persist synthetic visual output only; all model mutations roll back.
  Path('/tmp/six-phase-renders.json.gz').write_bytes(gzip.compress(json.dumps(exports).encode()))
  transaction.set_rollback(True)
 print('SIX_PHASE_WORKFLOW_PASSED',len(checks),flush=True)
finally:
 from django.core.files.storage import default_storage
 for name in media:
  if default_storage.exists(name):default_storage.delete(name)
