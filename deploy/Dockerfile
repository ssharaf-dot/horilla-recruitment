# Keep precisely the existing image's dependencies, models and migrations.
ARG HORILLA_BASE_IMAGE=horilla/horilla@sha256:324d547548bdec2f533080cb56d5dc36bd20f49884079bb23061170d8061b6a2
FROM ${HORILLA_BASE_IMAGE}

WORKDIR /app
COPY deploy/verify_base.py /tmp/verify_fakhruddin_baseline.py
RUN python3 /tmp/verify_fakhruddin_baseline.py && rm /tmp/verify_fakhruddin_baseline.py

# Preserve the authentication migration already generated/applied at installation.
COPY deploy/runtime_migrations/auth/0013_user_is_new_employee.py /usr/local/lib/python3.10/site-packages/django/contrib/auth/migrations/0013_user_is_new_employee.py

COPY recruitment_workspace/ /app/recruitment_workspace/
COPY recruitment_experience/ /app/recruitment_experience/
COPY recruitment_portal/ /app/recruitment_portal/
COPY horilla/horilla_middlewares.py /app/horilla/horilla_middlewares.py
COPY horilla/urls.py /app/horilla/urls.py
COPY recruitment/views/surveys.py /app/recruitment/views/surveys.py
COPY recruitment/templates/candidate/success.html /app/recruitment/templates/candidate/success.html
COPY recruitment/templates/survey/candidate_survey_form.html /app/recruitment/templates/survey/candidate_survey_form.html
COPY recruitment/views/dashboard.py /app/recruitment/views/dashboard.py
COPY templates/index.html /app/templates/index.html
COPY templates/login.html /app/templates/login.html
COPY templates/portal/ /app/templates/portal/
COPY recruitment/templates/recruitment/nav.html /app/recruitment/templates/recruitment/nav.html
COPY recruitment/templates/pipeline/nav.html /app/recruitment/templates/pipeline/nav.html
COPY horilla/settings.py /app/horilla/settings.py
COPY horilla/config.py /app/horilla/config.py
COPY base/templatetags/horillafilters.py /app/base/templatetags/horillafilters.py
COPY base/templates/base/general_settings.html /app/base/templates/base/general_settings.html
COPY templates/settings.html /app/templates/settings.html
COPY templates/sidebar.html /app/templates/sidebar.html
COPY templates/floating_button.html /app/templates/floating_button.html
COPY employee/templates/employee/view/individual.html /app/employee/templates/employee/view/individual.html
COPY employee/templates/employee_nav.html /app/employee/templates/employee_nav.html

# No schema generation, migration or user creation on application restart.
CMD ["sh", "-c", "python3 manage.py collectstatic --noinput && exec gunicorn --bind 0.0.0.0:8000 horilla.wsgi:application"]
