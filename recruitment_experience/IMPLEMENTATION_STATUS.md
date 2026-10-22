# Group recruitment implementation — demo release

This release extends the existing Horilla recruitment system. It is a demo implementation, not approval to collect real applicant data or activate company identity and messaging services.

## Approved operating decisions

- Hiring managers recommend; HR controls stages, rejections and interview scheduling.
- Existing legal employers remain unchanged. HR assigns each vacancy to a division.
- Divisions: Fakhruddin Properties, Fakhruddin Properties Development, FIS and Ovington.
- Microsoft sign-in is deferred until IT supplies the company configuration. Existing passwords remain valid.

## Included in this build

- Division profiles and server-side division scopes, with aggregate leadership access and assigned manager/interviewer access.
- Careers keyword/division/location/work-type search, division counts and clearer vacancy summaries.
- Four-step owned drafts: details, CV, screening questions, review/submit. Only final submissions create candidate records; questionnaire snapshots and answers are retained.
- Protected paginated PDF preview with original download fallback; protected questionnaire attachment downloads.
- Separate HR queues, application search/reference lookup, board/list views and outcomes outside the active pipeline.
- HR stage-change preview with the shared message, rejection reason, stale-state guard and private activity events.
- Structured manager recommendations, independent interview-feedback visibility, and recorded criteria identifiers for new submissions using the existing assessment scale.
- Dubai interview display, new appointments with an explicit timestamp, edit/cancel actions and stable downloadable calendar files. Legacy wall-clock records are converted from the installation zone without moving their instant.
- Applicant-friendly public status, own document access, phone updates, withdrawal and requests to reschedule.
- Vacancy editing, team assignment, screening questions, explicit publication checks and new-vacancy requisitions with a named approver.
- Explicit offer sent/accepted/declined/joined records with evidence. A hired stage does not imply joining.
- Durable notification records held while external delivery is disconnected.

## Remaining decisions and integrations

Microsoft identity, email verification/recovery, outbound email, Outlook/Teams delivery, automated reminders and offsite backups remain inactive. A downloaded calendar file is not an Outlook invitation or a booked Teams meeting.

The demo uses one explicitly selected approver per new requisition. HR must approve the real approval/delegation/budget policy before a pilot. Existing vacancies are not retroactively put through an invented approval process. Existing additional-opening approvals remain a separate ledger.

HR/legal must supply the privacy notice, retention and deletion policy, public message wording and role-specific assessment criteria. No real retention policy or automatic deletion is activated by the draft-resumption window. Historical stage-entry and outcome dates remain unknown when they were never recorded.

A real pilot also needs named operational owners, a mail failure/recovery runbook, company IT testing and a restore rehearsal for the internal environment. The separate deferred Claude register remains the record of suggestions outside this release.
