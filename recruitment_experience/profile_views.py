"""Explicit HR review before structured CV suggestions become profile data."""
import hashlib
import json
from django import forms
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from recruitment.models import Candidate
from .models import CandidateProfile
from .access import scoped_candidates, require_coordinate
from .cv_profile import extract_resume
from .services import audit
from .views import workspace, context

PROFILE_FIELDS=['headline','about','experience','education','skills']
CONTACT_FIELDS=['name','email','mobile','city','country','portfolio']
LABELS={'headline':'Professional headline','about':'About','experience':'Experience','education':'Education','skills':'Skills','name':'Full name','email':'Email','mobile':'Phone','city':'City','country':'Country','portfolio':'Portfolio / professional website'}


class ProfileForm(forms.Form):
    name=forms.CharField(max_length=100,label='Full name')
    email=forms.EmailField(max_length=254)
    mobile=forms.CharField(max_length=15,required=False,label='Phone')
    city=forms.CharField(max_length=30,required=False)
    country=forms.CharField(max_length=30,required=False)
    portfolio=forms.URLField(max_length=200,required=False,label=LABELS['portfolio'])
    headline=forms.CharField(max_length=160,required=False,label=LABELS['headline'])
    about=forms.CharField(max_length=4000,required=False,widget=forms.Textarea(attrs={'rows':4}))
    experience=forms.CharField(max_length=6000,required=False,widget=forms.Textarea(attrs={'rows':6}),help_text='Role, employer, dates and achievements. Keep separate roles on separate lines.')
    education=forms.CharField(max_length=4000,required=False,widget=forms.Textarea(attrs={'rows':4}))
    skills=forms.CharField(max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}),help_text='Enter skills separated by commas or on separate lines.')
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    confirm=forms.BooleanField(label='I have checked these details against the CV or candidate information and confirm this update')
    def clean_portfolio(self):
        value=self.cleaned_data['portfolio']
        if value and not value.startswith(('https://','http://')):raise forms.ValidationError('Use an http or https website address.')
        return value

    def clean_mobile(self):
        value=self.cleaned_data['mobile']
        for validator in Candidate._meta.get_field('mobile').validators:
            if value:validator(value)
        return value


@workspace
@require_http_methods(['GET','POST'])
def profile_edit(request,pk):
    record=get_object_or_404(scoped_candidates(request.user),pk=pk)
    require_coordinate(request.user,record)
    profile=CandidateProfile.objects.filter(candidate=record).first()
    initial={key:getattr(record,key) or '' for key in CONTACT_FIELDS}
    initial.update({key:getattr(profile,key) if profile else '' for key in PROFILE_FIELDS})
    initial['version']=profile.version if profile else 0
    suggestions={};resume_token='';extraction_note=''
    if request.method=='GET' and request.GET.get('extract')=='1':
        suggestions,digest,extraction_note=extract_resume(record)
        if digest:resume_token=signing.dumps({'candidate':record.pk,'digest':digest},salt='cv-profile-review')
    contact_token=signing.dumps({key:initial[key] for key in CONTACT_FIELDS},salt='profile-contact-snapshot')
    form=ProfileForm(request.POST or None,initial=initial)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            # Lock the existing application even before its first profile exists.
            current=Candidate.objects.select_for_update().get(pk=record.pk)
            require_coordinate(request.user,current)
            profile=CandidateProfile.objects.select_for_update().filter(candidate=current).first()
            try:
                contacts=signing.loads(request.POST.get('contact_token',''),salt='profile-contact-snapshot',max_age=7200)
                contact_current={key:getattr(current,key) or '' for key in CONTACT_FIELDS}
            except signing.BadSignature:
                contacts=None;contact_current={}
            if contacts != contact_current:
                form.add_error(None,'Contact details changed or this editing session expired. Reload the profile before saving.')
            elif form.cleaned_data['version']!=(profile.version if profile else 0):
                form.add_error(None,'This profile changed while you were reviewing it. Reload the current version before saving.')
            else:
                digest=''
                token=request.POST.get('resume_token','')
                if token:
                    try:
                        payload=signing.loads(token,salt='cv-profile-review',max_age=3600)
                        if payload['candidate']!=current.pk:raise signing.BadSignature()
                        with current.resume.open('rb') as source:raw=source.read(10*1024*1024+1)
                        digest=hashlib.sha256(raw).hexdigest()
                        if digest!=payload['digest']:raise signing.BadSignature()
                    except (signing.BadSignature,KeyError,OSError,ValueError):
                        form.add_error(None,'The CV review expired or the CV changed. Reload suggestions before saving. Your existing profile is unchanged.')
                if not form.errors:
                    profile=profile or CandidateProfile(candidate=current)
                    changed=[key for key in CONTACT_FIELDS if (getattr(current,key) or '')!=form.cleaned_data[key]]
                    # Update only reviewed contact fields, never stages, status, ownership or employer.
                    if changed:Candidate.objects.filter(pk=current.pk).update(**{key:form.cleaned_data[key] for key in changed})
                    changed += [key for key in PROFILE_FIELDS if getattr(profile,key)!=form.cleaned_data[key]]
                    for key in PROFILE_FIELDS:setattr(profile,key,form.cleaned_data[key])
                    profile.version+=1;profile.reviewed_by=request.user
                    if digest:profile.source_resume_sha256=digest
                    profile.save()
                    audit(current,request.user,'profile_review','HR confirmed profile fields',fields=changed,cv_assisted=bool(digest),version=profile.version)
                    messages.success(request,'Reviewed profile saved. The original CV and application stage are unchanged.')
                    return redirect('workspace-candidate',pk=pk)
        resume_token=request.POST.get('resume_token','')
    rows=[dict(key=key,label=LABELS.get(key,key.title()),value=value,current=initial.get(key,''),field_id='id_'+key) for key,value in suggestions.items() if key in CONTACT_FIELDS+PROFILE_FIELDS]
    return render(request,'experience/profile_edit.html',context(request,active='candidates',title='Review candidate profile',candidate=record,form=form,suggestions=rows,resume_token=resume_token,contact_token=contact_token,extraction_note=extraction_note,profile_fields=PROFILE_FIELDS))
