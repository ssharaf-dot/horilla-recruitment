from django.core.validators import RegexValidator
from django.db import models


class PortalBranding(models.Model):
    """One configurable brand per installation; contains no applicant data."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    portal_name = models.CharField(max_length=80, default='Recruitment')
    organization_name = models.CharField(max_length=100, blank=True)
    tagline = models.CharField(max_length=160, default='A place for your next chapter.')
    careers_headline = models.CharField(max_length=160, default='Build what comes next.')
    careers_intro = models.TextField(max_length=1200, default='Explore our open roles and find an opportunity to do work that matters.')
    accent_color = models.CharField(max_length=7, default='#14574b', validators=[RegexValidator(r'^#[0-9a-fA-F]{6}$', 'Enter a colour such as #14574b.')])
    logo = models.ImageField(upload_to='portal-branding/', blank=True)
    careers_banner = models.ImageField(upload_to='portal-branding/', blank=True)
    careers_banner_alt = models.CharField(max_length=180, blank=True, default='')
    logo_on_dark = models.BooleanField(default=False)
    website_url = models.URLField(blank=True)
    privacy_url = models.URLField(blank=True)
    contact_email = models.EmailField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return self.portal_name


def get_branding():
    # Reading a public page must never create or modify a settings record.
    return PortalBranding.objects.filter(pk=1).first() or PortalBranding()
