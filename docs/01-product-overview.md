# 01 — Product Overview

**Document type:** Product vision and scope definition
**Audience:** All readers — this is the recommended starting point
**Related documents:** [02 — Software Requirements Specification](02-software-requirements-specification.md) (detailed requirements derived from this scope) · [09 — Project Roadmap](09-project-roadmap.md) (everything explicitly out of MVP scope) · [10 — Business and Incubation](10-business-and-incubation.md) (full market and business case)

---

## 1. Vision

The **Ethiopia Innovation Hub** is a platform where Ethiopian universities, companies, NGOs, and government agencies can discover, run, and participate in hackathons and innovation challenges — in a system built for Ethiopia's languages, institutions, and payment infrastructure, rather than adapted from one built for somewhere else.

The product exists on a simple premise: hackathons are a low-cost way to convert youth energy into visible skill, and Ethiopia already has organizers running them — just without a platform that fits how the country actually operates. The MVP's job is to make the existing hackathon lifecycle (discover → register → form a team → submit → get judged → showcase) work well end to end, with the localization that decides whether an institution adopts a platform or keeps tolerating a spreadsheet-and-Telegram workaround.

## 2. The problem

Ethiopian organizers and participants already run hackathons — on Devpost, on university WordPress sites, through Facebook and Telegram groups, and via Google Forms. This is evidence of real, existing demand, not a hypothetical market. It also means the problem is fragmentation and mismatch, not absence of activity:

- **No Ethiopia-wide catalog.** Events are scattered across platforms with no shared discovery layer, so participants rely on word of mouth and organizers duplicate administrative work every time.
- **No local payment path.** Global platforms have no Telebirr, CBE Birr, or Chapa integration, forcing organizers into manual, off-platform prize disbursement.
- **English-only tooling.** No bilingual (Amharic/English) interface, which limits participation from students and organizers more comfortable working in Amharic.
- **No institutional trust layer.** Government and enterprise partners need data-residency and verification guarantees that a foreign-hosted, generic-ToS platform does not offer.

A full account of the evidence behind these claims, including what is proven versus what the pilot phase is designed to test, is in [Document 10, Section 1](10-business-and-incubation.md).

## 3. Product positioning

The product is best understood as **"Devpost, designed specifically for Ethiopia"**: the same core mechanics that make hackathon platforms work, rebuilt around local language, local institutions, and local payment rails.

| Dimension | Global platforms (e.g., Devpost) | Ethiopia Innovation Hub |
|---|---|---|
| Language | English only | Bilingual English/Amharic from MVP; Oromo/Tigrinya roadmapped |
| Payments | No local rails; manual prize distribution | Local payment integration path (Telebirr, CBE Birr, Chapa) |
| Data residency | Foreign-hosted, generic terms of service | Designed for alignment with Ethiopia's Data Protection Proclamation |
| Institutional verification | Manual, ad hoc | Domain-based or manual verification with a visible status badge |
| Connectivity assumptions | Assumes reliable broadband | Low-bandwidth tolerant; SMS treated as a first-class fallback channel |

A complete feature-by-feature comparison is in [Document 10, Section 4](10-business-and-incubation.md).

## 4. Target users

The platform serves two broad groups — organizations that host challenges and individuals who take part in them — plus the supporting roles that make judging and mentorship work.

| Role | Represents | Primary goal on the platform |
|---|---|---|
| **Participant** | Students and early-career developers | Discover relevant hackathons, find teammates, submit a project, build a public portfolio |
| **Organizer** | Universities, companies, NGOs, government agencies | Configure and run a hackathon end to end: eligibility, timeline, judging, results |
| **Sponsor** | A company funding one challenge track inside a larger event | Get a branded track with independent judging, without running the whole event |
| **Judge** | Faculty, industry professionals, invited reviewers | Score assigned submissions against a rubric |
| **Mentor** | Volunteer engineers and advisors | Offer lightweight guidance to teams during an event |
| **Platform Admin** | The team operating the Hub | Verify institutions, moderate content, support organizers |

These six roles are fixed across every document in this set; no other document introduces a role not listed here.

### Representative personas

- **Selam (21), CS student, Addis Ababa** — wants to discover hackathons relevant to her interests, find teammates, and leave each event with a public, shareable project.
- **Dr. Alemu, university club advisor** — wants to run campus hackathons without building his own registration and judging tooling from scratch.
- **Mr. Tesfaye, engineering manager** — wants to sponsor a themed challenge track to evaluate real candidate work, without operating the full event.
- **Ms. Bekele, government innovation officer** — wants to run a national-scale challenge and report participation data to her ministry.

## 5. Core product journey

At the center of every hackathon on the platform is one lifecycle, common to every organizer type:

```mermaid
flowchart LR
    A[Discover] --> B[Register]
    B --> C[Form a Team]
    C --> D[Submit a Project]
    D --> E[Eligibility Screening]
    E --> F[Judging]
    F --> G[Public Showcase]
```

Every functional requirement in Document 02 exists to make one stage of this journey work correctly for one of the six roles above. Section 5 of Document 02 groups requirements by stage and role for exactly this reason.

## 6. MVP scope boundary

The MVP is scoped to do the core journey above exceptionally well, plus the localization that determines institutional adoption. It is deliberately **not** scoped to build the surrounding ecosystem (recruitment, funding, certification, government integrations) — those are real, valuable, and explicitly deferred, not rejected.

### In scope for MVP

- End-to-end hackathon lifecycle: discovery, registration, team formation, submission, eligibility screening, judging (including sponsor challenge tracks and multi-round judging), and public showcase.
- Bilingual (English/Amharic) interface.
- Institutional verification via email domain or manual review.
- Organizer analytics (registration trend, conversion rate, demographics).
- Local-payment integration path (abstracted; see [Document 09](09-project-roadmap.md) for phasing detail).
- Low-bandwidth tolerance and SMS notifications as a fallback channel.

### Explicitly out of scope for MVP (see Document 09 for phase assignment and rationale)

- Full mentor-matching (MVP ships a lightweight mentor directory only).
- Recruitment and job-board features.
- Certificates and credentialing.
- Startup showcase, investor dashboard, and funding marketplace.
- University SSO and Fayda Digital ID integration.
- Native mobile applications and public third-party APIs.
- Oromo and Tigrinya localization (English/Amharic ship in MVP).

Every feature above the line was deliberately kept because it makes the core lifecycle work for Ethiopian institutions specifically. Every feature below the line was deliberately removed because it would meaningfully increase build effort without which the core lifecycle still fails to work — the discipline the MVP philosophy in Document 09 depends on.

## 7. Product-level success criteria

Detailed, testable acceptance criteria live in Document 02 (per-requirement) and Document 07 (test plan). At the product level, the MVP succeeds if, within 6 months of the first pilot:

- A participant can complete the full lifecycle (discover → showcase) with no manual intervention from the platform team.
- At least 10 hackathons have been hosted across at least one anchor university or government partner.
- At least 500 users have registered across major Ethiopian universities.
- A new organizer can take a hackathon from creation to publish in under one week.

## 8. Glossary

Definitions used consistently across all ten documents:

| Term | Meaning |
|---|---|
| Hackathon | A time-boxed innovation contest with registration, submission, and judging phases |
| Organizer | Any host (university, company, NGO, government agency) running a hackathon |
| Challenge Track | A sponsor- or theme-specific sub-category within a hackathon, with its own prize and judging round |
| Anchor Partner | A founding institutional partner (university or government agency) that hosts the platform's first pilot event |
| Eligibility Screening | Organizer review that marks a submission eligible or disqualified before it reaches judges |
| Judging Round | A scoring cycle against a rubric — either the Overall round or a track-specific sponsor round |
| MVP | Minimum Viable Product |
| SRS | Software Requirements Specification |
| SDS | Software Design Specification |
| EAT | East Africa Time (UTC+3) |
