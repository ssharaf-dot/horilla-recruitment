from django.db import migrations,models
from django.conf import settings


class Migration(migrations.Migration):
    dependencies=[('recruitment_experience','0006_activity_sources')]
    operations=[
        migrations.AlterField(model_name='jdproviderconfig',name='id',field=models.PositiveSmallIntegerField(primary_key=True,default=1,editable=False,serialize=False)),
        migrations.AlterField(model_name='workflowevent',name='applicant_actor',field=models.ForeignKey('recruitment_experience.applicantaccount',on_delete=models.SET_NULL,null=True,blank=True)),
        migrations.AlterField(model_name='workflowevent',name='requisition',field=models.ForeignKey('recruitment_experience.requisition',on_delete=models.PROTECT,related_name='activity_events',null=True,blank=True)),
        migrations.AlterField(model_name='jddraft',name='status',field=models.CharField(max_length=16,default='draft',choices=[('draft','Draft for HR review'),('applied','Applied by HR'),('failed','Draft attempt did not complete')]))]
