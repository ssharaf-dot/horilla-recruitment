"""Additive recruitment workflows; existing Horilla records remain authoritative."""
from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid


class ReviewRequest(models.Model):
    candidate = models.ForeignKey('recruitment.Candidate', on_delete=models.CASCADE, related_name='workspace_reviews')
    reviewer = models.ForeignKey('employee.Employee', on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['candidate', 'reviewer'], name='workspace_candidate_reviewer')]


class InterviewFeedback(models.Model):
    interview = models.ForeignKey('recruitment.InterviewSchedule', on_delete=models.CASCADE, related_name='workspace_feedback')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    technical = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    communication = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    evidence = models.TextField(max_length=4000)
    recommendation = models.CharField(max_length=24, choices=[('proceed', 'Proceed'), ('more_information', 'Need more information'), ('do_not_proceed', 'Do not proceed')])
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['interview', 'author'], name='workspace_interview_author')]


class HiringRequest(models.Model):
    job = models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, related_name='workspace_hiring_requests')
    openings = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    reason = models.TextField(max_length=4000)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workspace_requests')
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Pending'), ('approved', 'Approved'), ('declined', 'Declined')])
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workspace_decisions', null=True, blank=True)
    decision_note = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        permissions = [('view_hiringoverview', 'View organization hiring overview'), ('approve_hiringrequest', 'Approve additional job openings')]


class ApplicantAccount(models.Model):
    """Separate from staff authentication. Email alone never claims old records."""
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    password = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)


class ApplicantApplication(models.Model):
    account = models.ForeignKey(ApplicantAccount, on_delete=models.CASCADE, related_name='applications')
    candidate = models.OneToOneField('recruitment.Candidate', on_delete=models.CASCADE, related_name='workspace_owner')
    created_at = models.DateTimeField(auto_now_add=True)


class Division(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    class Meta:
        ordering = ['name']
    def __str__(self):
        return self.name


class VacancyProfile(models.Model):
    """Business division is deliberately separate from Recruitment.company_id."""
    job = models.OneToOneField('recruitment.Recruitment', on_delete=models.CASCADE, related_name='workspace_profile')
    division = models.ForeignKey(Division, on_delete=models.PROTECT, null=True, blank=True)
    location = models.CharField(max_length=160, blank=True)
    work_type = models.CharField(max_length=30, blank=True, choices=[('full_time', 'Full time'), ('part_time', 'Part time'), ('contract', 'Contract'), ('temporary', 'Temporary')])


class DivisionAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.PROTECT)
    role = models.CharField(max_length=20, choices=[('recruiter', 'Division recruiter'), ('leadership', 'Division leadership')])
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'division', 'role'], name='workspace_division_role')]


class WorkflowEvent(models.Model):
    candidate = models.ForeignKey('recruitment.Candidate', on_delete=models.PROTECT, related_name='workspace_events', null=True, blank=True)
    job = models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, related_name='workspace_events', null=True, blank=True)
    requisition = models.ForeignKey('Requisition', on_delete=models.PROTECT, related_name='activity_events', null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    actor_label = models.CharField(max_length=200, blank=True)
    applicant_actor = models.ForeignKey('ApplicantAccount', on_delete=models.SET_NULL, null=True, blank=True)
    origin = models.CharField(max_length=24, default='recorded', choices=[('recorded', 'Recorded interaction'), ('imported', 'Historical source')])
    kind = models.CharField(max_length=40)
    detail = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['job', '-created_at'], name='workspace_job_event_time')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Activity entries are retained as recorded. Add a correcting entry instead.')
        if self.candidate_id and not self.job_id:
            self.job_id = self.candidate.recruitment_id_id
        if not self.actor_label:
            self.actor_label = (self.actor.get_full_name() or self.actor.username) if self.actor_id else ('Applicant · ' + self.applicant_actor.name if self.applicant_actor_id else 'System / actor not recorded')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Activity entries cannot be deleted through the application.')


class InterviewPlan(models.Model):
    interview = models.OneToOneField('recruitment.InterviewSchedule', on_delete=models.CASCADE, related_name='workspace_plan')
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=45, validators=[MinValueValidator(15), MaxValueValidator(240)])
    time_zone = models.CharField(max_length=64, default='Asia/Dubai')
    format = models.CharField(max_length=20, default='in_person', choices=[('in_person', 'In person'), ('online', 'Online'), ('phone', 'Phone')])
    location = models.CharField(max_length=240, blank=True)
    meeting_url = models.URLField(blank=True)
    status = models.CharField(max_length=12, default='scheduled', choices=[('scheduled', 'Scheduled'), ('cancelled', 'Cancelled')])
    version = models.PositiveIntegerField(default=1)
    calendar_uid = models.UUIDField(default=uuid.uuid4, unique=True)


class NotificationDelivery(models.Model):
    """Delivery is held until an operator explicitly enables a real mail backend."""
    key = models.CharField(max_length=180, unique=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=12, default='held', choices=[('held', 'Not connected'), ('queued', 'Queued'), ('sending', 'Sending'), ('sent', 'Sent'), ('failed', 'Failed')])
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)


class ApplicationDraft(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT)
    account = models.ForeignKey(ApplicantAccount, on_delete=models.PROTECT, null=True, blank=True)
    owner_key = models.CharField(max_length=64)
    data = models.JSONField(default=dict)
    questions = models.JSONField(default=list)
    answers = models.JSONField(default=dict)
    resume = models.FileField(upload_to='recruitment_experience/drafts/', blank=True)
    attachments = models.JSONField(default=dict)
    step = models.PositiveSmallIntegerField(default=1)
    candidate = models.OneToOneField('recruitment.Candidate', on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Requisition(models.Model):
    title = models.CharField(max_length=120)
    division = models.ForeignKey(Division, on_delete=models.PROTECT)
    employer = models.ForeignKey('base.Company', on_delete=models.PROTECT)
    openings = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    reason = models.TextField(max_length=4000)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='workspace_requisitions')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_requisitions')
    status = models.CharField(max_length=12, default='pending', choices=[('pending', 'Awaiting approval'), ('approved', 'Approved'), ('declined', 'Declined')])
    decision_note = models.TextField(max_length=2000, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    job = models.OneToOneField('recruitment.Recruitment', on_delete=models.PROTECT, null=True, blank=True, related_name='workspace_requisition')
    created_at = models.DateTimeField(auto_now_add=True)


class CandidateProfile(models.Model):
    """HR-reviewed profile for one application; CV extraction never saves itself."""
    candidate = models.OneToOneField('recruitment.Candidate', on_delete=models.CASCADE, related_name='talent_profile')
    headline = models.CharField(max_length=160, blank=True)
    about = models.TextField(max_length=4000, blank=True)
    experience = models.TextField(max_length=6000, blank=True)
    education = models.TextField(max_length=4000, blank=True)
    skills = models.TextField(max_length=2000, blank=True)
    source_resume_sha256 = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class OfferApproval(models.Model):
    """An immutable submitted set of terms; a revision requires a new request."""
    candidate = models.ForeignKey('recruitment.Candidate', on_delete=models.PROTECT, related_name='offer_approvals')
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='prepared_offers')
    director = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_offers')
    role_title = models.CharField(max_length=160)
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])
    currency = models.CharField(max_length=3, default='AED', choices=[('AED','AED'),('USD','USD'),('GBP','GBP'),('EUR','EUR')])
    proposed_joining = models.DateField()
    terms = models.TextField(max_length=4000, help_text='Contract type, allowances, conditions and reference to the reviewed offer package. Do not upload passport details here.')
    status = models.CharField(max_length=12, default='pending', choices=[('pending','Awaiting Director'),('approved','Approved'),('declined','Changes required'),('withdrawn','Withdrawn by HR')])
    decision_note = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    def save(self, *args, **kwargs):
        if self.pk:
            original=type(self).objects.get(pk=self.pk)
            fields=['candidate_id','prepared_by_id','director_id','role_title','monthly_salary','currency','proposed_joining','terms']
            if any(getattr(self,name)!=getattr(original,name) for name in fields):
                raise ValidationError('Submitted offer terms cannot be edited. Submit a new request.')
            if original.status!='pending':
                raise ValidationError('A decided offer request cannot be changed.')
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-pk']
        permissions = [('approve_offer', 'Act as HR Director for assigned offer approvals')]
        constraints = [models.UniqueConstraint(fields=['candidate'], condition=models.Q(status='pending'), name='workspace_one_pending_offer')]


class JoiningPlan(models.Model):
    candidate = models.OneToOneField('recruitment.Candidate', on_delete=models.PROTECT, related_name='joining_plan')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    appointment_at = models.DateTimeField(null=True, blank=True)
    appointment_location = models.CharField(max_length=240, blank=True)
    handover_reference = models.CharField(max_length=240, blank=True)
    version = models.PositiveIntegerField(default=1)


class JoiningTask(models.Model):
    plan = models.ForeignKey(JoiningPlan, on_delete=models.PROTECT, related_name='tasks')
    key = models.SlugField(max_length=60)
    phase = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=180)
    required_for_joining = models.BooleanField(default=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='joining_tasks')
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, default='todo', choices=[('todo','To do'),('in_progress','In progress'),('done','Complete'),('not_applicable','Not applicable')])
    evidence = models.TextField(max_length=2000, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='completed_joining_tasks')
    version = models.PositiveIntegerField(default=1)
    class Meta:
        ordering = ['phase', 'pk']
        constraints = [models.UniqueConstraint(fields=['plan','key'], name='workspace_joining_task_key')]


class JDDraft(models.Model):
    job = models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, related_name='jd_drafts')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    brief = models.TextField(max_length=6000)
    text = models.TextField(max_length=16000, blank=True)
    source_description_sha256 = models.CharField(max_length=64)
    provider = models.CharField(max_length=24, default='manual')
    model_name = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=16, default='draft', choices=[('draft','Draft for HR review'),('applied','Applied by HR'),('failed','Draft attempt did not complete')])
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)


class JDProviderConfig(models.Model):
    """Singleton; encrypted key is never returned to forms, HTML or event metadata."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    encrypted_key = models.TextField(blank=True)
    key_suffix = models.CharField(max_length=4, blank=True)
    enabled = models.BooleanField(default=False)
    model_name = models.CharField(max_length=100, default='claude-sonnet-4-6')
    workspace_id = models.CharField(max_length=100, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
