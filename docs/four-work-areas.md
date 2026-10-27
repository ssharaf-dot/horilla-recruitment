# Four recruitment work areas

This interface groups the existing recruitment workflows into four work areas. It preserves existing roles, stages, legal employers, offer outcomes, applications, CVs and applicant ownership. No data migration or permission expansion is required.

1. **Requisitions & assignment, steps 01–03:** manpower requisition; HR Director review and assignment; vacancy registration.
2. **Sourcing & selection, steps 04–08:** sourcing/contact logging; CV submission; CV screening; interview coordination; interview and selection.
3. **Offers & acceptance, steps 09–10:** offer approval; offer management.
4. **Joining & closure, steps 11–14:** pre-joining documentation; pre-boarding/joining; onboarding/handover; reporting/closure.

The task-first home screen uses live scoped queues. Job cards show current application, sent-offer, accepted and joined counts separately; a hired-stage decision is not used as proof of joining. The right panel contains permitted upcoming interviews and shortcuts. Leadership sees aggregate data, without candidate identities in the panel or work areas. Managers still recommend while HR confirms moves and rejections.

Inside each area, use the view tabs to open existing queues. The process guide explains all fourteen steps with owners and capability labels. It is a reference, not evidence that a candidate completed those steps. Existing six-phase URLs remain valid as detailed views under the new four-area navigation. Division and vacancy filters stay within existing server-side access boundaries.

## Capabilities that are still partial or unconfigured

This visual release does **not** add automatic HR Director routing/TA assignment, contact-attempt tracking, formal CV submission batches, salary/notice-period tracking, a Director offer-approval gate, offer generation/delivery/signing/revocation, document verification, IT/SIM/NDA checklists, onboarding appointment booking, Document Controller acknowledgement, HRMS transfer, explicit requisition closure controls or AWFM reconciliation. Screens label these limits. Manual evidence-based offer outcomes remain as previously implemented; this release must not be presented as an enforced offer-approval workflow.

Applicant accounts retain their private applications and use a refreshed account summary. Microsoft sign-in, external messaging/calendar delivery and offsite backups remain separate configuration work. The public careers branding and existing demo profiles are retained.

## Validation and release

Run `deploy/six_phase_workflow.py` on **horilla_staging only**. It now tests the four-area routes, navigation, forged filters, role boundaries, read-only methods, capability labels and existing CV/profile flows, rolling back synthetic data. Also run the existing experience workflow, portal branding and recruitment boundary checks. Review desktop and phone rendering before publishing. Production checks use existing records only and must preserve record/media hashes, accounts, environment values, mounts, public ports and the existing database container. Keep a fresh restore-verified backup and the previous application image.


## Workflow controls release

Director offer approval, joining checklists, the activity tracker and Claude API configuration are documented in [workflow-controls.md](workflow-controls.md). That release supersedes the initial capability gaps for these features; external offer delivery, calendar delivery, automatic HRMS transfer, AWFM reconciliation and salary market estimates remain deferred.
