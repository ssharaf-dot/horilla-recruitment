"""Append-only operational history. No CV text, passwords or AI keys are logged."""
from contextvars import ContextVar
from django.conf import settings
from django.db.models.signals import pre_save, post_save, m2m_changed
from django.utils import timezone

current_request = ContextVar('recruitment_activity_request', default=None)


def record_event(*, candidate=None, job=None, actor=None, kind, detail='', metadata=None, requisition=None):
    from .models import WorkflowEvent, ApplicantAccount
    request = current_request.get()
    applicant = None
    if actor is None and request is not None:
        user = getattr(request, 'user', None)
        match=getattr(request,'resolver_match',None)
        public=bool(match and (match.url_name or '').startswith(('applicant-','portal-')))
        actor = user if getattr(user, 'is_authenticated', False) and not public else None
        if not actor:
            applicant = ApplicantAccount.objects.filter(pk=request.session.get('applicant_account')).first()
    return WorkflowEvent.objects.create(candidate=candidate, job=job, actor=actor,
        applicant_actor=applicant, requisition=requisition, kind=kind, detail=detail, metadata=metadata or {})


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(request)
        try:
            response = self.get_response(request)
            # Successful named detail views only: no failed access, static assets,
            # health checks, credential forms or repeated document page images.
            match = getattr(request, 'resolver_match', None)
            views = {'workspace-candidate':'candidate', 'workspace-job':'job',
                     'applicant-detail':'candidate'}
            target = views.get(match.url_name) if match else None
            if response.status_code == 200 and request.method == 'GET' and target:
                from recruitment.models import Candidate, Recruitment
                obj = (Candidate if target == 'candidate' else Recruitment).objects.filter(pk=match.kwargs['pk']).first()
                if obj:
                    record_event(**{target:obj}, kind='view', detail='Candidate profile opened' if target=='candidate' else 'Job workspace opened')
            return response
        finally:
            current_request.reset(token)


# Only audit business state. Description bodies and personal contact values are
# deliberately not copied into the audit metadata; presence/field names suffice.
FIELDS = {
    'recruitment.recruitment': ['title','vacancy','is_published','closed','is_active','description','start_date','end_date'],
    'recruitment.candidate': ['name','recruitment_id_id','stage_id_id','hired','canceled','offer_letter_status','joining_date','is_active','resume'],
    'recruitment.interviewschedule': ['interview_date','interview_time','completed','description'],
    'recruitment.stagenote': ['description','candidate_can_view'],
    'recruitment_experience.candidateprofile': ['headline','about','experience','education','skills'],
    'recruitment_experience.requisition': ['status','approver_id','job_id','openings'],
    'recruitment_experience.hiringrequest': ['status','openings','decided_by_id','decision_note'],
    'recruitment_experience.vacancyprofile': ['division_id','location','work_type'],
    'recruitment_experience.interviewfeedback': ['recommendation','technical','communication','evidence'],
}


def before_save(sender, instance, raw=False, **kwargs):
    if raw or not getattr(settings,'RECRUITMENT_ONLY',False):
        return
    fields = FIELDS[sender._meta.label_lower]
    previous = sender._base_manager.filter(pk=instance.pk).first() if instance.pk else None
    instance._workspace_previous = {k:str(getattr(previous,k,'')) for k in fields} if previous else None


def after_save(sender, instance, created, raw=False, **kwargs):
    if raw or not getattr(settings,'RECRUITMENT_ONLY',False):
        return
    fields = FIELDS[sender._meta.label_lower]
    old = getattr(instance,'_workspace_previous',None)
    changed = [k for k in fields if old is None or old[k] != str(getattr(instance,k,''))]
    if not created and not changed:
        return
    label = sender._meta.label_lower
    if label=='recruitment.candidate' and not created and any(k in changed for k in ['stage_id_id','recruitment_id_id','canceled']):
        from .models import OfferApproval
        ids=list(OfferApproval.objects.filter(candidate=instance,status__in=['pending','approved']).values_list('pk',flat=True))
        if ids:
            OfferApproval.objects.filter(pk__in=ids).update(status='withdrawn',decision_note='Application selection changed; fresh approval is required.',decided_at=timezone.now())
            record_event(candidate=instance,kind='offer_approval',detail='Offer approval invalidated because application selection changed',metadata={'approvals':ids})
    candidate = job = requisition = None
    if label == 'recruitment.recruitment': job=instance
    elif label == 'recruitment.candidate': candidate=instance
    elif label == 'recruitment_experience.requisition': job=instance.job;requisition=instance
    elif label in ['recruitment_experience.hiringrequest','recruitment_experience.vacancyprofile']: job=instance.job
    elif label == 'recruitment_experience.candidateprofile': candidate=instance.candidate
    elif label == 'recruitment_experience.interviewfeedback': candidate=instance.interview.candidate_id
    else: candidate=getattr(instance,'candidate_id',None)
    if candidate is None and job is None and requisition is None:
        return  # Unlinked requisition history is recorded explicitly on linkage.
    safe = {'stage_id_id','hired','canceled','offer_letter_status','joining_date','is_active','vacancy','is_published','closed','start_date','end_date','status','approver_id','job_id','openings','recommendation','technical','communication','interview_date','interview_time','completed','candidate_can_view','division_id','location','work_type','decided_by_id'}
    changes = {k:{'before':old[k] if old else '', 'after':str(getattr(instance,k,''))} for k in changed if k in safe}
    if 'stage_id_id' in changes:
        from recruitment.models import Stage
        for key in ['before','after']:
            value=changes['stage_id_id'][key]
            stage=Stage._base_manager.filter(pk=value).first() if value and value!='None' else None
            changes['stage_id_id'][key]=stage.stage if stage else 'Not assigned'
    kind='created' if created else 'rejected' if label=='recruitment.candidate' and instance.canceled and 'canceled' in changed else 'updated'
    record_event(candidate=candidate,job=job,requisition=requisition,kind=kind,
        detail=sender._meta.verbose_name.title() + (' created' if created else ' updated') + ' · ' + ', '.join(k.removesuffix('_id').replace('_',' ') for k in changed),
        metadata={'model':label,'record':instance.pk,'changes':changes})


def team_changed(sender,instance,action,reverse,model,pk_set,**kwargs):
    if not getattr(settings,'RECRUITMENT_ONLY',False) or action not in ['post_add','post_remove','post_clear']:
        return
    from recruitment.models import Recruitment, InterviewSchedule
    if reverse:
        # Reverse-side changes still retain the employee and related object IDs.
        for obj in model._base_manager.filter(pk__in=pk_set or []):
            record_event(job=obj if isinstance(obj,Recruitment) else None,
                candidate=obj.candidate_id if isinstance(obj,InterviewSchedule) else None,
                kind='team',detail='Hiring team assignment changed',metadata={'action':action,'member':instance.pk})
    else:
        record_event(job=instance if isinstance(instance,Recruitment) else None,
            candidate=instance.candidate_id if isinstance(instance,InterviewSchedule) else None,
            kind='team',detail='Hiring team assignment changed',metadata={'action':action,'members':sorted(pk_set or [])})


def connect():
    from django.apps import apps
    for label in FIELDS:
        model=apps.get_model(label)
        pre_save.connect(before_save,sender=model,dispatch_uid='workspace_before_'+label,weak=False)
        post_save.connect(after_save,sender=model,dispatch_uid='workspace_after_'+label,weak=False)
    from recruitment.models import Recruitment, InterviewSchedule
    for model,field in [(Recruitment,'recruitment_managers'),(InterviewSchedule,'employee_id')]:
        m2m_changed.connect(team_changed,sender=getattr(model,field).through,dispatch_uid='workspace_team_'+field,weak=False)
