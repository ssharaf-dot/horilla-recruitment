from io import BytesIO
import uuid
import re

from django import forms
from django.core.files.base import ContentFile
from PIL import Image

from .models import PortalBranding


class BrandingForm(forms.ModelForm):
    class Meta:
        model = PortalBranding
        exclude = ['id', 'updated_at']
        widgets = {'careers_intro': forms.Textarea(attrs={'rows': 4}),
                   'accent_color': forms.TextInput(attrs={'type': 'color'})}
        labels = {'portal_name': 'Portal name', 'organization_name': 'Organization or group name',
                  'tagline': 'Short tagline', 'careers_headline': 'Careers headline',
                  'careers_intro': 'Careers introduction', 'accent_color': 'Brand colour',
                  'website_url': 'Company website', 'privacy_url': 'Privacy notice URL',
                  'contact_email': 'Recruitment contact email', 'logo': 'Company logo',
                  'careers_banner': 'Careers homepage banner', 'careers_banner_alt': 'Banner image description',
                  'logo_on_dark': 'Use a dark background behind the logo'}

    def clean_accent_color(self):
        color = self.cleaned_data['accent_color']
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise forms.ValidationError('Enter a colour such as #14574b.')
        values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        luminance = sum(a*b for a, b in zip(linear, (.2126, .7152, .0722)))
        if 1.05 / (luminance + .05) < 4.5:
            raise forms.ValidationError('Choose a darker colour so white button text stays readable.')
        return color.lower()

    def clean_logo(self):
        logo = self.cleaned_data.get('logo')
        if not logo or not hasattr(logo, 'content_type'):
            return logo
        if logo.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Use a PNG, JPEG or WebP logo smaller than 2 MB.')
        try:
            image = Image.open(logo)
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or max(image.size) > 4096:
                raise ValueError()
            image.load()
            image = image.convert('RGBA')
            output = BytesIO()
            image.save(output, format='PNG')
        except (OSError, ValueError, Image.DecompressionBombError):
            raise forms.ValidationError('Use a valid PNG, JPEG or WebP image up to 4096 pixels.')
        return ContentFile(output.getvalue(), name=uuid.uuid4().hex + '.png')

    def clean_careers_banner(self):
        upload = self.cleaned_data.get('careers_banner')
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        if upload.size > 8 * 1024 * 1024:
            raise forms.ValidationError('Use an image smaller than 8 MB.')
        try:
            image = Image.open(upload)
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or max(image.size) > 6000:
                raise ValueError()
            image.load()
            image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='WEBP', quality=88)
        except (OSError, ValueError, Image.DecompressionBombError):
            raise forms.ValidationError('Use a PNG, JPEG or WebP image up to 6000 pixels.')
        return ContentFile(output.getvalue(), name=uuid.uuid4().hex + '.webp')


def application_form_class():
    # Import lazily so branding tests can run without starting Horilla schedulers.
    from recruitment.models import Candidate

    class PublicApplicationForm(forms.ModelForm):
        gender = forms.ChoiceField(required=False, choices=[('', 'Prefer not to say')] + list(Candidate.choices))

        class Meta:
            model = Candidate
            fields = ['name', 'email', 'mobile', 'job_position_id', 'resume', 'profile',
                      'portfolio', 'country', 'city', 'gender']
            labels = {'name': 'Full name', 'mobile': 'Phone number', 'job_position_id': 'Position',
                      'resume': 'Your CV', 'profile': 'Profile photo', 'portfolio': 'Portfolio or LinkedIn URL'}

        def __init__(self, *args, recruitment, **kwargs):
            super().__init__(*args, **kwargs)
            self.instance.recruitment_id = recruitment
            self.fields['job_position_id'].queryset = recruitment.open_positions.all()
            self.fields['job_position_id'].required = True
            self.fields['resume'].required = not recruitment.optional_resume
            self.fields['profile'].required = not recruitment.optional_profile_image
            self.fields['resume'].widget.attrs['accept'] = '.pdf'
            self.fields['profile'].widget.attrs['accept'] = '.png,.jpg,.jpeg,.webp'
            if self.fields['job_position_id'].queryset.count() == 1:
                self.fields['job_position_id'].initial = self.fields['job_position_id'].queryset.first()

        def clean_resume(self):
            resume = self.cleaned_data.get('resume')
            if resume and resume.size > 10 * 1024 * 1024:
                raise forms.ValidationError('Use a PDF smaller than 10 MB.')
            return resume

        def clean_gender(self):
            return self.cleaned_data.get('gender') or None

    return PublicApplicationForm
