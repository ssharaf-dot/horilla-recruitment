"""Saved, scoped requisition substeps and versioned leadership decisions."""
import html
import re
import uuid
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction, IntegrityError
from django.http import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .access import recruiter, scoped_jobs
from .activity import record_event
from .models import Requisition, RequisitionRevision
from .phase_data import permitted_requisitions
from .views import workspace

SUBSTEPS=[('Hiring need','Define the role and why it is needed.'),('Job description','Prepare and review the public job description.'),('Success measures','Define the internal outcomes expected from this hire.'),('Budget & terms','Propose the salary range and total hiring budget.'),('Review & submit','Review the complete package before CEO approval.')]
OUTLINE={'role_summary':'Role summary','responsibilities':'Responsibilities','required_skills':'Required skills','experience':'Experience and prerequisites','education':'Education or equivalent experience','desirable_skills':'Desirable skills'}
KPA={'kpa_outcomes':'Expected outcomes','kpa_measures':'How success will be measured','kpa_timeframe':'Timeframe'}
SUGGESTIONS={
 'role_summary':'We are seeking a [role title] to [describe the main purpose and contribution of this role].',
 'responsibilities':'• [List a key responsibility]\n• [List another responsibility]\n• [Describe the expected output]',
 'required_skills':'• [List an essential technical or professional skill]\n• [List another essential skill]',
 'experience':'[Describe relevant experience and practical prerequisites. Include a minimum only when justified.]',
 'education':'[State a relevant qualification or equivalent experience, or state that no formal qualification is required.]',
 'desirable_skills':'• [List an optional skill that would be helpful, or leave this section blank]',
 'kpa_outcomes':'• [Describe an outcome this hire should deliver]\n• [Describe another expected outcome]',
 'kpa_measures':'[Explain what evidence or measure will demonstrate each outcome.]',
 'kpa_timeframe':'[Specify when these outcomes should be achieved or reviewed.]',
}
BASE=['title','division','employer','openings','department','grade','work_location','employment_type','hire_reason','reason']
BUDGET=['salary_min','salary_max','salary_currency','salary_period','salary_basis','annual_budget','budget_notes','target_start_date']
SECTIONS={1:BASE,2:list(OUTLINE)+['jd_text','jd_document','jd_reviewed'],3:list(KPA)+['kpa_document'],4:BUDGET,5:['approver','assignment_director','confirm']}
MODEL_FIELDS=BASE+['jd_text','jd_document','jd_reviewed','kpa_document']+BUDGET+['approver','assignment_director']
SNAPSHOT_FIELDS=MODEL_FIELDS+['kpa_text','jd_outline','wizard_step','status','approved_version','ta_owner_id']
PROMPTS=re.compile(r'\[(?:role title|describe|add|list|state|specify|explain|enter|key|primary|expected|measure|time|qualification|relevant)[^\]]*\]',re.I)


def snapshot(item):
    from django.db.models.fields.files import FieldFile
    data={}
    for key in SNAPSHOT_FIELDS:
        value=getattr(item,key)
        if hasattr(value,'pk'):value=value.pk
        elif isinstance(value,FieldFile):value=value.name
        elif isinstance(value,Decimal):value=str(value)
        elif hasattr(value,'isoformat'):value=value.isoformat()
        data[key]=value
    return data


def revision(item,user,kind,note=''):
    return RequisitionRevision.objects.create(requisition=item,version=item.version,actor=user,kind=kind,note=note,snapshot=snapshot(item))


def budget_floor(item):
    return (item.salary_max or Decimal(0))*(12 if item.salary_period=='month' else 1)*(item.openings or 0)


def missing(item):
    issues=[]
    for key,label in [('title','Role title'),('division_id','Division'),('employer_id','Legal employer'),('openings','Number of openings'),('reason','Hiring reason'),('department','Department / team'),('work_location','Work location'),('employment_type','Employment type'),('hire_reason','New position / replacement')]:
        if not getattr(item,key,None):issues.append((1,label+' is required.'))
    if not item.jd_text.strip() or len(item.jd_text.strip())<40:issues.append((2,'Provide a public JD with responsibilities and requirements.'))
    if not item.jd_reviewed:issues.append((2,'Review and confirm the public JD.'))
    if PROMPTS.search(item.jd_text):issues.append((2,'Replace the unfinished [prompts] in the JD.'))
    if not item.kpa_text.strip() or len(item.kpa_text.strip())<40:issues.append((3,'Define the expected outcomes, measures and timeframe.'))
    if PROMPTS.search(item.kpa_text):issues.append((3,'Replace the unfinished [prompts] in the success measures.'))
    if item.salary_min is None or item.salary_max is None or item.salary_min<=0 or item.salary_max<item.salary_min:issues.append((4,'Enter a positive salary range with maximum at least equal to minimum.'))
    if not item.salary_basis:issues.append((4,'Specify whether salary means gross cash or base pay.'))
    if item.annual_budget is None or item.annual_budget<budget_floor(item):issues.append((4,'The annual total budget must cover the salary-only upper estimate for all openings.'))
    if not item.approver_id or not item.assignment_director_id:issues.append((5,'Select the CEO approver and HR Director.'))
    if item.approver_id==item.requested_by_id:issues.append((5,'The requester cannot approve their own hiring need.'))
    return issues


class SectionForm(forms.ModelForm):
    expected_version=forms.IntegerField(widget=forms.HiddenInput,initial=1)
    creation_token=forms.UUIDField(widget=forms.HiddenInput,required=False)
    confirm=forms.BooleanField(required=False,label='I reviewed the complete hiring package and want to submit it for CEO approval')
    role_summary=forms.CharField(required=False,max_length=1200,label=OUTLINE['role_summary'])
    responsibilities=forms.CharField(required=False,max_length=2400,label=OUTLINE['responsibilities'])
    required_skills=forms.CharField(required=False,max_length=1600,label=OUTLINE['required_skills'])
    experience=forms.CharField(required=False,max_length=1200,label=OUTLINE['experience'])
    education=forms.CharField(required=False,max_length=1000,label=OUTLINE['education'])
    desirable_skills=forms.CharField(required=False,max_length=1600,label=OUTLINE['desirable_skills'])
    kpa_outcomes=forms.CharField(required=False,max_length=2500,label=KPA['kpa_outcomes'])
    kpa_measures=forms.CharField(required=False,max_length=2000,label=KPA['kpa_measures'])
    kpa_timeframe=forms.CharField(required=False,max_length=500,label=KPA['kpa_timeframe'])
    class Meta:
        model=Requisition
        fields=MODEL_FIELDS
        labels={'title':'Role title / designation','grade':'Grade / seniority (if applicable)','department':'Department / team','work_location':'Work location','employment_type':'Employment type','hire_reason':'Type of hiring need','employer':'Legal employer','openings':'Number of openings','reason':'Why is this role needed?','jd_text':'Public JD — preview and edit','jd_document':'Supporting JD document (PDF)','jd_reviewed':'I reviewed the public JD for accuracy; it is ready to submit','kpa_document':'Supporting KPA document (PDF)','salary_min':'Proposed salary — minimum per person','salary_max':'Proposed salary — maximum per person','salary_currency':'Currency','salary_period':'Pay period','salary_basis':'Salary basis','annual_budget':'Total budget for the first 12 months — all openings','budget_notes':'What does this budget include?','target_start_date':'Desired joining date (if known)','approver':'CEO approver','assignment_director':'HR Director for recruiter assignment'}
        widgets={key:forms.Textarea(attrs={'rows':3}) for key in ['reason','budget_notes']}|{'jd_text':forms.Textarea(attrs={'rows':12}),'target_start_date':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,user,section=1,ceo=False,**kwargs):
        from .operations import allowed_divisions
        from .requisitions import RequestForm
        super().__init__(*args,**kwargs)
        self.section=section
        allowed=(['title','openings','department','grade','work_location','employment_type','hire_reason','reason','jd_text','jd_reviewed']+BUDGET) if ceo else SECTIONS[section]
        for key in list(self.fields):
            if key not in allowed+['expected_version','creation_token']:del self.fields[key]
        self.order_fields(allowed+['expected_version','creation_token'])
        for key,field in self.fields.items():
            if key not in ['expected_version']:field.required=False
            if key in OUTLINE or key in KPA:
                field.widget=forms.Textarea(attrs={'rows':3,'data-template':SUGGESTIONS[key],'placeholder':SUGGESTIONS[key],'aria-describedby':'hint_'+key})
                field.help_text='Use the template, or press Tab to insert it while this empty field is focused. Escape skips the suggestion. Replace every [prompt].'
            if key in ['salary_min','salary_max','annual_budget']:field.widget.attrs.update(min='0',step='0.01',inputmode='decimal')
            if key.endswith('_document'):
                field.widget=forms.FileInput(attrs={'accept':'application/pdf'});field.help_text='Private PDF, up to 5 MB / 50 pages. The reviewed public JD text is the version used for the vacancy.'
        if 'division' in self.fields:self.fields['division'].queryset=allowed_divisions(user)
        if 'approver' in self.fields:
            route=RequestForm(user=user)
            self.fields['approver'].queryset=route.fields['approver'].queryset
            self.fields['assignment_director'].queryset=route.fields['assignment_director'].queryset
        self.fields.get('employer',forms.CharField()).help_text='Contracting entity; this can differ from the operational division.'
        if self.instance.pk:
            for key in OUTLINE:
                if key in self.fields:self.initial[key]=(self.instance.jd_outline or {}).get(key,'')
            for key in KPA:
                if key in self.fields:self.initial[key]=(self.instance.jd_outline or {}).get('kpa',{}).get(key,self.instance.kpa_text if key=='kpa_outcomes' else '')
            self.initial['expected_version']=self.instance.version
    def clean(self):
        values=super().clean()
        for key in ['jd_document','kpa_document']:
            upload=self.files.get(key)
            if upload:
                import fitz
                try:
                    if upload.size>5*1024*1024:raise ValueError()
                    data=upload.read();upload.seek(0)
                    if not data.startswith(b'%PDF-'):raise ValueError()
                    pdf=fitz.open(stream=data,filetype='pdf');valid=not pdf.is_encrypted and 0<pdf.page_count<=50;pdf.close()
                    if not valid:raise ValueError()
                except (ValueError,RuntimeError):self.add_error(key,'Use an unencrypted, readable PDF with 1–50 pages, up to 5 MB.')
                else:upload.name=uuid.uuid4().hex+'.pdf'
        return values


def fields_for(form):return [dict(bound=form[key],template=SUGGESTIONS.get(key,'')) for key in form.fields if key not in ['expected_version','creation_token']]


def wizard_context(request,item,section,**extra):
    from .requisitions import page_context,steps
    return page_context(request,title=f'Step 1{chr(64+section)} · '+SUBSTEPS[section-1][0],item=item,wizard_section=True,hide_action_rail=True,wizard_steps=steps(1,item),substeps=[dict(number=i,label=label,url=(reverse('workspace-requisition-edit',args=[item.pk])+'?section='+str(i)) if item else '',current=i==section,available=bool(item and i<=item.wizard_step)) for i,(label,_) in enumerate(SUBSTEPS,1)],section=section,section_label=SUBSTEPS[section-1][0],section_intro=SUBSTEPS[section-1][1],salary_floor=budget_floor(item) if item else 0,**extra)


@workspace
@require_http_methods(['GET','POST'])
def edit(request,pk=None):
    from .requisitions import editable
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk) if pk else None
    if item and not editable(request.user,item):raise PermissionDenied('This request is under review. Open its status to see who acts next.')
    if not item and not (recruiter(request.user) or scoped_jobs(request.user).exists()):raise PermissionDenied()
    raw=request.POST.get('section',request.GET.get('section',str(item.resume_section if item else 1)))
    section=min(max(int(raw),1),item.wizard_step if item else 1) if raw.isdigit() else 1
    token=uuid.uuid4() if not item else item.creation_token
    form=SectionForm(request.POST or None,request.FILES or None,instance=item,user=request.user,section=section,initial={'creation_token':token,'expected_version':item.version if item else 1,'openings':1})
    action=request.POST.get('action','save')
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk) if item else None
            if current and (not editable(request.user,current) or current.version!=form.cleaned_data['expected_version']):form.add_error(None,'Another person saved a newer version. Your input is still shown below; open the latest saved request in another tab before retrying.')
            elif not item and not form.cleaned_data.get('creation_token'):form.add_error(None,'The draft form expired. Open a new request and copy your inputs before retrying.')
            else:
                value=form.save(commit=False)
                if not item:
                    value.requested_by=request.user;value.status='draft';value.creation_token=form.cleaned_data['creation_token']
                    duplicate=Requisition.objects.filter(creation_token=value.creation_token).first()
                    if duplicate:
                        if duplicate.requested_by_id!=request.user.pk:raise PermissionDenied()
                        return redirect('workspace-requisition-edit',pk=duplicate.pk)
                if not value.title.strip():form.add_error('title' if 'title' in form.fields else None,'Add a role title so this draft can be found again.')
                if section==2:
                    value.jd_outline={**(value.jd_outline or {}),**{k:form.cleaned_data.get(k,'') for k in OUTLINE}}
                    if action=='build_jd':
                        value.jd_text='\n\n'.join(OUTLINE[k]+'\n'+form.cleaned_data[k].strip() for k in OUTLINE if form.cleaned_data.get(k,'').strip());value.jd_reviewed=False
                    if request.FILES.get('jd_document'):
                        import fitz
                        upload=request.FILES['jd_document'];upload.seek(0);doc=fitz.open(stream=upload.read(),filetype='pdf');text='\n'.join(page.get_text() for page in doc)[:16000];doc.close();upload.seek(0)
                        value.jd_text=text.strip();value.jd_reviewed=False;action='upload_jd'
                if section==3:
                    data={k:form.cleaned_data.get(k,'').strip() for k in KPA};value.jd_outline={**(value.jd_outline or {}),'kpa':data}
                    value.kpa_text='\n\n'.join(KPA[k]+'\n'+v for k,v in data.items() if v)
                if action in ['next','submit']:
                    issues=missing(value)
                    for step,problem in issues:
                        if step==section or action=='submit':form.add_error(None,problem)
                    if action=='submit' and not form.cleaned_data.get('confirm'):form.add_error('confirm','Confirm you reviewed the package before submitting.')
                if not form.errors:
                    value.version=(current.version if current else 0)+1
                    value.wizard_step=max(current.wizard_step if current else 1,min(section+1,5) if action=='next' else section)
                    if action=='submit':value.status='pending';value.submitted_at=timezone.now();value.decided_at=None;value.decision_note='';value.approved_version=0
                    value.resume_section=min(section+1,5) if action=='next' else max(1,section-1) if action=='back' else section
                    try:
                        with transaction.atomic():value.save()
                    except IntegrityError:
                        duplicate=Requisition.objects.filter(creation_token=value.creation_token,requested_by=request.user).first()
                        if current or not duplicate:raise
                        return redirect('workspace-requisition-edit',pk=duplicate.pk)
                    record_event(requisition=value,kind='requisition_submitted' if action=='submit' else 'requisition_draft',detail='Hiring package submitted for CEO approval' if action=='submit' else f'Step 1{chr(64+section)} saved: '+SUBSTEPS[section-1][0],metadata={'version':value.version,'section':section})
                    if action=='submit':
                        revision(value,request.user,'submitted');messages.success(request,'Submitted to '+str(value.approver.get_full_name() or value.approver.username)+'. Your task is complete for now; the CEO owns the next action.');return redirect('workspace-requisition-detail',pk=value.pk)
                    if action=='close':messages.success(request,'Draft saved. Resume it at the last unfinished section.');return redirect('workspace-area',slug='requisitions')
                    if action=='ai':return redirect('workspace-requisition-jd',pk=value.pk)
                    if action=='upload_jd':messages.success(request,'PDF saved privately. Review the extracted public text below; paste or complete it if extraction missed content.')
                    elif action=='build_jd':messages.success(request,'JD draft prepared from your inputs. Review the wording, replace [prompts] and confirm it before continuing.')
                    target=section+1 if action=='next' else max(1,section-1) if action=='back' else section
                    return redirect(reverse('workspace-requisition-edit',args=[value.pk])+'?section='+str(min(target,5)))
    return render(request,'experience/requisition_wizard.html',wizard_context(request,item,section,form=form,form_fields=fields_for(form),package_issues=missing(item) if item and section==5 else []))


@workspace
@require_http_methods(['GET','POST'])
def ceo_edit(request,pk):
    from .requisitions import page_context,steps
    item=get_object_or_404(permitted_requisitions(request.user),pk=pk)
    if item.approver_id!=request.user.pk or not request.user.has_perm('recruitment_experience.approve_hiringrequest'):raise PermissionDenied()
    if item.status!='pending':messages.error(request,'This request is no longer awaiting your decision.');return redirect('workspace-requisition-detail',pk=pk)
    form=SectionForm(request.POST or None,instance=item,user=request.user,section=5,ceo=True)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            current=Requisition.objects.select_for_update().get(pk=pk)
            if current.status!='pending' or current.version!=form.cleaned_data['expected_version']:form.add_error(None,'This package changed. Your edits remain below; reload the latest version before recording a decision.')
            else:
                action=request.POST.get('decision');note=request.POST.get('note','').strip()[:2000];value=form.save(commit=False)
                if action not in ['approved','changes']:form.add_error(None,'Choose Edit & approve or Return with changes.')
                if action=='changes' and not note:form.add_error(None,'Explain what the requester must change.')
                if request.POST.get('confirm')!='yes':form.add_error(None,'Confirm you reviewed your changes and this decision.')
                if action=='approved':
                    for _,problem in missing(value):form.add_error(None,problem)
                if not form.errors:
                    before=snapshot(current);value.version=current.version+1;value.status=action;value.decision_note=note;value.decided_at=timezone.now();value.approved_version=value.version if action=='approved' else 0
                    if action=='changes':value.wizard_step=5;value.resume_section=5
                    value.save();changed=[k for k,v in snapshot(value).items() if k not in ['status','approved_version','wizard_step'] and before.get(k)!=v]
                    revision(value,request.user,'ceo_edited_approved' if action=='approved' else 'ceo_edited_returned',note)
                    record_event(requisition=value,kind='requisition_decision',detail='CEO edited and '+('approved the revised package' if action=='approved' else 'returned the package for changes')+(' · '+note if note else ''),metadata={'version':value.version,'changed_fields':changed})
                    messages.success(request,'Revised version approved. The HR Director now assigns a recruiter.' if action=='approved' else 'Changes and reason saved. The requester can revise and resubmit.');return redirect('workspace-requisition-detail',pk=pk)
    return render(request,'experience/requisition_ceo_edit.html',page_context(request,title='CEO · Edit hiring package',item=item,form=form,form_fields=fields_for(form),wizard_section=True,hide_action_rail=True,wizard_steps=steps(2,item),ceo_edit=True,note=request.POST.get('note','')[:2000]))
