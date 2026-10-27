from django.apps import AppConfig


class RecruitmentExperienceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recruitment_experience'

    def ready(self):
        from .activity import connect
        connect()
