"""Six-phase boards over existing recruitment workflows and permissions."""
from collections import OrderedDict
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from recruitment.models import Stage
from .access import recruiter, scoped_interviews
from .models import WorkflowEvent, ReviewRequest
from .phase_data import BY_SLUG, candidate_phase, phase_scope
from .services import decorate_interview, interview_time
from .views import workspace, context


def card_for(candidate, stage_names):
    event = candidate.board_events[0] if candidate.board_events else None
    previous = stage_names.get(event.metadata.get('previous')) if event else None
    if previous and previous.recruitment_id_id != candidate.recruitment_id_id:
        previous = None
    return dict(title=candidate.name, subtitle=candidate.recruitment_id.title, reference=f'Application #{candidate.pk}', url=reverse('workspace-candidate',args=[candidate.pk]), candidate=candidate, status=candidate.stage_id.stage if candidate.stage_id else 'Stage not assigned', owner='HR team', next_action='Review application', previous=previous.stage if previous else '', moved_at=event.created_at if event else None)


def column(label, guide, tone, cards=None):
    return dict(label=label, guide=guide, tone=str(tone), cards=cards or [])


def finish(columns):
    for item in columns:
        item['count']=len(item['cards'])
        item['cards']=sorted(item['cards'],key=lambda card: card.get('sort',0))
    return columns


def candidate_boards(request, scope, slug):
    rows = list(scope['candidates'].prefetch_related(Prefetch('workspace_events',queryset=WorkflowEvent.objects.filter(kind='stage').order_by('-created_at','-pk'),to_attr='board_events')))
    stages = {s.pk:s for s in Stage.objects.filter(recruitment_id__in=scope['jobs'])}
    cards = [(candidate,card_for(candidate,stages)) for candidate in rows if candidate_phase(candidate)==slug]
    if slug=='screen':
        groups=OrderedDict()
        reviews=set(ReviewRequest.objects.filter(candidate__in=[c.pk for c,_ in cards],completed_at__isnull=True).values_list('candidate_id',flat=True))
        for c,card in cards:
            label=c.stage_id.stage if c.stage_id else 'Stage not assigned'
            key=(label,c.stage_id.stage_type if c.stage_id else '')
            groups.setdefault(key,column(label,'Review the CV and role requirements. HR confirms the next stage.',2))['cards'].append(card)
            card['sort']=(c.stage_id.sequence or 0) if c.stage_id else -1
            if c.pk in reviews:
                card.update(owner='Requested hiring manager', next_action='Recommendation requested')
        if not groups:
            groups[('New applications','')]=column('New applications','New applications appear here for HR screening.',1)
        ordered=sorted(groups.values(),key=lambda g:min([c['sort'] for c in g['cards']] or [0]))
        for i,g in enumerate(ordered):g['tone']=str(min(2+i,4))
        return finish(ordered)
    if slug=='interview':
        columns=[column('To schedule','HR confirms a time and assigns interviewers.',2),column('Interview booked','Prepare for the next scheduled assessment.',3),column('Feedback due','Submit the outstanding interview evidence.',3),column('Decision pending','HR reviews completed assessments and confirms the next step.',4)]
        appointments={}
        for appointment in scoped_interviews(request.user).filter(candidate_id__in=[c.pk for c,_ in cards]):
            item=decorate_interview(appointment)
            if not item.cancelled:appointments.setdefault(item.candidate_id_id,[]).append(item)
        for c,card in cards:
            meetings=appointments.get(c.pk,[])
            past=[m for m in meetings if interview_time(m)<timezone.now() and not m.completed]
            future=[m for m in meetings if interview_time(m)>=timezone.now() and not m.completed]
            index=2 if past else 1 if future else 3 if meetings else 0
            if future:
                next_one=min(future,key=interview_time)
                card['detail']=next_one.dubai_time.strftime('%d %b · %H:%M Dubai')
            card['next_action']=['Schedule / review with HR','Prepare for interview','Complete assessment feedback','Review selection evidence'][index]
            card['owner']='Interviewers / HR' if index==2 else 'HR team'
            columns[index]['cards'].append(card)
        return finish(columns)
    if slug=='offer':
        columns=[column('Prepare offer','HR confirms terms and authorization before issuing an offer.',4),column('Awaiting response','The offer is recorded as sent; acceptance is still outstanding.',5)]
        for c,card in cards:
            index=1 if c.offer_letter_status=='sent' else 0
            card.update(status=c.get_offer_letter_status_display(),owner='Applicant / HR' if index else 'HR team',next_action='Record offer response' if index else 'Record confirmed offer outcome')
            if recruiter(request.user):card['action_url']=reverse('workspace-offer',args=[c.pk])
            columns[index]['cards'].append(card)
        return finish(columns)
    columns=[column('Joining preparation','Accepted offer; HR confirms joining arrangements. No HRMS handover is implied.',5),column('Joined · handover pending','Joining is recorded. HRMS acknowledgement still needs a connected workflow.',6)]
    for c,card in cards:
        index=int(c.offer_letter_status=='joined')
        card.update(status=c.get_offer_letter_status_display(),next_action='Coordinate HRMS handover' if index else 'Confirm joining arrangements',detail='HRMS connection not configured')
        if recruiter(request.user) and not index:
            card['action_url']=reverse('workspace-offer',args=[c.pk]);card['next_action']='Record actual joining when confirmed'
        columns[index]['cards'].append(card)
    return finish(columns)


def workflow_overview(request):
    scope=phase_scope(request)
    if scope['aggregate']:
        return {}
    rows=list(scope['candidates'].prefetch_related(Prefetch('workspace_events',queryset=WorkflowEvent.objects.filter(kind='stage').order_by('-created_at','-pk'),to_attr='board_events')))
    stage_names={s.pk:s for s in Stage.objects.filter(recruitment_id__in=scope['jobs'])}
    columns=[column(BY_SLUG[s]['label'],BY_SLUG[s]['purpose'],i+3) for i,s in enumerate(['screen','interview','offer','handover'])]
    for col,slug in zip(columns,['screen','interview','offer','handover']):
        selected=[c for c in rows if candidate_phase(c)==slug]
        col.update(count=len(selected),cards=[card_for(c,stage_names) for c in selected[:4]],url=reverse('workspace-phase',args=[slug])+('?'+request.GET.urlencode() if request.GET else ''),hidden=max(len(selected)-4,0))
    return dict(pipeline_columns=columns,closed_count=sum(candidate_phase(c)=='closed' for c in rows),application_total=len(rows))


@workspace
@require_http_methods(['GET','HEAD'])
def phase(request,slug):
    if slug not in BY_SLUG:raise Http404()
    if slug=='plan':
        from .requisitions import overview
        return overview(request)
    spec=BY_SLUG[slug];scope=phase_scope(request);columns=[]
    if slug=='plan':
        columns=[column('Awaiting approval','The named approver reviews the staffing need.',1),column('Approved · prepare vacancy','HR prepares an approved request as a draft vacancy.',2),column('Vacancy / openings prepared','Continue with the approved vacancy or updated openings.',3),column('Declined','Keep the decision and reason for reference.','closed')]
        for item in scope['requisitions'].select_related('division','approver','requested_by','job'):
            index=3 if item.status=='declined' else 2 if item.job_id else 1 if item.status=='approved' else 0
            card=dict(title=item.title,subtitle=str(item.division),reference=f'Requisition #{item.pk}',status=item.get_status_display(),owner=str(item.approver.get_full_name() or item.approver.username) if index==0 else 'HR team',next_action='Review requisition',url=reverse('workspace-requisitions')+'#requisition-'+str(item.pk))
            if index==1 and recruiter(request.user):card.update(action_url=reverse('workspace-vacancy-new')+'?requisition='+str(item.pk),next_action='Prepare approved vacancy')
            columns[index]['cards'].append(card)
        for item in scope['additional_requests'].select_related('job','requested_by'):
            index=3 if item.status=='declined' else 2 if item.status=='approved' else 0
            columns[index]['cards'].append(dict(title=item.job.title,subtitle=f'{item.openings} additional openings',reference=f'Opening request #{item.pk}',status=item.get_status_display(),owner='Authorized leadership approver',next_action='Review opening request',url=reverse('workspace-requests')+'#request-'+str(item.pk)))
        finish(columns)
    elif slug=='attract':
        columns=[column('Preparing vacancy','Complete the role, division, questions and hiring team.',2),column('Published','Candidates can explore published vacancies on the careers site.',3),column('Recruitment closed','Existing applications and their history are retained.','closed')]
        for job in scope['jobs'].select_related('company_id','workspace_profile__division'):
            index=2 if job.closed else 1 if job.is_published else 0
            profile=getattr(job,'workspace_profile',None)
            card=dict(title=job.title,subtitle=str(profile.division) if profile and profile.division else 'Division not assigned',reference=f'Vacancy #{job.pk}',status=['Draft','Published','Closed'][index],owner='HR team',next_action='Open vacancy',url=None if scope['aggregate'] else reverse('workspace-job',args=[job.pk]),detail='Employer: '+str(job.company_id))
            if recruiter(request.user):card.update(action_url=reverse('workspace-publish',args=[job.pk]),next_action='Review publication checklist')
            columns[index]['cards'].append(card)
        finish(columns)
    elif scope['aggregate']:
        columns=[column('Division overview',spec['purpose'],spec['number'])]
        counts={}
        for c in scope['candidates'].select_related('recruitment_id__workspace_profile__division'):
            if candidate_phase(c)!=slug:continue
            profile=getattr(c.recruitment_id,'workspace_profile',None)
            label=str(profile.division) if profile and profile.division else 'Division not assigned'
            counts[label]=counts.get(label,0)+1
        for label,total in counts.items():
            columns[0]['cards'].append(dict(title=label,reference=f'{total} '+spec['unit'],subtitle='Permitted division · aggregate only',status='Current workload',owner=spec['owner'],next_action='Review leadership overview',url=reverse('workspace-ceo')))
        finish(columns)
        # Column count is application volume, not the number of division cards.
        columns[0]['count']=sum(counts.values())
    else:
        columns=candidate_boards(request,scope,slug)
    total=sum(c['count'] for c in columns)
    return render(request,'experience/phase.html',context(request,active=slug,phase_slug=slug,title=spec['label'],phase=spec,columns=columns,phase_total=total,aggregate_only=scope['aggregate'],phase_jobs=scope['available_jobs'].order_by('title'),selected_job=request.GET.get('job','')))
