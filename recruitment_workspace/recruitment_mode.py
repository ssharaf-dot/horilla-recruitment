"""A reversible HTTP boundary for the existing Horilla recruitment workflow.

This is an additional restriction, never a replacement for Horilla's view
permissions. Applications, models, signals and migrations remain installed.
"""

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin
from django.utils.translation import gettext as _


HIDDEN_MODULES = frozenset({
    "attendance", "leave", "payroll", "pms", "helpdesk", "offboarding",
    "onboarding", "asset", "project", "biometric", "geofencing",
    "facedetection", "report", "horilla_automations", "horilla_backup",
})

# Shared authentication, organisation, email and permission administration.
# Explicit names also prevent unrelated HR settings hosted by base.urls from
# slipping through merely because they belong to the base app.
BASE_ROUTES = frozenset({
    "portal-careers", "portal-job-detail", "portal-apply", "portal-application-received",
    "portal-logo", "portal-branding",
    "applicant-home", "applicant-login", "applicant-register", "applicant-logout",
    "applicant-detail", "applicant-cv", "applicant-questionnaire", "workspace-applicant-preview",
    "home-page", "404", "login", "forgot-password", "employee-reset-password",
    "reset-send-success", "change-password", "change-username", "two-factor",
    "send-otp", "logout", "settings", "general-settings", "user-group-create",
    "user-group-view", "user-group-search", "user-group-delete",
    "group-permission-remove", "user-group-assign-view", "user-group-assign",
    "group-remove-user", "employee-permission-assign", "permission-search",
    "update-user-permission", "update-group-permission", "permission-table",
    "mail-server-conf", "mail-server-create-update", "mail-server-test-email",
    "mail-server-delete", "replace-primary-mail", "view-mail-templates",
    "view-mail-template", "create-mail-template", "duplicate-mail-template",
    "delete-mail-template", "company-create", "company-view", "company-update",
    "company-delete", "department-view", "department-creation",
    "department-update", "department-delete", "job-position-creation",
    "job-position-view", "job-position-update", "job-position-delete",
    "job-role-create", "job-role-view", "job-role-update", "job-role-delete",
    "update-selected-company", "date-settings", "save_date_format", "get-date-format", "save_time_format",
    "get-time-format", "enable-account-block-unblock",
    "enable-profile-edit-feature", "pagination-settings-view", "tag-view",
    "tag-create", "tag-update", "tag-delete", "audit-tag-create",
    "audit-tag-update", "audit-tag-delete", "notifications", "clear-notifications",
    "delete-all-notifications", "read-notifications", "mark-as-read-notification",
    "mark-as-read-notification-json", "all-notifications", "delete-notifications",
    "protected_media",
})

# Horilla logins and recruiter/manager relationships require Employee and work
# information records. Keep their existing protected administration routes.
STAFF_ROUTES = frozenset({
    "get-language-code", "employee-profile", "employee-view-individual",
    "edit-profile", "profile-edit-access", "update-profile-image",
    "update-own-profile-image", "remove-profile-image", "remove-own-profile-image",
    "employee-view", "employee-view-new", "employee-view-update",
    "employee-create-personal-info", "employee-update-personal-info",
    "employee-create-work-info", "employee-update-work-info", "employee-filter-view",
    "employee-profile-bank-update", "employee-create-bank-details",
    "employee-update-bank-details", "employee-bank-details-view-create",
    "employee-bank-details-view-update",
    "employee-view-card", "employee-view-list", "search-employee", "employee-update",
    "employee-archive", "employee-delete", "employee-bulk-archive", "employee-bulk-delete", "employee-bulk-mail",
    "employee-account-block-unblock", "employee-user-group-assign-delete",
    "employee-work-info-view-create", "employee-work-info-view-update", "about-tab",
    "employee-select", "employee-select-filter", "employee-widget-filter", "get-manager-in",
    "get-job-positions", "get-job-roles", "initial-prefix", "get-first-last-badge-id",
    "note-tab", "add-employee-note", "add-employee-note-post", "employee-note-update",
    "add-more-files-employee", "delete-employee-note-file", "employee-note-delete",
    "employee-get-mail-log", "send-mail-employee", "send-mail-to-employee",
    "get-template-employee", "get-employee-mail-preview",
})

SHARED_ROUTES = frozenset({
    "health", "set_language", "user-accessibility", "get-initial-accessibility-data",
    "toggle-columns", "active-tab", "cbv-active-group", "reload-messages",
    "saved-filter", "saved-filter-update", "delete-saved-filter",
    "active-hnv-view-type", "search-in-instance-ids", "last-applied-filter",
})

SHARED_MODELS = frozenset({
    "base.company", "base.department", "base.jobposition", "base.jobrole",
    "base.horillamailtemplate", "employee.employee", "employee.employeeworkinformation",
    "employee.employeenote",
    "auth.user", "auth.group",
})

SHARED_FORMS = frozenset({
    "base.forms.CompanyForm", "base.forms.DepartmentForm", "base.forms.JobPositionForm",
    "base.forms.JobRoleForm", "base.forms.MailTemplateForm", "employee.forms.EmployeeForm",
    "employee.forms.EmployeeWorkInformationForm", "employee.forms.EmployeeBankDetailsForm",
})


def recruitment_only():
    return getattr(settings, "RECRUITMENT_ONLY", False)


def module_visible(app_name):
    """Template visibility only; django.apps.is_installed is never changed."""
    return not recruitment_only() or app_name not in HIDDEN_MODULES


def context(request):
    return {"recruitment_only": recruitment_only()}


def dashboard_accessible(user):
    # Match the existing dashboard's permission-or-manager rule. Its denial
    # script sends users back to '/', so reject here to avoid a landing loop.
    if user.has_perm("recruitment.view_recruitment") or user.has_perm("recruitment_experience.view_hiringoverview"):
        return True
    employee = getattr(user, "employee_get", None)
    return employee is not None and (
        employee.stage_set.exists() or employee.recruitment_set.exists()
        or (getattr(employee, "interviewschedule_set", None) is not None and employee.interviewschedule_set.exists())
    )


def model_allowed(label):
    label = label.lower()
    app, separator, model = label.partition(".")
    return bool(separator and model.isidentifier()) and (
        app == "recruitment" or label in SHARED_MODELS
    )


def media_allowed(path):
    # Prevent a permitted prefix being used with '../' to reach an HR file.
    if path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    parts = path.split("/")
    if any(part in {".", ".."} for part in parts) or len(parts) < 3:
        return False
    return path.startswith("base/icon/") or model_allowed(".".join(parts[:2]))


def route_allowed(request, view_func):
    path = request.path_info.lstrip("/")
    first_segment = path.split("/", 1)[0]
    if path == "health/":
        return True
    # This version has no recruitment REST API. Reject APIs before their token
    # authentication executes; session authentication alone is not sufficient.
    if first_segment in HIDDEN_MODULES or first_segment in {"api", "admin"}:
        return False
    if first_segment in {"recruitment", "accounts", "inbox", "i18n"}:
        return True

    match = request.resolver_match
    name = match.url_name if match else None
    if name == "protected_media":
        return media_allowed(match.kwargs.get("path", ""))
    if name in {"generic-delete", "history-revert"}:
        label = request.GET.get("model", "").lower()
        if not model_allowed(label) or not request.user.is_authenticated:
            return False
        app, model = label.split(".")
        action = "delete" if name == "generic-delete" else "change"
        return request.user.has_perm(f"{app}.{action}_{model}")
    if name == "reload-field":
        form = request.GET.get("form_class_path", "")
        return request.user.is_authenticated and (
            form in SHARED_FORMS or (
                form.startswith("recruitment.forms.")
                and all(part.isidentifier() for part in form.split("."))
            )
        )
    if name == "get-filter-form":
        return request.user.is_authenticated and request.GET.get("template_path") == "employee_filters.html"
    if name in BASE_ROUTES | STAFF_ROUTES | SHARED_ROUTES:
        return True
    # Generic handlers can operate on any installed model. Validate the target
    # before the handler executes, including for superusers and POST requests.
    view_class = getattr(view_func, "view_class", None)
    model = getattr(view_class, "model", None)
    meta = getattr(model, "_meta", None)
    if meta:
        return model_allowed(meta.label)
    return False


class RecruitmentOnlyMiddleware(MiddlewareMixin):
    def process_request(self, request):
        if recruitment_only():
            first_segment = request.path_info.lstrip("/").split("/", 1)[0]
            if first_segment in HIDDEN_MODULES | {"api", "admin"}:
                return HttpResponseForbidden(
                    _("This module is unavailable in recruitment-only mode.")
                )

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not recruitment_only():
            return None
        if not route_allowed(request, view_func):
            return HttpResponseForbidden(
                _("This module is unavailable in recruitment-only mode.")
            )
        if request.resolver_match.url_name == "open-recruitments" and request.method in {"GET", "HEAD"}:
            return redirect("portal-careers")
        if (
            request.resolver_match.url_name in {"home-page", "recruitment-dashboard"}
            and request.user.is_authenticated
            and not dashboard_accessible(request.user)
        ):
            return HttpResponseForbidden(
                _("Ask your administrator for access to Recruitment.")
            )
        if (
            request.resolver_match.url_name == "home-page"
            and request.user.is_authenticated
            and request.method in {"GET", "HEAD"}
        ):
            return redirect("recruitment-dashboard")
        # Authentication, object permissions and recruitment-manager checks
        # remain the responsibility of the unmodified original view.
        return None
