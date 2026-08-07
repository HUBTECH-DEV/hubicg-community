# P0 marks gate

Owner and approver: Paulo Cesar Benjamin Junior.

Registration at INPI is not a prerequisite for this release. The gate requires
an evidence-backed decision about the safe use of both `HubTech` and `HubICG`.

## Evidence required for each mark

1. Exact word and visual forms intended for use.
2. Territories and relevant Nice classes for software, SaaS and technology
   services.
3. Dated searches covering INPI, web search, GitHub, package registries,
   domains and major app or service directories.
4. Search query, result URL or private evidence reference, similar names found,
   owner, class, territory and status.
5. Confusion and coexistence analysis covering spelling, sound, meaning,
   audience, products and distribution channels.
6. One decision per mark: `clear`, `accepted` or `mitigated`, with rationale and
   any naming, visual or territory restriction.
7. Review date, approved baseline and Paulo's approval.

The gate closes only when `.hubicg/gates/p0-marks.json` has status `approved`,
all required evidence is present and `python scripts/check_p0_gates.py
--require-closed` succeeds. Evidence containing personal or confidential data
must be referenced by an opaque identifier and retained in HubTech's private
legal archive.
