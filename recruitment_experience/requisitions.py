"""Three explicit, server-enforced steps for the staffing need before sourcing."""
import uuid
from django import forms
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .access import recruiter, scoped_jobs, employee_for
from .activity import record_event
from .models import Requisition, JDDraft, JDProviderConfig
from .phase_data import phase_scope, permitted_requisitions
from .views import workspace, context
from .jd import digest, generate, provider_configured

STEPS = [
    (1,'Raise Requisition','Hiring manager / HR','Define the need. Write or attach the JD and KPA, then submit.'),
    (2,'CEO Approval & TA Assignment','CEO → HR Director','The CEO approves the need. The HR Director then assigns one TA.'),
    (3,'Register Vacancy','Assigned TA','Carry the approved need into a draft vacancy, then start sourcing.'),
]


def name(user):
    return user.get_full_name() or user.username if user else 'Not assigned'


def editable(user, item):
    return item.status in ['draft','changes'] and (item.requested_by_id==user.pk or (recruiter(user) and permitted_requisitions(user).filter(pk=item.pk).exists())) and not item.job_id


def can_register(user,item):
    # An explicit Director assignment is required; legacy approved rows are not
    # silently treated as having completed the new assignment workflow.
    return (item.status=='approved' and item.ta_owner_id is not None and item.assigned_at is not None
            and item.ta_owner.is_active and recruiter(item.ta_owner)
            and (user.is_superuser or (recruiter(user) and item.ta_owner_id==user.pk))
            and permitted_requisitions(user).filter(pk=item.pk).exists())


def step_for(item):
    return 3 if item.job_id or (item.status=='approved' and item.ta_owner_id and item.assigned_at) else 1 if item.status in ['draft','changes'] else 2


def steps(selected=1,item=None,counts=None):
    result=[]
    for n,label,owner,detail in STEPS:
        complete=bool(item and ((n==1 and item.submitted_at and item.status not in ['draft','changes']) or (n==2 and item.status=='approved' and item.assigned_at) or (n==3 and item.job_id)))
        result.append(dict(number=n,label=label,owner=owner,detail=detail,current=n==selected,complete=complete,
            count=(counts or {}).get(n),url=(reverse('workspace-requisition-detail',args=[item.pk])+'#step-'+str(n)) if item else reverse('workspace-area',args=['requisitions'])+'?tab='+{1:'plan',2:'review',3:'registration'}[n]))
    return result


def page_context(request,**values):
    request._workspace_area='requisitions'
    return context(request,active='requests',**values)


@workspace
@require_http_methods(['GET','HEAD','POST'])
def overview(request):
    # Keep old bookmarks and legacy POSTs safe: the new mandatory JD/KPA checks
    # apply regardless of whether the wizard or the old requisition URL is used.
    if request.method=='POST':return edit(request)
    tab=request.GET.get('tab','plan')
    selected={'plan':1,'review':2,'registration':3}.get(tab)
    if not selected:raise Http404()
    rows=list(phase_scope(request)['requisitions'].select_related('division','employer','requested_by','approver','assignment_director','ta_owner','job').order_by('-created_at'))
    counts={n:sum(step_for(r)==n and r.status!='declined' for r in rows) for n in [1,2,3]}
    selected_rows=[r for r in rows if step_for(r)==selected and r.status!='declined']
    for row in selected_rows:
        row.next_owner=name(row.requested_by if selected==1 else row.approver if row.status=='pending' else row.assignment_director if selected==2 else row.ta_owner)
        row.next_action='Edit and submit' if selected==1 else 'CEO review' if row.status=='pending' else 'Assign TA owner' if selected==2 else 'Open vacancy' if row.job_id else 'Register vacancy'
    return render(request,'experience/requisition_overview.html',page_context(request,title='Requisitions & Assignments',wizard_steps=steps(selected,counts=counts),selected_step=selected,step_detail=STEPS[selected-1][3],items=selected_rows,declined=[r for r in rows if r.status=='declined'],can_request=recruiter(request.user) or scoped_jobs(request.user).exists()))


class RequestForm(forms.ModelForm):
    expected_version=forms.IntegerField(widget=forms.HiddenInput,initial=1)
    confirm=forms.BooleanField(required=False,label='I have reviewed the hiring need, JD and KPA and am ready to submit for CEO approval')
    class Meta:
        model=Requisition
        fields=['title','division','employer','openings','reason','jd_text','jd_document','kpa_text','kpa_document','approver','assignment_director']
        labels={'title':'Role title','employer':'Legal employer','openings':'Number of openings','reason':'Why is this role needed?','jd_text':'Job description (JD)','jd_document':'Or attach a JD (PDF)','kpa_text':'Key performance areas (KPA)','kpa_document':'Or attach a KPA (PDF)','approver':'CEO approver','assignment_director':'HR Director for TA assignment'}
        widgets={key:forms.Textarea(attrs={'rows':rows}) for key,rows in [('reason',3),('jd_text',10),('kpa_text',5)]}
    def __init__(self,*args,user,**kwargs):
        from .operations import allowed_divisions
        super().__init__(*args,**kwargs)
        self.fields['division'].queryset=allowed_divisions(user)
        self.fields['approver'].queryset=User.objects.filter(is_active=True).filter(Q(is_superuser=True)|Q(user_permissions__codename='approve_hiringrequest')|Q(groups__permissions__codename='approve_hiringrequest')).exclude(pk=user.pk).distinct()
        self.fields['assignment_director'].queryset=User.objects.filter(is_active=True).filter(Q(is_superuser=True)|Q(user_permissions__codename='approve_offer')|Q(groups__permissions__codename='approve_offer')).distinct()
        for key in ['approver','assignment_director']:self.fields[key].required=False
        for key in ['jd_document','kpa_document']:
            self.fields[key].widget=forms.FileInput(attrs={'accept':'application/pdf'})
            self.fields[key].help_text='Private PDF, maximum 5 MB. A reviewed text version can be used instead. Saving a replacement retains the original in storage for recovery.'
    def clean(self):
        values=super().clean()
        # Validate actual PDF bytes and parser, not the supplied MIME type/name.
        for key in ['jd_document','kpa_document']:
            upload=self.files.get(key)
            if upload:
                import fitz
                try:
                    if upload.size>5*1024*1024:raise ValueError()
                    data=upload.read();upload.seek(0)
                    if not data.startswith(b'%PDF-'):raise ValueError()
                    pdf=fitz.open(stream=data,filetype='pdf')
                    valid=not pdf.is_encrypted and 0<pdf.page_count<=50
                    pdf.close()
                    if not valid:raise ValueError()
                except (RuntimeError,ValueError):self.add_error(key,'Upload a readable, unencrypted PDF with 1–50 pages, no larger than 5 MB.')
                else:upload.name=uuid.uuid4().hex+'.pdf'
        return values


@workspace
@require_http_methods(['GET','POST'])
def edit(request,pk=None):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk) if pk else None
    if item and not editable(request.user,item):raise PermissionDenied('Only a draft or returned requisition can be edited. Submitted requirements are locked for review.')
    if not item and not (recruiter(request.user) or scoped_jobs(request.user).exists()):raise PermissionDenied()
    form=RequestForm(request.POST or None,request.FILES or None,instance=item,user=request.user,initial={'expected_version':item.version if item else 1})
    if request.method=='POST' and form.is_valid():
        submit=request.POST.get('action')=='submit'
        if submit:
            for text,file in [('jd_text','jd_document'),('kpa_text','kpa_document')]:
                if len(form.cleaned_data.get(text,'').strip())<40 and not form.cleaned_data.get(file):form.add_error(text,'Provide a reviewed description (at least 40 characters) or attach a PDF before submission.')
            for key in ['approver','assignment_director']:
                if not form.cleaned_data.get(key):form.add_error(key,'Select the next owner before submission.')
            if not form.cleaned_data['confirm']:form.add_error('confirm','Review and confirm the JD and KPA before submitting.')
        if not form.errors:
            with transaction.atomic():
                current=Requisition.objects.select_for_update().get(pk=item.pk) if item else None
                if current and (not editable(request.user,current) or current.version!=form.cleaned_data['expected_version']):form.add_error(None,'This requisition changed. Reload its latest version before saving.')
                else:
                    value=form.save(commit=False)
                    if not item:value.requested_by=request.user
                    value.version=(current.version if current else 0)+1
                    value.status='pending' if submit else current.status if current else 'draft'
                    if submit:value.submitted_at=timezone.now();value.decided_at=None;value.decision_note=''
                    value.save()
                    record_event(requisition=value,kind='requisition_submitted' if submit else 'requisition_draft',detail='Step 1: reviewed JD and KPA submitted for CEO approval' if submit else 'Step 1: requisition draft saved',metadata={'version':value.version})
                    messages.success(request,'Step 1 complete. The named CEO approver now reviews the hiring need.' if submit else 'Draft saved. Continue Step 1 when ready; no vacancy has been created.')
                    return redirect('workspace-requisition-detail',pk=value.pk)
    return render(request,'experience/requisition_edit.html',page_context(request,title='Step 1 · Raise Requisition',item=item,form=form,wizard_steps=steps(1,item),ai_ready=provider_configured()))


@workspace
@require_http_methods(['GET','HEAD'])
def detail(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user).select_related('division','employer','requested_by','approver','assignment_director','ta_owner','assigned_by','job'),pk=pk)
    item.ceo_name=name(item.approver);item.director_name=name(item.assignment_director);item.ta_name=name(item.ta_owner);item.assigner_name=name(item.assigned_by)
    events=list(item.activity_events.select_related('actor').order_by('-created_at','-pk')[:60])
    for event in events:event.display_actor=name(event.actor) if event.actor else event.actor_label or 'System'
    can_decide=item.status=='pending' and item.approver_id==request.user.pk and request.user.has_perm('recruitment_experience.approve_hiringrequest')
    can_assign=item.status=='approved' and not item.job_id and item.assignment_director_id==request.user.pk and request.user.has_perm('recruitment_experience.approve_offer')
    form=AssignmentForm(requisition=item,initial={'expected_version':item.version,'ta_owner':item.ta_owner_id}) if can_assign else None
    return render(request,'experience/requisition_detail.html',page_context(request,title=item.title,item=item,wizard_steps=steps(step_for(item),item),can_edit=editable(request.user,item),can_decide=can_decide,can_assign=can_assign,assignment_form=form,can_register=can_register(request.user,item),events=events))


@workspace
@require_http_methods(['POST'])
def decision(request,pk):
    with transaction.atomic():
        item=get_object_or_404(permitted_requisitions(request.user).select_for_update(),pk=pk)
        if item.approver_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_hiringrequest'):raise PermissionDenied()
        action=request.POST.get('decision');note=request.POST.get('note','').strip()[:2000]
        if item.status!='pending' or str(item.version)!=request.POST.get('expected_version'):messages.error(request,'The request changed. Reload before recording a decision.')
        elif action not in ['approved','changes','declined'] or request.POST.get('confirm')!='yes':messages.error(request,'Confirm the decision before continuing.')
        elif action in ['changes','declined'] and not note:messages.error(request,'Explain what must change or why the request is declined.')
        elif action=='approved' and not ((item.jd_text.strip() or item.jd_document) and (item.kpa_text.strip() or item.kpa_document) and item.assignment_director_id):messages.error(request,'This legacy request needs a JD, KPA and assignment Director. Return it for changes before approval.')
        else:
            item.status=action;item.decision_note=note;item.decided_at=timezone.now();item.version+=1;item.save()
            record_event(requisition=item,kind='requisition_decision',detail='Step 2: CEO '+{'approved':'approved the hiring need','changes':'requested changes','declined':'declined the hiring need'}[action],metadata={'decision':action,'version':item.version})
            messages.success(request,'CEO decision recorded. '+('The HR Director now assigns a TA owner.' if action=='approved' else 'The requester can revise and resubmit.' if action=='changes' else 'The request remains in history.'))
    return redirect('workspace-requisition-detail',pk=pk)


class AssignmentForm(forms.Form):
    ta_owner=forms.ModelChoiceField(queryset=User.objects.none(),label='One TA owner')
    expected_version=forms.IntegerField(widget=forms.HiddenInput)
    confirm=forms.BooleanField(label='I confirm this TA is responsible for registering and progressing this approved requisition')
    def __init__(self,*args,requisition,**kwargs):
        super().__init__(*args,**kwargs)
        # Eligible active HR coordinators with staff/employer records and access
        # to this division; assigning an account does not grant it new roles.
        ids=[u.pk for u in User.objects.filter(is_active=True) if recruiter(u) and employee_for(u) and permitted_requisitions(u).filter(pk=requisition.pk).exists()]
        self.fields['ta_owner'].queryset=User.objects.filter(pk__in=ids).order_by('username')


@workspace
@require_http_methods(['POST'])
def assign(request,pk):
    with transaction.atomic():
        item=get_object_or_404(permitted_requisitions(request.user).select_for_update(),pk=pk)
        if item.assignment_director_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_offer'):raise PermissionDenied()
        form=AssignmentForm(request.POST,requisition=item)
        if not form.is_valid():messages.error(request,'Select an active TA with access to this division and confirm the assignment.')
        elif item.status!='approved' or item.job_id or item.version!=form.cleaned_data['expected_version']:messages.error(request,'CEO approval is required and registered vacancies cannot be reassigned here. Reload the latest request.')
        else:
            item.ta_owner=form.cleaned_data['ta_owner'];item.assigned_by=request.user;item.assigned_at=timezone.now();item.version+=1;item.save()
            record_event(requisition=item,kind='requisition_assignment',detail='Step 2 complete: HR Director assigned TA owner',metadata={'ta_owner_id':item.ta_owner_id,'version':item.version})
            messages.success(request,'TA assigned. Step 3 is now ready for that TA to register the vacancy.')
    return redirect('workspace-requisition-detail',pk=pk)


@workspace
@require_http_methods(['GET'])
def document(request,pk,kind):
    if kind not in ['jd','kpa']:raise Http404()
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    field=getattr(item,kind+'_document')
    if not field:raise Http404()
    try:response=FileResponse(field.open('rb'),as_attachment=True,filename=f'requisition-{pk}-{kind}.pdf',content_type='application/pdf')
    except (OSError,FileNotFoundError):raise Http404()
    response['X-Content-Type-Options']='nosniff'
    record_event(requisition=item,kind='requisition_document',detail=kind.upper()+' attachment downloaded')
    return response


@workspace
@require_http_methods(['GET','POST'])
def ai_draft(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if not editable(request.user,item):raise PermissionDenied('Draft only before submitting the requisition.')
    class BriefForm(forms.Form):
        brief=forms.CharField(max_length=6000,label='Describe the role you need',widget=forms.Textarea(attrs={'rows':7}))
        expected_version=forms.IntegerField(widget=forms.HiddenInput,initial=item.version)
        consent=forms.BooleanField(label='Send only this role title and brief to Anthropic (Claude) to draft a JD for my review')
    form=BriefForm(request.POST or None);ready=provider_configured();draft=None
    if request.method=='POST' and form.is_valid():
        if not ready:form.add_error(None,'Claude is not connected. No external request was sent. You can write or attach the JD in Step 1.')
        elif not cache.add('jd-draft:'+str(request.user.pk),True,60):form.add_error(None,'Wait one minute before requesting another draft.')
        else:
            with transaction.atomic():
                config=JDProviderConfig.objects.select_for_update().get(pk=1)
                current=Requisition.objects.select_for_update().get(pk=pk)
                attempts=JDDraft.objects.filter(provider='anthropic',created_at__date=timezone.localdate())
                if not editable(request.user,current) or current.version!=form.cleaned_data['expected_version']:form.add_error(None,'The requisition changed. Reload before generating a draft.')
                elif attempts.filter(author=request.user).count()>=10 or attempts.count()>=100:form.add_error(None,'The daily demo drafting allowance has been reached.')
                else:draft=JDDraft.objects.create(requisition=current,author=request.user,brief=form.cleaned_data['brief'],source_description_sha256=digest(current.jd_text),provider='anthropic',model_name=config.model_name,status='failed')
            if draft:
                try:text,model_name=generate(item.title,form.cleaned_data['brief'])
                except ValueError as error:form.add_error(None,str(error))
                else:
                    draft.text=text;draft.model_name=model_name;draft.status='draft';draft.save()
                    record_event(requisition=item,kind='jd_draft',detail='Step 1: AI-assisted JD drafted for human review',metadata={'draft':draft.pk})
                    return redirect('workspace-requisition-jd-review',pk=pk,draft_pk=draft.pk)
    return render(request,'experience/requisition_jd.html',page_context(request,title='Step 1 · Draft a JD',item=item,form=form,ai_ready=ready,wizard_steps=steps(1,item)))


@workspace
@require_http_methods(['GET','POST'])
def ai_review(request,pk,draft_pk):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if not editable(request.user,item):raise PermissionDenied()
    draft=get_object_or_404(JDDraft,requisition=item,pk=draft_pk,status='draft')
    class ReviewForm(forms.Form):
        text=forms.CharField(max_length=16000,min_length=40,label='Review and edit the JD',widget=forms.Textarea(attrs={'rows':18}))
        expected_version=forms.IntegerField(widget=forms.HiddenInput)
        confirm=forms.BooleanField(label='I reviewed this draft and want to save it to the requisition. It will still require CEO approval.')
    form=ReviewForm(request.POST or None,initial={'text':draft.text,'expected_version':item.version})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            saved=JDDraft.objects.select_for_update().get(pk=draft_pk)
            if not editable(request.user,current) or current.version!=form.cleaned_data['expected_version'] or saved.status!='draft' or digest(current.jd_text)!=saved.source_description_sha256:form.add_error(None,'The request or draft changed. Reload before saving.')
            else:
                current.jd_text=form.cleaned_data['text'];current.version+=1;current.save()
                saved.text=current.jd_text;saved.status='applied';saved.applied_at=timezone.now();saved.version+=1;saved.save()
                record_event(requisition=current,kind='jd_applied',detail='Step 1: human reviewed and saved the AI-assisted JD',metadata={'draft':saved.pk})
                return redirect('workspace-requisition-edit',pk=pk)
    return render(request,'experience/requisition_jd.html',page_context(request,title='Step 1 · Review JD draft',item=item,form=form,review=True,wizard_steps=steps(1,item)))
