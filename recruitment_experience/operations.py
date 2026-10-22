"""Focused recruitment operations, preserving Horilla's existing records."""
import hashlib
import json
import secrets
from datetime import timedelta
from zoneinfo import ZoneInfo

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache

from base.models import Company, JobPosition
from employee.models import Employee
from recruitment.models import Candidate, Recruitment, RecruitmentSurvey, RecruitmentSurveyAnswer, Stage, StageNote, InterviewSchedule
from .models import Division, DivisionAccess, VacancyProfile, WorkflowEvent, InterviewPlan, NotificationDelivery, ApplicationDraft, Requisition
from .access import recruiter, scoped_jobs, scoped_candidates, scoped_interviews, reporting_jobs, leadership, require_coordinate, employee_for
from .services import WORKING_ZONE, decorate_interview, interview_time, notify, audit, task_message, public_status
from .forms import InterviewPlanForm
from .views import workspace, context, enabled, applicant_account, owned_candidates, attach_application


def document_response(request,record,applicant=False,page=None):
    if not record.resume:
        raise Http404()
    import fitz
    try:
        with record.resume.open('rb') as source:
            document=fitz.open(stream=source.read(),filetype='pdf')
        if page is not None:
            if page<1 or page>min(document.page_count,100):
                raise Http404()
            sheet=document[page-1]
            scale=min(1.3,1800/max(sheet.rect.width,sheet.rect.height,1))
            pixels=sheet.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
            response=HttpResponse(pixels.tobytes('png'),content_type='image/png')
            response['Cache-Control']='private, no-store'
            response['X-Content-Type-Options']='nosniff'
            document.close()
            return response
        raw=request.GET.get('page','1')
        number=min(max(int(raw),1),max(1,min(document.page_count,100))) if raw.isdigit() else 1
        count=min(document.page_count,100);document.close()
        audit(record,request.user,'cv_view','Document preview opened',applicant=applicant)
        return render(request,'experience/document.html',{'candidate':record,'page':number,'pages':count,'previous':number-1 if number>1 else None,'next':number+1 if number<count else None,'applicant':applicant})
    except (FileNotFoundError,OSError,RuntimeError,ValueError):
        return render(request,'experience/document.html',{'candidate':record,'error':'The document preview could not be rendered. Use Open PDF to view the original.','applicant':applicant})


@workspace
@require_http_methods(['GET'])
def document(request,pk,page=None):
    return document_response(request,get_object_or_404(scoped_candidates(request.user),pk=pk),page=page)


@never_cache
@require_http_methods(['GET'])
def applicant_document(request,pk,page=None):
    enabled()
    return document_response(request,get_object_or_404(owned_candidates(request),pk=pk),applicant=True,page=page)


def require_hr(request):
    if not recruiter(request.user):
        raise PermissionDenied('HR manages this setting.')


def allowed_divisions(user):
    qs = Division.objects.filter(is_active=True)
    if not user.is_superuser and DivisionAccess.objects.filter(user=user).exists():
        qs = qs.filter(divisionaccess__user=user).distinct()
    return qs


@workspace
@require_http_methods(['GET', 'POST'])
def job_settings(request, pk):
    require_hr(request)
    job = get_object_or_404(scoped_jobs(request.user), pk=pk)
    profile = VacancyProfile.objects.filter(job=job).first()
    class ProfileForm(forms.ModelForm):
        class Meta:
            model = VacancyProfile
            fields = ['division', 'location', 'work_type']
    form = ProfileForm(request.POST or None, instance=profile)
    form.fields['division'].queryset = allowed_divisions(request.user)
    if request.method == 'POST' and form.is_valid():
        row = form.save(commit=False)
        row.job = job
        row.save()
        messages.success(request, 'Division and vacancy details saved. The legal employer has not changed.')
        return redirect('workspace-job', pk=pk)
    return render(request, 'experience/form.html', context(request, active='jobs', title='Division and vacancy details', intro=str(job.title) + ' · Legal employer: ' + str(job.company_id), form=form, submit_label='Save vacancy details', cancel_url=reverse('workspace-job', args=[pk])))


@workspace
@require_http_methods(['GET'])
def settings_home(request):
    require_hr(request)
    return render(request, 'experience/settings_home.html', context(request, active='settings', title='Recruitment settings', divisions=allowed_divisions(request.user), jobs=scoped_jobs(request.user).select_related('workspace_profile__division', 'company_id'), delivery_counts={state:NotificationDelivery.objects.filter(status=state).count() for state in ['held','queued','failed','sent']} if request.user.is_superuser else None, notifications_connected=getattr(settings,'RECRUITMENT_NOTIFICATIONS_ENABLED',False)))


@workspace
@require_http_methods(['GET', 'POST'])
def schedule(request, pk, interview_pk=None):
    candidate = get_object_or_404(scoped_candidates(request.user), pk=pk)
    require_coordinate(request.user, candidate)
    appointment = get_object_or_404(scoped_interviews(request.user), pk=interview_pk, candidate_id=candidate) if interview_pk else None
    initial = {}
    if appointment:
        time = interview_time(appointment)
        initial = {'date':time.date(), 'time':time.time().replace(tzinfo=None), 'interviewers':appointment.employee_id.all(), 'details':appointment.description}
        plan = getattr(appointment,'workspace_plan',None)
        if plan:
            initial.update(duration_minutes=plan.duration_minutes, format=plan.format, location=plan.location, meeting_url=plan.meeting_url)
    form = InterviewPlanForm(request.POST or None, initial=initial, employees=Employee.objects.filter(is_active=True,employee_user_id__is_active=True))
    if request.method == 'POST' and form.is_valid():
        if appointment and appointment.workspace_feedback.exists():
            form.add_error(None,'This interview already has submitted feedback. Keep its history and schedule a separate follow-up interview instead.')
        else:
            return save_interview(request,pk,candidate,appointment,form)
    return render(request,'experience/form.html',context(request,active='interviews',title='Update interview' if appointment else 'Schedule interview',intro=candidate.name + ' · Enter Dubai time; existing appointments are converted, not relabelled.',form=form,version=getattr(getattr(appointment,'workspace_plan',None),'version',None),submit_label='Save interview',cancel_url=reverse('workspace-candidate',args=[pk])))


def save_interview(request,pk,candidate,appointment,form):
        with transaction.atomic():
            if appointment:
                appointment = InterviewSchedule.objects.select_for_update().get(pk=appointment.pk)
                plan = InterviewPlan.objects.select_for_update().filter(interview=appointment).first()
                if plan and str(plan.version) != request.POST.get('version'):
                    messages.error(request, 'This interview changed. Reload its current details before saving.')
                    return redirect('workspace-interview-edit', pk=pk, interview_pk=appointment.pk)
            starts = form.cleaned_data['starts_at']
            # Keep the legacy wall-clock fields in their original installation zone.
            old_clock = starts.astimezone(ZoneInfo(getattr(settings,'RECRUITMENT_LEGACY_TIME_ZONE',settings.TIME_ZONE)))
            if not appointment:
                appointment = InterviewSchedule(candidate_id=candidate)
            appointment.interview_date, appointment.interview_time = old_clock.date(), old_clock.time().replace(tzinfo=None)
            appointment.description = form.cleaned_data['details']
            appointment.completed = False
            appointment.save()
            appointment.employee_id.set(form.cleaned_data['interviewers'])
            plan, _ = InterviewPlan.objects.get_or_create(interview=appointment, defaults={'starts_at':starts})
            plan.starts_at = starts
            for name in ['duration_minutes','format','location','meeting_url']:
                setattr(plan,name,form.cleaned_data[name])
            plan.status = 'scheduled'
            plan.version += 1
            plan.save()
            audit(candidate,request.user,'interview','Interview scheduled or updated',interview=appointment.pk,version=plan.version)
            shared = 'Your interview is scheduled for ' + starts.strftime('%d %b %Y at %H:%M') + ' Dubai time (UTC+04:00). Check your application for details.'
            StageNote.objects.create(candidate_id=candidate,stage_id=candidate.stage_id,description=shared,updated_by=employee_for(request.user),candidate_can_view=True)
            for email in {candidate.email, *appointment.employee_id.values_list('email',flat=True)}:
                notify(f'interview:{appointment.pk}:{plan.version}:{email}',email,'Interview details updated',shared)
        messages.success(request, 'Interview saved. Calendar download is available; external delivery remains inactive until connected.')
        return redirect('workspace-candidate',pk=pk)


@workspace
@require_http_methods(['GET','POST'])
def cancel_interview(request, pk):
    appointment = get_object_or_404(scoped_interviews(request.user),pk=pk)
    require_coordinate(request.user,appointment.candidate_id)
    class CancelForm(forms.Form):
        reason=forms.CharField(max_length=2000,widget=forms.Textarea(attrs={'rows':3}))
        confirm=forms.BooleanField(label='Cancel this interview and share the cancellation with the applicant')
    form=CancelForm(request.POST or None)
    if request.method!='POST' or not form.is_valid():
        return render(request,'experience/form.html',context(request,active='interviews',title='Cancel interview',intro=appointment.candidate_id.name+' · '+interview_time(appointment).strftime('%d %b %Y %H:%M')+' Dubai time. The appointment history will be retained.',form=form,submit_label='Confirm cancellation',cancel_url=reverse('workspace-candidate',args=[appointment.candidate_id_id])))
    with transaction.atomic():
        appointment = InterviewSchedule.objects.select_for_update().get(pk=pk)
        plan,_ = InterviewPlan.objects.get_or_create(interview=appointment,defaults={'starts_at':interview_time(appointment)})
        if plan.status != 'cancelled':
            plan.status='cancelled';plan.version+=1;plan.save()
            audit(appointment.candidate_id,request.user,'interview_cancelled',request.POST.get('reason','')[:2000],interview=pk)
            text='Your interview has been cancelled. The recruitment team will share any next steps here.'
            StageNote.objects.create(candidate_id=appointment.candidate_id,stage_id=appointment.candidate_id.stage_id,description=text,updated_by=employee_for(request.user),candidate_can_view=True)
            for email in {appointment.candidate_id.email,*appointment.employee_id.values_list('email',flat=True)}:
                notify(f'interview-cancel:{pk}:{plan.version}:{email}',email,'Interview cancelled',text)
    messages.success(request,'Interview cancelled. Its history has been retained.')
    return redirect('workspace-candidate',pk=appointment.candidate_id_id)


def calendar_response(appointment):
    decorate_interview(appointment)
    starts=appointment.dubai_time
    duration=appointment.plan.duration_minutes if appointment.plan else 45
    def clean(value):
        return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    uid=f'horilla-interview-{appointment.pk}@recruitment.local'
    stamp=lambda value:value.astimezone(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')
    rows=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Recruitment Workspace//Interview//EN','BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp(timezone.now()),'DTSTART:'+stamp(starts),'DTEND:'+stamp(starts+timedelta(minutes=duration)),'SUMMARY:'+clean('Interview · '+str(appointment.candidate_id.recruitment_id.title)),'DESCRIPTION:'+clean(appointment.description),'SEQUENCE:'+str(appointment.plan.version if appointment.plan else 0),'STATUS:'+('CANCELLED' if appointment.cancelled else 'CONFIRMED')]
    if appointment.plan:
        rows+=['LOCATION:'+clean(appointment.plan.location or appointment.plan.meeting_url)]
    rows+=['END:VEVENT','END:VCALENDAR','']
    response=HttpResponse('\r\n'.join(rows),content_type='text/calendar; charset=utf-8')
    response['Content-Disposition']='attachment; filename="interview.ics"'
    response['Cache-Control']='private, no-store'
    return response


@workspace
@require_http_methods(['GET'])
def staff_calendar(request,pk):
    return calendar_response(get_object_or_404(scoped_interviews(request.user),pk=pk))


@never_cache
@require_http_methods(['GET'])
def applicant_calendar(request,pk):
    enabled()
    return calendar_response(get_object_or_404(InterviewSchedule.objects.filter(candidate_id__in=owned_candidates(request)),pk=pk))


@never_cache
@require_http_methods(['GET','POST'])
def applicant_action(request,pk,action):
    enabled()
    record=get_object_or_404(owned_candidates(request),pk=pk)
    if action not in ['withdraw','reschedule','contact']:
        raise Http404()
    class ActionForm(forms.Form):
        details=forms.CharField(max_length=15 if action=='contact' else 2000,label={'withdraw':'Optional reason','reschedule':'Preferred availability and timezone','contact':'New phone number'}[action],required=action!='withdraw',widget=forms.Textarea(attrs={'rows':3}) if action!='contact' else forms.TextInput())
        confirm=forms.BooleanField(label='I confirm this request',required=True)
    form=ActionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            record=Candidate.objects.select_for_update().get(pk=record.pk)
            if action=='withdraw':
                if record.hired or record.offer_letter_status in ['accepted','joined']:
                    form.add_error(None,'Contact recruitment about this application; its outcome has already progressed.')
                elif not record.canceled:
                    withdrawn=Stage.objects.filter(recruitment_id=record.recruitment_id,stage_type='cancelled').first()
                    if withdrawn is None:
                        withdrawn=Stage.objects.create(recruitment_id=record.recruitment_id,stage='Withdrawn',stage_type='cancelled',sequence=999)
                    record.stage_id=withdrawn;record.canceled=True;record.save()
                    audit(record,None,'withdrawn',form.cleaned_data['details'])
                    from .models import ReviewRequest
                    ReviewRequest.objects.filter(candidate=record,completed_at__isnull=True).update(completed_at=timezone.now())
                    for appointment in InterviewSchedule.objects.filter(candidate_id=record,completed=False):
                        if interview_time(appointment)>=timezone.now():
                            plan,_=InterviewPlan.objects.get_or_create(interview=appointment,defaults={'starts_at':interview_time(appointment)})
                            if plan.status!='cancelled':
                                plan.status='cancelled';plan.version+=1;plan.save()
            elif action=='contact':
                from recruitment.models import validate_mobile
                try:
                    validate_mobile(form.cleaned_data['details'])
                    record.mobile=form.cleaned_data['details'];record.save()
                    audit(record,None,'contact','Applicant updated their phone number')
                except ValidationError:
                    form.add_error('details','Enter a valid international phone number.')
            elif not record.workspace_events.filter(kind='reschedule_requested',created_at__gte=timezone.now()-timedelta(minutes=10)).exists():
                audit(record,None,'reschedule_requested',form.cleaned_data['details'])
            if not form.errors:
                messages.success(request,'Request saved. An interview time changes only after HR confirms a new appointment.' if action=='reschedule' else 'Your application has been updated.')
                return redirect('applicant-detail',pk=pk)
    return render(request,'experience/applicant_action.html',{'candidate':record,'form':form,'action':action})


@workspace
@require_http_methods(['GET','POST'])
def requisitions(request):
    permitted=allowed_divisions(request.user)
    class RequestForm(forms.ModelForm):
        class Meta:
            model=Requisition
            fields=['title','division','employer','openings','reason','approver']
            widgets={'reason':forms.Textarea(attrs={'rows':4})}
    form=RequestForm(request.POST or None)
    form.fields['division'].queryset=permitted
    form.fields['approver'].queryset=User.objects.filter(is_active=True).filter(Q(is_superuser=True)|Q(user_permissions__codename='approve_hiringrequest')|Q(groups__permissions__codename='approve_hiringrequest')).exclude(pk=request.user.pk).distinct()
    if request.method=='POST':
        if not recruiter(request.user) and not scoped_jobs(request.user).exists():
            raise PermissionDenied()
        if form.is_valid():
            item=form.save(commit=False);item.requested_by=request.user;item.save()
            notify('requisition:'+str(item.pk),item.approver.email,'A hiring requisition needs your review',task_message(reverse('workspace-requisitions'),'Review the hiring need in your recruitment workspace.'))
            messages.success(request,'Requisition submitted. It has not created or published a vacancy.')
            return redirect('workspace-requisitions')
    items=Requisition.objects.filter(Q(requested_by=request.user)|Q(approver=request.user))
    if request.user.is_superuser:
        items=Requisition.objects.all()
    elif recruiter(request.user):
        items=Requisition.objects.filter(division__in=permitted)
    return render(request,'experience/requisitions.html',context(request,active='requests',title='Hiring requisitions',form=form,items=items.select_related('division','employer','requested_by','approver','job').order_by('-created_at')))


@workspace
@require_http_methods(['POST'])
def requisition_decide(request,pk):
    with transaction.atomic():
        item=get_object_or_404(Requisition.objects.select_for_update(),pk=pk)
        if item.approver_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_hiringrequest'):
            raise PermissionDenied()
        if item.status!='pending':
            messages.error(request,'This requisition already has a decision.')
        elif request.POST.get('decision') in ['approved','declined'] and request.POST.get('confirm')=='yes':
            item.status=request.POST['decision'];item.decision_note=request.POST.get('note','')[:2000];item.decided_at=timezone.now();item.save()
            messages.success(request,'Decision recorded. HR must prepare the vacancy before publication.')
    return redirect('workspace-requisitions')


@workspace
@require_http_methods(['GET','POST'])
def vacancy_form(request,pk=None):
    require_hr(request)
    job=get_object_or_404(scoped_jobs(request.user),pk=pk) if pk else None
    requisition=None
    if not job and request.GET.get('requisition','').isdigit():
        requisition=get_object_or_404(Requisition,status='approved',pk=request.GET['requisition'],division__in=allowed_divisions(request.user))
        if requisition.job_id:
            return redirect('workspace-job',pk=requisition.job_id)
    class VacancyForm(forms.ModelForm):
        class Meta:
            model=Recruitment
            fields=['title','company_id','open_positions','vacancy','description','start_date','end_date','optional_resume','closed']
            widgets={'description':forms.Textarea(attrs={'rows':7}),'start_date':forms.DateInput(attrs={'type':'date'}),'end_date':forms.DateInput(attrs={'type':'date'})}
    form=VacancyForm(request.POST or None,instance=job,initial={'title':requisition.title,'company_id':requisition.employer_id,'vacancy':requisition.openings} if requisition else None)
    if job or requisition:
        form.fields['company_id'].disabled=True
    else:
        form.fields['company_id'].queryset=Company.objects.filter(pk__in=scoped_jobs(request.user).values('company_id')) if not request.user.is_superuser else Company.objects.all()
    if request.method=='POST' and form.is_valid():
        if not job and not requisition:
            form.add_error(None,'Start with an approved hiring requisition, then select Prepare approved vacancy. Existing vacancies can be edited directly.')
        else:
            return save_vacancy(request,form,job,requisition)
    return render(request,'experience/form.html',context(request,active='jobs',title='Edit vacancy' if job else 'Prepare a vacancy',intro='For a new vacancy, open Hiring requisitions and prepare an approved request. The employer on an existing vacancy is preserved.',form=form,submit_label='Save vacancy',cancel_url=reverse('workspace-requisitions') if not job else reverse('workspace-jobs')))


def save_vacancy(request,form,job,requisition):
        with transaction.atomic():
            value=form.save(commit=False)
            if not job:
                value.is_published=False;value.optional_profile_image=True;value.publish_in_linkedin=False
            if requisition:
                requisition=Requisition.objects.select_for_update().get(pk=requisition.pk)
                if requisition.job_id:
                    return redirect('workspace-job',pk=requisition.job_id)
                value.company_id=requisition.employer;value.vacancy=requisition.openings
            value.save();form.save_m2m()
            if not job:
                for sequence,(label,kind) in enumerate([('Applied','applied'),('Screening','test'),('Interview','interview'),('Hired','hired'),('Not progressing','cancelled')]):
                    Stage.objects.get_or_create(recruitment_id=value,stage_type=kind,defaults={'stage':label,'sequence':sequence})
            if requisition:
                VacancyProfile.objects.create(job=value,division=requisition.division)
                requisition.job=value;requisition.save()
        messages.success(request,'Vacancy saved. New vacancies remain drafts until HR reviews and publishes them.')
        return redirect('workspace-job',pk=value.pk)


@workspace
@require_http_methods(['GET','POST'])
def offer(request,pk):
    record=get_object_or_404(scoped_candidates(request.user),pk=pk)
    require_coordinate(request.user,record)
    transitions={'not_sent':['sent'],'sent':['accepted','rejected'],'accepted':['joined'],'rejected':[],'joined':[]}
    class OutcomeForm(forms.Form):
        outcome=forms.ChoiceField(choices=[(s,dict(Candidate.offer_letter_statuses)[s]) for s in transitions.get(record.offer_letter_status,[])])
        date=forms.DateField(label='Outcome date',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
        evidence=forms.CharField(max_length=2000,label='Evidence or reference',widget=forms.Textarea(attrs={'rows':3}))
        confirm=forms.BooleanField(label='I confirm this outcome has actually occurred')
    form=OutcomeForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Candidate.objects.select_for_update().get(pk=pk)
            if current.offer_letter_status!=record.offer_letter_status or form.cleaned_data['date']>timezone.localdate():
                form.add_error(None,'The record changed, or the outcome date is in the future. Review before saving.')
            else:
                values={'offer_letter_status':form.cleaned_data['outcome']}
                if values['offer_letter_status']=='joined':
                    values['joining_date']=form.cleaned_data['date']
                Candidate.objects.filter(pk=pk).update(**values)
                audit(current,request.user,'offer',form.cleaned_data['evidence'],outcome=values['offer_letter_status'],date=str(form.cleaned_data['date']))
                messages.success(request,'Offer outcome recorded. No offer document or email has been generated.')
                return redirect('workspace-candidate',pk=pk)
    return render(request,'experience/form.html',context(request,active='candidates',title='Record an offer outcome',intro=record.name+' · Current status: '+record.get_offer_letter_status_display(),form=form,submit_label='Record outcome',cancel_url=reverse('workspace-candidate',args=[pk])))


@workspace
@require_http_methods(['GET','POST'])
def publication(request,pk):
    require_hr(request)
    job=get_object_or_404(scoped_jobs(request.user),pk=pk)
    profile=getattr(job,'workspace_profile',None)
    checks=[('A division is assigned',bool(profile and profile.division)),('Legal employer is set',bool(job.company_id_id)),('Role description is written',bool(job.description and job.description.strip())),('At least one position is selected',job.open_positions.exists()),('At least one opening is configured',bool(job.vacancy and job.vacancy>0)),('An application stage exists',job.stage_set.filter(is_active=True,stage_type='applied').exists()),('The application closing date has not passed',not job.end_date or job.end_date>=timezone.localdate()),('Start date has been reached',job.start_date<=timezone.localdate()),('The vacancy is open',not job.closed)]
    class PublishForm(forms.Form):
        action=forms.ChoiceField(choices=[('publish','Publish on careers site'),('unpublish','Unpublish from careers site')])
        confirm=forms.BooleanField(label='I reviewed this vacancy and confirm this publication change')
    form=PublishForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            Recruitment.objects.select_for_update().get(pk=job.pk)
            if form.cleaned_data['action']=='publish' and not all(ok for _,ok in checks):
                form.add_error(None,'Complete every publication check first.')
            else:
                Recruitment.objects.filter(pk=job.pk).update(is_published=form.cleaned_data['action']=='publish')
                messages.success(request,'Publication status updated. Existing application records are retained.')
                return redirect('workspace-job',pk=job.pk)
    return render(request,'experience/publication.html',context(request,active='jobs',job=job,checks=checks,form=form))


@workspace
@require_http_methods(['GET'])
def questionnaire_attachment(request,pk,key):
    record=get_object_or_404(scoped_candidates(request.user),pk=pk)
    draft=get_object_or_404(ApplicationDraft,candidate=record)
    path=draft.attachments.get(key)
    if not path or key=='profile' or not any('q'+str(q['id'])==key and q['type']=='file' for q in draft.questions):
        raise Http404()
    audit(record,request.user,'attachment_download','Screening attachment downloaded',question=key)
    response=FileResponse(default_storage.open(path,'rb'),as_attachment=True,filename='screening-attachment')
    response['Content-Type']='application/octet-stream'
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    return response


@workspace
@require_http_methods(['GET','POST'])
def job_team(request,pk):
    require_hr(request)
    job=get_object_or_404(scoped_jobs(request.user),pk=pk)
    class TeamForm(forms.Form):
        managers=forms.ModelMultipleChoiceField(queryset=Employee.objects.filter(is_active=True,employee_user_id__is_active=True),required=False,label='Hiring managers')
    form=TeamForm(request.POST or None,initial={'managers':job.recruitment_managers.all()})
    if request.method=='POST' and form.is_valid():
        job.recruitment_managers.set(form.cleaned_data['managers'])
        messages.success(request,'Hiring team updated. Managers recommend changes; HR controls stages and scheduling.')
        return redirect('workspace-job',pk=pk)
    return render(request,'experience/form.html',context(request,active='jobs',title='Hiring team',intro=job.title,form=form,submit_label='Save hiring team',cancel_url=reverse('workspace-job',args=[pk])))


@workspace
@require_http_methods(['GET','POST'])
def questions(request,pk):
    require_hr(request)
    job=get_object_or_404(scoped_jobs(request.user),pk=pk)
    class QuestionForm(forms.ModelForm):
        class Meta:
            model=RecruitmentSurvey
            fields=['question','type','options','is_mandatory']
            widgets={'question':forms.Textarea(attrs={'rows':3})}
        def clean(self):
            data=super().clean()
            if data.get('type') in ['options','multiple'] and not data.get('options','').strip():
                self.add_error('options','Enter comma-separated answer choices.')
            return data
    form=QuestionForm(request.POST or None)
    if request.method=='POST' and request.POST.get('remove','').isdigit():
        question=get_object_or_404(RecruitmentSurvey,recruitment_ids=job,pk=request.POST['remove'])
        question.recruitment_ids.remove(job)
        messages.success(request,'Question removed from future application drafts. Submitted answers and existing draft snapshots remain intact.')
        return redirect('workspace-questions',pk=pk)
    if request.method=='POST' and form.is_valid():
        question=form.save(commit=False);question.sequence=RecruitmentSurvey.objects.filter(recruitment_ids=job).count()+1;question.save();question.recruitment_ids.add(job)
        messages.success(request,'Question added for new application drafts.')
        return redirect('workspace-questions',pk=pk)
    return render(request,'experience/questions.html',context(request,active='jobs',job=job,questions=RecruitmentSurvey.objects.filter(recruitment_ids=job).order_by('sequence','pk'),form=form))


@workspace
@require_http_methods(['GET','POST'])
def access_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied()
    class AccessForm(forms.ModelForm):
        class Meta:
            model=DivisionAccess
            fields=['user','division','role']
    form=AccessForm(request.POST or None)
    form.fields['user'].queryset=User.objects.filter(is_active=True,is_superuser=False)
    if request.method=='POST' and form.is_valid():
        form.save()
        messages.success(request,'Division access saved. Users with division grants are restricted to their granted divisions; administrators remain unrestricted.')
        return redirect('workspace-access-settings')
    return render(request,'experience/access_settings.html',context(request,active='settings',form=form,grants=DivisionAccess.objects.select_related('user','division')))
