from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('recruitment_experience', '0003_confirmed_divisions'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='CandidateProfile', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('headline', models.CharField(blank=True,max_length=160)),
        ('about', models.TextField(blank=True,max_length=4000)),
        ('experience', models.TextField(blank=True,max_length=6000)),
        ('education', models.TextField(blank=True,max_length=4000)),
        ('skills', models.TextField(blank=True,max_length=2000)),
        ('source_resume_sha256', models.CharField(blank=True,max_length=64)),
        ('version', models.PositiveIntegerField(default=1)),
        ('updated_at', models.DateTimeField(auto_now=True)),
        ('candidate', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='talent_profile',to='recruitment.candidate')),
        ('reviewed_by', models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
    ])]
