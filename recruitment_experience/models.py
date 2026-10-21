"""Additive recruitment workflows; existing Horilla records remain authoritative."""
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


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
