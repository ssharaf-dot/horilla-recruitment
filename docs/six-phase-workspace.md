# Six-phase recruitment workspace

The workspace organizes existing recruitment records into six phases. It does not rewrite historic stages, employers, approvals, offer responses or joining dates.

## Using the workspace

1. **Plan & approve:** create a hiring requisition and select its named approver. Review requests through their linked decision screen. Approved new requisitions can be prepared as draft vacancies. Additional-opening requests remain separate records; approved openings update their existing vacancy once.
2. **Publish & attract:** prepare the vacancy, assign its division and hiring team, add questions, and review the publication checklist. Draft, published and closed vacancies appear in separate columns. Existing published demo vacancies retain their original status; missing division assignments remain visible for HR to resolve.
3. **Screen & shortlist:** open candidate profiles, inspect the CV and answers, and request hiring manager recommendations. Columns use existing screening-stage names. HR reviews and confirms stage changes; managers cannot move or reject applications.
4. **Interview & select:** review the scheduling/assessment queue. HR schedules interviews; assigned interviewers record their feedback. Cards show the next relevant scheduling, interview, feedback or decision task. Dates and times use Dubai time while preserving the original appointment instant.
5. **Offer & acceptance:** record confirmed offer outcomes with evidence through the existing HR-only form. Preparing an offer, recording it as sent, and recording acceptance are distinct. The platform does not generate/sign/send an offer document in this release.
6. **Joining & HRMS handover:** accepted offers appear in joining preparation; recorded joining appears separately with handover still pending. Onboarding appointment booking and an HRMS connection are not configured. No card is marked as successfully transferred to an HRMS.

The Overview opens with a colour-coded candidate pipeline. The sticky phase navigation remains available across staff screens. Each phase shows its purpose, owner, completion guidance and counts. On a phone, swipe the phase strip and board horizontally; the selected phase is brought into view automatically. Settings, advanced tools and external-site links are in **Tools & settings**.

HR sees permitted operational work; managers see assigned applications and their recommendations/assessments; leadership phase screens show aggregate application counts rather than candidate names or CVs. Applicants use their separate account and private application journey.

## Counts and stage mapping

Phase 1 counts visible requisitions plus visible additional-opening requests; phase 2 counts permitted vacancies, including draft, published and closed records. Phases 3–6 count applications/joiners. Do not add these different units into a single funnel total.

Every scoped application is classified once, in this order:

- Cancelled applications/stages or rejected offers: closed outcomes, separate from successful hires.
- Accepted or joined offer status: joining/handover; joined remains distinct from accepted.
- Sent offer, hired decision/stage, or an existing stage whose name includes “offer”: offer/acceptance.
- Interview stages, or test stages not named as screening: interview/selection.
- Remaining applications: screening/shortlisting, retaining their configured stage labels.

This is a read-only presentation mapping. A historical hired-stage record with an offer marked “Not sent” does not become an accepted offer or a joined employee. Historic movement is shown only when a recorded stage event exists; otherwise the card says movement history is not recorded. Changes in job-stage configuration should be reviewed against this mapping.

## Candidate profiles and CV suggestions

The profile contains a professional header, contact details, About, Experience, Education and Skills, plus existing CV, screening answers, feedback and private activity. Initials provide a neutral avatar. The applied-for role is not presented as the candidate's current employment.

HR can choose **Review CV suggestions**. PDF text is extracted on the server using the existing local PDF library. No CV is sent to an external AI service. Supported suggestions are explicitly labelled names/phone numbers, email addresses and recognised summary/experience/education/skills sections. Name guesses, age, gender, nationality, qualification conclusions and candidate scoring are excluded.

Suggestions are unverified source text. They do not auto-populate saved fields. **Use in draft** copies one suggestion into an editable field; HR must check the result, tick the confirmation and save. Existing values remain visible for comparison. Experience and education are editable section text, not inferred structured employers/dates or verified qualifications.

Only permitted HR coordinators can extract or save profile details. Managers may read profiles they already have access to, and leadership has no new candidate access. Signed contact snapshots and profile versions prevent stale writes; signed CV review tokens detect changed files. Profile review is audited. No stage, employer, application ownership, offer status or original CV is changed by a profile edit.

Text extraction is limited to PDFs up to 10 MB, the first 20 pages and bounded section lengths. Image-only/scanned or protected PDFs may need manual entry. The original CV remains the authoritative reference. If there are no recognised sections, the form stays available for manual review.

## Deployment and testing

Apply the additive `recruitment_experience` migration `0004_candidateprofile`; it creates one optional profile table and does not modify existing recruitment records. Stage-only verification is `deploy/six_phase_workflow.py` and refuses any database other than `horilla_staging`. It rolls back its synthetic records and removes its generated CV file. The existing full experience workflow and access-boundary suites remain required. Do not run synthetic workflow fixtures against the live demo.

Microsoft sign-in, mail/calendar delivery, offer signing, onboarding appointment booking and HRMS transfer need separate configuration or implementation. Screens must continue to identify these capabilities accurately.
