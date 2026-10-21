"""Read-only role/ownership checks for explicitly provisioned demo personas."""
import json, os
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from recruitment.models import Candidate
from recruitment_experience.models import ApplicantAccount
from recruitment_experience.access import scoped_jobs

credentials = json.loads(Path(os.environ['HORILLA_DEMO_ACCOUNTS_FILE']).read_text())
clients = {}
for username in ['demo_hr','demo_manager','demo_ceo']:
    user = User.objects.get(username=username)
    assert user.is_active and not user.is_superuser and not user.is_staff
    client = Client(HTTP_X_FORWARDED_PROTO='https')
    response = client.post(reverse('login'), {'username':username, 'password':credentials[username]})
    assert response.status_code == 302 and response.url != reverse('login'), username+' failed actual staff login'
    assert str(client.session.get('_auth_user_id')) == str(user.pk)
    response = client.get(reverse('recruitment-dashboard'))
    assert response.status_code == 200, username+' failed landing'
    clients[username] = client
hr, manager, ceo = [clients[x] for x in ['demo_hr','demo_manager','demo_ceo']]
assert 'Your hiring day, made clearer.' in hr.get(reverse('recruitment-dashboard')).content.decode() or 'Today' in hr.get(reverse('recruitment-dashboard')).content.decode()
assert 'Hiring, at a glance.' in ceo.get(reverse('recruitment-dashboard')).content.decode()
assert 'Advanced tools' not in manager.get(reverse('recruitment-dashboard')).content.decode()
assert 'Advanced tools' not in ceo.get(reverse('recruitment-dashboard')).content.decode()
assert ceo.get(reverse('workspace-requests')).status_code == 200
assert 'Request an opening</h2>' not in ceo.get(reverse('workspace-requests')).content.decode()
manager_user = User.objects.get(username='demo_manager')
inside = Candidate.objects.filter(recruitment_id__in=scoped_jobs(manager_user)).first()
outside = Candidate.objects.exclude(recruitment_id__in=scoped_jobs(manager_user)).first()
assert inside and outside
assert manager.get(reverse('workspace-candidate', args=[inside.pk])).status_code == 200
assert manager.get(reverse('workspace-candidate', args=[outside.pk])).status_code == 404
assert manager.get(reverse('workspace-cv', args=[outside.pk])).status_code == 404
assert manager.get(reverse('recruitment-view')).status_code == 403
assert manager.get(reverse('workspace-ceo')).status_code == 403
assert ceo.get(reverse('workspace-candidate', args=[inside.pk])).status_code == 404
assert ceo.get(reverse('workspace-cv', args=[inside.pk])).status_code == 404
assert hr.get(reverse('workspace-candidate', args=[outside.pk])).status_code == 200
for c in [hr,manager,ceo]:
    assert c.get('/admin/').status_code == 403
    assert c.get('/payroll/').status_code == 403
    assert c.get(reverse('portal-branding')).status_code == 403
account = ApplicantAccount.objects.get(email='demo.applicant@example.invalid')
owned = account.applications.get().candidate
applicant = Client(HTTP_X_FORWARDED_PROTO='https')
r = applicant.post(reverse('applicant-login'), {'email':account.email, 'password':credentials['applicant']})
assert r.status_code == 302 and r.url == reverse('applicant-home')
assert applicant.session['applicant_account'] == account.pk
page = applicant.get(reverse('applicant-detail',args=[owned.pk]))
assert page.status_code == 200 and 'Your interview' in page.content.decode()
assert 'DEMO INTERNAL NOTE' not in page.content.decode()
assert applicant.get(reverse('applicant-cv',args=[owned.pk])).status_code == 200
other = Candidate.objects.exclude(pk=owned.pk).first()
assert applicant.get(reverse('applicant-detail',args=[other.pk])).status_code == 404
assert applicant.get(reverse('applicant-cv',args=[other.pk])).status_code == 404
for c in [applicant,manager,ceo,Client(HTTP_X_FORWARDED_PROTO='https')]:
    assert c.get('/media/'+owned.resume.name,HTTP_REFERER='/login').status_code == 403
public = Client(HTTP_X_FORWARDED_PROTO='https')
assert public.get(reverse('portal-careers')).status_code == 200
assert public.get(reverse('portal-logo')).status_code == 200
assert public.get(reverse('portal-banner')).status_code == 200
print('FOUR_ACTUAL_LOGINS_LANDINGS_SCOPED_DOCUMENTS_AND_APPLICANT_PRIVACY_VERIFIED',flush=True)
