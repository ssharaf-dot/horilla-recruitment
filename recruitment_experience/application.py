"""A resumable application draft is not a Candidate until final submission."""
import secrets
import json
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from recruitment.models import Candidate, RecruitmentSurvey, RecruitmentSurveyAnswer
from .models import ApplicationDraft
from .views import enabled, applicant_account, attach_application
from .services import notify, audit


def snapshot(job):
    return list(RecruitmentSurvey.objects.filter(recruitment_ids=job).order_by('sequence','pk').values('id','question','type','options','is_mandatory'))


def draft_owner(request):
    if not request.session.get('application_draft_owner'):
        request.session['application_draft_owner']=secrets.token_hex(32)
    return request.session['application_draft_owner']


def owned_drafts(request):
    from django.db.models import Q
    account=applicant_account(request)
    access=Q(owner_key=draft_owner(request))
    if account:
        access|=Q(account=account)
    return ApplicationDraft.objects.filter(access,created_at__gte=timezone.now()-timedelta(days=30))


def about_form(job,account=None):
    class AboutForm(forms.Form):
        name=forms.CharField(max_length=100,label='Full name')
        email=forms.EmailField()
        mobile=forms.CharField(max_length=15,required=False,label='Phone number',help_text='Include your country code, for example +971. Applicants outside the UAE can use their own country code.')
        job_position_id=forms.ModelChoiceField(queryset=job.open_positions.all(),label='Position')
        country=forms.CharField(max_length=30,required=False)
        city=forms.CharField(max_length=30,required=False)
        portfolio=forms.URLField(required=False,label='Portfolio or LinkedIn URL')
        def clean_mobile(self):
            from recruitment.models import validate_mobile
            value=self.cleaned_data['mobile']
            if value:
                validate_mobile(value)
            return value
        def clean_email(self):
            email=self.cleaned_data['email'].strip().lower()
            if account and email!=account.email.lower():
                raise forms.ValidationError('Use the email for your signed-in applicant account.')
            return email
    if job.open_positions.count()==1:
        field=AboutForm.base_fields['job_position_id']
        field.initial=job.open_positions.first();field.widget=forms.HiddenInput()
    return AboutForm


def questions_form(questions,initial_files=None):
    fields={}
    for question in questions:
        key='q'+str(question['id'])
        args={'label':question['question'],'required':question['is_mandatory']}
        kind=question['type']
        choices=[(x.strip(),x.strip()) for x in (question['options'] or '').split(',') if x.strip()]
        if kind in ['options','multiple']:
            field=forms.MultipleChoiceField(choices=choices,**args) if kind=='multiple' else forms.ChoiceField(choices=[('','Choose an answer')]+choices,**args)
        elif kind=='checkbox':
            field=forms.ChoiceField(choices=[('','Choose an answer'),('yes','Yes'),('no','No')],**args)
        elif kind in ['number','percentage','rating']:
            limits={'min_value':0,'max_value':100} if kind=='percentage' else ({'min_value':1,'max_value':5} if kind=='rating' else {})
            field=forms.DecimalField(**limits,**args)
        elif kind=='date':
            field=forms.DateField(widget=forms.DateInput(attrs={'type':'date'}),**args)
        elif kind=='file':
            field=forms.FileField(initial=(initial_files or {}).get(key),help_text='Maximum file size 5 MB. Files are available only to the authorized hiring team.',**args)
        else:
            field=forms.CharField(max_length=4000,widget=forms.Textarea(attrs={'rows':3}) if kind=='textarea' else forms.TextInput(),**args)
        fields[key]=field
    return type('QuestionsForm',(forms.Form,),fields)


@never_cache
@require_http_methods(['GET','POST'])
def wizard(request,pk,draft_id=None):
    enabled()
    from recruitment_portal.views import public_jobs
    job=get_object_or_404(public_jobs(),pk=pk)
    account=applicant_account(request)
    if draft_id is None:
        draft=owned_drafts(request).filter(job=job,candidate=None).order_by('-updated_at').first()
        if not draft:
            draft=ApplicationDraft.objects.create(job=job,account=account,owner_key=draft_owner(request),questions=snapshot(job))
        return redirect('portal-apply-draft',pk=pk,draft_id=draft.pk)
    draft=get_object_or_404(owned_drafts(request),pk=draft_id,job=job)
    if draft.candidate_id:
        return receipt(request,draft.pk)
    raw=request.GET.get('step',str(draft.step))
    step=min(max(int(raw),1),draft.step,4) if raw.isdigit() else draft.step
    if step==1:
        initial=dict(draft.data)
        if account:
            initial.setdefault('name',account.name);initial.setdefault('email',account.email)
        form=about_form(job,account)(request.POST or None,initial=initial)
    elif step==2:
        class UploadForm(forms.Form):
            resume=forms.FileField(required=not job.optional_resume,label='Your CV',help_text='PDF only, up to 10 MB. A saved file stays with this draft.',initial=draft.resume or None,widget=forms.ClearableFileInput(attrs={'accept':'.pdf'}))
            if not job.optional_profile_image:
                profile=forms.ImageField(label='Photo required by this vacancy',required=True,initial=draft.attachments.get('profile'))
            def clean_resume(self):
                value=self.cleaned_data.get('resume')
                if value and hasattr(value,'chunks'):
                    if value.size>10*1024*1024:
                        raise forms.ValidationError('This file exceeds 10 MB. Upload a smaller PDF.')
                    value.seek(0);valid=value.read(5)==b'%PDF-';value.seek(0)
                    if not valid:
                        raise forms.ValidationError('Upload a valid PDF CV.')
                return value
        form=UploadForm(request.POST or None,request.FILES or None)
    elif step==3:
        form=questions_form(draft.questions,draft.attachments)(request.POST or None,request.FILES or None,initial=draft.answers)
    else:
        class ConfirmForm(forms.Form):
            confirm=forms.BooleanField(label='I have reviewed my details and want to submit this application.')
        form=ConfirmForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if step==1:
            draft.data={k:str(v.pk) if k=='job_position_id' else v for k,v in form.cleaned_data.items()}
        elif step==2:
            upload=form.cleaned_data.get('resume')
            if upload is False:
                draft.resume=''
            elif upload and hasattr(upload,'chunks'):
                draft.resume.save(secrets.token_hex(16)+'.pdf',upload,save=False)
            if form.cleaned_data.get('profile') and hasattr(form.cleaned_data['profile'],'chunks'):
                upload=form.cleaned_data['profile']
                draft.attachments['profile']=default_storage.save('recruitment_experience/drafts/'+secrets.token_hex(16)+'.image',upload)
        elif step==3:
            for key,value in form.cleaned_data.items():
                if hasattr(value,'chunks'):
                    if value.size>5*1024*1024:
                        form.add_error(key,'This file exceeds 5 MB. Upload a smaller file.');continue
                    path=default_storage.save('recruitment_experience/drafts/'+secrets.token_hex(20),value)
                    draft.attachments[key]=path;draft.answers[key]='File received'
                elif value is not None:
                    draft.answers[key]=value if isinstance(value,(list,str,bool,int,float)) else str(value)
        else:
            # Validate every preceding step again, then lock the draft against double submit.
            about=about_form(job,account)(draft.data)
            questions=questions_form(draft.questions,draft.attachments)(draft.answers)
            if not about.is_valid() or not questions.is_valid() or (not job.optional_resume and not draft.resume):
                form.add_error(None,'Review your details, CV and required questions before submitting.')
            else:
                with transaction.atomic():
                    draft=ApplicationDraft.objects.select_for_update().get(pk=draft.pk)
                    if not draft.candidate_id:
                        get_object_or_404(public_jobs().select_for_update(of=('self',)),pk=job.pk)
                        values=about.cleaned_data.copy()
                        values['job_position_id']=values.pop('job_position_id')
                        candidate=Candidate(**values,recruitment_id=job,source='application')
                        candidate.resume.name=draft.resume.name if draft.resume else ''
                        if draft.attachments.get('profile'):
                            candidate.profile.name=draft.attachments['profile']
                        stages=job.stage_set.filter(is_active=True)
                        candidate.stage_id=stages.filter(stage_type='applied').first() or stages.order_by('sequence','pk').first()
                        if not candidate.stage_id:
                            form.add_error(None,'This vacancy is not ready to receive applications. Please contact recruitment.')
                        else:
                            candidate.save()
                            if draft.questions:
                                answers={q['question']:draft.answers.get('q'+str(q['id']),draft.attachments.get('q'+str(q['id']),'')) for q in draft.questions}
                                RecruitmentSurveyAnswer.objects.create(candidate_id=candidate,recruitment_id=job,job_position_id=candidate.job_position_id,answer_json=json.dumps(answers))
                            attach_application(request,candidate)
                            draft.candidate=candidate;draft.save()
                            audit(candidate,None,'submitted','Application and questionnaire submitted together')
                            notify('application:'+str(candidate.pk),candidate.email,'Application received',f'We received your application for {job.title}. Your reference is #{candidate.pk}. Sign in to your applicant account to see shared updates.')
                    if draft.candidate_id:
                        return redirect('portal-apply-receipt',draft_id=draft.pk)
        if not form.errors:
            draft.step=max(draft.step,min(step+1,4));draft.save()
            return redirect(reverse('portal-apply-draft',kwargs={'pk':pk,'draft_id':draft.pk})+'?step='+str(min(step+1,4)))
    answers=[(q['question'],draft.answers.get('q'+str(q['id']),'')) for q in draft.questions]
    return render(request,'portal/application_wizard.html',{'job':job,'draft':draft,'form':form,'step':step,'steps':[(1,'About you'),(2,'CV'),(3,'Questions'),(4,'Review and submit')],'answer_summary':answers,'account':account})


@never_cache
@require_http_methods(['GET'])
def receipt(request,draft_id):
    enabled()
    draft=get_object_or_404(owned_drafts(request).select_related('candidate','job'),pk=draft_id,candidate__isnull=False)
    return render(request,'portal/application_receipt.html',{'candidate':draft.candidate,'job':draft.job})
