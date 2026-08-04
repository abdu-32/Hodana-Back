# 02 — Software Requirements Specification

**Document type:** Software Requirements Specification (IEEE 29148 style)
**Audience:** Product owners, software engineers, QA engineers, technical reviewers
**Status:** Complete — source of truth for all downstream documents
**Related documents:** [01 — Product Overview](01-product-overview.md) (scope this SRS formalizes) · [03 — Software Design Specification](03-software-design-specification.md) (how these requirements are implemented) · [07 — Testing and Quality Assurance](07-testing-and-quality-assurance.md) (requirement-to-test traceability)

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional requirements, business rules, and non-functional requirements for the Ethiopia Innovation Hub MVP. It is implementation-independent: it defines *what* the system must do and *how well* it must do it, not the technology used to build it. Architecture and implementation decisions are made in Document 03 and must trace back to a requirement defined here.

### 1.2 Scope

This SRS covers the MVP scope boundary defined in [Document 01, Section 6](01-product-overview.md#6-mvp-scope-boundary): the end-to-end hackathon lifecycle (discovery, registration, team formation, submission, eligibility screening, judging, showcase), institutional verification, organizer analytics, bilingual localization, and notification delivery including an SMS fallback channel. Features outside this scope are documented in [Document 09 — Project Roadmap](09-project-roadmap.md) and are not specified here.

### 1.3 Requirement identification and format

Every functional requirement has a unique, permanent ID of the form `FR-<MODULE>-<NNN>` and is specified with the following fields:

| Field | Meaning |
|---|---|
| Priority | `Must Have` (MVP cannot ship without it) or `Should Have` (materially improves the MVP but a documented workaround exists) |
| Description | The atomic, testable behavior the system shall provide |
| Preconditions | System/user state required before the behavior applies |
| Acceptance Criteria | Objective, verifiable conditions used to confirm the requirement is met |
| Dependencies | Other requirement IDs this requirement relies on |

Business rules use the form `BR-<NNN>` and are stated as standalone policy statements, not system behaviors — see Section 4 for why they are kept separate. Non-functional requirements use the form `NFR-<CATEGORY>-<NNN>` and are specified in Section 5.

Module codes used in this document: `AUTH`, `PROFILE`, `ORG`, `HACK`, `DISC`, `REG`, `TEAM`, `SUB`, `ELIG`, `JUDGE`, `TRACK`, `SHOWCASE`, `NOTIFY`, `ANALYTICS`, `ADMIN`, `I18N`.

### 1.4 Roles referenced in this document

This SRS uses the six roles fixed in [Document 01, Section 4](01-product-overview.md#4-target-users): `Participant`, `Organizer`, `Sponsor`, `Judge`, `Mentor`, `Platform Admin`. No requirement in this document introduces a role not listed there.

### 1.5 Conventions

- All timestamps referenced in acceptance criteria are evaluated in East Africa Time (EAT, UTC+3) unless otherwise stated.
- "Authenticated user" means a user holding a valid, non-expired session as defined in FR-AUTH-002.
- Character and file-size limits stated in this document are MVP defaults; where an organizer-configurable range is specified, the range itself is normative and the default is illustrative.

---

## 2. Overall Description

### 2.1 Product perspective

The Ethiopia Innovation Hub is a new, standalone web platform (not an extension of an existing system). It is a multi-tenant system: one deployment serves many independent organizers and their hackathons, each with independently scoped participants, teams, submissions, and judges.

### 2.2 User classes and characteristics

User classes correspond to the six roles in Section 1.4. A single account may hold different roles in different contexts (e.g., a user is a `Participant` in one hackathon and, separately, an `Organizer` of another), except where a business rule in Section 4 restricts this. Role assignment is always scoped to a hackathon or organization, not global, with the exception of `Platform Admin`, which is a global role.

### 2.3 Assumptions and dependencies

- Participants and organizers have access to a smartphone or computer with intermittent internet connectivity; the system does not assume constant broadband (see NFR-USE-002).
- Institutional email domains (e.g., `@aau.edu.et`) are a usable, though imperfect, verification signal for Ethiopian universities and government agencies; the manual verification path (FR-ORG-003) exists specifically to cover organizations without a distinct institutional domain.
- Local payment aggregator integration is treated as an external dependency behind an abstraction; the specific aggregator is a deferred decision documented in [Document 09](09-project-roadmap.md), not specified in this document.
- SMS delivery depends on a third-party SMS gateway with Ethiopian carrier reach; this is an external dependency of FR-NOTIFY-002.

### 2.4 Constraints

- The MVP must be buildable by a small independent team within a realistic timeframe (see [Document 01](01-product-overview.md) MVP philosophy); this SRS does not specify any capability that was assessed and rejected for MVP scope under that constraint.
- The technology stack is fixed at the design level (Document 03, Section 3) and does not constrain the requirements in this document, which are implementation-independent by design.

---

## 3. Functional Requirements

Requirements are grouped by module in the order a hackathon moves through the core product journey ([Document 01, Section 5](01-product-overview.md#5-core-product-journey)): identity and organizations first, then the lifecycle itself, then supporting capabilities.

### 3.1 Module: Authentication (AUTH)

#### FR-AUTH-001 — Account registration

**Priority:** Must Have
**Description:** The system shall allow a new user to create an account using an email address and password, selecting an initial display role of `Participant` or `Organizer`.
**Preconditions:** The email address is not already associated with an existing account.
**Acceptance Criteria:**
- Email must match RFC 5322 format; invalid format is rejected with a field-level error before submission.
- Password must be at least 10 characters and include at least one letter and one number.
- A verification email is sent within 60 seconds of submission.
- The account is created in an `unverified` state and cannot log in until FR-AUTH-003 completes.
- Duplicate email submission returns HTTP 409 with a message that does not reveal whether the existing account belongs to the requester (to prevent account enumeration).
**Dependencies:** None.

#### FR-AUTH-002 — Login and session issuance

**Priority:** Must Have
**Description:** The system shall authenticate a user by email and password and issue a session token valid for subsequent authenticated requests.
**Preconditions:** The account exists and is in a `verified` state (FR-AUTH-003).
**Acceptance Criteria:**
- Correct credentials return an access token (15-minute expiry) and a refresh token (30-day expiry).
- Incorrect credentials return HTTP 401 with a generic "invalid credentials" message that does not indicate whether the email exists.
- After 5 consecutive failed attempts for one account within 15 minutes, the account is temporarily locked for 15 minutes and the account owner is notified by email.
- A successful login updates the account's `last_login` timestamp.
**Dependencies:** FR-AUTH-001, FR-AUTH-003.

#### FR-AUTH-003 — Email verification

**Priority:** Must Have
**Description:** The system shall require a user to confirm ownership of their registration email via a time-limited verification link before the account can authenticate.
**Preconditions:** FR-AUTH-001 has completed and a verification email has been sent.
**Acceptance Criteria:**
- The verification link expires 24 hours after issuance.
- Following an expired link, the user can request a new verification email, rate-limited to 1 request per 5 minutes.
- On successful verification, the account transitions from `unverified` to `verified` and the user is redirected to login.
**Dependencies:** FR-AUTH-001.

#### FR-AUTH-004 — Password reset

**Priority:** Must Have
**Description:** The system shall allow a user who has forgotten their password to reset it via a time-limited, single-use email link.
**Preconditions:** The account exists and is `verified`.
**Acceptance Criteria:**
- The reset link expires 1 hour after issuance and is invalidated after first use.
- The new password is subject to the same complexity rule as FR-AUTH-001.
- All existing sessions for the account are invalidated when a password reset completes.
- Requesting a reset for a non-existent email returns the same success response as for an existing email (to prevent account enumeration).
**Dependencies:** FR-AUTH-001.

### 3.2 Module: User Profile (PROFILE)

#### FR-PROFILE-001 — Update profile

**Priority:** Must Have
**Description:** The system shall allow an authenticated user to update their Bio, Skills, University/Organization, GitHub URL, LinkedIn URL, and Portfolio URL.
**Preconditions:** The requester is authenticated as the profile owner.
**Acceptance Criteria:**
- Bio is limited to 500 characters; submissions above the limit are rejected with a field-level error.
- Skills is a multi-select list of up to 15 entries from a controlled vocabulary plus free-text entry.
- GitHub, LinkedIn, and Portfolio URLs must be well-formed URLs (RFC 3986); malformed URLs are rejected before submission.
- Changes persist and are visible on page refresh and on subsequent logins.
- An unauthenticated request, or a request from a user other than the profile owner, returns HTTP 401 or HTTP 403 respectively.
**Dependencies:** FR-AUTH-002.

#### FR-PROFILE-002 — View public profile

**Priority:** Must Have
**Description:** The system shall render a public-facing profile page for any user who has opted into a public profile, showing display name, avatar, bio, skills, and past showcased projects (FR-SHOWCASE-002).
**Preconditions:** The target user has `profile_visibility = public` (default for `Participant` accounts).
**Acceptance Criteria:**
- The page is reachable without authentication.
- Email address and phone number are never rendered on the public profile regardless of visibility setting.
- If `profile_visibility = private`, the endpoint returns HTTP 404, not HTTP 403, to avoid confirming account existence.
**Dependencies:** FR-PROFILE-001.

#### FR-PROFILE-003 — Upload avatar

**Priority:** Should Have
**Description:** The system shall allow an authenticated user to upload a profile avatar image.
**Preconditions:** The requester is authenticated.
**Acceptance Criteria:**
- Accepted formats: JPEG, PNG, WebP. Maximum file size: 5 MB.
- Images are served resized to a maximum of 512×512 px.
- An oversized or wrong-format upload is rejected with a specific error identifying the violated constraint.
**Dependencies:** FR-AUTH-002.

### 3.3 Module: Organizations and Institutional Verification (ORG)

#### FR-ORG-001 — Register an organization

**Priority:** Must Have
**Description:** The system shall allow an authenticated user to register a new Organization (university, company, NGO, or government agency) that they will administer.
**Preconditions:** The requester is authenticated and verified (FR-AUTH-003).
**Acceptance Criteria:**
- Required fields: organization name, organization type (one of the four listed), contact email, primary email domain (optional).
- The registering user is assigned the `Organizer` role scoped to the new organization.
- The organization is created in `unverified` status.
**Dependencies:** FR-AUTH-002.

#### FR-ORG-002 — Domain-matched fast-track (revised)

**Priority:** Must Have
**Description:** The system shall fast-track an organization into the FR-ORG-003 pending-review queue -- but shall NOT set it directly to `verified` -- when the registering user's account email domain matches the organization's declared primary email domain against a maintained list of recognized Ethiopian institutional domains.
**Revision note:** the original version of this requirement auto-verified on domain match alone. That was found to be a real authority-impersonation gap: a matching domain proves the registrant holds an email address at that domain (e.g. any enrolled student at a university), not that they are authorized to represent that institution as an Organizer. A human `Platform Admin` decision (FR-ORG-003) is now required in every case; domain match only changes queue priority and same-request feedback, not trust level.
**Preconditions:** FR-ORG-001 has completed and a primary email domain was declared.
**Acceptance Criteria:**
- The fast-track determination (and the resulting `pending` status) completes within the same request cycle as registration (no manual step, no added latency beyond normal request handling) -- only the final verification decision is manual.
- Organizations that fast-tracked this way are flagged for admins (`domainFastTracked`) and sorted first in the FR-ORG-003 review queue, but display no "Verified" badge until a `Platform Admin` approves them.
- A domain not present on the recognized-institution list, or not matching the registrant's own email, falls through to plain FR-ORG-003 (no fast-track flag) rather than being auto-verified or prioritized.
**Dependencies:** FR-ORG-001.

#### FR-ORG-003 — Manual verification review

**Priority:** Must Have
**Description:** The system shall allow a `Platform Admin` to review and approve or reject every organization awaiting verification -- both those fast-tracked by FR-ORG-002 and those relying solely on submitted supporting evidence (e.g., an official registration document or a letter of introduction). There is no path to `verified` status that skips this human decision.
**Preconditions:** The organization is in `unverified` or `pending` status (FR-ORG-002 may or may not have applied).
**Acceptance Criteria:**
- The registering Organizer can upload up to 3 supporting documents (PDF or image, 10 MB max each).
- A `Platform Admin` can approve (organization becomes `verified`) or reject (organization remains `unverified`, with a required rejection reason visible to the Organizer).
- The Organizer is notified by email within 5 minutes of the admin decision.
- Median time from submission to decision is tracked and reported to Platform Admins (used as an internal SLA metric, not a public commitment).
**Dependencies:** FR-ORG-001, FR-ADMIN-001.

### 3.4 Module: Hackathon Configuration (HACK)

#### FR-HACK-001 — Create a hackathon

**Priority:** Must Have
**Description:** The system shall allow an `Organizer` belonging to a `verified` organization to create a new hackathon in `draft` status.
**Preconditions:** The requester holds the `Organizer` role for a `verified` organization.
**Acceptance Criteria:**
- Required fields: title, description, start date, end date, registration deadline, submission deadline, eligibility rules (FR-HACK-003), at least one judging rubric criterion.
- The submission deadline must be on or after the registration deadline; the registration deadline must be on or after the current time; violations are rejected with a field-level error before creation.
- The hackathon is created in `draft` status and is not publicly visible until FR-HACK-005.
**Dependencies:** FR-ORG-002 or FR-ORG-003.

#### FR-HACK-002 — Configure timeline

**Priority:** Must Have
**Description:** The system shall allow the Organizer to define and later edit the hackathon's key dates: registration open/close, submission open/close, judging window, and results announcement.
**Preconditions:** The hackathon exists and is not yet `archived`.
**Acceptance Criteria:**
- Each date field enforces the ordering constraint in FR-HACK-001.
- Editing a date after the hackathon is `published` triggers a notification to all registered participants (FR-NOTIFY-001).
- The registration close date cannot be edited to a time in the past once registration has already closed (enforced per BR-002).
**Dependencies:** FR-HACK-001.

#### FR-HACK-003 — Configure eligibility rules

**Priority:** Must Have
**Description:** The system shall allow the Organizer to define eligibility rules for a hackathon from a fixed set of criteria: minimum/maximum team size, university/institution restriction, age restriction, and geographic restriction.
**Preconditions:** The hackathon exists in `draft` or `published` status.
**Acceptance Criteria:**
- Minimum team size ≥ 1 and maximum team size ≥ minimum team size; violating values are rejected.
- Institution restriction accepts a list of one or more verified organizations; registrants outside the list are blocked at FR-REG-001 with a specific error message.
- Rules configured after registration has opened apply only to registrations submitted after the change; existing registrations are not retroactively invalidated.
**Dependencies:** FR-HACK-001.

#### FR-HACK-004 — Configure judging rubric

**Priority:** Must Have
**Description:** The system shall allow the Organizer to define a scoring rubric consisting of one or more named criteria, each with a numeric score range and a weight.
**Preconditions:** The hackathon exists in `draft` or `published` status, before judging opens.
**Acceptance Criteria:**
- Each criterion has a name (≤ 100 characters), a minimum and maximum score (integers, min < max), and a weight (0–100%).
- The sum of all criteria weights must equal 100%; a rubric that does not sum to 100% is rejected on save.
- The rubric cannot be edited once judging has opened (enforced per BR-005), to preserve score comparability across judges.
**Dependencies:** FR-HACK-001.

#### FR-HACK-005 — Publish a hackathon

**Priority:** Must Have
**Description:** The system shall allow the Organizer to publish a `draft` hackathon, making it publicly visible in discovery (FR-DISC-001) and open for registration once the registration-open date is reached.
**Preconditions:** The hackathon has a title, description, complete timeline (FR-HACK-002), at least one eligibility rule set (FR-HACK-003), and a complete rubric (FR-HACK-004).
**Acceptance Criteria:**
- Publishing an incomplete hackathon (missing any precondition field) is rejected with a list of the specific missing fields.
- A published hackathon can be unpublished only if it has zero registrations; otherwise it can only be `archived` after its end date.
- Publishing triggers indexing into the public discovery catalog (FR-DISC-001) within 60 seconds.
**Dependencies:** FR-HACK-001 through FR-HACK-004.

### 3.5 Module: Discovery (DISC)

#### FR-DISC-001 — Browse published hackathons

**Priority:** Must Have
**Description:** The system shall display a public, paginated catalog of all `published` hackathons, ordered by registration deadline ascending by default.
**Preconditions:** None (public, unauthenticated access permitted).
**Acceptance Criteria:**
- Each catalog entry shows title, organizing institution, verification badge, registration deadline, and a status tag (`Registration Open`, `Registration Closed`, `In Progress`, `Judging`, `Completed`).
- Pagination returns 20 results per page.
- A hackathon whose registration deadline has passed remains listed (as `Registration Closed`) until its end date, not removed.
**Dependencies:** FR-HACK-005.

#### FR-DISC-002 — Search and filter

**Priority:** Must Have
**Description:** The system shall allow a user to filter the catalog by organizing institution, status, and theme/tag, and to search by keyword against hackathon title and description.
**Preconditions:** None.
**Acceptance Criteria:**
- Keyword search returns results within 1 second at MVP data volumes (see NFR-PERF-002).
- Filters are combinable (e.g., institution AND status) using AND logic across filter categories.
- A search with no matching results displays an explicit empty state, not an error.
**Dependencies:** FR-DISC-001.

#### FR-DISC-003 — Hackathon detail page

**Priority:** Must Have
**Description:** The system shall display a public detail page for each published hackathon, including full description, timeline, eligibility rules, rubric criteria (names and weights, not judge scores), organizing institution, and sponsor tracks (if any).
**Preconditions:** The hackathon is `published`.
**Acceptance Criteria:**
- The page is reachable without authentication.
- A visible call-to-action reflects current status: "Register" while registration is open, "Registration Closed" otherwise.
- Rubric minimum/maximum score bounds are shown; individual judge identities and scores are never shown on this page.
**Dependencies:** FR-DISC-001.

### 3.6 Module: Registration (REG)

#### FR-REG-001 — Register for a hackathon

**Priority:** Must Have
**Description:** The system shall allow an authenticated `Participant` to register for a published hackathon whose registration window is open and whose eligibility rules (FR-HACK-003) the participant satisfies.
**Preconditions:** The hackathon status is `published`, current time is within the registration window, and the participant is not already registered.
**Acceptance Criteria:**
- A participant failing an eligibility rule (e.g., institution restriction) receives a specific error naming the failed rule, not a generic rejection.
- On success, the participant's registration status is `registered` and a confirmation notification is sent (FR-NOTIFY-001).
- Attempting to register twice for the same hackathon returns HTTP 409 with a message indicating existing registration.
- Registration submitted after the deadline is rejected per BR-002, regardless of client-side clock state (server time is authoritative).
**Dependencies:** FR-AUTH-002, FR-HACK-005.

#### FR-REG-002 — Withdraw registration

**Priority:** Must Have
**Description:** The system shall allow a registered participant to withdraw from a hackathon before the submission deadline.
**Preconditions:** The participant's registration status is `registered` and the current time is before the submission deadline.
**Acceptance Criteria:**
- On withdrawal, registration status becomes `withdrawn`; the participant is removed from any team roster they belonged to (see FR-TEAM-004).
- Withdrawal after the submission deadline is rejected, since submissions are read-only per BR-003.
- The Organizer's registration count and analytics (FR-ANALYTICS-001) reflect the withdrawal within 60 seconds.
**Dependencies:** FR-REG-001.

#### FR-REG-003 — View my registrations

**Priority:** Must Have
**Description:** The system shall display an authenticated participant's list of current and past hackathon registrations with current status.
**Preconditions:** The requester is authenticated.
**Acceptance Criteria:**
- The list includes registration status, team status (if applicable), and submission status (if applicable) for each hackathon.
- The list is scoped strictly to the requester; no participant can view another participant's registration list.
**Dependencies:** FR-REG-001.

### 3.7 Module: Team Formation (TEAM)

#### FR-TEAM-001 — Create a team

**Priority:** Must Have
**Description:** The system shall allow a registered participant to create a team within a specific hackathon, becoming that team's owner.
**Preconditions:** The participant's registration status for that hackathon is `registered`, and they do not already belong to a team within that same hackathon.
**Acceptance Criteria:**
- Team name is required, 3–60 characters, unique within the hackathon.
- The creator is automatically added as the first team member with role `Owner`.
- Attempting to create a second team within the same hackathon by a participant who already belongs to one is rejected per BR-001.
**Dependencies:** FR-REG-001.

#### FR-TEAM-002 — Invite a member

**Priority:** Must Have
**Description:** The system shall allow a team `Owner` to invite another registered participant of the same hackathon to join the team by username or email.
**Preconditions:** The team has not yet reached the hackathon's maximum team size (FR-HACK-003); the invited user is registered for the same hackathon and not already on a team within it.
**Acceptance Criteria:**
- The invited user receives a notification (FR-NOTIFY-001) with accept/decline actions.
- An invitation not acted on within 7 days automatically expires.
- Inviting a user who already belongs to a team in the same hackathon is rejected per BR-001, with a specific error.
**Dependencies:** FR-TEAM-001.

#### FR-TEAM-003 — Accept or decline an invitation

**Priority:** Must Have
**Description:** The system shall allow the invited participant to accept or decline a pending team invitation.
**Preconditions:** The invitation is in `pending` status and not expired.
**Acceptance Criteria:**
- Accepting adds the participant to the team roster with role `Member` and adds the team to their registration record (FR-REG-003).
- Accepting when the team is already at maximum size (a race condition where two invitations were accepted concurrently) fails the second acceptance with a clear "team is full" error, and the invitation reverts to `pending` for Owner re-action.
- Declining removes the invitation without affecting the participant's individual registration.
**Dependencies:** FR-TEAM-002.

#### FR-TEAM-004 — Leave or remove a team member

**Priority:** Must Have
**Description:** The system shall allow a `Member` to leave a team voluntarily, and shall allow the team `Owner` to remove a `Member`, at any point before the submission deadline.
**Preconditions:** Current time is before the hackathon's submission deadline.
**Acceptance Criteria:**
- If the `Owner` leaves a team with remaining members, ownership transfers to the longest-tenured remaining member automatically.
- If the last member leaves, the team is deleted.
- Leave/remove actions after the submission deadline are rejected, since team rosters lock with submissions per BR-003.
**Dependencies:** FR-TEAM-001.

#### FR-TEAM-005 — View team roster

**Priority:** Must Have
**Description:** The system shall display the current team roster, including each member's role and public profile link, to all members of that team and to the hackathon's Organizer.
**Preconditions:** The requester is a team member or the hackathon's Organizer.
**Acceptance Criteria:**
- A user who is neither a team member nor the Organizer receives HTTP 403.
- The roster reflects membership changes (FR-TEAM-002 through FR-TEAM-004) without requiring a page reload delay beyond 5 seconds.
**Dependencies:** FR-TEAM-001.

### 3.8 Module: Submission (SUB)

#### FR-SUB-001 — Create and edit a submission

**Priority:** Must Have
**Description:** The system shall allow a team (via any team member) to create and iteratively edit one project submission per hackathon before the submission deadline.
**Preconditions:** The team is registered for the hackathon and the current time is before the submission deadline.
**Acceptance Criteria:**
- Required fields: project title, description (≤ 3,000 characters), at least one of {repository URL, demo URL, uploaded media}.
- Edits are saved as a draft and are visible to all team members immediately.
- Only one submission record exists per team per hackathon; a second creation attempt updates the existing draft rather than creating a duplicate.
**Dependencies:** FR-TEAM-001.

#### FR-SUB-002 — Attach project media

**Priority:** Must Have
**Description:** The system shall allow a team to attach up to 5 media files (images or a single demo video link) and one repository URL to their submission.
**Preconditions:** A draft submission exists (FR-SUB-001).
**Acceptance Criteria:**
- Accepted image formats: JPEG, PNG, WebP, 10 MB max each. Video is accepted as an external URL (e.g., YouTube), not a direct upload, for MVP.
- Repository URL must be a well-formed URL; the system does not validate that the URL resolves (network validation is out of scope for MVP).
- Exceeding 5 media attachments is rejected with a specific error.
**Dependencies:** FR-SUB-001.

#### FR-SUB-003 — Finalize submission

**Priority:** Must Have
**Description:** The system shall allow a team to mark its submission as `final`, indicating readiness for eligibility screening and judging.
**Preconditions:** The submission has all required fields (FR-SUB-001) and the current time is before the submission deadline.
**Acceptance Criteria:**
- A `final` submission can still be edited by the team until the submission deadline (finalizing is a readiness signal, not a lock).
- At the submission deadline, all submissions — `draft` or `final` — transition to `locked` and become read-only per BR-003.
- A team with no submission at all at the deadline is marked `no_submission` and is excluded from FR-ELIG-001.
**Dependencies:** FR-SUB-001, FR-SUB-002.

#### FR-SUB-004 — View own submission history

**Priority:** Should Have
**Description:** The system shall retain and display prior saved versions of a team's submission description for the team's own reference.
**Preconditions:** The submission has been edited at least once.
**Acceptance Criteria:**
- Up to the 10 most recent versions are retained per submission.
- Version history is visible only to team members and the Organizer, never to judges (to prevent bias from watching edit history) or the public.
**Dependencies:** FR-SUB-001.

### 3.9 Module: Eligibility Screening (ELIG)

#### FR-ELIG-001 — Screen a submission

**Priority:** Must Have
**Description:** The system shall allow the Organizer to mark each locked submission as `eligible` or `disqualified`, with a required reason for disqualification, before judging opens.
**Preconditions:** The submission status is `locked` (FR-SUB-003).
**Acceptance Criteria:**
- Disqualification requires a reason of at least 10 characters, shown to the affected team.
- A submission not explicitly screened defaults to `eligible` at the judging-open time, so that screening is opt-out for compliant submissions rather than a blocking gate for every team.
- A disqualified submission is excluded from FR-JUDGE-001 assignment and from FR-SHOWCASE-001 by default (see FR-SHOWCASE-001 for the visibility override).
**Dependencies:** FR-SUB-003.

#### FR-ELIG-002 — Bulk screening view

**Priority:** Should Have
**Description:** The system shall provide the Organizer a single view listing all locked submissions with one-click eligible/disqualify actions, to screen a full cohort efficiently.
**Preconditions:** At least one submission is `locked` for the hackathon.
**Acceptance Criteria:**
- The view supports filtering by current screening status.
- Each action in the bulk view produces the same audit record as FR-ELIG-001 (actor, timestamp, reason if applicable).
**Dependencies:** FR-ELIG-001.

### 3.10 Module: Judging (JUDGE)

#### FR-JUDGE-001 — Assign judges to submissions

**Priority:** Must Have
**Description:** The system shall allow the Organizer to assign one or more invited Judges to review a defined subset of eligible submissions, either manually or via balanced automatic distribution.
**Preconditions:** At least one submission is `eligible` (FR-ELIG-001) and at least one Judge has accepted an invitation to the hackathon.
**Acceptance Criteria:**
- Automatic distribution assigns submissions such that the difference between any two judges' assignment counts is at most 1.
- A judge can be reassigned or removed from an assignment before that judge has submitted any score for it; reassignment after scoring requires Organizer confirmation of score discard.
- A submission with zero assigned judges is flagged to the Organizer in the judging dashboard.
**Dependencies:** FR-ELIG-001.

#### FR-JUDGE-002 — Score a submission

**Priority:** Must Have
**Description:** The system shall allow an assigned Judge to submit a score for each criterion in the hackathon's rubric (FR-HACK-004) for each submission assigned to them, plus an optional free-text comment.
**Preconditions:** The judge is assigned to the submission and the hackathon's judging window is open.
**Acceptance Criteria:**
- Each criterion score must fall within that criterion's configured min/max range; out-of-range values are rejected before submission.
- A judge can save a score as draft and revise it until they explicitly submit it as final, or until the judging window closes, whichever is first.
- A submitted-final score cannot be edited by the judge; the Organizer can reopen a specific score for revision with a logged reason.
**Dependencies:** FR-JUDGE-001, FR-HACK-004.

#### FR-JUDGE-003 — Calculate results

**Priority:** Must Have
**Description:** The system shall calculate each submission's final score as the weighted sum of its rubric criteria, averaged across all judges who submitted a final score for it, and shall rank submissions accordingly within their judging round.
**Preconditions:** The hackathon's judging window has closed.
**Acceptance Criteria:**
- Weighted score per judge = Σ(criterion score × criterion weight); submission final score = mean of weighted scores across all judges who scored it.
- A submission scored by zero judges is excluded from ranking and flagged to the Organizer rather than defaulting to a score of zero.
- Results are computed automatically within 5 minutes of judging window close and are visible to the Organizer immediately; public visibility is separately gated by FR-SHOWCASE-001.
**Dependencies:** FR-JUDGE-002.

#### FR-JUDGE-004 — Multi-round and track-scoped judging

**Priority:** Must Have
**Description:** The system shall support an Overall judging round evaluated against all eligible submissions, and, where sponsor Challenge Tracks exist (FR-TRACK-001), independent track-scoped judging rounds evaluated only against submissions opted into that track.
**Preconditions:** At least one Challenge Track exists for the hackathon (for track rounds); the Overall round always exists implicitly.
**Acceptance Criteria:**
- A submission may be scored in the Overall round and, independently, in any track round(s) it opted into, with fully independent judge pools, rubrics, and results per round.
- A team opting into a track does so at submission time (FR-SUB-001) and this selection locks with the submission per BR-003.
- Round results (FR-JUDGE-003) are calculated and stored independently per round; a submission's track result never affects its Overall result.
**Dependencies:** FR-JUDGE-003, FR-TRACK-001.

### 3.11 Module: Sponsor Challenge Tracks (TRACK)

#### FR-TRACK-001 — Create a challenge track

**Priority:** Must Have
**Description:** The system shall allow the Organizer to create one or more Challenge Tracks within a hackathon, each with its own name, description, and rubric (independent of, or inherited from, the Overall rubric).
**Preconditions:** The hackathon exists in `draft` or `published` status, before judging opens.
**Acceptance Criteria:**
- Each track has a distinct name within the hackathon and its own rubric configured per the rules in FR-HACK-004.
- A track can be associated with a Sponsor account (FR-TRACK-002) or remain organizer-run.
- Tracks configured after publication are immediately visible on the hackathon detail page (FR-DISC-003) as new opt-in options for teams that have not yet finalized their submission.
**Dependencies:** FR-HACK-001.

#### FR-TRACK-002 — Assign a sponsor to a track

**Priority:** Must Have
**Description:** The system shall allow the Organizer to associate an authenticated `Sponsor` account with a specific Challenge Track, granting that Sponsor visibility into the track's submissions and the ability to assign track-scoped Judges.
**Preconditions:** The track exists (FR-TRACK-001); the Sponsor account exists and has accepted the Organizer's invitation.
**Acceptance Criteria:**
- A Sponsor can view only submissions opted into their assigned track(s), never the full hackathon submission set.
- A Sponsor can invite and assign Judges scoped only to their track, using the same mechanism as FR-JUDGE-001 restricted to that track's submission pool.
- Removing a Sponsor's assignment does not delete track data; it revokes the Sponsor account's access only.
**Dependencies:** FR-TRACK-001, FR-JUDGE-001.

### 3.12 Module: Public Showcase (SHOWCASE)

#### FR-SHOWCASE-001 — Publish showcase results

**Priority:** Must Have
**Description:** The system shall, once the Organizer confirms results, publish a public showcase page listing eligible submissions for a completed hackathon, with placement and awards visible for the Overall round and any Challenge Track rounds.
**Preconditions:** FR-JUDGE-003 has completed for all applicable rounds and the Organizer has explicitly confirmed publication.
**Acceptance Criteria:**
- Results are not auto-published on judging close; an explicit Organizer action is required, so an Organizer can review results before they go public.
- Disqualified submissions (FR-ELIG-001) are excluded from the showcase by default; the Organizer may override visibility per submission with a logged reason.
- The showcase page displays team name, members (linking to public profiles per FR-PROFILE-002), project description, media, and final placement, but never individual judge identities or raw per-judge scores.
**Dependencies:** FR-JUDGE-003.

#### FR-SHOWCASE-002 — Public project gallery

**Priority:** Must Have
**Description:** The system shall maintain a cross-hackathon, searchable public gallery of all showcased projects, linked from each participant's public profile (FR-PROFILE-002).
**Preconditions:** At least one hackathon has published showcase results (FR-SHOWCASE-001).
**Acceptance Criteria:**
- The gallery is filterable by hackathon, institution, and technology tag.
- A project appears in the gallery only after its parent hackathon's showcase is published; it is removed automatically if the Organizer later revokes publication.
**Dependencies:** FR-SHOWCASE-001.

### 3.13 Module: Notifications (NOTIFY)

#### FR-NOTIFY-001 — Email and in-app notifications

**Priority:** Must Have
**Description:** The system shall send an email notification and create a corresponding in-app notification for each of the following events: registration confirmation, team invitation, invitation response, hackathon timeline change, submission deadline reminder (24 hours before deadline), eligibility screening result, and judging results published.
**Preconditions:** The recipient has a verified email address.
**Acceptance Criteria:**
- Email is sent within 60 seconds of the triggering event for at least 99% of events (see NFR-PERF-003).
- The in-app notification is marked unread until the user views the notification center and is retained for 90 days.
- A user can opt out of non-critical email categories (e.g., timeline changes) individually; registration confirmations and deadline reminders cannot be opted out of, since they are required for the participant to exercise their rights under the hackathon's rules.
**Dependencies:** FR-AUTH-003.

#### FR-NOTIFY-002 — SMS fallback notification

**Priority:** Must Have
**Description:** The system shall send an SMS notification, in addition to email, for the submission deadline reminder and judging-results-published events, to any user who has provided and verified a phone number.
**Preconditions:** The user has a verified Ethiopian phone number on file.
**Acceptance Criteria:**
- SMS is sent through the configured SMS gateway within 2 minutes of the triggering event for at least 95% of events.
- SMS content is limited to a single 160-character segment where possible, in the user's selected interface language (FR-I18N-001).
- SMS delivery failure does not block or delay the corresponding email notification (FR-NOTIFY-001).
**Dependencies:** FR-NOTIFY-001.

### 3.14 Module: Organizer Analytics (ANALYTICS)

#### FR-ANALYTICS-001 — Registration and conversion dashboard

**Priority:** Must Have
**Description:** The system shall provide the Organizer a dashboard showing, for their hackathon: registration count over time, team formation rate (percentage of registrants on a team), and submission conversion rate (percentage of registrants whose team submitted).
**Preconditions:** The hackathon has at least one registration.
**Acceptance Criteria:**
- The registration-over-time chart is bucketed by day and updates within 5 minutes of a new registration.
- Conversion rates are computed as defined percentages and displayed to one decimal place.
- The dashboard is visible only to Organizers of that specific hackathon and to Platform Admins.
**Dependencies:** FR-REG-001, FR-TEAM-001, FR-SUB-001.

#### FR-ANALYTICS-002 — Demographic breakdown

**Priority:** Should Have
**Description:** The system shall provide the Organizer an aggregated, anonymized breakdown of registrants by university/institution and self-reported skill category.
**Preconditions:** The hackathon has at least 10 registrations (minimum cohort size to protect individual privacy).
**Acceptance Criteria:**
- Breakdowns are shown only in aggregate; no individual participant is identifiable from the breakdown view.
- A hackathon with fewer than 10 registrations shows a placeholder explaining the privacy threshold, not partial data.
**Dependencies:** FR-ANALYTICS-001.

### 3.15 Module: Platform Administration (ADMIN)

#### FR-ADMIN-001 — Review and moderate organizations and content

**Priority:** Must Have
**Description:** The system shall provide a `Platform Admin` a dashboard to review pending organization verifications (FR-ORG-003), and to suspend a hackathon, organization, or user account that violates platform terms.
**Preconditions:** The requester holds the global `Platform Admin` role.
**Acceptance Criteria:**
- Suspending a hackathon immediately removes it from public discovery (FR-DISC-001) while preserving all underlying data.
- Every moderation action records actor, target, timestamp, and a required reason, retained indefinitely for audit purposes.
- A non-admin requesting any endpoint under this module receives HTTP 403.
**Dependencies:** FR-ORG-003.

#### FR-ADMIN-002 — Platform-wide search

**Priority:** Should Have
**Description:** The system shall allow a `Platform Admin` to search across users, organizations, and hackathons by name or email for support and moderation purposes.
**Preconditions:** The requester holds the global `Platform Admin` role.
**Acceptance Criteria:**
- Search results return within 2 seconds at MVP data volumes.
- Every search query is logged with the requesting admin's identity, for audit purposes given the sensitivity of cross-account search.
**Dependencies:** FR-ADMIN-001.

### 3.16 Module: Localization (I18N)

#### FR-I18N-001 — Language toggle

**Priority:** Must Have
**Description:** The system shall allow any user, authenticated or not, to switch the interface language between English and Amharic, applied to all platform-authored UI text.
**Preconditions:** None.
**Acceptance Criteria:**
- The toggle is reachable from every page without scrolling, in a fixed location.
- Switching language does not reload lost form input where technically avoidable (e.g., a partially filled registration form retains its values across a language switch).
- User-generated content (hackathon descriptions, submission text) is displayed as authored and is not machine-translated in MVP.
**Dependencies:** None.

#### FR-I18N-002 — Persisted language preference

**Priority:** Must Have
**Description:** The system shall remember an authenticated user's selected interface language across sessions and devices, and shall remember an unauthenticated visitor's selection for the duration of their browser session.
**Preconditions:** FR-I18N-001 has been exercised at least once.
**Acceptance Criteria:**
- An authenticated user's language preference is stored on their account and applied automatically at next login, on any device.
- SMS notifications (FR-NOTIFY-002) and email notifications (FR-NOTIFY-001) are sent in the recipient's stored language preference.
**Dependencies:** FR-I18N-001, FR-AUTH-002.

---

## 4. Business Rules

Business rules are policy constraints that shape *how* functional requirements behave. They are kept separate from Section 3 because they are cross-cutting — each one constrains multiple functional requirements rather than describing a single system behavior — and because product owners can change a business rule without necessarily changing the functional requirement's shape.

| ID | Rule | Enforced by |
|---|---|---|
| BR-001 | A participant may belong to only one team per hackathon. | FR-TEAM-001, FR-TEAM-002, FR-TEAM-003 |
| BR-002 | Registration closes automatically at the configured registration deadline; no registration is accepted after this time regardless of client-side state. | FR-REG-001, FR-HACK-002 |
| BR-003 | Submissions, team rosters, and track opt-ins become read-only immediately at the configured submission deadline. | FR-SUB-003, FR-TEAM-004, FR-JUDGE-004 |
| BR-004 | A hackathon must have at least one eligibility rule set and a complete, weight-balanced rubric before it can be published. | FR-HACK-005 |
| BR-005 | A judging rubric cannot be modified once judging has opened, to preserve score comparability across all judges and rounds. | FR-HACK-004 |
| BR-006 | A submission defaults to eligible unless explicitly disqualified by the Organizer before judging opens. | FR-ELIG-001 |
| BR-007 | Judging results are not visible to the public until the Organizer explicitly publishes the showcase. | FR-SHOWCASE-001 |
| BR-008 | Judge identities and individual per-judge scores are never exposed outside the Organizer's own dashboard. | FR-JUDGE-002, FR-JUDGE-003, FR-SHOWCASE-001 |
| BR-009 | A Sponsor account may access only submissions opted into a track that Sponsor is explicitly assigned to. | FR-TRACK-002 |
| BR-010 | An organization must be `verified` (domain-based or manual) before any Organizer belonging to it can publish a hackathon. | FR-ORG-002, FR-ORG-003, FR-HACK-005 |
| BR-011 | Demographic data is never displayed at a granularity that could identify an individual participant (minimum cohort size of 10). | FR-ANALYTICS-002 |
| BR-012 | Account enumeration is prevented on every endpoint that could otherwise confirm whether an email address has a registered account. | FR-AUTH-001, FR-AUTH-004, FR-PROFILE-002 |

---

## 5. Non-Functional Requirements

Every non-functional requirement below is measurable and independently verifiable; verification methods are elaborated in [Document 07](07-testing-and-quality-assurance.md).

### 5.1 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-001 | 95% of authenticated API requests shall complete within 500 ms, and 99% within 1,500 ms, under a sustained load of 500 concurrent users. |
| NFR-PERF-002 | Discovery search and filter queries (FR-DISC-002) shall return results within 1 second at a catalog size of up to 5,000 published hackathons. |
| NFR-PERF-003 | 99% of triggering events for FR-NOTIFY-001 shall result in a sent email within 60 seconds of the event under normal operating load. |
| NFR-PERF-004 | The hackathon public detail page (FR-DISC-003) shall achieve a Largest Contentful Paint of under 2.5 seconds on a simulated 3G connection (400 Kbps, 400 ms RTT). |

### 5.2 Security

| ID | Requirement |
|---|---|
| NFR-SEC-001 | All data in transit shall be encrypted via TLS 1.2 or higher; plaintext HTTP requests shall be redirected to HTTPS. |
| NFR-SEC-002 | Passwords shall be stored using a salted, adaptive hashing algorithm (e.g., Argon2 or bcrypt with a cost factor reviewed annually); plaintext or reversibly-encrypted passwords shall never be stored. |
| NFR-SEC-003 | Every state-changing endpoint shall enforce role- and ownership-based authorization server-side, independent of any client-side role display, verified by an authorization test for every FR in Section 3 with an access-control acceptance criterion. |
| NFR-SEC-004 | The system shall pass an OWASP Top 10-aligned security review prior to first production pilot, with all Critical and High findings remediated before launch. |
| NFR-SEC-005 | Session refresh tokens (FR-AUTH-002) shall be invalidated on password reset (FR-AUTH-004) and shall be individually revocable by the account owner from an active-sessions view. |

### 5.3 Availability and Reliability

| ID | Requirement |
|---|---|
| NFR-AVAIL-001 | The platform shall maintain 99.5% uptime measured monthly, excluding scheduled maintenance windows announced at least 24 hours in advance. |
| NFR-AVAIL-002 | Automated database backups shall run at least once every 24 hours, with a Recovery Point Objective (RPO) of 24 hours and a Recovery Time Objective (RTO) of 4 hours. |
| NFR-AVAIL-003 | A failure in the SMS gateway dependency (FR-NOTIFY-002) shall not degrade availability of any other platform function, verified by dependency isolation testing. |

### 5.4 Scalability

| ID | Requirement |
|---|---|
| NFR-SCALE-001 | The system architecture shall support horizontal scaling of the application tier to sustain at least 2,000 concurrent users without requiring a schema migration, for the traffic pattern of a national-scale hackathon's registration opening. |
| NFR-SCALE-002 | The database design shall support at least 50,000 registered users and 500 concurrently active hackathons without requiring a redesign of core tables, verified against the schema in Document 05. |

### 5.5 Accessibility

| ID | Requirement |
|---|---|
| NFR-ACC-001 | All public-facing pages (discovery, hackathon detail, public profile, showcase) shall conform to WCAG 2.1 Level AA. |
| NFR-ACC-002 | Every interactive element reachable by mouse shall also be reachable and operable via keyboard alone. |
| NFR-ACC-003 | All non-decorative images shall have descriptive alternative text in the page's active interface language. |

### 5.6 Usability

| ID | Requirement |
|---|---|
| NFR-USE-001 | A first-time Organizer with no prior training shall be able to complete FR-HACK-001 through FR-HACK-005 (create through publish) in under 20 minutes, measured in usability testing with at least 5 representative participants. |
| NFR-USE-002 | Core participant flows (FR-REG-001, FR-TEAM-001 through FR-TEAM-003, FR-SUB-001) shall remain fully functional on a simulated 3G connection, with no flow requiring more than 2 MB of total page weight. |
| NFR-USE-003 | Every user-facing form validation error (as specified in Section 3 acceptance criteria) shall be displayed inline, adjacent to the offending field, in the user's active interface language. |

### 5.7 Maintainability

| ID | Requirement |
|---|---|
| NFR-MAINT-001 | All backend code shall maintain a minimum of 80% automated test coverage on business-logic modules, measured per Document 07's testing strategy. |
| NFR-MAINT-002 | Every functional requirement in Section 3 shall be traceable to at least one automated test, per the traceability matrix in Document 07. |
| NFR-MAINT-003 | API contracts (Document 04) shall be versioned; a breaking change to a published endpoint shall be released under a new version path rather than mutating the existing one while it has active consumers. |

### 5.8 Localization

| ID | Requirement |
|---|---|
| NFR-L10N-001 | 100% of platform-authored UI strings (excluding user-generated content, per FR-I18N-001) shall have both English and Amharic translations before a feature ships to production. |
| NFR-L10N-002 | Date, time, and number formatting shall be locale-aware for both supported languages, with all dates additionally displaying the EAT timezone abbreviation. |

### 5.9 Compliance

| ID | Requirement |
|---|---|
| NFR-COMP-001 | Personal data handling (collection, storage, retention, deletion) shall align with Ethiopia's Data Protection Proclamation, including a documented lawful basis for each category of personal data collected. |
| NFR-COMP-002 | A user shall be able to request export or deletion of their personal data; a deletion request shall be fulfilled within 30 days, with hackathon submission records anonymized (author unlinked) rather than deleted where deletion would break published showcase results (FR-SHOWCASE-001) for other team members. |
| NFR-COMP-003 | Production user data shall be hosted in a region and under a hosting agreement consistent with the data-residency expectations described in [Document 01, Section 3](01-product-overview.md#3-product-positioning); the specific hosting decision is documented in Document 08. |

---

## 6. Requirement Traceability

Every requirement ID introduced in this document (`FR-*`, `BR-*`, `NFR-*`) is carried forward unchanged into:

- **Document 03** (Software Design Specification) — each architectural component states which requirement IDs it satisfies.
- **Document 04** (API Specification) — each endpoint states which `FR-*` ID it implements.
- **Document 05** (Database Design) — each table's design rationale references the `FR-*`/`BR-*` IDs that shaped it.
- **Document 06** (UI/UX Specification) — each screen references the `FR-*` IDs it exposes to the user.
- **Document 07** (Testing and Quality Assurance) — the full requirement-to-test traceability matrix, mapping every `FR-*` and `NFR-*` ID to at least one test case.

No downstream document introduces a requirement not defined here; if implementation reveals a gap, this document is updated first, per the consistency rule in [Document README, Section 2](README.md#2-how-this-documentation-set-is-organized).
