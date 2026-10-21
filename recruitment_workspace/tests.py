"""Exercise the real middleware with HTTP requests and isolated Django auth."""

import ast
import re
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from django.template import Context, Engine, Library
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import ResolverMatch, path, re_path

from recruitment_workspace.recruitment_mode import (
    BASE_ROUTES, STAFF_ROUTES, RecruitmentOnlyMiddleware, model_allowed, module_visible,
)

ROOT = Path(__file__).resolve().parents[1]


def ok(request, **kwargs):
    return HttpResponse("allowed by original view")


@permission_required("auth.view_user", raise_exception=True)
def restricted_recruitment(request):
    return ok(request)


urlpatterns = [
    path("", ok, name="home-page"),
    path("recruitment/dashboard", ok, name="recruitment-dashboard"),
    path("recruitment/candidates", restricted_recruitment, name="test-candidates"),
    path("recruitment/application-form", ok, name="test-application"),
    path("generic-delete", ok, name="generic-delete"),
    path("reload-field", ok, name="reload-field"),
    re_path(r"^media/(?P<path>.*)$", ok, name="protected_media"),
    path("horilla-history-revert/1/1/", ok, name="history-revert"),
    path("settings/company-view/", ok, name="company-view"),
    path("settings/employee-shift-view/", ok, name="employee-shift-view"),
    path("employee/employee-view/", ok, name="employee-view"),
    path("employee/bonus-points-tab/1", ok, name="bonus-points-tab"),
    path("accounts/password_reset/", ok, name="password_reset"),
    path("login/", ok, name="login"),
    path("health/", ok, name="health"),
    path("new-module/", ok, name="new-unreviewed-route"),
    re_path(r"^(?:attendance|leave|payroll|pms|helpdesk|offboarding|onboarding|asset|project|biometric|api|admin)/.*$", ok),
]

# Register actual URL names used by settings/sidebar templates, without
# importing Horilla's database-bound view modules or starting its schedulers.
known_names = {p.name for p in urlpatterns}
source_names = set()
for filename in list(ROOT.glob("**/urls.py")) + list(ROOT.glob("*/apps.py")) + [ROOT / "base/context_processors.py"]:
    if ".venv" in filename.parts:
        continue
    tree = ast.parse(filename.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    source_names.add(kw.value.value)
for name in sorted(source_names - known_names):
    urlpatterns.append(path("test-route/" + name, ok, name=name))

# All modules/permissions are present for rendering tests, like a superuser.
# This library substitutes only heavy Horilla model imports.
register = Library()
register.filter("app_installed", module_visible)
register.filter("config_perms", lambda user: True)


@override_settings(RECRUITMENT_ONLY=True)
class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("recruiter", password="local-test")
        content_type = ContentType.objects.create(app_label="recruitment", model="recruitment")
        permission = Permission.objects.create(
            content_type=content_type, codename="view_recruitment", name="View recruitment"
        )
        cls.user.user_permissions.add(permission)
        cls.unprivileged = get_user_model().objects.create_user("without-recruitment-access")
        cls.admin = get_user_model().objects.create_superuser(
            "administrator", "test@example.invalid", "local-test"
        )

    def test_disabled_html_and_api_routes_rejected_for_every_role_and_method(self):
        targets = [
            "/attendance/attendance-view", "/leave/request-view", "/payroll/payslip/",
            "/pms/dashboard", "/helpdesk/tickets/", "/offboarding/offboarding-pipeline",
            "/onboarding/", "/asset/", "/project/", "/biometric/",
            "/api/payroll/payslip/", "/api/attendance/attendance/", "/api/base/",
            "/admin/payroll/contract/", "/admin/",
            "/settings/employee-shift-view/", "/employee/bonus-points-tab/1",
            "/new-module/",
        ]
        for user in [None, self.user, self.admin]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for target in targets:
                for method in ["get", "post", "head"]:
                    with self.subTest(user=user, target=target, method=method):
                        response = getattr(self.client, method)(
                            target, HTTP_AUTHORIZATION="Bearer local-test-token"
                        )
                        self.assertEqual(response.status_code, 403)

    def test_home_redirects_authenticated_user_and_preserves_login_for_anonymous(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.force_login(self.user)
        for method in ["get", "head"]:
            self.assertRedirects(
                getattr(self.client, method)("/"), "/recruitment/dashboard",
                fetch_redirect_response=False,
            )

    def test_existing_recruitment_permissions_are_not_overridden(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/recruitment/candidates").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/recruitment/candidates").status_code, 200)

    def test_unprivileged_landing_does_not_loop_through_dashboard(self):
        self.client.force_login(self.unprivileged)
        for target in ["/", "/recruitment/dashboard"]:
            self.assertEqual(self.client.get(target).status_code, 403)

    def test_public_applications_auth_health_and_core_staff_are_preserved(self):
        for target in [
            "/recruitment/application-form", "/accounts/password_reset/", "/login/",
            "/health/", "/settings/company-view/", "/employee/employee-view/",
        ]:
            self.assertEqual(self.client.get(target).status_code, 200)

    def test_generic_handlers_cannot_target_disabled_models_even_for_superusers(self):
        self.client.force_login(self.admin)
        for target in ["/generic-delete", "/horilla-history-revert/1/1/"]:
            for label in ["payroll.Contract", "leave.LeaveRequest", "base.EmployeeShift", "", "Candidate"]:
                with self.subTest(target=target, model=label):
                    self.assertEqual(self.client.post(target + "?model=" + label).status_code, 403)
            for label in ["recruitment.Candidate", "base.JobPosition", "employee.Employee"]:
                self.assertEqual(self.client.post(target + "?model=" + label).status_code, 200)

    def test_shared_history_and_delete_require_model_permissions(self):
        for user in [None, self.user]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for target in ["/generic-delete", "/horilla-history-revert/1/1/"]:
                self.assertEqual(self.client.post(target + "?model=recruitment.Candidate").status_code, 403)

    def test_media_cannot_fetch_disabled_models_or_traverse_from_a_candidate_path(self):
        for user in [None, self.admin]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for target in [
                "/media/payroll/contract/document/test.pdf",
                "/media/leave/leaverequest/attachment/test.pdf",
                "/media/recruitment/candidate/../../payroll/contract/test.pdf",
                "/media/base/announcement/file/test.pdf",
            ]:
                self.assertEqual(self.client.get(target, HTTP_AUTHORIZATION="Bearer local-test-token").status_code, 403)
            for target in ["/media/recruitment/candidate/resume/test.pdf", "/media/base/company/icon/test.png", "/media/employee/employee/employee_profile/test.png"]:
                self.assertEqual(self.client.get(target).status_code, 403 if user is None and "/candidate/" in target else 200)

    def test_dynamic_forms_retain_recruitment_and_block_hr_forms(self):
        self.client.force_login(self.user)
        for form in ["recruitment.forms.CandidateForm", "base.forms.JobPositionForm", "employee.forms.EmployeeForm"]:
            self.assertEqual(self.client.get("/reload-field", {"form_class_path": form}).status_code, 200)
        for form in ["payroll.forms.ContractForm", "base.forms.EmployeeShiftForm", "recruitment.forms..CandidateForm", "os.path"]:
            self.assertEqual(self.client.get("/reload-field", {"form_class_path": form}).status_code, 403)

    @override_settings(RECRUITMENT_ONLY=False)
    def test_switch_off_restores_original_routes_and_home(self):
        self.client.force_login(self.admin)
        for target in ["/", "/payroll/payslip/", "/api/base/", "/admin/", "/generic-delete?model=payroll.Contract"]:
            self.assertEqual(self.client.get(target).status_code, 200)


class ConfigurationTests(SimpleTestCase):
    def test_allowlisted_core_routes_exist_in_the_installed_source(self):
        self.assertFalse((BASE_ROUTES | STAFF_ROUTES) - source_names)

    def test_dynamic_class_based_handlers_validate_their_model(self):
        request = RequestFactory().get("/dynamic-payroll-table")
        request.user = SimpleNamespace(is_authenticated=True)
        request.resolver_match = ResolverMatch(ok, (), {}, url_name="dynamic-table")
        middleware = RecruitmentOnlyMiddleware(ok)
        for label, blocked in [("payroll.Contract", True), ("recruitment.Candidate", False)]:
            view = SimpleNamespace(view_class=SimpleNamespace(model=SimpleNamespace(_meta=SimpleNamespace(label=label))))
            with self.subTest(model=label), override_settings(RECRUITMENT_ONLY=True):
                response = middleware.process_view(request, view, (), {})
                self.assertEqual(response is not None, blocked)

    def test_stage_managers_keep_dashboard_access_without_a_global_permission(self):
        request = RequestFactory().get("/")
        request.user = SimpleNamespace(
            is_authenticated=True, has_perm=lambda permission: False,
            employee_get=SimpleNamespace(stage_set=SimpleNamespace(exists=lambda: True), recruitment_set=SimpleNamespace(exists=lambda: False)),
        )
        request.resolver_match = ResolverMatch(ok, (), {}, url_name="home-page")
        with override_settings(RECRUITMENT_ONLY=True):
            response = RecruitmentOnlyMiddleware(ok).process_view(request, ok, (), {})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/recruitment/dashboard")

    @override_settings(RECRUITMENT_ONLY=True)
    def test_hidden_modules_preserve_recruitment_and_employee_dependencies(self):
        for name in ["attendance", "leave", "payroll", "pms", "helpdesk", "offboarding", "onboarding", "asset", "project"]:
            self.assertFalse(module_visible(name))
        for name in ["recruitment", "employee", "base"]:
            self.assertTrue(module_visible(name))

    @override_settings(RECRUITMENT_ONLY=False)
    def test_switch_off_restores_template_visibility(self):
        self.assertTrue(module_visible("payroll"))

    def test_generic_model_labels_are_strict(self):
        for label in ["recruitment", "recruitment.", "recruitment.Candidate.other", ".Candidate", "payroll.Contract", "base.EmployeeShift"]:
            self.assertFalse(model_allowed(label))

    def test_rendered_settings_keep_required_sections_and_hide_hr_sections(self):
        engine = Engine(
            loaders=[
                ("django.template.loaders.locmem.Loader", {"index.html": "{% block content %}{% endblock %}"}),
                ("django.template.loaders.filesystem.Loader", [str(ROOT / "templates")]),
            ],
            libraries={"horillafilters": "recruitment_workspace.tests", "i18n": "django.templatetags.i18n", "static": "django.templatetags.static"},
        )
        permissions = defaultdict(lambda: defaultdict(lambda: True))
        for enabled in [True, False]:
            with override_settings(RECRUITMENT_ONLY=enabled):
                html = engine.get_template("settings.html").render(Context({"recruitment_only": enabled, "perms": permissions}))
            for label in ["Department", "Job Positions", "Job Role", "Company", "Recruitment"]:
                self.assertIn(label, html)
            for label in ["Attendance", "Leave", "Payroll", "Performance", "Help Desk", "Rotating Shift"]:
                with self.subTest(enabled=enabled, label=label):
                    if enabled:
                        self.assertNotIn(label, html)
                    else:
                        self.assertIn(label, html)
            self.assertEqual("Staff Users" in html, enabled)

    def test_changed_templates_compile_with_their_original_line_endings(self):
        filenames = [
            ROOT / "templates/settings.html", ROOT / "templates/sidebar.html",
            ROOT / "base/templates/base/general_settings.html",
            ROOT / "employee/templates/employee/view/individual.html",
            ROOT / "employee/templates/employee_nav.html", ROOT / "templates/floating_button.html",
        ]
        # Retain only template parsing here; substitute unchanged, model-bound
        # filters so the test never initializes the full Horilla application.
        def placeholder(value, argument=None):
            return value
        for filename in filenames:
            for name in re.findall(r"\|([a-zA-Z_]\w*)", filename.read_text()):
                if name not in register.filters:
                    register.filter(name, placeholder)
        engine = Engine(libraries={
            "horillafilters": "recruitment_workspace.tests", "basefilters": "recruitment_workspace.tests",
            "i18n": "django.templatetags.i18n", "static": "django.templatetags.static",
        })
        for filename in filenames:
            with self.subTest(template=filename.name):
                engine.from_string(filename.read_text())
