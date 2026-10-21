from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core import serializers
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import BrandingForm, application_form_class
from .models import get_branding


def public_jobs():
    from recruitment.models import Recruitment
    today = timezone.localdate()
    return Recruitment.default.filter(is_active=True, is_published=True, closed=False, start_date__lte=today).filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).select_related('company_id', 'job_position_id').prefetch_related('open_positions', 'skills').order_by('-created_at', '-pk')


def enabled():
    if not settings.RECRUITMENT_ONLY:
        raise Http404()


@require_http_methods(['GET', 'HEAD'])
def careers(request):
    enabled()
    jobs = public_jobs()
    query = request.GET.get('q', '').strip()[:100]
    if query:
        jobs = jobs.filter(Q(title__icontains=query) | Q(open_positions__job_position__icontains=query)).distinct()
    return render(request, 'portal/careers.html', {'jobs': Paginator(jobs, 12).get_page(request.GET.get('page')), 'search_query': query, 'open_job_count': public_jobs().count()})


@require_http_methods(['GET', 'HEAD'])
def job_detail(request, pk):
    enabled()
    return render(request, 'portal/job_detail.html', {'job': get_object_or_404(public_jobs(), pk=pk)})


@require_http_methods(['GET', 'POST', 'HEAD'])
def apply(request, pk):
    enabled()
    job = get_object_or_404(public_jobs(), pk=pk)
    form = application_form_class()(request.POST or None, request.FILES or None, recruitment=job)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            candidate = form.save(commit=False)
            candidate.recruitment_id = job
            stages = job.stage_set.filter(is_active=True)
            candidate.stage_id = stages.filter(stage_type='applied').first() or stages.order_by('sequence').first()
            candidate.source = 'application'
            candidate.save()
        from recruitment_experience.views import attach_application
        attach_application(request, candidate)
        request.session['candidate'] = serializers.serialize('json', [candidate])
        from recruitment.models import RecruitmentSurvey
        if RecruitmentSurvey.objects.filter(recruitment_ids=job.pk).exists():
            from recruitment.views.surveys import candidate_survey
            return redirect(candidate_survey)
        return redirect('portal-application-received')
    return render(request, 'portal/apply.html', {'job': job, 'form': form})


@require_http_methods(['GET', 'HEAD'])
def application_received(request):
    enabled()
    return render(request, 'portal/received.html')


@login_required(login_url='login')
@permission_required('recruitment_portal.change_portalbranding', raise_exception=True)
@require_http_methods(['GET', 'POST', 'HEAD'])
def branding(request):
    enabled()
    brand = get_branding()
    form = BrandingForm(request.POST or None, request.FILES or None, instance=brand)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Portal settings saved. Your workspace and careers site now use this branding.')
        return redirect('portal-branding')
    return render(request, 'portal/branding.html', {'form': form})


@require_http_methods(['GET', 'HEAD'])
def logo(request):
    enabled()
    brand = get_branding()
    if not brand.logo:
        raise Http404()
    try:
        response = FileResponse(brand.logo.open('rb'), content_type='image/png')
    except FileNotFoundError:
        raise Http404()
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-cache'
    return response


@login_required(login_url='login')
def overview(request):
    enabled()
    from recruitment_experience.views import today, manager, ceo
    if request.user.has_perm('recruitment.view_recruitment'):
        return today(request)
    if request.user.has_perm('recruitment_experience.view_hiringoverview'):
        return ceo(request)
    return manager(request)
