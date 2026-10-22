# Recruitment workspace

The recruitment-only deployment adds a Django workspace over the existing Horilla recruitment models. Branding remains configurable at `/settings/portal/`. Existing jobs, accounts, questionnaires, media and legacy recruitment tools are retained.

## Journeys

- `/recruitment/dashboard` is the existing login destination; it opens HR Today for recruiters, the leadership overview for users granted `recruitment_experience.view_hiringoverview`, and the manager home for assigned hiring managers/interviewers.
- `/recruitment/workspace/jobs/`: job list and per-job stage boards.
- `/recruitment/workspace/candidates/`: searchable applications, protected CVs, questionnaire answers, stage changes, review requests, notes and interviews.
- `/recruitment/workspace/manager/`: pending reviews, assigned hiring plan and interview feedback.
- `/recruitment/workspace/leadership/`: aggregate division progress, opening counts and pending decisions.
- `/recruitment/workspace/hiring-requests/`: request additional openings against an existing job. `recruitment_experience.approve_hiringrequest` permits approval; it updates vacancy headcount once under a database lock and records the deciding user and timestamp.
- `/careers/`: public jobs, division/location/work-type search and a four-step application draft with CV and screening questions before final submission.
- `/careers/account/`: separate applicant sign-in, owned applications, shared updates and interview details. An application submitted anonymously is accessible only in that browser session; an applicant account can retain those same-session submissions, or own new submissions made while signed in. Email matching alone never grants access to earlier candidate records.

All writes use POST and CSRF protection. Staff access is scoped to recruitment/stage assignments or assigned interviews unless existing global recruitment permissions grant wider access. A leadership overview permission grants aggregates, not access to private CVs. Only a superuser can preview an existing application as an applicant; that preview does not create an applicant session. Applicant identities never become Django staff users. CV responses require ownership or staff scope, use private/no-store caching and permit same-origin embedding only.

## Deployment and testing

Build using `deploy/Dockerfile`; no new Python packages are required. Apply the additive `recruitment_experience` migration before switching the app image. Preserve the existing database/media volumes, environment, worker command and published ports. Take and restore-test a fresh backup first; retain the preceding app image for rollback. The new tables may remain after an app rollback, preserving workflow records for the next deployment.

`deploy/experience_workflow.py` runs real Django requests against `horilla_staging` only. It refuses production, exercises the role journeys, stage changes, saved notes/reviews/feedback, idempotent approval, public applications and cross-role/cross-applicant access, then rolls back its synthetic database changes and deletes only its own generated test PDFs. The existing isolated recruitment-mode and branding tests continue to apply.

## Demo limits

Scheduling and review requests save records and update the workspace; they do not send email, publish to LinkedIn or create calendar invitations. Interview displays use Dubai time. Existing legacy date/time records are interpreted in the installation's original timezone and converted without rescheduling. New appointments retain an explicit timestamp. Email verification, applicant password recovery and outbound notifications require a separately configured delivery service before real applicant use. Existing mock candidates are not automatically converted into applicant accounts. Use the administrator-only preview to inspect their public view, or create an applicant account and submit a new application to test ownership.

Headcount is the configured number of vacancies on current open jobs, including recorded approvals. Critical means unfilled after 30 days; no budget or cost predictions are fabricated. Jobs are grouped under their HR-assigned division, with unassigned vacancies clearly identified. Each candidate row remains a separate job application as in Horilla. Existing stage names and outcomes are preserved; no unimplemented offer or onboarding process is presented as completed.

See [implementation status and remaining business/IT gates](IMPLEMENTATION_STATUS.md) for the current demo scope, division administration, application drafts, publication, requisitions and explicit offer outcomes. Calendar files are downloadable; Microsoft/Outlook integration and outbound delivery remain inactive.
