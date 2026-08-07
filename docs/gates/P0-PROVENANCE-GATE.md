# P0 provenance gate

Owner and approver: Paulo Cesar Benjamin Junior.

## Evidence required

1. Confirm every Git name/e-mail alias and map public-safe aliases in
   `.mailmap`.
2. Inventory every tracked release file in
   `docs/legal/PROVENANCE-MANIFEST.csv`.
3. Record path, SHA-256, origin, source commit, author, classification, license,
   decision, reviewer and evidence reference.
4. Classify each item as first-party, generated, upstream license text or other
   explicitly reviewed class.
5. Confirm that third-party components remain under their upstream licenses and
   are covered by `THIRD_PARTY_NOTICES.md` and the SBOM.
6. Confirm that no private chat history, secrets, credentials, personal
   documents, local paths or Enterprise-only content is present.
7. Bind the approval to an immutable baseline commit and tree.

Every tracked file except the CSV manifest itself must have one current,
approved row. The gate closes only when `.hubicg/gates/p0-provenance.json` has
status `approved`, all confirmations are true and `python
scripts/check_p0_gates.py --require-closed` succeeds.

Generate or refresh the review worksheet with:

```sh
python scripts/build_provenance_manifest.py
```

Generation does not approve a row. Paulo must review the worksheet, replace
each `pending` decision with `approved`, record evidence and then approve the
gate document.
