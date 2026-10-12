from io import BytesIO
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import BrandingForm
from .models import PortalBranding, get_branding


def brand_context(request):
    return {'portal_brand': get_branding()}


class Jobs(list):
    def count(self):
        return len(self)


class BrandingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.invalid', 'test-only')
        self.viewer = User.objects.create_user('viewer')
        self.data = {'portal_name': 'Example Talent', 'organization_name': 'Example Company',
                     'tagline': 'A shared future.', 'careers_headline': 'Make your next move.',
                     'careers_intro': 'Work with our team.', 'accent_color': '#14574b'}

    def test_reading_defaults_does_not_write(self):
        self.assertEqual(get_branding().portal_name, 'Recruitment')
        self.assertEqual(PortalBranding.objects.count(), 0)

    def test_settings_require_authentication_and_branding_permission(self):
        response = self.client.post(reverse('portal-branding'), self.data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('portal-branding'), self.data).status_code, 403)
        self.assertFalse(PortalBranding.objects.exists())

    def test_branding_updates_the_public_page_without_code_changes(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('portal-branding'), self.data).status_code, 302)
        self.client.logout()
        with patch('recruitment_portal.views.public_jobs', return_value=Jobs()):
            response = self.client.get(reverse('portal-careers'))
        self.assertContains(response, 'Example Talent')
        self.assertContains(response, 'Example Company')
        self.assertContains(response, 'Make your next move.')
        self.assertContains(response, 'Work with our team.')
        self.assertContains(response, 'We don’t have any open roles right now.')
        self.assertEqual(PortalBranding.objects.count(), 1)

    def test_delegated_permission_can_save_branding_without_becoming_superuser(self):
        self.viewer.user_permissions.add(Permission.objects.get(codename='change_portalbranding'))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('portal-branding'), self.data).status_code, 302)
        self.assertEqual(get_branding().portal_name, 'Example Talent')
        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.is_superuser)

    def test_invalid_colour_and_low_contrast_are_validation_errors(self):
        for color in ('#zzzzzz', '#ffffff', 'red', '};body{', '#ffff00'):
            form = BrandingForm(dict(self.data, accent_color=color))
            self.assertFalse(form.is_valid(), color)
            self.assertIn('accent_color', form.errors)

    def test_script_urls_are_rejected(self):
        for field in ('website_url', 'privacy_url'):
            form = BrandingForm(dict(self.data, **{field: 'javascript:alert(1)'}))
            self.assertFalse(form.is_valid())
            self.assertIn(field, form.errors)

    def test_branding_text_is_escaped_in_public_html(self):
        PortalBranding.objects.create(**dict(self.data, organization_name='<script>alert(1)</script>'))
        with patch('recruitment_portal.views.public_jobs', return_value=Jobs()):
            response = self.client.get(reverse('portal-careers'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_logo_is_decoded_and_reencoded_before_public_serving(self):
        stream = BytesIO(); Image.new('RGB', (20, 20), '#14574b').save(stream, 'JPEG')
        upload = SimpleUploadedFile('logo.jpg', stream.getvalue(), content_type='image/jpeg')
        form = BrandingForm(self.data, {'logo': upload})
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save()
        self.assertTrue(record.logo.name.endswith('.png'))
        response = self.client.get(reverse('portal-logo'))
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'\x89PNG'))
        record.logo.delete()

    def test_active_html_and_invalid_images_cannot_be_uploaded_as_a_logo(self):
        upload = SimpleUploadedFile('logo.svg', b'<svg onload="alert(1)"></svg>', content_type='image/svg+xml')
        form = BrandingForm(self.data, {'logo': upload})
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)

    def test_public_logo_endpoint_has_no_path_parameter(self):
        self.assertEqual(self.client.get(reverse('portal-logo')).status_code, 404)
        self.assertEqual(self.client.get('/careers/brand/logo/../../secret').status_code, 404)

    @override_settings(RECRUITMENT_ONLY=False)
    def test_portal_routes_are_unavailable_when_mode_is_disabled(self):
        self.assertEqual(self.client.get(reverse('portal-careers')).status_code, 404)

    def test_public_reads_reject_write_methods(self):
        self.assertEqual(self.client.post(reverse('portal-careers')).status_code, 405)
        self.assertEqual(self.client.post(reverse('portal-logo')).status_code, 405)
