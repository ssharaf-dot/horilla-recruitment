from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('recruitment_experience', '0007_draft_attempt_status'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(model_name='requisition', name='approver', field=models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='assigned_requisitions')),
        migrations.AlterField(model_name='requisition', name='status', field=models.CharField(max_length=12, default='draft', choices=[('draft', 'Draft'), ('changes', 'Changes requested'), ('pending', 'Awaiting CEO approval'), ('approved', 'CEO approved'), ('declined', 'Declined')])),
        migrations.AddField(model_name='requisition', name='jd_text', field=models.TextField(max_length=16000, blank=True)),
        migrations.AddField(model_name='requisition', name='kpa_text', field=models.TextField(max_length=8000, blank=True)),
        migrations.AddField(model_name='requisition', name='jd_document', field=models.FileField(upload_to='requisition_documents/', blank=True)),
        migrations.AddField(model_name='requisition', name='kpa_document', field=models.FileField(upload_to='requisition_documents/', blank=True)),
        migrations.AddField(model_name='requisition', name='assignment_director', field=models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='requisitions_to_assign')),
        migrations.AddField(model_name='requisition', name='ta_owner', field=models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='owned_requisitions')),
        migrations.AddField(model_name='requisition', name='assigned_by', field=models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='ta_assignments_made')),
        migrations.AddField(model_name='requisition', name='submitted_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='requisition', name='assigned_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='requisition', name='registered_at', field=models.DateTimeField(null=True, blank=True)),
        migrations.AddField(model_name='requisition', name='version', field=models.PositiveIntegerField(default=1)),
        migrations.AlterField(model_name='jddraft', name='job', field=models.ForeignKey('recruitment.Recruitment', on_delete=models.PROTECT, null=True, blank=True, related_name='jd_drafts')),
        migrations.AddField(model_name='jddraft', name='requisition', field=models.ForeignKey('recruitment_experience.Requisition', on_delete=models.PROTECT, null=True, blank=True, related_name='jd_drafts')),
        migrations.AddConstraint(model_name='jddraft', constraint=models.CheckConstraint(check=(models.Q(job__isnull=False, requisition__isnull=True) | models.Q(job__isnull=True, requisition__isnull=False)), name='workspace_jd_one_parent')),
    ]
