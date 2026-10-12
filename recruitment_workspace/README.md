# Recruitment workspace for Horilla

An optional recruitment interface built on Horilla 1.0. It keeps Horilla's applications and dependencies installed, preserves recruitment data, and uses existing hiring permissions. Set `HORILLA_RECRUITMENT_ONLY=true` to enable it; set it to `false` to restore the original HRMS interface.

The workspace provides a hiring overview, flat navigation for jobs, pipelines, candidates and interviews, plus a public careers site with search, job details, applications and questionnaires. Administrators can configure the portal name, company name, logo, brand colour and careers copy at `/settings/portal/`. Those saved values appear across the workspace, team sign-in and public site. Defaults are generic. Branding is installation-wide; independent employers should use separate installations.

Public jobs must be active, published, open, already started and not expired. Applications are bound to the selected job and an explicit set of applicant fields. CVs remain behind Horilla's protected media route. Portal settings require `recruitment_portal.change_portalbranding`; assigning that permission allows a trusted administrator to manage branding without making them a superuser.

## Existing installations

Back up the database and media before changing the application. Rehearse with separate staging credentials, database and media volume first. Keep the current application image and deployment configuration for rollback. This source is pinned to upstream commit `bbfe3bd3e2ab54d05e20ed1cf782d4bbea66397b` and the matching published image; the Docker build checks the original files before applying the overlay. It does not claim compatibility with newer Horilla releases.

Build with `docker build -f deploy/Dockerfile -t horilla/recruitment-workspace:local .`. Against the intended database, run `python manage.py migrate recruitment_portal --noinput` before switching to the new application image. On a fresh installation, apply all existing Horilla migrations as well. This adds one portal-branding table. Application restart does not generate migrations, reset accounts or seed jobs.

Configure hosts, trusted origins and HTTPS for the destination environment. A reverse proxy must not expose the media volume as a public directory. Use fresh secrets, and keep `.env` files and uploaded media out of Git. Recruiters and managers still need the employee/user records required by Horilla. No live database, CVs or accounts are included in the public source.

## New installation with Docker Compose

Copy `deploy/.env.recruitment.example` to `deploy/.env.recruitment` and supply fresh secrets. Keep the initial mode `false` while completing Horilla’s normal company, administrator and employee setup. The example binds the application to localhost; use a controlled HTTPS reverse proxy for shared access.

```sh
docker compose --env-file deploy/.env.recruitment -f deploy/compose.recruitment.yaml build
docker compose --env-file deploy/.env.recruitment -f deploy/compose.recruitment.yaml up -d db
docker compose --env-file deploy/.env.recruitment -f deploy/compose.recruitment.yaml run --rm horilla python manage.py migrate --noinput
docker compose --env-file deploy/.env.recruitment -f deploy/compose.recruitment.yaml up -d
```

After initial setup, set `HORILLA_RECRUITMENT_ONLY=true` in the local environment file and recreate the application with the last command. Visit `/settings/portal/` to name and brand the portal, then create and publish jobs. The two named volumes hold the database and uploads; this source repository does not back up those volumes.

## Checks

Run the two isolated suites separately:

```sh
python -m django test recruitment_workspace --settings=recruitment_workspace.test_settings
python -m django test recruitment_portal --settings=recruitment_portal.test_settings
```

`deploy/staging_workflow.py` exercises existing hiring workflows. `deploy/portal_workflow.py` exercises branding, public visibility, applications, protected CVs and questionnaires. Both deliberately require the synthetic database name `horilla_staging` and create test records. Never run them against a live database.

The overlay retains Horilla's license and attribution. Read the root `LICENSE` and upstream project documentation before redistribution. This is a community customization and is not an official Horilla release.
