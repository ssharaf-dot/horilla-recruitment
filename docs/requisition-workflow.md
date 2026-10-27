# Requisitions & Assignments — saved hiring-package wizard

Work Area 1 covers the staffing need before sourcing. A requisition is the internal request to hire; it becomes a separate, unpublished vacancy only after approval and recruiter assignment. The remaining three work areas continue to handle sourcing, offers and joining.

## Navigation and ownership

The screen shows three levels: **Work area → Workflow step → Current section**. The section ribbon distinguishes available, current and locked sections. The editor removes the unrelated action rail and duplicate division filter, keeps the active form prominent, and places its save actions together. Leaving unsaved inputs prompts the user. An interrupted enhanced save keeps current inputs on screen and permits a retry; stale versions cannot overwrite someone else's save.

### Step 1 — Raise Requisition (hiring manager / HR)

| Section | Contents | Handoff |
| --- | --- | --- |
| **1A · Hiring need** | Role title/designation, operational division, legal employer, openings, department/team, optional grade, location, employment type, new/replacement/backfill and justification | Save the role, then continue to the JD |
| **1B · Job description** | Guided role summary, responsibilities, required skills, experience/prerequisites, education or equivalent experience and optional desirable skills; editable public JD preview | Review and confirm the wording before continuing |
| **1C · Success measures** | Expected outcomes, how they will be measured and timeframe; optional supporting KPA PDF | Internal approval evidence, separate from the public JD |
| **1D · Budget & terms** | Proposed salary minimum/maximum per person, currency, monthly/annual period, base/gross basis, first-year total budget for all openings, assumptions and optional desired joining date | Internal proposal for CEO review |
| **1E · Review & submit** | Full hiring package, links to missing items, named CEO and HR Director, explicit confirmation | Submit a recorded version to the CEO |

**Save & Next**, **Save & back** and **Save & close** persist the current section. A title is needed to identify a draft; the rest may remain incomplete when saving for later. Next checks the current section; submission checks the entire package. Resume returns to the last saved section. Previously unlocked sections can be revisited. First-save retries use a unique token to prevent duplicate drafts.

### JD guidance, PDFs and AI

Empty guided fields visibly show bracketed template prompts. Focus an empty field and press **Tab** to insert the suggestion; press **Escape** to skip it and let Tab move onward. An **Insert suggested template** button provides an explicit alternative. Populated fields retain ordinary Tab behavior. No suggestion overwrites existing text.

**Build JD preview** composes ordinary headings and bullets that can be copied into a LinkedIn job editor. It is not a LinkedIn integration or posting action. Replace every instructional `[prompt]` and review the canonical public JD. The server blocks unfinished prompts even if browser validation is bypassed.

Supporting PDFs remain private, limited to 5 MB / 50 pages, with actual bytes/parser validation. A JD PDF is extracted locally into editable text; the user must review that text before advancing. An image-only/scanned PDF requires manual text because this feature does not perform OCR. The reviewed public text, rather than an ambiguous choice between text and attachment, carries into the vacancy. Supporting KPA PDFs do not replace the structured success measures.

The existing optional Claude/Anthropic drafting and human-review screens use the same saved requisition and section hierarchy. Templates and manual editing require no API key. A disconnected provider sends no external request. AI output does not submit, approve or publish a request. Claude is the model family and Anthropic is its provider; this is one provider configuration, not two independent API services.

Salary fields capture an internal proposal, not an industry benchmark or automated pay recommendation. The salary-only upper estimate is maximum pay × pay periods in 12 months × openings. The proposed total must cover that estimate; assumptions explain additional costs. A future market salary indicator remains out of scope.

### Step 2 — CEO Approval & TA Assignment

**2A · CEO review:** only the named eligible CEO can act. They can:

- Approve the submitted package unchanged.
- Edit the role title, grade, department, location, employment terms, hiring reason, JD, proposed salary and budget, then **save edits and approve forward**.
- Edit and return the package for clarification, or return it unchanged. A reason is required.
- Reject the hiring need with a required reason. The request closes and its history remains available.

The submitted version and subsequent decisions are stored as separate snapshots. CEO edits do not silently rewrite the earlier submission and do not require a requester acknowledgement before approval. The detail screen compares meaningful fields between recorded versions. Returned requests reopen for revision and resubmission; the requester cannot edit while the CEO owns a pending review. The operational division and legal employer remain unchanged in the CEO editor; return the request if those need correction, to preserve record scope.

**2B · HR Director assignment:** after a complete recorded CEO approval, the named Director selects one active eligible recruiter/TA. Assignment records the Director, TA and time and grants no new permissions. The CEO does not assign the TA through approval. This staffing approval is distinct from HR Director **offer approval** in Work Area 3.

### Step 3 — Register Vacancy (assigned TA)

**3A · Vacancy details:** the approved role, employer, headcount and reviewed JD carry forward. TA selects an existing internal job-position mapping, recruitment dates and whether applications require a CV. Save & Next persists setup without creating a job. HR must configure a suitable internal job position separately if none exists.

**3B · Review & create:** review the approved package and saved setup and confirm creation. The result is an **unpublished draft vacancy** with its assigned recruiter and initial recruitment stages. Registration stays in Work Area 1 until complete. The completion screen then links to Sourcing & Selection for explicit publication review. Repeated creation attempts cannot produce a second vacancy.

## Queues, history and access

Active requests stay under their current workflow step. Queue filters distinguish **Needs my action** from **Waiting on others**, with the next owner and waiting-since time shown. Registered and rejected requests move to history and leave active step counts. Additional openings on existing jobs remain a separate linked workflow with a separate count.

Requester, named CEO, named Director, assigned TA and already-authorized HR scope can read the package. Actions also require the matching role and current version. Existing manager/team and division boundaries remain enforced. A first-time requester must already have recruitment access through administrator setup; this release does not grant all employees request access.

History records section saves, submission, return/rejection reasons, CEO edits/approval, assignment, JD review, document downloads and registration with actor/time. Generic event metadata excludes complete JD/KPA text and salary bodies. Detailed hiring-package snapshots are restricted to the request's authorized viewers. Earlier missing interactions are never reconstructed as if they occurred.

## Existing records and migration

Migration `0009_saved_requisition_wizard` adds fields and a revision table and permits incomplete draft employer/division/headcount values. It does not rewrite existing jobs, applications, employer ownership, accounts or CVs. Existing pre-feature requests may lack budget, reviewed JD and version snapshots. No CEO approval is invented for them. Their named CEO can return the package for completion; only a newly recorded complete approval unlocks registration.

Keep the old application image and verified database/media backup for recovery. Do not reverse the migration or restore an older database over newer recruitment activity as a routine application rollback.

## Verification

`deploy/requisition_workflow.py` is staging-only and rolls synthetic database rows back. It exercises partial drafts, saved sections, token retries, prompts, PDF extraction, salary validation, complete submission, role boundaries, stale edits, CEO edit-and-approve/return/reject, snapshots, Director assignment, two saved registration sections, vacancy inheritance and optional mocked AI. Uploaded fixtures are removed. Run the existing workflow, work-area, offer/joining controls, branding and recruitment-boundary suites before publishing. Desktop/mobile visual review remains necessary in addition to these server checks.
