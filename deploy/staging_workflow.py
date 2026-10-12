"""Exercise actual Horilla views, only against the isolated synthetic database."""
import os
import secrets
from datetime import date, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "horilla.settings")
import django
django.setup()
from django.conf import settings
from django.contrib.auth.models import User, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from functools import partial
Client = partial(Client, HTTP_X_FORWARDED_PROTO="https")
from django.urls import reverse, resolve, Resolver404
from base.models import Company, Department, JobPosition
from employee.models import Employee, EmployeeWorkInformation
from recruitment.models import Recruitment, Stage, Candidate, InterviewSchedule, CandidateRating, RecruitmentGeneralSetting
from recruitment_workspace.recruitment_mode import route_allowed

assert settings.DATABASES["default"]["NAME"] == "horilla_staging", "STAGING ONLY"
assert settings.RECRUITMENT_ONLY
settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

def checked(condition, label):
    assert condition, label
    print("PASS", label, flush=True)

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.paths = set()
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and key in {"href", "hx-get", "hx-post", "action"} and value.startswith("/"):
                self.paths.add(value)

def req(client, name, args=None, data=None, method="get", expected=(200,), **extra):
    url = reverse(name, args=args)
    r = getattr(client, method)(url, data or {}, **extra)
    checked(r.status_code in expected, f"{method.upper()} {name}: {r.status_code}")
    if settings.RECRUITMENT_ONLY and r.status_code == 200 and "text/html" in r.get("Content-Type", ""):
        parser = Links(); parser.feed(r.content.decode())
        denied = []
        for path in parser.paths:
            try:
                match = resolve(urlsplit(path).path)
            except Resolver404:
                continue
            from django.test import RequestFactory
            request = RequestFactory().get(path)
            request.user = admin; request.resolver_match = match
            if not route_allowed(request, match.func):
                denied.append((path, match.url_name))
        if denied:
            print("BLOCKED_RENDERED_LINKS", name, sorted(denied), flush=True)
        checked(not denied, "rendered navigation "+name)
    return r

company, _ = Company.objects.get_or_create(company="Synthetic Staging Company", address="Test only", defaults={"country":"United Arab Emirates", "state":"Dubai", "city":"Dubai", "zip":"00000", "icon":"base/icon/staging.png"})
department = Department.objects.filter(department="Staging Recruitment").first()
if department is None:
    department = Department(department="Staging Recruitment"); department.save()
department.company_id.add(company)
position = JobPosition.objects.filter(job_position="Synthetic Property Consultant", department_id=department).first()
if position is None:
    position = JobPosition(job_position="Synthetic Property Consultant", department_id=department); position.save()
position.company_id.add(company)
users = {}
passwords = {}
for role in ("admin", "recruiter", "manager", "unprivileged"):
    user, _ = User.objects.get_or_create(username="staging_"+role)
    password = secrets.token_urlsafe(32); passwords[role] = password
    user.set_password(password); user.is_staff = role == "admin"; user.is_superuser = role == "admin"; user.save()
    emp, _ = Employee.objects.get_or_create(employee_user_id=user, defaults={"employee_first_name":role.title(), "email":role+"@staging.invalid", "phone":"0000000000"})
    EmployeeWorkInformation.objects.get_or_create(employee_id=emp, defaults={"company_id":company,"department_id":department,"job_position_id":position})
    users[role] = user
    if role == "recruiter":
        user.user_permissions.set(Permission.objects.filter(content_type__app_label="recruitment"))
admin = users["admin"]
client = Client()
req(client, "login")
req(client, "login", data={"username":admin.username,"password":passwords["admin"]}, method="post", expected=(302,))
home = client.get("/"); checked(home.status_code == 302 and home.url == reverse("recruitment-dashboard"), "administrator landing")
hx = {"HTTP_HX_REQUEST":"true"}
req(client, "recruitment-dashboard")
req(client, "settings")
req(client, "general-settings")
req(client, "department-view")
req(client, "employee-view")
req(client, "employee-view-new")
req(client, "user-group-view")
staff_email = "staff-"+secrets.token_hex(4)+"@staging.invalid"
req(client,"employee-create-personal-info",data={"employee_first_name":"Synthetic Staff","email":staff_email,"phone":"0500000002","gender":"male","marital_status":"single","badge_id":"ST"+secrets.token_hex(3)+"1"},method="post",expected=(302,))
new_staff = Employee.objects.get(email=staff_email)
checked(new_staff.employee_user_id is not None,"staff user creation persisted")
req(client,"employee-permission-assign")
req(client,"update-user-permission",data={"employee":users["recruiter"].employee_get.pk,"permissions":list(Permission.objects.filter(content_type__app_label="recruitment").values_list("codename",flat=True))},method="post")
checked(User.objects.get(pk=users["recruiter"].pk).has_perm("recruitment.view_recruitment"),"recruiter permission assignment persisted")
req(client, "recruitment-create", **hx)
req(client, "get-filter-form", data={"template_path":"employee_filters.html"}, **hx)
title = "Synthetic Vacancy "+secrets.token_hex(3)
req(client, "recruitment-create", data={"title":title,"description":"Synthetic workflow validation","vacancy":2,"is_published":"on","open_positions":[position.pk],"recruitment_managers":[users["manager"].employee_get.pk],"company_id":company.pk,"start_date":date.today().isoformat(),"end_date":(date.today()+timedelta(days=30)).isoformat(),"optional_profile_image":"on"}, method="post", **hx)
rec = Recruitment.objects.filter(title=title).first()
checked(rec is not None, "vacancy creation persisted")
checked(rec.recruitment_managers.filter(pk=users["manager"].employee_get.pk).exists(), "manager assignment persisted")
stages = {}
for sequence, (label, kind) in enumerate((("Applied", "initial"),("Interview", "interview"),("Hired", "hired"))):
    stage, _ = Stage.objects.get_or_create(recruitment_id=rec,stage=label,defaults={"stage_type":kind,"sequence":sequence})
    stage.stage_managers.add(users["manager"].employee_get); stages[kind] = stage

def cv():
    import fitz
    doc = fitz.open(); page = doc.new_page(); page.insert_text((72,72),"SYNTHETIC CV - staging workflow test")
    return SimpleUploadedFile("synthetic-cv.pdf", doc.tobytes(), content_type="application/pdf")

email = "candidate-"+secrets.token_hex(4)+"@staging.invalid"
req(client,"candidate-create",data={"name":"Synthetic Candidate","email":email,"mobile":"0500000000","gender":"male","source":"software","is_active":"on","recruitment_id":rec.pk,"job_position_id":position.pk,"resume":cv()},method="post",expected=(302,))
cand = Candidate.objects.get(email=email)
checked(cand.resume.storage.exists(cand.resume.name), "synthetic CV uploaded")
req(client,"candidate-view-individual",args=[cand.pk])
req(client,"candidate-stage-change",data={"canIds":cand.pk,"stageId":stages["interview"].pk},method="post",**hx)
cand.refresh_from_db(); checked(cand.stage_id == stages["interview"],"candidate stage persisted")
req(client,"interview-schedule",args=[cand.pk],data={"candidate_id":cand.pk,"employee_id":[users["manager"].employee_get.pk],"interview_date":(date.today()+timedelta(days=1)).isoformat(),"interview_time":"12:00","description":"Synthetic interview"},method="post",**hx)
checked(InterviewSchedule.objects.filter(candidate_id=cand).exists(),"interview persisted")
req(client,"create-candidate-rating",args=[cand.pk],data={"rating":4},method="post",expected=(302,))
checked(CandidateRating.objects.filter(candidate_id=cand,rating=4).exists(),"candidate feedback persisted")
req(client,"pipeline")
req(client,"candidate-view")
req(client,"interview-view")
req(client,"employee-widget-filter",**hx)
req(client,"protected_media",args=[cand.resume.name])

public = Client()
req(public,"open-recruitments", expected=(302,))
req(public,"application-form",data={"recruitmentId":rec.pk}, expected=(302,))
public_email = "applicant-"+secrets.token_hex(4)+"@staging.invalid"
r = public.post(reverse("application-form")+"?recruitmentId="+str(rec.pk),{"name":"Synthetic Public Applicant","email":public_email,"mobile":"0500000001","gender":"male","recruitment_id":rec.pk,"job_position_id":position.pk,"resume":cv()})
checked(r.status_code == 302 and Candidate.objects.filter(email=public_email).exists(), "public application saved")
RecruitmentGeneralSetting.objects.update_or_create(pk=1, defaults={"candidate_self_tracking":True})
req(public,"candidate-login",data={"email":public_email,"phone":"0500000001"},method="post",expected=(302,))
req(public,"candidate-self-status-tracking")

for role, user in users.items():
    c = Client()
    req(c,"login",data={"username":user.username,"password":passwords[role]},method="post",expected=(302,))
    home = c.get("/")
    checked(home.status_code == (403 if role == "unprivileged" else 302), role+" landing permissions")
    if role in {"recruiter","manager"}:
        req(c,"recruitment-dashboard")
        req(c,"pipeline")
    for name in ("attendance-view","user-request-view","view-payroll-dashboard","employee-shift-view"):
        try:
            path = reverse(name)
        except Exception:
            continue
        for method in ("get","post","head"):
            checked(getattr(c,method)(path).status_code == 403,role+" denied "+method+" "+name)
    for path in ("/admin/", "/api/employee/employees/"):
        checked(c.get(path).status_code == 403, role+" denied "+path)

before = (Recruitment.objects.count(),Candidate.objects.count(),InterviewSchedule.objects.count())
with override_settings(RECRUITMENT_ONLY=False):
    c = Client(); c.force_login(admin)
    req(c,"home-page")
    req(c,"employee-shift-view")
checked(before == (Recruitment.objects.count(),Candidate.objects.count(),InterviewSchedule.objects.count()),"mode off preserves recruitment data")
checked(cand.resume.storage.exists(cand.resume.name),"mode off preserves CV")
print("FULL_WORKFLOW_PASSED", flush=True)
