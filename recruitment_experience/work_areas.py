"""Four read-only work areas over the existing authorized recruitment workflows."""
from urllib.parse import urlencode
from django.http import Http404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from .access import recruiter, scoped_interviews
from .phase_data import candidate_phase, phase_scope
from .services import decorate_interview

AREAS = [
    dict(slug='requisitions', number=1, label='Requisitions & assignment', short='Requisitions', steps='01–03', icon='briefcase', purpose='Agree the hiring need, review the request and prepare the vacancy.', tabs=[('plan','Requests & approvals'),('registration','Vacancy registration')]),
    dict(slug='recruitment', number=2, label='Sourcing & selection', short='Recruitment', steps='04–08', icon='people', purpose='Manage vacancies, review CVs and coordinate interviews in one workspace.', tabs=[('jobs','My jobs'),('screen','CVs & screening'),('interview','Interviews & selection')]),
    dict(slug='offers', number=3, label='Offers & acceptance', short='Offers', steps='09–10', icon='document', purpose='Review the offer process and record confirmed candidate responses.', tabs=[('offer','Offer progress')]),
    dict(slug='joining', number=4, label='Joining & closure', short='Joining', steps='11–14', icon='check', purpose='Follow accepted candidates through actual joining and the receiving HR team.', tabs=[('handover','Joining board')]),
]
BY_AREA = {a['slug']: a for a in AREAS}
PHASE_AREA = dict(plan='requisitions', attract='recruitment', screen='recruitment', interview='recruitment', offer='offers', handover='joining')
STEPS = [
    (1,'Manpower requisition','Stakeholder','Available','Submit a hiring request. HRMS intake is not connected.'),
    (2,'HR Director review & assignment','HR Director','Partial','Named-approver decisions are available. Automatic Director routing and TA assignment are not configured.'),
    (3,'Vacancy registration','Assigned TA / HR','Partial','Prepare an approved vacancy and hiring team. Budget, target closure and AWFM registration need further implementation.'),
    (4,'Sourcing & candidate logging','Assigned TA','Partial','Applications and source are recorded. Prospect contacts and repeat call attempts are not yet tracked.'),
    (5,'CV submission','Assigned TA','Partial','Request a manager review from the candidate profile. Formal CV submission batches are not configured.'),
    (6,'CV screening','Stakeholder / HR','Available','Managers recommend; HR confirms stage changes and rejections.'),
    (7,'Interview coordination','Assigned TA / HR','Partial','Schedule, edit and download calendar files. Salary/notice-period tracking and invitation delivery are not configured.'),
    (8,'Interview & selection','Interviewer / HR','Available','Record interview evidence and recommendations. HR confirms the next stage.'),
    (9,'Offer approval','HR Director','Not configured','A separate HR Director approval gate and approved offer terms still need implementation. No approval is implied here.'),
    (10,'Offer management','Assigned TA / HR','Partial','Record actual sent, accepted or declined outcomes with evidence. Offer generation, signing, revocation and delivery are not connected.'),
    (11,'Pre-joining documentation','HR Operations / PRO','Not configured','Document verification checklists and HR Operations / PRO handoffs still need implementation.'),
    (12,'Pre-boarding & joining','TA / IT','Partial','Actual joining can be recorded. IT, SIM, NDA, welcome tasks and onboarding booking are not configured.'),
    (13,'Onboarding & handover','TA / Document Controller','Not configured','Document Controller acknowledgement and HRMS transfer are not connected.'),
    (14,'Reporting & closure','Assigned TA','Partial','Current summaries are available. Requisition closure controls, productivity tracking and AWFM reconciliation still need implementation.'),
]


def area_url(slug, request=None, tab=None):
    query={k:request.GET[k] for k in ['division','job'] if request and request.GET.get(k)}
    if tab: query['tab']=tab
    return reverse('workspace-area',args=[slug])+('?' + urlencode(query) if query else '')


def interface_context(request, data):
    counts={p['slug']:p['count'] for p in data['phase_nav']}
    active=getattr(request,'_workspace_area',None) or PHASE_AREA.get(data.get('phase_slug') or data.get('active'))
    if not active:
        active={'jobs':'recruitment','candidates':'recruitment','interviews':'recruitment','requests':'requisitions'}.get(data.get('active'))
    if data.get('candidate'): active=PHASE_AREA.get(candidate_phase(data['candidate']))
    descriptors={
        'requisitions':f"{counts.get('plan',0)} request"+('' if counts.get('plan',0)==1 else 's'),
        'recruitment':f"{counts.get('attract',0)} vacancies · {counts.get('screen',0)+counts.get('interview',0)} applications",
        'offers':f"{counts.get('offer',0)} applications",
        'joining':f"{counts.get('handover',0)} joiners",
    }
    scope=phase_scope(request)
    assigned=scope['requisitions'].filter(approver=request.user,status='pending').count()
    area=BY_AREA.get(active)
    current_tab=getattr(request,'_workspace_tab',None) or data.get('phase_slug') or {'jobs':'jobs','candidates':'screen','interviews':'interview','requests':'plan'}.get(data.get('active'))
    lower,upper={'requisitions':(1,3),'recruitment':(4,8),'offers':(9,10),'joining':(11,14)}.get(active,(0,0))
    step_rows=[dict(number=f'{n:02d}',label=label,owner=owner,status=status,detail=detail) for n,label,owner,status,detail in STEPS if lower<=n<=upper]
    rail=[]
    if not scope['aggregate']:
        appointments=[decorate_interview(i) for i in scoped_interviews(request.user).filter(candidate_id__in=scope['candidates'],completed=False)]
        from django.utils import timezone
        rail=sorted([i for i in appointments if not i.cancelled and i.dubai_time>=timezone.now()],key=lambda i:i.dubai_time)[:3]
    return dict(
        area_nav=[dict(a,url=area_url(a['slug'],request),current=active==a['slug'],descriptor=descriptors[a['slug']]) for a in AREAS],
        work_area=area, area_steps=step_rows,
        work_tabs=[dict(label=label,url=area_url(active,request,tab),current=tab==current_tab) for tab,label in area['tabs']] if area else [],
        assigned_approvals=assigned,rail_interviews=rail,rail_aggregate=scope['aggregate'],
        show_work_area_heading=bool(area and (data.get('phase_slug') or getattr(request,'_workspace_area',None))),
    )


@require_http_methods(['GET','HEAD'])
def area(request,slug):
    # Delegated views retain their existing login, object and role checks.
    if slug not in BY_AREA: raise Http404()
    spec=BY_AREA[slug]
    tab=request.GET.get('tab',spec['tabs'][0][0])
    if tab not in [t[0] for t in spec['tabs']]: raise Http404()
    request._workspace_area=slug;request._workspace_tab=tab
    from . import views,phase_views
    if tab=='jobs':
        from .access import leadership,scoped_jobs
        if request.user.is_authenticated and leadership(request.user) and not recruiter(request.user) and not scoped_jobs(request.user).exists():
            return phase_views.phase(request,'attract')
        return views.jobs(request)
    return phase_views.phase(request,'attract' if tab=='registration' else tab)
