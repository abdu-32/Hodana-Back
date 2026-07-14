# contracts/openapi.yaml

This file is **generated**, not hand-written. Run `scripts/export_contract.sh`
after changing any serializer, view, or urls.py, then commit the result.

Until the real endpoints exist, this starts as a copy of `docs/04-openapi-
specification.yaml` (the hand-authored spec from the design phase). As each
app's views/serializers get built, regenerate this file and it will start
reflecting the real API instead of the hand-written draft — at that point
`docs/04-openapi-specification.yaml` becomes historical/reference only.

The frontend team consumes ONLY this file (via `scripts/sync-contract.sh`
in their repo). They do not run this backend to get it.
