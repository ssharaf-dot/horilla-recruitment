"""Director approval, joining controls and scoped activity views."""
from datetime import datetime
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from recruitment.models import Candidate, Recruitment
from .access import recruiter, scoped_jobs, scoped_candidates, division_scope, require_coordinate
from .models import OfferApproval, JoiningPlan, JoiningTask, WorkflowEvent
from .activity import record_event
from .services import WORKING_ZONE, selected_jobs
from .views import workspace, context

TASKS = [
    ('documents',11,'Identity, qualification and required joining documents verified',True),
    ('compliance',11,'HR Operations / PRO compliance review completed',True),
    ('agreement',12,'Required employment agreements and NDA recorded',True),
    ('it',12,'IT access and equipment prepared',True),
    ('sim',12,'SIM / telephone requirement reviewed',False),
    ('welcome',12,'Welcome instructions shared with the new joiner',True),
    ('appointment',12,'Onboarding appointment agreed',True),
    ('joined',13,'Actual attendance and joining confirmed',False),
    ('handover',13,'Personnel file handover acknowledged',False),
    ('hrms',13,'Receiving HRMS reference recorded',False),
]


def director(user):
    return user.is_active and user.has_perm('recruitment_experience.approve_offer')


def eligible_directors(user, candidate):
    users=get_user_model().objects.filter(is_active=True).filter(Q(is_superuser=True)|Q(user_permissions__codename='approve_offer')|Q(groups__permissions__codename='approve_offer')).exclude(pk=user.pk).distinct()
    return users.filter(pk__in=[u.pk for u in users if director(u) and division_scope(u, candidate.recruitment_id.__class__.objects.filter(pk=candidate.recruitment_id_id)).exists()])


def approval_for(candidate):
    return candidate.offer_approvals.order_by('-pk').first()


def offer_gate(candidate):
    approval=approval_for(candidate)
    if candidate.canceled or not candidate.is_active or not candidate.stage_id or candidate.stage_id.stage_type!='hired':
        return 'HR must confirm selection before recording an offer as sent.'
    if not approval or approval.status!='approved':
        return 'An HR Director must approve the latest offer terms before the offer can be recorded as sent.'
    return ''


def joining_gate(candidate):
    if candidate.canceled or not candidate.is_active:
        return 'A closed application cannot be confirmed as joined.'
    plan=JoiningPlan.objects.filter(candidate=candidate).first()
    if not plan:
        return 'Start the joining checklist and complete the required pre-joining tasks first.'
    if plan.tasks.filter(required_for_joining=True).exclude(status__in=['done','not_applicable']).exists():
        return 'Complete or explain each required pre-joining checklist item before confirming joining.'
    if not plan.appointment_at or not plan.appointment_location:
        return 'Record the agreed onboarding appointment before confirming joining.'
    return ''


@workspace
@require_http_methods(['GET','HEAD'])
def approvals(request):
    rows=OfferApproval.objects.select_related('candidate__recruitment_id','director','prepared_by')
    if recruiter(request.user):
        rows=rows.filter(candidate__in=scoped_candidates(request.user))
    elif director(request.user):
        rows=rows.filter(director=request.user,candidate__recruitment_id__in=division_scope(request.user, Recruitment.objects.all()))
    else:
        raise PermissionDenied()
    rows=rows.filter(candidate__recruitment_id__in=selected_jobs(request,Recruitment.objects.all()))
    if request.GET.get('job'):
        rows=rows.filter(candidate__recruitment_id_id=request.GET['job']) if request.GET['job'].isdigit() else rows.none()
    return render(request,'experience/approvals.html',context(request,active='offers',title='Director offer approvals',approvals=rows))


class OfferTermsForm(forms.ModelForm):
    confirm=forms.BooleanField(label='I have reviewed these terms and the selection evidence')
    class Meta:
        model=OfferApproval
        fields=['director','role_title','monthly_salary','currency','proposed_joining','terms']
        labels={'monthly_salary':'Total monthly salary','director':'HR Director'}
        widgets={'proposed_joining':forms.DateInput(attrs={'type':'date'}),'terms':forms.Textarea(attrs={'rows':5})}
    def clean_proposed_joining(self):
        value=self.cleaned_data['proposed_joining']
        if value<timezone.localdate():
            raise forms.ValidationError('Choose today or a future proposed joining date.')
        return value


@workspace
@require_http_methods(['GET','POST'])
def prepare_offer(request,pk):
    candidate=get_object_or_404(scoped_candidates(request.user),pk=pk)
    require_coordinate(request.user,candidate)
    form=OfferTermsForm(request.POST or None,initial={'role_title':candidate.recruitment_id.title})
    form.fields['director'].queryset=eligible_directors(request.user,candidate)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            candidate=Candidate.objects.select_for_update().get(pk=pk)
            if candidate.offer_letter_status!='not_sent' or candidate.canceled or not candidate.stage_id or candidate.stage_id.stage_type!='hired':
                form.add_error(None,'Select this candidate in the hired stage before preparing an offer. Issued offers cannot be changed here.')
            elif candidate.offer_approvals.filter(status='pending').exists():
                form.add_error(None,'A request is already awaiting the Director. Withdraw it before submitting revised terms.')
            else:
                item=form.save(commit=False);item.candidate=candidate;item.prepared_by=request.user;item.save()
                record_event(candidate=candidate,kind='offer_approval',detail='Offer terms submitted for HR Director approval',metadata={'approval':item.pk,'director':item.director_id})
                messages.success(request,'Offer submitted for Director review. The candidate has not been sent an offer.')
                return redirect('workspace-offer-approval',pk=item.pk)
    return render(request,'experience/form.html',context(request,active='offers',candidate=candidate,title='Prepare offer approval',intro='Terms are retained per request. HR preparation and Director approval must use different accounts. Compensation is visible only to HR and the assigned Director.',form=form,submit_label='Submit for Director approval',cancel_url=reverse('workspace-candidate',args=[pk])))


@workspace
@require_http_methods(['GET','POST'])
def approval_detail(request,pk):
    with transaction.atomic():
        item=get_object_or_404(OfferApproval.objects.select_for_update(of=('self',)).select_related('candidate__recruitment_id','director','prepared_by'),pk=pk)
        hr=recruiter(request.user) and scoped_candidates(request.user).filter(pk=item.candidate_id).exists()
        assigned=director(request.user) and item.director_id==request.user.pk and division_scope(request.user,Recruitment.objects.filter(pk=item.candidate.recruitment_id_id)).exists()
        if not (hr or assigned):
            raise PermissionDenied()
        class DecisionForm(forms.Form):
            decision=forms.ChoiceField(choices=[('approved','Approve these terms'),('declined','Request changes')] if assigned else [('withdrawn','Withdraw request')])
            note=forms.CharField(max_length=2000,widget=forms.Textarea(attrs={'rows':4}),label='Decision reason / evidence')
            confirm=forms.BooleanField(label='I confirm this decision on the displayed terms')
        form=DecisionForm(request.POST or None)
        if request.method=='POST' and form.is_valid():
            # Lock the candidate as well: approval and HR offer recording serialize.
            current=Candidate.objects.select_for_update().get(pk=item.candidate_id)
            if item.status!='pending':form.add_error(None,'This request already has a decision. Reload the history.')
            elif assigned and item.prepared_by_id==request.user.pk:form.add_error(None,'A preparer cannot approve their own offer.')
            elif current.canceled or current.stage_id.stage_type!='hired' or current.offer_letter_status!='not_sent':form.add_error(None,'The application changed. HR must withdraw and review the request.')
            else:
                item.status=form.cleaned_data['decision'];item.decision_note=form.cleaned_data['note'];item.decided_at=timezone.now();item.save(update_fields=['status','decision_note','decided_at'])
                record_event(candidate=current,kind='offer_approval',detail='Director offer decision: '+item.get_status_display(),metadata={'approval':item.pk,'decision':item.status})
                messages.success(request,'Offer decision recorded. Issuance and candidate response remain separate steps.')
                return redirect('workspace-offer-approval',pk=pk)
    return render(request,'experience/approval.html',context(request,active='offers',title='Offer approval',approval=item,form=form if item.status=='pending' else None,can_hr=hr))


@workspace
@require_http_methods(['GET','POST'])
def joining(request,pk):
    candidate=get_object_or_404(scoped_candidates(request.user),pk=pk)
    hr=recruiter(request.user)
    if request.method=='POST':
        require_coordinate(request.user,candidate)
        if request.POST.get('confirm')!='yes':
            messages.error(request,'Confirm that you want to start the joining checklist.')
        else:
            with transaction.atomic():
                current=Candidate.objects.select_for_update().get(pk=pk)
                if current.canceled or current.offer_letter_status not in ['accepted','joined']:
                    messages.error(request,'Record actual offer acceptance before starting joining preparation.')
                else:
                    plan,created=JoiningPlan.objects.get_or_create(candidate=current,defaults={'created_by':request.user})
                    if created:
                        JoiningTask.objects.bulk_create([JoiningTask(plan=plan,key=key,phase=phase,title=title,required_for_joining=required) for key,phase,title,required in TASKS])
                        record_event(candidate=current,kind='joining',detail='Joining and onboarding checklist started')
                    return redirect('workspace-joining',pk=pk)
    plan=JoiningPlan.objects.filter(candidate=candidate).first()
    tasks=list(plan.tasks.select_related('assigned_to','completed_by')) if plan else []
    return render(request,'experience/joining.html',context(request,active='handover',title='Joining & onboarding',candidate=candidate,plan=plan,tasks=tasks,completed=sum(t.status in ['done','not_applicable'] for t in tasks),can_coordinate=hr))


@workspace
@require_http_methods(['GET','POST'])
def joining_task(request,pk):
    task=get_object_or_404(JoiningTask.objects.select_related('plan__candidate','assigned_to'),pk=pk,plan__candidate__in=scoped_candidates(request.user))
    candidate=task.plan.candidate
    hr=recruiter(request.user)
    if not hr and task.assigned_to_id!=request.user.pk:raise PermissionDenied()
    class TaskForm(forms.ModelForm):
        expected_version=forms.IntegerField(widget=forms.HiddenInput)
        class Meta:
            model=JoiningTask
            fields=['assigned_to','due_date','status','evidence'] if hr else ['status','evidence']
            widgets={'due_date':forms.DateInput(attrs={'type':'date'}),'evidence':forms.Textarea(attrs={'rows':4})}
        def clean(self):
            values=super().clean()
            if values.get('status') in ['done','not_applicable'] and not values.get('evidence','').strip():
                self.add_error('evidence','Record completion evidence, or explain why this item is not applicable.')
            if values.get('status')=='not_applicable' and not hr:
                self.add_error('status','HR must confirm that a checklist item is not applicable.')
            if task.key=='appointment' and values.get('status')=='done' and not task.plan.appointment_at:
                self.add_error('status','HR must record the onboarding appointment first.')
            if task.key=='joined' and values.get('status')=='done' and candidate.offer_letter_status!='joined':
                self.add_error('status','HR must record the actual joined outcome first.')
            if task.key=='hrms' and values.get('status')=='done' and not task.plan.handover_reference:
                self.add_error('status','Record the receiving HRMS reference first. This is a manual acknowledgement.')
            return values
    form=TaskForm(request.POST or None,instance=task,initial={'expected_version':task.version})
    if hr:
        # Only existing scoped staff can be assigned; this grants no new access.
        form.fields['assigned_to'].queryset=get_user_model().objects.filter(is_active=True,pk__in=[u.pk for u in get_user_model().objects.filter(is_active=True) if scoped_candidates(u).filter(pk=candidate.pk).exists()])
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            Candidate.objects.select_for_update().get(pk=candidate.pk)
            current=JoiningTask.objects.select_for_update().get(pk=pk)
            if current.version!=form.cleaned_data['expected_version']:form.add_error(None,'This task changed. Reload before saving.')
            else:
                previous=current.status
                for field in form.Meta.fields:setattr(current,field,getattr(task,field))
                current.version+=1
                current.completed_at=timezone.now() if current.status in ['done','not_applicable'] else None
                current.completed_by=request.user if current.completed_at else None
                current.save()
                record_event(candidate=candidate,kind='checklist',detail=task.title+' · '+current.get_status_display()+'\n'+current.evidence,metadata={'task':pk,'previous':previous,'status':current.status,'assigned_to':current.assigned_to_id,'due_date':str(current.due_date or '')})
                messages.success(request,'Checklist task updated; its previous actions remain in the tracker.')
                return redirect('workspace-joining',pk=candidate.pk)
    return render(request,'experience/form.html',context(request,active='handover',candidate=candidate,title=task.title,intro='Record what actually happened. Every update is timestamped and attributed.',form=form,submit_label='Save task',cancel_url=reverse('workspace-joining',args=[candidate.pk])))


@workspace
@require_http_methods(['GET','POST'])
def joining_details(request,pk):
    candidate=get_object_or_404(scoped_candidates(request.user),pk=pk);require_coordinate(request.user,candidate)
    plan=get_object_or_404(JoiningPlan,candidate=candidate)
    class PlanForm(forms.ModelForm):
        expected_version=forms.IntegerField(widget=forms.HiddenInput)
        appointment_date=forms.DateField(required=False,widget=forms.DateInput(attrs={'type':'date'}))
        appointment_time=forms.TimeField(required=False,widget=forms.TimeInput(attrs={'type':'time'}),help_text='Dubai time (UTC+04:00)')
        class Meta:
            model=JoiningPlan
            fields=['appointment_location','handover_reference']
        def clean(self):
            values=super().clean();day=values.get('appointment_date');clock=values.get('appointment_time')
            if bool(day)!=bool(clock):raise forms.ValidationError('Provide both the appointment date and time.')
            if day and not values.get('appointment_location'):self.add_error('appointment_location','Provide a location or meeting reference.')
            return values
    initial={'expected_version':plan.version}
    if plan.appointment_at:
        when=plan.appointment_at.astimezone(WORKING_ZONE);initial.update(appointment_date=when.date(),appointment_time=when.time().replace(tzinfo=None))
    form=PlanForm(request.POST or None,instance=plan,initial=initial)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            Candidate.objects.select_for_update().get(pk=candidate.pk)
            locked=JoiningPlan.objects.select_for_update().get(pk=plan.pk)
            if locked.version!=form.cleaned_data['expected_version']:form.add_error(None,'The joining details changed. Reload before saving.')
            else:
                locked.appointment_location=plan.appointment_location;locked.handover_reference=plan.handover_reference
                locked.appointment_at=datetime.combine(form.cleaned_data['appointment_date'],form.cleaned_data['appointment_time'],tzinfo=WORKING_ZONE) if form.cleaned_data.get('appointment_date') else None
                locked.version+=1;locked.save()
                record_event(candidate=candidate,kind='onboarding',detail='Onboarding appointment / handover reference updated',metadata={'appointment_at':locked.appointment_at.isoformat() if locked.appointment_at else '', 'version':locked.version})
                messages.success(request,'Joining details saved. This records an agreed appointment; email, calendar delivery and HRMS transfer are not connected.')
                return redirect('workspace-joining',pk=pk)
    return render(request,'experience/form.html',context(request,active='handover',candidate=candidate,title='Onboarding appointment & handover',intro='Record an agreed appointment and the receiving HRMS reference. No external booking or data transfer is performed.',form=form,submit_label='Save joining details',cancel_url=reverse('workspace-joining',args=[pk])))


@workspace
@require_http_methods(['GET','HEAD'])
def tracker(request,pk=None,candidate_pk=None):
    candidate=get_object_or_404(scoped_candidates(request.user),pk=candidate_pk) if candidate_pk else None
    job=candidate.recruitment_id if candidate else get_object_or_404(scoped_jobs(request.user),pk=pk)
    rows=WorkflowEvent.objects.filter(candidate=candidate) if candidate else WorkflowEvent.objects.filter(Q(job=job)|Q(requisition__job=job)).filter(Q(candidate__isnull=True)|Q(candidate__in=scoped_candidates(request.user)))
    if not recruiter(request.user):
        rows=rows.exclude(Q(kind='feedback') & ~Q(actor=request.user)).exclude(Q(metadata__model='recruitment_experience.interviewfeedback') & ~Q(actor=request.user))
    mode=request.GET.get('kind','changes')
    if mode=='views':rows=rows.filter(kind__in=['view','cv_view','cv_download','attachment_download'])
    elif mode=='changes':rows=rows.exclude(kind__in=['view','cv_view','cv_download','attachment_download'])
    elif mode!='all':rows=rows.none()
    query=request.GET.copy();query.pop('page',None)
    page=Paginator(rows.select_related('actor','candidate').order_by('-created_at','-pk'),40).get_page(request.GET.get('page'))
    if not recruiter(request.user):
        for event in page:
            if event.kind=='offer':event.detail='Offer outcome recorded by HR'
    return render(request,'experience/tracker.html',context(request,active='jobs',title='Activity tracker',job=job,candidate=candidate,events=page,filter_kind=mode,pagination_query=query.urlencode()))


# Account credential entry is performed by the administrator in this private
# form. No preset password is saved in source code or shared in a chat log.
from django.views.decorators.debug import sensitive_post_parameters


@sensitive_post_parameters('password','confirm_password')
@workspace
@require_http_methods(['GET','POST'])
def director_demo_setup(request):
    if not request.user.is_superuser:raise PermissionDenied()
    from django.contrib.auth.models import Permission
    from django.contrib.auth.password_validation import validate_password
    from employee.models import Employee,EmployeeWorkInformation
    from base.models import Company
    User=get_user_model()
    existing=User.objects.filter(username='demo_director').first()
    class DemoForm(forms.Form):
        employer=forms.ModelChoiceField(queryset=Company.objects.all(),label='Demo account employer')
        password=forms.CharField(max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}),label='Password for demo_director')
        confirm_password=forms.CharField(max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}),label='Confirm password')
        confirm=forms.BooleanField(label='Create demo_director with permission to review only assigned offer approval packages')
        def clean(self):
            data=super().clean()
            if data.get('password')!=data.get('confirm_password'):self.add_error('confirm_password','Passwords must match.')
            if data.get('password'):
                try:validate_password(data['password'],user=User(username='demo_director'))
                except forms.ValidationError as error:self.add_error('password',error)
            return data
    form=DemoForm(request.POST or None)
    if request.method=='POST' and not existing and form.is_valid():
        with transaction.atomic():
            if User.objects.filter(username='demo_director').exists():
                messages.error(request,'The account already exists. It has not been overwritten.')
                return redirect('workspace-director-demo')
            user=User.objects.create_user(username='demo_director',password=form.cleaned_data['password'],first_name='Demo',last_name='HR Director',email='demo.director@example.invalid')
            if hasattr(user,'is_new_employee'):User.objects.filter(pk=user.pk).update(is_new_employee=False)
            user.user_permissions.add(Permission.objects.get(content_type__app_label='recruitment_experience',codename='approve_offer'))
            employee=Employee.objects.create(employee_user_id=user,employee_first_name='Demo',employee_last_name='HR Director',email='demo.director@example.invalid',phone='0000000000')
            info,_=EmployeeWorkInformation.objects.get_or_create(employee_id=employee)
            EmployeeWorkInformation.objects.filter(pk=info.pk).update(company_id=form.cleaned_data['employer'])
        messages.success(request,'demo_director is ready. HR can select this account when submitting offer approval requests.')
        return redirect('workspace-director-demo')
    return render(request,'experience/director_demo.html',context(request,active='settings',title='Demo HR Director account',form=form,existing=existing))
