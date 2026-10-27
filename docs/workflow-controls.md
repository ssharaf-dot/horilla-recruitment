# Recruitment workflow controls

The four work areas now support Director offer approval, joining/onboarding checklists, a job/candidate activity tracker and an administrator-configured Claude drafting workflow. Existing applications, employers, profiles and CVs remain authoritative.

## Offer approval (step 09)

HR selects the candidate in the hired stage, opens **Prepare Director approval**, chooses a different authorised HR Director and records the role, total monthly salary/currency, proposed joining date, terms and evidence/reference. A pending request cannot be duplicated. Submitted terms are retained per request and cannot be edited; withdraw a pending request or submit revised terms after a decision.

The assigned Director sees only their assigned approval packages. The Director can approve or request changes with a reason; they cannot approve their own request. Existing HR accounts cannot approve simply because they can prepare offers. A superuser can act as a Director when assigned, but cannot self-approve.

HR cannot record an offer as sent until the latest terms are approved. New revised requests block issuance until approved. Changes to candidate selection invalidate outstanding approvals. Offer sent, acceptance and joined are separate evidence-based outcomes. External generation, signing and delivery of offer letters are not connected.

The dedicated permission is `recruitment_experience.approve_offer`. Do not grant general recruitment/candidate read permissions merely to let a Director approve. An administrator creates `demo_director` from Recruitment settings → Demo HR Director account, entering and confirming a password privately. This demo account is intended only for testing assigned requests. No preset password is committed or reused.

## Joining and onboarding (steps 11–13)

After actual offer acceptance, HR opens **Joining checklist**. One plan creates ten tasks covering document verification, compliance, agreements/NDA, IT, SIM, welcome instructions, appointment, actual joining, personnel-file handover and receiving HRMS reference. HR assigns existing scoped staff and due dates. Assignment grants no new candidate access.

HR can update all tasks in their scope; assigned staff can update their own tasks. Completion needs evidence. HR may mark an item not applicable with an explicit reason. Every save records an actor and timestamp; reopening retains previous actions. Stale versions are rejected.

HR records the agreed appointment in Dubai time, location and optional receiving HRMS reference. All required pre-joining items must be complete or explicitly not applicable, and an appointment recorded, before actual joining can be confirmed. The post-joining attendance task requires a joined outcome; the HRMS task requires a receiving reference. These are manual confirmations. No invitation is sent and no employee is automatically created in an HRMS.

## Activity tracker

Open **Activity tracker** from a job or candidate. Job history combines the job, linked requisition and visible candidate events. Filters separate changes from views/downloads; pages show 40 events each. Times include seconds and are displayed in Dubai time. Staff names are snapshotted so a later display-name change does not rewrite the old attribution.

Captured workspace actions include job creation/edit/publication, applications, stage changes/rejections, manager assignments, review/feedback, notes, CV access/profile review, offer requests/decisions/outcomes, checklist updates, onboarding details and JD drafts/application. Successful profile/job views are recorded separately. No mouse/keystroke surveillance or time-spent measurement is included. Anonymous applicants are labelled when an authenticated account is unavailable; email alone does not claim ownership.

The migration imports verifiable original job/application/requisition/interview-record creation dates and preserves earlier workflow event dates. Imported entries are marked **Historical source**. Appointment creation is not evidence that an interview took place. Earlier unrecorded stage moves, rejection dates and missing actors are not fabricated.

Operational event rows have no edit/delete interface; model edits/deletes are rejected, and job/candidate deletion is protected by retained events. This is an application audit trail, not a cryptographically immutable external archive. Database administrators can still change database rows. Legacy recruitment write handlers are read-only in recruitment-only mode because bulk writes can bypass scoping, approval and audit controls; use the workspace for changes. Normal Horilla mode is unaffected.

## Claude-assisted job descriptions

An administrator opens **Recruitment settings → Claude API settings**. Claude is Anthropic's model; one Anthropic API key is sufficient. Configure the model ID available to that API account and a workspace ID only if required. Save and explicitly enable drafting. Saving settings makes no external request. The key input is masked and blank on subsequent visits; blank retains the saved key. An explicit remove option clears it and disables drafting.

The server encrypts the key with Fernet using a domain-separated key derived from this installation's Django `SECRET_KEY`. Retain that secret privately when migrating; a changed server secret requires re-entry of the provider key. Never put the API key, encrypted settings database or private server secret in the public Git repository. Only a short key suffix is displayed. Ordinary HR, managers, Directors and leadership cannot access provider settings.

For a vacancy, HR opens **AI-assisted JD**, describes the role/topic, responsibilities, skills, seniority and location, then confirms sending the title and brief to Anthropic. Candidate/CV/offer data is never included automatically. The fixed official Messages endpoint is used with a 25-second timeout, no redirects or automatic retries, a bounded input and a 2,400-token response cap. Ten attempts per user and 100 across the demo per day are allowed; a one-minute user cooldown also applies. Failed attempts count. Configure an account spending limit in Anthropic Console as well; request counts are not a monetary budget.

Generated content is a draft. HR edits and confirms before applying it to the job. Existing publication status is preserved. Applying a stale draft is blocked if another user edited the description. Draft versions and actions are retained, and generated text is escaped before becoming public HTML. Provider refusal/incomplete/error responses leave the vacancy unchanged. Until a real key is entered, the UI says **Claude not connected**. Mocked provider tests do not establish that a real key, billing or model access works.

The salary market indicator is deferred. No generated salary is presented as researched market information. A later version needs an agreed source, geography, currency/period, seniority, data date, range and confidence explanation.

API reference: https://platform.claude.com/docs/en/api/overview and https://platform.claude.com/docs/en/api/messages/create.

## Deployment and rollback

Apply additive migrations in private staging first, run `deploy/workflow_controls.py` and the existing workflow/role suites, and review desktop/phone screens. Production release requires a fresh consistent database/media backup with a restore rehearsal. Stop application writes during the migration and verification window. Preserve the existing DB container, mount points, environment and uploads.

An application rollback leaves additive schema and imported activity in place. Do not reverse/drop workflow tables to roll back presentation code; that would remove new history. If a database restore is ever needed, account for any actions since the backup and obtain explicit approval before replacing current data. AI remains disabled until an administrator supplies a key. Tests use synthetic records inside rolled-back transactions, with no real Anthropic requests or messages to candidates.
