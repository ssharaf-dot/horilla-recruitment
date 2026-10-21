from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ('recruitment', '__first__'), ('employee', '__first__')]
    operations = [
        migrations.CreateModel(name='ApplicantAccount', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('email', models.EmailField(max_length=254, unique=True)), ('name', models.CharField(max_length=100)),
            ('password', models.CharField(max_length=128)), ('created_at', models.DateTimeField(auto_now_add=True))]),
        migrations.CreateModel(name='ApplicantApplication', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='applications', to='recruitment_experience.applicantaccount')),
            ('candidate', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_owner', to='recruitment.candidate'))]),
        migrations.CreateModel(name='ReviewRequest', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('created_at', models.DateTimeField(auto_now_add=True)), ('completed_at', models.DateTimeField(blank=True, null=True)),
            ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_reviews', to='recruitment.candidate')),
            ('reviewer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='employee.employee')),
            ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL))]),
        migrations.AddConstraint(model_name='reviewrequest', constraint=models.UniqueConstraint(fields=('candidate', 'reviewer'), name='workspace_candidate_reviewer')),
        migrations.CreateModel(name='InterviewFeedback', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('technical', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
            ('communication', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
            ('evidence', models.TextField(max_length=4000)),
            ('recommendation', models.CharField(choices=[('proceed', 'Proceed'), ('more_information', 'Need more information'), ('do_not_proceed', 'Do not proceed')], max_length=24)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('author', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('interview', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_feedback', to='recruitment.interviewschedule'))]),
        migrations.AddConstraint(model_name='interviewfeedback', constraint=models.UniqueConstraint(fields=('interview', 'author'), name='workspace_interview_author')),
        migrations.CreateModel(name='HiringRequest', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('openings', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(100)])),
            ('reason', models.TextField(max_length=4000)),
            ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('declined', 'Declined')], default='pending', max_length=12)),
            ('decision_note', models.TextField(blank=True, max_length=2000)), ('created_at', models.DateTimeField(auto_now_add=True)), ('decided_at', models.DateTimeField(blank=True, null=True)),
            ('job', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='workspace_hiring_requests', to='recruitment.recruitment')),
            ('requested_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='workspace_requests', to=settings.AUTH_USER_MODEL)),
            ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='workspace_decisions', to=settings.AUTH_USER_MODEL))],
            options={'permissions': [('view_hiringoverview', 'View organization hiring overview'), ('approve_hiringrequest', 'Approve additional job openings')]})
    ]
