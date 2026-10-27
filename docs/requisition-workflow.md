# Work Area 1: Requisitions & Assignments

Purpose: agree a complete hiring need before creating a vacancy. The four work areas remain unchanged. This area exposes original workflow steps 1–3 as a visible wizard, with a separate record for each requisition.

| Step | Owner | Actions | Exit condition |
| --- | --- | --- | --- |
| 1. Raise Requisition | Hiring manager or HR | Define role, division, legal employer, headcount and business need. Write or attach the JD and KPA. Save a draft; optionally use Claude for JD drafting. Review and submit. | Reviewed JD and KPA supplied; CEO approver and assignment Director selected; requester confirms submission. |
| 2A. CEO Approval | Named CEO approver | Read the complete package. Approve, return with a rework reason, or decline. | Explicit CEO approval, with actor and timestamp. |
| 2B. TA Assignment | Named HR Director | Assign one active TA who already has coordinator access to the division. | Explicit Director assignment, with actor and timestamp. |
| 3. Register Vacancy | Assigned TA (administrator recovery access retained) | Create a draft vacancy using the approved role title, employer, headcount and JD. Select job positions and recruitment dates. | One resulting draft vacancy; continue in Sourcing & Selection for publication. |

## Screens and continuity

- Work Area 1 has three persistent step cards, showing number, name, owner and workload. Select a card to view its queue.
- Each requisition has the same step strip plus the hiring package, CEO decision, Director assignment, vacancy link and timestamped history.
- Step 1 form is divided into need, JD, KPA and review routing. A missing AI key does not prevent manual drafting or PDF submission.
- JD and KPA can be reviewed text or private PDFs (up to 5 MB / 50 pages each). An uploaded-only JD remains attached to the approved requisition; the TA supplies its public wording during registration. Text JDs carry forward automatically.
- Submitted packages are locked. Returning for changes unlocks Step 1; resubmission requires another CEO decision. Prior decisions remain in the history.
- Vacancy registration is blocked until both approval and assignment have happened. Duplicate registration cannot create another vacancy. Registration does not publish a job.
- Offer approval remains a separate HR Director action in Work Area 3.

## Access and data

Requester, named approver, named assignment Director, assigned TA and existing authorized HR scope can access the requisition. Only the assigned actor with the appropriate existing role can perform its action. TA assignment grants no extra role permissions. General candidate/CV access remains governed by the existing hiring-team and division controls.

Record creation, submission, returns, decisions, assignment, JD review, attachment downloads and vacancy registration have actor/time history. Full JD/KPA bodies and credentials are excluded from event metadata. Submitted requirement contents remain on the requisition even if the later vacancy description is edited.

Existing jobs, employers, applicants, CVs and accounts are preserved. Legacy requests are not given invented submission or assignment timestamps. Additional openings for an existing job remain a separate workflow.

## Deliberate boundaries

- CEO and HR Director are explicitly selected from eligible existing accounts; directory-based automatic routing is not connected.
- Claude drafting uses the existing administrator-managed Anthropic configuration. Generation is requested explicitly, reviewed by a person, and shares the existing daily/cooldown allowance with vacancy JD drafting. It never submits, approves or publishes automatically.
- Notifications, Microsoft 365, AWFM and receiving HRMS integration remain separate future work. A saved workflow action does not imply email delivery.
- Separate per-TA visibility rules for all recruitment records, rather than the existing central HR scope, remain a policy decision.

## Verification

`deploy/requisition_workflow.py` runs only against `horilla_staging`. It exercises drafts, required documents, rework/resubmission, role boundaries, stale writes, assignment gates, vacancy inheritance, duplicate registration, private PDFs and mocked AI-before-vacancy drafting. Synthetic rows roll back and uploaded fixtures are removed. Run the existing workflow, work-area, branding and recruitment-boundary suites as release regression checks.
