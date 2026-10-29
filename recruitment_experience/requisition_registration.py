"""Two saved registration sections; no publication side effects."""
import html
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from base.models import JobPosition
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404,render,redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from recruitment.models import Recruitment,Stage
from .models import Requisition,VacancyProfile
from .phase_data import permitted_requisitions
from .access import employee_for
from .activity import record_event
from .views import workspace
from .requisitions import can_register,page_context,steps
from .requisition_wizard import revision


class RegistrationForm(forms.ModelForm):
    expected_version=forms.IntegerField(widget=forms.HiddenInput)
    open_positions=forms.ModelChoiceField(queryset=JobPosition.objects.none(),label='Internal job position')
    class Meta:
        model=Recruitment
        fields=['start_date','end_date','optional_resume']
        labels={'open_positions':'Internal job-position mapping','start_date':'Recruitment opens','end_date':'Recruitment closes (optional)','optional_resume':'Allow applications without a CV'}
        widgets={'start_date':forms.DateInput(attrs={'type':'date'}),'end_date':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,requisition,**kwargs):
        super().__init__(*args,**kwargs)
        self.order_fields(['open_positions','start_date','end_date','optional_resume','expected_version'])
        self.fields['open_positions'].queryset=JobPosition.objects.filter(is_active=True,department_id__is_active=True).filter(Q(company_id=requisition.employer)|Q(company_id__isnull=True)).filter(Q(department_id__company_id=requisition.employer)|Q(department_id__company_id__isnull=True)).distinct()
        self.fields['open_positions'].required=True
        self.fields['open_positions'].help_text='For internal reporting and application routing. Choose the single position matching this approved role. Only active shared positions or positions for this employer are offered.'

    def clean(self):
        values=super().clean()
        if hasattr(self.data,'getlist') and len(self.data.getlist('open_positions'))>1:self.add_error('open_positions','Choose one internal position for this role.')
        if values.get('end_date') and values['end_date']<timezone.localdate():self.add_error('end_date','Choose a closing date that has not already passed.')
        return values


def setup_current(item):
    saved=item.vacancy_setup or {}
    return bool(saved and saved.get('_ta_owner')==item.ta_owner_id and saved.get('_approved_version')==item.approved_version and saved.get('_assigned_at')==(item.assigned_at.isoformat() if item.assigned_at else None))


def draft_job(item):
    return Recruitment(title=item.title,company_id=item.employer,vacancy=item.openings,description=html.escape(item.jd_text).replace('\n','<br>'),is_published=False,publish_in_linkedin=False,closed=False,optional_profile_image=True)


@workspace
@require_http_methods(['GET','POST'])
def registration(request,pk):
    item=get_object_or_404(permitted_requisitions(request.user).select_related('employer','division','ta_owner'),pk=pk)
    if item.job_id:return redirect('workspace-requisition-detail',pk=pk)
    if not can_register(request.user,item):raise PermissionDenied('CEO approval and HR Director assignment are required; only the assigned recruiter registers this vacancy.')
    section=request.GET.get('section','review' if setup_current(item) else 'setup')
    if section not in ['setup','review']:section='setup'
    if section=='review' and not setup_current(item):return redirect(reverse('workspace-vacancy-new')+f'?requisition={pk}&section=setup')
    saved_position=(item.vacancy_setup or {}).get('open_positions',[])
    position=saved_position[0] if len(saved_position)==1 else None
    initial={**item.vacancy_setup,'open_positions':position,'expected_version':item.version}
    payload=request.POST or None
    if request.method=='POST' and section=='review':payload={**item.vacancy_setup,'open_positions':position,'expected_version':request.POST.get('expected_version')}
    form=RegistrationForm(payload,instance=draft_job(item),initial=initial,requisition=item)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            if current.job_id:return redirect('workspace-requisition-detail',pk=pk)
            if not can_register(request.user,current):raise PermissionDenied()
            if current.version!=form.cleaned_data['expected_version']:form.add_error(None,'This request changed. Your entries remain below; reload its latest saved version before continuing.')
            elif section=='setup':
                current.vacancy_setup={'open_positions':[form.cleaned_data['open_positions'].pk],'start_date':str(form.cleaned_data['start_date']),'end_date':str(form.cleaned_data['end_date']) if form.cleaned_data['end_date'] else '', 'optional_resume':form.cleaned_data['optional_resume'],'_ta_owner':current.ta_owner_id,'_approved_version':current.approved_version,'_assigned_at':current.assigned_at.isoformat()}
                current.version+=1;current.save();record_event(requisition=current,kind='requisition_draft',detail='Step 3A vacancy setup saved',metadata={'version':current.version})
                if request.POST.get('action')=='close':messages.success(request,'Vacancy setup saved. Resume the request when ready.');return redirect('workspace-area',slug='requisitions')
                return redirect(reverse('workspace-vacancy-new')+f'?requisition={pk}&section=review')
            elif not setup_current(current):form.add_error(None,'The approval or recruiter assignment changed. Review Step 3A again before creating the vacancy.')
            elif request.POST.get('confirm')!='yes':form.add_error(None,'Confirm the approved package and dates before creating the draft vacancy.')
            else:
                job=form.save(commit=False);job.title=current.title;job.company_id=current.employer;job.vacancy=current.openings;job.description=html.escape(current.jd_text).replace('\n','<br>');job.save();form.save_m2m();job.open_positions.set([form.cleaned_data['open_positions']])
                for n,(label,kind) in enumerate([('Applied','applied'),('Screening','test'),('Interview','interview'),('Hired','hired'),('Not progressing','cancelled')]):Stage.objects.get_or_create(recruitment_id=job,stage_type=kind,defaults={'stage':label,'sequence':n})
                VacancyProfile.objects.update_or_create(job=job,defaults={'division':current.division,'location':current.work_location,'work_type':current.employment_type if current.employment_type in dict(VacancyProfile._meta.get_field('work_type').choices) else ''})
                employee=employee_for(current.ta_owner)
                if employee:job.recruitment_managers.add(employee)
                requester=employee_for(current.requested_by)
                if requester and requester.is_active and current.requested_by.is_active:job.recruitment_managers.add(requester)
                current.job=job;current.registered_at=timezone.now();current.version+=1;current.save();revision(current,request.user,'vacancy_registered')
                record_event(requisition=current,job=job,kind='requisition_registered',detail='Step 3 complete: draft vacancy registered; ready for Sourcing & Selection',metadata={'version':current.version,'approved_version':current.approved_version})
                messages.success(request,'Work Area 1 complete. The vacancy is a draft; continue to Sourcing & Selection for publication review.');return redirect('workspace-requisition-detail',pk=pk)
    return render(request,'experience/requisition_registration.html',page_context(request,title='Step 3 · Register Vacancy',item=item,form=form,review=section=='review',wizard_section=True,hide_action_rail=True,wizard_steps=steps(3,item),setup=item.vacancy_setup,selected_position=form.fields['open_positions'].queryset.filter(pk=position).first(),setup_needs_review=bool(item.vacancy_setup and not setup_current(item)),eligible_positions=form.fields['open_positions'].queryset.exists(),setup_url=reverse('workspace-vacancy-new')+f'?requisition={pk}&section=setup'))
