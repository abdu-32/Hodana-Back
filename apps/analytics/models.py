"""
analytics -- models

Implements FR modules: ANALYTICS
Depends on: registrations, teams, submissions

Per DB Design Sec 4 traceability table: "FR-ANALYTICS-001 - FR-ANALYTICS-002
-- Derived from `registration`, `team`, `submission` (no dedicated table;
see Document 03 Sec 6 for the query/caching approach)". This app
deliberately has no models of its own: every figure the dashboard and
demographic breakdown show is computed on read, in services.py, from rows
owned by apps.registrations, apps.teams, and apps.submissions.

BR-011 ("no individual identifiable from the breakdown, minimum cohort
size of 10") is likewise "enforced at the analytics query layer, not the
schema" per DB Design Sec 6 -- see services.py, not a model constraint
here.
"""
