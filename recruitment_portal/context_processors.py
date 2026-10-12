from django.conf import settings
from django.urls import reverse

from .models import get_branding


def portal(request):
    if not getattr(settings, 'RECRUITMENT_ONLY', False):
        return {}
    brand = get_branding()
    if not brand.organization_name:
        from base.models import Company
        company = Company.objects.first()
        brand.organization_name = str(company) if company else 'Your company'
    navigation = []
    if request.user.is_authenticated:
        from recruitment import sidebar
        from recruitment_workspace.recruitment_mode import dashboard_accessible
        if dashboard_accessible(request.user):
            navigation.append({'label': 'Overview', 'url': reverse('recruitment-dashboard'), 'icon': 'grid', 'group': 'Hire'})
        entries = [('Jobs', 'recruitment-view', 'recruitment_accessibility', 'briefcase', 'Hire'),
                   ('Pipeline', 'pipeline', 'pipeline_accessibility', 'columns', 'Hire'),
                   ('Candidates', 'candidate-view', 'candidates_accessibility', 'users', 'Hire'),
                   ('Interviews', 'interview-view', 'interview_accessibility', 'calendar', 'Hire'),
                   ('Talent pool', 'skill-zone-view', 'skill_zone_accessibility', 'spark', 'Tools'),
                   ('Questionnaires', 'recruitment-survey-question-template-view', 'survey_accessibility', 'file', 'Tools'),
                   ('Hiring stages', 'rec-stage-view', 'stage_accessibility', 'steps', 'Tools')]
        for label, route, check, icon, group in entries:
            if getattr(sidebar, check)(request, {'redirect': reverse(route)}):
                navigation.append({'label': label, 'url': reverse(route) + ('?closed=false' if route == 'pipeline' else ''), 'icon': icon, 'group': group})
    for item in navigation:
        item['active'] = request.path == item['url'].split('?')[0]
    can_brand = request.user.is_authenticated and request.user.has_perm('recruitment_portal.change_portalbranding')
    return {'portal_brand': brand, 'portal_navigation': navigation, 'can_manage_brand': can_brand}
