from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import InterviewFeedback, HiringRequest, ApplicantAccount


class NoteForm(forms.Form):
    note = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={'rows': 4}), label='Internal note')


class FeedbackForm(forms.ModelForm):
    class Meta:
        model = InterviewFeedback
        fields = ['technical', 'communication', 'evidence', 'recommendation']
        labels = {'technical': 'Role skills · 1 to 5', 'communication': 'Communication · 1 to 5', 'evidence': 'Evidence from the interview'}
        widgets = {'evidence': forms.Textarea(attrs={'rows': 5})}


class HiringRequestForm(forms.ModelForm):
    class Meta:
        model = HiringRequest
        fields = ['job', 'openings', 'reason']
        labels = {'openings': 'Additional openings', 'reason': 'Why is this opening needed?'}
        widgets = {'reason': forms.Textarea(attrs={'rows': 5})}
    def __init__(self, *args, jobs, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['job'].queryset = jobs.filter(closed=False)


class ScheduleForm(forms.Form):
    interview_date = forms.DateField(label='Date', widget=forms.DateInput(attrs={'type': 'date'}))
    interview_time = forms.TimeField(label='Time', widget=forms.TimeInput(attrs={'type': 'time'}))
    interviewers = forms.ModelMultipleChoiceField(queryset=None)
    details = forms.CharField(max_length=2000, label='Details shared with the applicant', help_text='Include location or a meeting link. Scheduling saves the appointment; it does not send email or create a calendar event.', widget=forms.Textarea(attrs={'rows': 4}))
    def __init__(self, *args, employees, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['interviewers'].queryset = employees
        self.fields['interview_time'].help_text = 'Time zone: ' + timezone.get_current_timezone_name()
    def clean(self):
        data = super().clean()
        date, time = data.get('interview_date'), data.get('interview_time')
        if date and time and (date < timezone.localdate() or (date == timezone.localdate() and time <= timezone.localtime().time().replace(tzinfo=None))):
            raise forms.ValidationError('Choose an interview time in the future.')
        return data


class ApplicantAccessForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput(), max_length=128)


class ApplicantRegistrationForm(ApplicantAccessForm):
    name = forms.CharField(max_length=100, label='Full name')
    confirm_password = forms.CharField(widget=forms.PasswordInput(), max_length=128)
    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if ApplicantAccount.objects.filter(email=email).exists():
            raise forms.ValidationError('An applicant account already uses this email. Sign in instead.')
        return email
    def clean(self):
        data = super().clean()
        if data.get('password') != data.get('confirm_password'):
            self.add_error('confirm_password', 'Passwords must match.')
        if data.get('password'):
            try:
                validate_password(data['password'])
            except ValidationError as error:
                self.add_error('password', error)
        return data


class ReviewDecisionForm(forms.Form):
    recommendation = forms.ChoiceField(choices=[('advance', 'Advance'), ('hold', 'Hold'), ('decline', 'Decline')])
    note = forms.CharField(max_length=4000, label='Reason and evidence', widget=forms.Textarea(attrs={'rows': 4}))


class InterviewPlanForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}), help_text='Dubai time (Asia/Dubai, UTC+04:00)')
    duration_minutes = forms.IntegerField(min_value=15, max_value=240, initial=45)
    format = forms.ChoiceField(choices=[('in_person', 'In person'), ('online', 'Online'), ('phone', 'Phone')])
    location = forms.CharField(max_length=240, required=False)
    meeting_url = forms.URLField(required=False)
    interviewers = forms.ModelMultipleChoiceField(queryset=None)
    details = forms.CharField(max_length=2000, label='Instructions visible to the applicant', widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, employees, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['interviewers'].queryset = employees

    def clean(self):
        data = super().clean()
        from datetime import datetime
        from .services import WORKING_ZONE
        if data.get('date') and data.get('time'):
            starts = datetime.combine(data['date'], data['time'], tzinfo=WORKING_ZONE)
            if starts <= timezone.now():
                self.add_error('time', 'Choose an interview time in the future.')
            data['starts_at'] = starts
        if data.get('format') == 'online' and not data.get('meeting_url'):
            self.add_error('meeting_url', 'Add the online meeting link. Meeting creation is not connected yet.')
        if data.get('format') == 'in_person' and not data.get('location'):
            self.add_error('location', 'Add the interview location.')
        return data
