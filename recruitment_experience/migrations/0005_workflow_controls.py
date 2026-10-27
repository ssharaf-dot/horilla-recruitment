from django.conf import settings
from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('recruitment_experience', '0004_candidateprofile'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='OfferApproval', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('candidate', models.ForeignKey('recruitment.Candidate', on_delete=models.PROTECT, related_name='offer_approvals')),
            ('prepared_by', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='prepared_offers')),
            ('director', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_offers')),
            ('role_title', models.CharField(max_length=160)),
            ('monthly_salary', models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(1)])),
            ('currency', models.CharField(max_length=3, default='AED', choices=[('AED', 'AED'), ('USD', 'USD'), ('GBP', 'GBP'), ('EUR', 'EUR')])),
            ('proposed_joining', models.DateField()),
            ('terms', models.TextField(max_length=4000, help_text='Contract type, allowances, conditions and reference to the reviewed offer package. Do not upload passport details here.')),
            ('status', models.CharField(max_length=12, default='pending', choices=[('pending', 'Awaiting Director'), ('approved', 'Approved'), ('declined', 'Changes required'), ('withdrawn', 'Withdrawn by HR')])),
            ('decision_note', models.TextField(max_length=2000, blank=True)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('decided_at', models.DateTimeField(null=True, blank=True))
        ], options={'ordering': ['-pk'], 'permissions': [('approve_offer', 'Act as HR Director for assigned offer approvals')], 'constraints': [models.UniqueConstraint(fields=['candidate'], condition=models.Q(status='pending'), name='workspace_one_pending_offer')]}),
        migrations.CreateModel(name='JoiningPlan', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('candidate', models.OneToOneField('recruitment.Candidate', on_delete=models.PROTECT, related_name='joining_plan')),
            ('created_by', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('appointment_at', models.DateTimeField(null=True, blank=True)),
            ('appointment_location', models.CharField(max_length=240, blank=True)),
            ('handover_reference', models.CharField(max_length=240, blank=True)),
            ('version', models.PositiveIntegerField(default=1))
        ], options={}),
        migrations.CreateModel(name='JoiningTask', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('plan', models.ForeignKey('recruitment_experience.JoiningPlan', on_delete=models.PROTECT, related_name='tasks')),
            ('key', models.SlugField(max_length=60)),
            ('phase', models.PositiveSmallIntegerField()),
            ('title', models.CharField(max_length=180)),
            ('required_for_joining', models.BooleanField(default=True)),
            ('assigned_to', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='joining_tasks')),
            ('due_date', models.DateField(null=True, blank=True)),
            ('status', models.CharField(max_length=16, default='todo', choices=[('todo', 'To do'), ('in_progress', 'In progress'), ('done', 'Complete'), ('not_applicable', 'Not applicable')])),
            ('evidence', models.TextField(max_length=2000, blank=True)),
            ('completed_at', models.DateTimeField(null=True, blank=True)),
            ('completed_by', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='completed_joining_tasks')),
            ('version', models.PositiveIntegerField(default=1))
        ], options={'ordering': ['phase', 'pk'], 'constraints': [models.UniqueConstraint(fields=['plan', 'key'], name='workspace_joining_task_key')]}),
        migrations.CreateModel(name='JDDraft', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('job', models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, related_name='jd_drafts')),
            ('author', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)),
            ('brief', models.TextField(max_length=6000)),
            ('text', models.TextField(max_length=16000, blank=True)),
            ('source_description_sha256', models.CharField(max_length=64)),
            ('provider', models.CharField(max_length=24, default='manual')),
            ('model_name', models.CharField(max_length=100, blank=True)),
            ('status', models.CharField(max_length=16, default='draft', choices=[('draft', 'Draft for HR review'), ('applied', 'Applied by HR')])),
            ('version', models.PositiveIntegerField(default=1)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('applied_at', models.DateTimeField(null=True, blank=True))
        ], options={}),
        migrations.CreateModel(name='JDProviderConfig', fields=[
            ('id', models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)),
            ('encrypted_key', models.TextField(blank=True)),
            ('key_suffix', models.CharField(max_length=4, blank=True)),
            ('enabled', models.BooleanField(default=False)),
            ('model_name', models.CharField(max_length=100, default='claude-sonnet-4-6')),
            ('workspace_id', models.CharField(max_length=100, blank=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('updated_by', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True))
        ], options={}),
        migrations.AddField(model_name='workflowevent', name='job', field=models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, related_name='workspace_events', null=True, blank=True)),
        migrations.AddField(model_name='workflowevent', name='requisition', field=models.ForeignKey('Requisition', on_delete=models.PROTECT, related_name='activity_events', null=True, blank=True)),
        migrations.AddField(model_name='workflowevent', name='actor_label', field=models.CharField(max_length=200, blank=True)),
        migrations.AddField(model_name='workflowevent', name='applicant_actor', field=models.ForeignKey('ApplicantAccount', on_delete=models.SET_NULL, null=True, blank=True)),
        migrations.AddField(model_name='workflowevent', name='origin', field=models.CharField(max_length=24, default='recorded', choices=[('recorded', 'Recorded interaction'), ('imported', 'Historical source')])),
        migrations.AlterField(model_name='workflowevent', name='candidate', field=models.ForeignKey('recruitment.Candidate', on_delete=models.PROTECT, related_name='workspace_events', null=True, blank=True)),
        migrations.AddIndex(model_name='workflowevent', index=models.Index(fields=['job','-created_at'], name='workspace_job_event_time')),
    ]
