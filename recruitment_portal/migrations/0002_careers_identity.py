from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('recruitment_portal', '0001_initial')]
    operations = [
        migrations.AddField(model_name='portalbranding', name='careers_banner', field=models.ImageField(blank=True, upload_to='portal-branding/')),
        migrations.AddField(model_name='portalbranding', name='careers_banner_alt', field=models.CharField(blank=True, default='', max_length=180)),
        migrations.AddField(model_name='portalbranding', name='logo_on_dark', field=models.BooleanField(default=False)),
    ]
