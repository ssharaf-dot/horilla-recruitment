# CEO approval, TA assignment and vacancy registration — usability review

**Repository snapshot — 29 October 2026:** implementation prepared locally; Python/JavaScript syntax and diff checks passed. Staging runtime tests, visual verification and live publication are pending Hostinger access. The live demo has not been changed for this review.

This review follows one hiring request from the completed Step 1 package through CEO decision, Director assignment and creation of an unpublished vacancy. The intended experience is a guided task for the person responsible, and a readable status view for other authorized people. Opening a page or pressing a navigation link never counts as approval.

## Findings and resulting design

| Finding | Why it mattered | Change |
| --- | --- | --- |
| Approval actions appeared before much of the package | A CEO could reach decision buttons without a coherent review sequence | A dedicated **2A Review package → Record decision** flow shows the package first, then one clearly selected outcome and confirmation |
| Review and ownership actions were mixed into a long status page | Requesters, CEO, Director and TA saw different fragments without a strong handoff | Dedicated actor workspaces, with the status page naming the next owner and showing read-only context to observers |
| Approved requests had no correction handback | A Director or TA spotting a wrong JD, budget or scope could not safely resolve it | **Return for correction** requires a reason, invalidates current approval/assignment, retains history and requires fresh CEO approval and Director assignment |
| Reassignment looked like the original assignment | A new TA could inherit another person's saved setup without reviewing it | Reassignment requires a reason; saved setup remains visible but must be checked again by the new owner |
| Registration review omitted the actual selected position | TA could not fully check what was about to be created | **3B** shows the real position name, title, employer/division, location, dates, CV requirement and unpublished outcome |
| Internal mapping was a broad multi-select | One approved role could be mapped to unrelated or inactive positions | Single active position, shared or explicitly eligible for the legal employer; other-employer mappings and expired closing dates are rejected |
| Numeric version alone did not prove content still matched approval | A changed package could retain an old approval flag | Compare the current hiring-package fields to the exact recorded approved snapshot before assignment and registration; money values are compared numerically to handle database decimal formatting |
| Completion could strand the original hiring manager | The resulting job team included the TA but not the requester | Attach the active requester as hiring manager of the new vacancy; the Director gains no new candidate access |
| A later generic vacancy editor could change approved headcount/JD | Approval could be bypassed immediately after registration | Linked approved title, employer, headcount and JD stay locked; approved division stays attached. Additional headcount uses the existing additional-openings approval workflow |

## The complete flow

### 2A — CEO review and decision

1. Open the assigned request from the Step 2 queue or its status page.
2. Read the hiring need, public JD, internal success measures, employer/division, headcount and salary/budget proposal. Supporting documents remain protected downloads.
3. **Continue to decision** changes the view only. It records no approval.
4. Select one outcome: approve, return for changes, or reject. Return/rejection needs a meaningful reason. Confirm and record the decision.
5. Alternatively, edit the package first. The editor groups role/need, JD, success measures and budget/terms. **Edit & approve** records the revised package and moves it forward directly; **edit & return** keeps those changes and sends it back with instructions. Unsaved edits are not silently committed by navigation.

Approval sends responsibility to the named HR Director. A return reopens the requester's Step 1 package and requires resubmission. Rejection closes the request while retaining its history. The requester cannot edit a package currently owned by CEO review.

Missing or older packages cannot be approved merely because they already have a pending/approved label. Missing routing details are corrected by the requester; historical approvals are not invented.

### 2B — HR Director assignment

The Director reviews the approved version, then selects one eligible recruiter. Eligibility requires an active user, active staff profile, recruitment role and access to the division. Selecting someone grants no new permissions.

A change of owner needs a reason. A no-op assignment does not create a misleading new milestone. If the TA becomes inactive or loses eligibility, the request returns to the Director's action queue. Other authorized viewers can read status; they do not receive the Director's controls.

### 3A — Vacancy setup

Only the assigned eligible TA can register the request. Administrator status alone does not bypass that assignment.

The TA chooses one eligible internal position, recruitment opening/closing dates and the CV requirement. Approved role, employer, headcount and JD remain locked. Save & Next stores setup without creating a vacancy; Save & close permits later resumption.

Setup confirmation belongs to a specific approved version, TA and assignment timestamp. If any of these change, earlier entries remain for reference but the new responsible TA must check and save Step 3A again.

### 3B — Review and create

Review the actual position name and the complete creation summary. **Edit Step 3A details** returns to the saved settings; leaving retains them. Confirm explicitly to create one draft vacancy.

The resulting vacancy inherits approved content, location and supported employment type. The active requester and assigned TA join its hiring team. It is **not published** on careers or LinkedIn. Publication remains an explicit subsequent task in Sourcing & Selection. Repeated creation cannot produce a second vacancy for the same request.

## Corrections without bypassing approval

Before registration, the named CEO, authorized named Director, assigned recruiter or administrator can request correction of an approved package. They must give a reason and confirm the consequence. Current registration authority and assignment are invalidated; earlier approval and assignment events remain readable.

The package returns to its requester/authorized HR for correction, then goes through CEO approval and Director assignment again. This action cannot delete or unlink a registered vacancy or modify applications. After registration, extra openings use the separate approval flow; a materially different approved role or JD needs a new requisition. A full amendment workflow for an already registered/live vacancy is future work.

## Checks and balances

- Named actor plus existing role and record scope are checked on the server, not only by hiding buttons.
- Required reasons, confirmations and complete hiring packages are enforced on the server.
- Stale versions cannot overwrite newer decisions, assignments or saved setup.
- Current approval must match its recorded package; a flag alone is insufficient.
- New ownership and new approval require a fresh setup review.
- Private JD/KPA files and salary/budget data remain within the existing request scope.
- Observer pages name the next owner and show status/history without exposing that owner's decision controls.
- No email, Microsoft SSO, AWFM sync, AI provider call or automatic publication is implied by these internal handoffs.

## Verification and release

Run `deploy/requisition_handoffs.py` only against `horilla_staging`. It covers the full correction/resubmission/reapproval/reassignment/registration loop, observer boundaries, stale writes, inactive recruiters, company position eligibility, setup inheritance, requester access and locks on approved content. Synthetic database changes roll back.

Run it alongside the existing requisition, application, offer/joining, work-area, branding and recruitment-boundary suites. Inspect the actual rendered actor screens at desktop and mobile widths. A release needs the tested source saved to Git, a fresh restore-verified backup and preservation checks for existing records, accounts and uploads.
