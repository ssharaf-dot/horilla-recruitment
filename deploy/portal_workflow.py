"""Real-view recruitment portal checks against a synthetic staging database only."""
import os, secrets, json, gzip
from pathlib import Path
from datetime import date,timedelta
os.environ.setdefault('DJANGO_SETTINGS_MODULE','horilla.settings')
import django
django.setup()
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from recruitment.models import Recruitment,Candidate,RecruitmentSurvey,RecruitmentSurveyAnswer,Stage
from recruitment_portal.models import PortalBranding
assert settings.DATABASES['default']['NAME']=='horilla_staging','STAGING ONLY'
settings.EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
def check(value,label):
 assert value,label
 print('PASS',label,flush=True)
def client(user=None):
 c=Client(HTTP_X_FORWARDED_PROTO='https')
 if user:c.force_login(user)
 return c
admin=User.objects.get(username='staging_admin');a=client(admin);public=client()
rec=Recruitment.objects.filter(is_active=True,is_published=True,closed=False).order_by('-pk').first()
position=rec.open_positions.first()
brand={'portal_name':'Careers','organization_name':'Example Employer','tagline':'A place for your next chapter.','careers_headline':'Build what comes next.','careers_intro':'Join the people creating considered spaces and lasting communities. Discover your next chapter with Example Employer.','accent_color':'#14574b','website_url':'','privacy_url':'','contact_email':''}
check(a.post(reverse('portal-branding'),brand).status_code==302,'branding saved through admin settings')
check(PortalBranding.objects.count()==1,'one branding record')
for name in ['portal-careers','login','recruitment-dashboard','portal-branding']:
 r=(a if name in ['recruitment-dashboard','portal-branding'] else public).get(reverse(name))
 check(r.status_code==200 and b'Example Employer' in r.content and b'Careers' in r.content,'branding reflects on '+name)
check(client(User.objects.get(username='staging_recruiter')).post(reverse('portal-branding'),brand).status_code==403,'recruiter cannot change branding without permission')
check(client(User.objects.get(username='staging_unprivileged')).get(reverse('recruitment-dashboard')).status_code==403,'unprivileged overview denied')
check(public.post(reverse('portal-careers')).status_code==405,'public jobs page read only')
original=(rec.is_published,rec.closed,rec.start_date,rec.end_date,rec.is_active)
for field,value in [('is_published',False),('closed',True),('start_date',date.today()+timedelta(days=1)),('end_date',date.today()-timedelta(days=1)),('is_active',False)]:
 Recruitment.default.filter(pk=rec.pk).update(**{field:value})
 check(public.get(reverse('portal-job-detail',args=[rec.pk])).status_code==404,'hidden public job when '+field)
 check(public.post(reverse('portal-apply',args=[rec.pk]),{}).status_code==404,'application blocked when '+field)
 Recruitment.default.filter(pk=rec.pk).update(**dict(zip(['is_published','closed','start_date','end_date','is_active'],original)))
email='portal-'+secrets.token_hex(4)+'@staging.invalid'
import fitz
pdf=fitz.open();pdf.new_page().insert_text((72,72),'SYNTHETIC CV FOR PORTAL TEST')
def cv():return SimpleUploadedFile('synthetic.pdf',pdf.tobytes(),content_type='application/pdf')
other=Recruitment.objects.exclude(pk=rec.pk).first()
data={'name':'Synthetic Portal Applicant','email':email,'mobile':'0500000033','job_position_id':position.pk,'resume':cv(),'recruitment_id':other.pk if other else 999999,'hired':'on','canceled':'on','is_active':'','stage_id':'999999','source':'software'}
r=public.post(reverse('portal-apply',args=[rec.pk]),data)
check(r.status_code==302,'canonical public application accepted')
candidate=Candidate.objects.get(email=email)
check(candidate.recruitment_id_id==rec.pk and not candidate.hired and not candidate.canceled and candidate.is_active and candidate.source=='application','internal candidate fields cannot be injected')
check(candidate.resume.storage.exists(candidate.resume.name),'uploaded CV persisted')
check(public.get(reverse('protected_media',args=[candidate.resume.name])).status_code in [302,403],'CV remains private')
check(a.get(reverse('protected_media',args=[candidate.resume.name])).status_code==200,'administrator can view CV')
question=RecruitmentSurvey.objects.create(question='Synthetic screening question',type='text',is_mandatory=False)
question.recruitment_ids.add(rec)
data.update(email='survey-'+secrets.token_hex(4)+'@staging.invalid',resume=cv())
r=public.post(reverse('portal-apply',args=[rec.pk]),data)
check(r.status_code==302 and 'candidate-survey' in r.url,'questionnaire redirect preserved')
r=public.get(r.url);check(r.status_code==200 and b'Example Employer' in r.content,'questionnaire uses portal branding')
r=public.post(reverse('candidate-survey'),{'text_Synthetic screening question':'Synthetic response'})
check(r.status_code==200 and b'Example Employer' in r.content,'questionnaire completion page branded')
check(RecruitmentSurveyAnswer.objects.filter(candidate_id__email=data['email']).exists(),'questionnaire answers persisted')
question.recruitment_ids.clear()
exports={}
for file,name,args in [('overview','recruitment-dashboard',None),('branding','portal-branding',None),('careers','portal-careers',None),('job_detail','portal-job-detail',[rec.pk]),('apply','portal-apply',[rec.pk]),('login','login',None)]:
 c=a if file in ['overview','branding'] else public
 r=c.get(reverse(name,args=args));check(r.status_code==200,'render '+file)
 exports[file]=r.content.decode()
Path('/tmp/portal-rendered-review.json.gz').write_bytes(gzip.compress(json.dumps(exports).encode()))
print('PORTAL_WORKFLOW_PASSED',flush=True)
