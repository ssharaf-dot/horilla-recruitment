"""Guided review, assignment and correction without granting new record access."""
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .models import Requisition
from .access import recruiter,employee_for
from .phase_data import permitted_requisitions
from .activity import record_event
from .views import workspace
from .requisitions import page_context,steps,name,AssignmentForm
from .requisition_wizard import MODEL_FIELDS,missing,snapshot,revision,budget_floor


def approved_valid(item):
    if item.status!='approved' or not item.approved_version:return False
    saved=item.revisions.filter(version=item.approved_version,kind__in=['ceo_approved','ceo_edited_approved']).first()
    if not saved:return False
    current=snapshot(item)
    def equal(key):
        a,b=current.get(key),saved.snapshot.get(key)
        if key in ['salary_min','salary_max','annual_budget'] and a is not None and b is not None:
            return Decimal(str(a))==Decimal(str(b))
        return a==b
    return not missing(item) and all(equal(k) for k in MODEL_FIELDS+['kpa_text','jd_outline'])


def ta_eligible(user,item):
    employee=employee_for(user) if user else None
    return bool(user and user.is_active and employee and employee.is_active and recruiter(user) and permitted_requisitions(user).filter(pk=item.pk).exists())


def can_assign(user,item):
    return bool(item.status=='approved' and not item.job_id and item.assignment_director_id==user.pk and user.has_perm('recruitment_experience.approve_offer') and approved_valid(item))


def can_correct(user,item):
    # A handback removes an approval; it never grants the sender approval rights.
    return bool(item.status=='approved' and not item.job_id and (user.is_superuser or item.approver_id==user.pk and user.has_perm('recruitment_experience.approve_hiringrequest') or item.assignment_director_id==user.pk and user.has_perm('recruitment_experience.approve_offer') or item.ta_owner_id==user.pk and recruiter(user)))


class DecisionForm(forms.Form):
    expected_version=forms.IntegerField(widget=forms.HiddenInput)
    decision=forms.ChoiceField(label='What should happen next?',choices=[('approved','Approve this package — send to the HR Director'),('changes','Return for changes — send to the requester'),('declined','Reject this hiring need — close the request')],widget=forms.RadioSelect)
    note=forms.CharField(required=False,max_length=2000,label='Reason / instructions',widget=forms.Textarea(attrs={'rows':3}),help_text='Required for a return or rejection. Explain what should change.')
    confirm=forms.BooleanField(label='I reviewed the hiring package and confirm this decision')
    def clean(self):
        values=super().clean()
        if values.get('decision') in ['changes','declined'] and not values.get('note','').strip():self.add_error('note','Explain the reason so the requester knows what to do next.')
        return values


def decide_locked(item,user,form):
    if item.approver_id!=user.pk or not user.has_perm('recruitment_experience.approve_hiringrequest'):raise PermissionDenied()
    decision=form.cleaned_data['decision']
    legacy=item.status=='approved' and not item.approved_version and not item.job_id and decision=='changes'
    if (item.status!='pending' and not legacy) or item.version!=form.cleaned_data['expected_version']:
        form.add_error(None,'This request changed. Your decision has not been recorded. Open the latest request before retrying.');return False
    if decision=='approved' and missing(item):
        form.add_error(None,'Complete the package before approval: '+missing(item)[0][1]+' Edit it or return it to its requester.');return False
    item.status=decision;item.decision_note=form.cleaned_data.get('note','').strip();item.decided_at=timezone.now();item.version+=1;item.approved_version=item.version if decision=='approved' else 0
    if decision=='changes':item.wizard_step=5;item.resume_section=5
    item.save();revision(item,user,{'approved':'ceo_approved','changes':'ceo_returned','declined':'ceo_rejected'}[decision],item.decision_note)
    record_event(requisition=item,kind='requisition_decision',detail='CEO '+{'approved':'approved the submitted package','changes':'returned the request for changes','declined':'rejected the hiring need'}[decision]+(': '+item.decision_note if item.decision_note else ''),metadata={'version':item.version,'decision':decision})
    return True


def decide_request(request,pk):
    form=DecisionForm(request.POST)
    with transaction.atomic():
        item=get_object_or_404(permitted_requisitions(request.user).select_for_update(),pk=pk)
        if item.approver_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_hiringrequest'):raise PermissionDenied()
        if form.is_valid() and decide_locked(item,request.user,form):messages.success(request,'Decision recorded. The next owner and action are shown below.')
        else:messages.error(request,' '.join(str(e) for errors in form.errors.values() for e in errors))
    return redirect('workspace-requisition-detail',pk=pk)


@workspace
@require_http_methods(['GET','POST'])
def review(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if item.approver_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_hiringrequest'):raise PermissionDenied()
    if item.status!='pending':return redirect('workspace-requisition-detail',pk=pk)
    decision=request.GET.get('section')=='decision' or request.method=='POST'
    form=DecisionForm(request.POST or None,initial={'expected_version':item.version})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            if decide_locked(current,request.user,form):messages.success(request,'Decision recorded. The next owner and action are shown below.');return redirect('workspace-requisition-detail',pk=pk)
    return render(request,'experience/requisition_review.html',page_context(request,title='Step 2A · CEO review',item=item,wizard_section=True,hide_action_rail=True,wizard_steps=steps(2,item),form=form,decision=decision,package_issues=missing(item),salary_floor=budget_floor(item),open_package=True))


def assign_locked(item,user,form):
    if item.assignment_director_id!=user.pk or not user.has_perm('recruitment_experience.approve_offer'):raise PermissionDenied()
    if not can_assign(user,item) or item.version!=form.cleaned_data['expected_version']:
        form.add_error(None,'A current, complete CEO approval is required. Registered or newer requests cannot be overwritten. Open the latest request.');return False
    previous=item.ta_owner_id;chosen=form.cleaned_data['ta_owner']
    if previous==chosen.pk:
        form.add_error('ta_owner','This recruiter is already assigned. No change was made.');return False
    if previous and not form.cleaned_data.get('reason','').strip():form.add_error('reason','Explain the reassignment for the previous and new recruiter.');return False
    item.ta_owner=chosen;item.assigned_by=user;item.assigned_at=timezone.now();item.version+=1;item.save()
    record_event(requisition=item,kind='requisition_assignment',detail=('HR Director reassigned TA owner to ' if previous else 'Step 2 complete: HR Director assigned TA owner ')+name(chosen)+(': '+form.cleaned_data['reason'].strip() if form.cleaned_data.get('reason') else ''),metadata={'previous_ta_owner_id':previous,'ta_owner_id':chosen.pk,'version':item.version})
    return True


def assign_request(request,pk):
    with transaction.atomic():
        item=get_object_or_404(permitted_requisitions(request.user).select_for_update(),pk=pk)
        if item.assignment_director_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_offer'):raise PermissionDenied()
        form=AssignmentForm(request.POST,requisition=item)
        if form.is_valid() and assign_locked(item,request.user,form):messages.success(request,'Recruiter assigned. They now review the vacancy setup in Step 3A.')
        else:messages.error(request,' '.join(str(e) for errors in form.errors.values() for e in errors))
    return redirect('workspace-requisition-detail',pk=pk)


@workspace
@require_http_methods(['GET','POST'])
def assignment(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if item.assignment_director_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_offer'):raise PermissionDenied()
    if not can_assign(request.user,item):return redirect('workspace-requisition-detail',pk=pk)
    form=AssignmentForm(request.POST or None,requisition=item,initial={'expected_version':item.version,'ta_owner':item.ta_owner_id})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            if assign_locked(current,request.user,form):messages.success(request,'Recruiter assigned. They now review the vacancy setup in Step 3A.');return redirect('workspace-requisition-detail',pk=pk)
    return render(request,'experience/requisition_assignment.html',page_context(request,title='Step 2B · Recruiter assignment',item=item,form=form,wizard_section=True,hide_action_rail=True,wizard_steps=steps(2,item),eligible_count=form.fields['ta_owner'].queryset.count(),salary_floor=budget_floor(item)))


@workspace
@require_http_methods(['GET','POST'])
def correction(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if not can_correct(request.user,item):raise PermissionDenied()
    class CorrectionForm(forms.Form):
        expected_version=forms.IntegerField(widget=forms.HiddenInput)
        reason=forms.CharField(max_length=2000,label='What needs correcting?',widget=forms.Textarea(attrs={'rows':4}))
        confirm=forms.BooleanField(label='Return this request for correction and require fresh CEO approval before assignment or registration')
    form=CorrectionForm(request.POST or None,initial={'expected_version':item.version})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            if not can_correct(request.user,current) or current.version!=form.cleaned_data['expected_version']:form.add_error(None,'This request changed. No correction handback was recorded. Open the latest request.')
            else:
                previous=dict(approved_version=current.approved_version,ta_owner_id=current.ta_owner_id)
                current.status='changes';current.approved_version=0;current.ta_owner=None;current.assigned_by=None;current.assigned_at=None;current.decided_at=None;current.wizard_step=5;current.resume_section=5;current.decision_note=form.cleaned_data['reason'].strip();current.version+=1;current.save()
                revision(current,request.user,'correction_requested',current.decision_note)
                record_event(requisition=current,kind='requisition_correction',detail='Returned to requester for correction by '+name(request.user)+': '+current.decision_note,metadata={**previous,'version':current.version})
                messages.success(request,'Returned to the requester. Earlier approvals remain in history; fresh CEO approval and Director assignment are now required.');return redirect('workspace-requisition-detail',pk=pk)
    return render(request,'experience/requisition_correction.html',page_context(request,title='Request correction',item=item,form=form,wizard_section=True,hide_action_rail=True,wizard_steps=steps(2,item)))
