# 09 — Project Roadmap

**Document type:** Post-MVP Capability Roadmap and Deferred Decisions Register
**Audience:** Product owners, technical reviewers, engineers planning post-MVP work
**Status:** Complete — derived from and traceable to the SRS
**Related documents:** [01 — Product Overview](01-product-overview.md), [Section 6](01-product-overview.md#6-mvp-scope-boundary) (the MVP scope boundary this roadmap picks up beyond) · [02 — Software Requirements Specification](02-software-requirements-specification.md), [Section 2.3](02-software-requirements-specification.md#23-assumptions-and-dependencies) (the deferred external dependencies formalized here) · [03 — Software Design Specification](03-software-design-specification.md), [Section 2](03-software-design-specification.md#2-system-context) (the architecture this roadmap's items are intentionally absent from) · [10 — Business and Incubation](10-business-and-incubation.md) (the business model, go-to-market strategy, and risk register that determine *whether and how fast* this roadmap gets funded — this document assumes that context rather than repeating it)

---

## 1. Introduction

### 1.1 Purpose

This document specifies **what the Ethiopia Innovation Hub does not do yet, and in what order it will**. Every capability listed here was deliberately excluded from the MVP defined in [Document 01](01-product-overview.md) and [Document 02](02-software-requirements-specification.md), and every exclusion referenced from those documents as "Phase 2," "deferred," or "roadmapped" is registered here with the reasoning, sequencing, and — where a technical decision was postponed rather than simply scheduled later — the criteria that will settle it.

This document is not a specification. Nothing here carries an `FR-*`, `BR-*`, or `NFR-*` ID, and nothing here is implemented against. When a roadmap item is promoted into a build cycle, it graduates into Document 02 as new or amended requirements, and this document is updated to reflect that it has shipped.

### 1.2 Scope

This document covers two things:

1. **Phased capability roadmap** (Section 2) — what ships after MVP, and roughly when.
2. **Deferred technical decisions** (Section 3) — MVP-scope dependencies that were deliberately left as external abstractions rather than specified, per [Document 02, Section 2.3](02-software-requirements-specification.md#23-assumptions-and-dependencies).

This document deliberately does **not** cover business model, monetization, go-to-market sequencing, or the risk register — that material lives in [Document 10](10-business-and-incubation.md), which owns it as a single source of truth. Where a phase in Section 2 depends on a business or partnership milestone (for example, a phase that assumes subscription revenue or a government relationship is already in place), this document references the relevant section of Document 10 rather than restating it.

### 1.3 How to read the phase labels

`Phase 2`, `Phase 3`, and `Phase 4` are sequencing labels, not calendar commitments. They express **dependency order** — a Phase 3 item generally assumes a Phase 2 item (or the revenue/adoption evidence it produces) is already in place — rather than a fixed number of months. Where an approximate timeframe is given, it is an estimate made at MVP planning time and should be treated as illustrative, not contractual.

---

## 2. Phased Capability Roadmap

| Phase | Capability | Depends on | Rationale for deferral |
|---|---|---|---|
| Phase 2 (~6–12 mo post-launch) | Full mentor-matching (structured mentor–mentee pairing, office-hours scheduling) | MVP `Mentor` role and directory (already shipped, capability-light per [Document 03, Section 1.4](03-software-design-specification.md#14-note-on-roles)) | No MVP functional requirement module needs it; validating the core hackathon lifecycle first avoids building a matching system before there's a mentor pool or participant demand signal to design it against. |
| Phase 2 (~6–12 mo post-launch) | Internship/job board tied to participant portfolios | MVP portfolio/profile data (FR-PROFILE-\*) | Requires a large enough graduated-participant pool to be worth an employer paying for; premature before Phase 1 adoption is proven. |
| Phase 2 (~6–12 mo post-launch) | Oromo and Tigrinya localization (beyond MVP English/Amharic) | MVP i18n framework (FR-I18N-\*) | The MVP bilingual (English/Amharic) i18n architecture is built to be extended, not rebuilt, so adding locales is additive; sequencing is about translation/content investment, not platform risk. |
| Phase 2 (~6–12 mo post-launch) | Bank-transfer and mobile-money-agent payment options (beyond whatever aggregator is chosen per Section 3.1) | Section 3.1 payment aggregator decision | Additional payout rails are only worth the integration cost once payment volume from the first aggregator justifies it. |
| Phase 2 (~6–12 mo post-launch) | Enhanced analytics and custom reporting for funders/government | MVP organizer analytics (FR-ANALYTICS-\*) | Custom reporting requirements vary per funder; building bespoke reports before a funder relationship exists risks guessing wrong. |
| Phase 2 (~6–12 mo post-launch) | University certificate issuance | MVP submission/showcase data | Requires institutional agreement on certificate criteria per university, which is a partnership dependency, not a build one. |
| Phase 3 | Startup showcase and funding-call marketplace for investors/incubators | Phase 2 job board and a mature showcase dataset | Needs a track record of showcased projects worth an investor's time before the marketplace has any supply. |
| Phase 3 | Gov/NGO challenge modules with NDA and data-sharing support | MVP challenge-track infrastructure (FR-TRACK-\*), plus legal review of NDA handling | Government/NGO data-sharing terms require legal groundwork that shouldn't gate MVP launch. |
| Phase 3 | Institutional SSO and Fayda Digital ID integration for automated student verification | Section 3.2 Fayda Digital ID decision | Fayda integration requires government-side API access and certification that is outside the team's control and unlikely to be ready at MVP launch; MVP ships with domain-based/manual verification instead. |
| Phase 4 | White-label licensing of the platform to other African markets | Proven, stable single-country deployment ([Document 10](10-business-and-incubation.md)) | Licensing to new markets multiplies compliance and localization surface area; doing this before the Ethiopia deployment is proven would compound risk rather than validate the model. |

Two comparison points from market analysis are worth carrying forward as roadmap justification rather than MVP scope: recruitment/hiring tooling and formal mentor-matching are both areas where the MVP is intentionally lighter than mature global platforms, and both are explicitly the Phase 2 items above rather than gaps to close before launch.

---

## 3. Deferred Technical Decisions

These are dependencies the MVP architecture treats as external abstractions — [Document 03](03-software-design-specification.md) integrates against an interface, not a specific vendor — because the underlying decision could not be settled at MVP design time. Each is a decision this document tracks until it is resolved and promoted into Document 02/03 as a concrete requirement.

### 3.1 Payment aggregator selection

**Status:** Open. **Decision owner:** Tech Lead, with Founder sign-off.

The MVP's payment abstraction (per [Document 02, Section 2.3](02-software-requirements-specification.md#23-assumptions-and-dependencies) and [Document 03](03-software-design-specification.md)) does not commit to a specific local payment aggregator. Candidates under consideration include Telebirr, CBE Birr, and Chapa as an aggregation layer over multiple local rails. This is deliberately unresolved at MVP time because:

- Merchant onboarding and sandbox access timelines for Ethiopian fintech integrations are a known source of schedule risk (see [Document 10](10-business-and-incubation.md)'s risk register) and outside the dev team's direct control.
- The MVP's first pilot events can run with **manual payout as a fallback**, so the integration is not on the MVP's critical path.

**Resolution criteria:** a technical feasibility spike (sandbox access confirmed, merchant-onboarding timeline confirmed for at least one candidate) should be run in the first month of Phase 2 planning, before this decision is treated as fixed. Once resolved, this section is retired and the concrete integration becomes a set of `FR-NOTIFY`/payment-adjacent requirements in Document 02, with corresponding design in Document 03 and endpoints in [Document 04](04-openapi-specification.yaml).

### 3.2 Fayda Digital ID and institutional SSO

**Status:** Open. **Decision owner:** Tech Lead, pending government-side API availability.

MVP institutional verification is domain-based or manual (visible as a "Verified Student" badge). Automated verification against Ethiopia's Fayda Digital ID system, and institutional SSO more broadly, is deferred to Phase 3 (Section 2) because it depends on external government API access and certification that cannot be secured or scheduled unilaterally by the team.

**Resolution criteria:** this becomes actionable once the government/ministry relationship described in [Document 10](10-business-and-incubation.md#5-go-to-market-and-partnership-strategy) is established and Fayda API access can be requested through it. Until then, the MVP's manual/domain verification is the durable interim solution, not a stopgap expected to be replaced on a fixed timeline.

### 3.3 Mentor-matching mechanism

**Status:** Open, intentionally not designed yet.

Beyond the Phase 2 scheduling noted in Section 2, the actual matching mechanism (manual curation vs. rule-based matching vs. participant self-selection) is unspecified. This is deferred rather than merely scheduled because the right mechanism depends on data the MVP doesn't yet have — how many mentors sign up, how participants actually use the lightweight MVP mentor directory, and what matching friction they report. Designing the mechanism before that data exists risks over-building.

---

## 4. Traceability to MVP Scope Exclusions

Every item in this document exists because another document explicitly pushed it here. This table closes that loop.

| Roadmap item | Excluded from | Reference |
|---|---|---|
| Mentor-matching, office-hours scheduling | Document 03 architecture | [Document 03, Section 1.4 note on roles](03-software-design-specification.md#14-note-on-roles) |
| Payment aggregator selection | Document 02 scope, Document 03 architecture | [Document 02, Section 2.3](02-software-requirements-specification.md#23-assumptions-and-dependencies) |
| Fayda Digital ID / institutional SSO | Document 03 system context | [Document 03, Section 2](03-software-design-specification.md#2-system-context) |
| Oromo/Tigrinya localization | Document 02 MVP scope boundary | [Document 01, Section 6](01-product-overview.md#6-mvp-scope-boundary) |
| Recruitment/job board tooling | Document 01 competitive positioning | [Document 01, Section 6](01-product-overview.md#6-mvp-scope-boundary) |
| Full mentor community/matching | Document 01 competitive positioning | [Document 01, Section 6](01-product-overview.md#6-mvp-scope-boundary) |

Where a roadmap item is promoted into active development, this table — and Section 2's phase table — should be updated to mark it shipped, and the corresponding requirement should appear in [Document 02](02-software-requirements-specification.md) with a real `FR-*`/`NFR-*` ID.
