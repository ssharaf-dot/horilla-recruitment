from django.conf import settings
from django.db import models,migrations
from django.core.validators import MinValueValidator,MaxValueValidator

class Migration(migrations.Migration):
    dependencies=[('recruitment_experience','0008_requisition_steps'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AlterField(model_name='requisition',name='division',field=models.ForeignKey('recruitment_experience.Division', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AlterField(model_name='requisition',name='employer',field=models.ForeignKey('base.Company', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AlterField(model_name='requisition',name='openings',field=models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(100)])),
        migrations.AddField(model_name='requisition',name='department',field=models.CharField(max_length=120, blank=True)),
        migrations.AddField(model_name='requisition',name='grade',field=models.CharField(max_length=100, blank=True)),
        migrations.AddField(model_name='requisition',name='work_location',field=models.CharField(max_length=160, blank=True)),
        migrations.AddField(model_name='requisition',name='employment_type',field=models.CharField(max_length=24, blank=True, choices=[('full_time', 'Full time'), ('part_time', 'Part time'), ('contract', 'Contract'), ('temporary', 'Temporary'), ('internship', 'Internship')])),
        migrations.AddField(model_name='requisition',name='hire_reason',field=models.CharField(max_length=20, blank=True, choices=[('new', 'New position'), ('replacement', 'Replacement'), ('backfill', 'Internal backfill')])),
        migrations.AddField(model_name='requisition',name='target_start_date',field=models.DateField(null=True, blank=True)),
        migrations.AddField(model_name='requisition',name='salary_min',field=models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])),
        migrations.AddField(model_name='requisition',name='salary_max',field=models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])),
        migrations.AddField(model_name='requisition',name='salary_currency',field=models.CharField(max_length=3, default='AED', choices=[('AED', 'AED'), ('USD', 'USD'), ('EUR', 'EUR'), ('GBP', 'GBP')])),
        migrations.AddField(model_name='requisition',name='salary_period',field=models.CharField(max_length=8, default='month', choices=[('month', 'Per month'), ('year', 'Per year')])),
        migrations.AddField(model_name='requisition',name='salary_basis',field=models.CharField(max_length=12, blank=True, choices=[('gross', 'Gross cash including fixed allowances'), ('base', 'Base pay only')])),
        migrations.AddField(model_name='requisition',name='annual_budget',field=models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])),
        migrations.AddField(model_name='requisition',name='budget_notes',field=models.TextField(max_length=2000, blank=True)),
        migrations.AddField(model_name='requisition',name='jd_outline',field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='requisition',name='jd_reviewed',field=models.BooleanField(default=False)),
        migrations.AddField(model_name='requisition',name='wizard_step',field=models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])),
        migrations.AddField(model_name='requisition',name='approved_version',field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='requisition',name='resume_section',field=models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(5)])),
        migrations.AddField(model_name='requisition',name='updated_at',field=models.DateTimeField(auto_now=True, null=True, blank=True)),
        migrations.AddField(model_name='requisition',name='vacancy_setup',field=models.JSONField(default=dict, blank=True)),
        migrations.AddField(model_name='requisition',name='creation_token',field=models.UUIDField(null=True, blank=True, unique=True, editable=False)),
        migrations.CreateModel(name='RequisitionRevision',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('requisition',models.ForeignKey('recruitment_experience.Requisition', on_delete=models.PROTECT, related_name='revisions')),('version',models.PositiveIntegerField()),('kind',models.CharField(max_length=32)),('actor',models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)),('snapshot',models.JSONField(default=dict)),('note',models.TextField(max_length=2000, blank=True)),('created_at',models.DateTimeField(auto_now_add=True))],options={'ordering':['-pk'],'constraints':[models.UniqueConstraint(fields=['requisition','version'],name='workspace_requisition_revision')]}),
    ]
