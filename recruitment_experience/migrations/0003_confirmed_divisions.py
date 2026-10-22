from django.db import migrations


def seed(apps, schema_editor):
    Division = apps.get_model('recruitment_experience', 'Division')
    for name, slug in [
        ('Fakhruddin Properties', 'fakhruddin-properties'),
        ('Fakhruddin Properties Development', 'fakhruddin-properties-development'),
        ('FIS', 'fis'),
        ('Ovington', 'ovington'),
    ]:
        Division.objects.get_or_create(slug=slug, defaults={'name': name})
    # Legal employers, existing vacancies and role assignments are deliberately untouched.


class Migration(migrations.Migration):
    dependencies = [('recruitment_experience', '0002_division_notificationdelivery_workflowevent_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
