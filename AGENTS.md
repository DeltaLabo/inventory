# Inventory context

This is a small Streamlit inventory with public browsing, password-protected
additions and edits via GitHub PR, and immediate withdrawals via atomic GitHub commits.
Keep it simple: no separate database or server. `app.py` is the only application
entry point; `inventory.py` has import-safe CSV helpers and validation,
`forms.py` holds the three protected forms, and `github_inventory.py` handles GitHub.
UI and user documentation are Spanish.

Resolve paths relative to source files. Preserve editable CSVs and codes, including
padding zeros and periods. Do not infer physical item identities, rename ambiguous
codes, assign missing stock, or fabricate descriptions. Expose problems instead:
unmatched stock stays visible, unknown quantities stay blank, and duplicate catalog
records must not multiply stock rows.

The user explicitly requested the new GitHub-backed write flow after the initial
catalog cleanup. The old version directories stay deleted. Never restore the old
hardcoded password or local CSV-writing usage flow. Read credentials from Streamlit
secrets or environment variables. Blank credentials disable each protected form;
public search remains available. Secrets must never be committed or logged.

New product IDs are four random uppercase ASCII letters plus MMYY of ID issuance
in America/Costa_Rica, e.g. KQZT1026. IDs remain fixed after assignment. Check current
catalog/stock codes and atomically reserve `refs/tags/inventory-ids/<code>` to avoid
collisions with pending/concurrent submissions. Do not delete these reservation tags.
Submission/movement IDs remain UUIDs; they are separate from product IDs.
Existing products reuse their original IDs. Additions create a branch and PR;
only the owner merges them. Withdrawals change exactly one stock location and append
`movements.csv` in one commit; use non-forced ref updates and re-read after conflicts.
Submission IDs make retries idempotent. Never retry by allocating a new ID after an
uncertain write. Reject ambiguous products/locations and invalid or insufficient stock.
`usage_log.csv` is historical only. `not_found.csv`, `smd.csv`, and `to_buy.csv` remain
independent auxiliary sources. No source-data migration is authorized by inference.

Run `python -m unittest discover -s tests -v` for behavior checks and
`python inventory.py` for source validation. The latter deliberately returns 1
while ambiguous/missing source data remain unresolved. Never fix these by guessing.
Keep network calls optional, bounded, and cached.
Tests must mock GitHub; never submit real PRs or stock movements as a test.

The top-level actions are Consultar, Ingresar, Editar, Retirar. Edits reuse the
addition password and propose changes on `inventory/edit-<id>` branches. Prefill the
form and freeze its original snapshot until another product/location is selected.
Compare only changed fields with the latest data before proposing an edit; preserve
unmodified fields and never overwrite intervening withdrawals. Record before/after
values, responsible person, and a required reason. IDs are immutable. Reject invalid
balances and destination-location collisions; never merge stock rows automatically.
Show the global "Datos por revisar" panel only under Editar, not public browsing.

On 2026-10-22 the user explicitly authorized provisional relay counts and sharing
one compartment, while keeping the two variants distinct. SRD5VDCS was split into
GPQM1026 (4-relay module, provisional 4 units) and SINW1026 (2-relay module,
provisional 2 units), both A/12. Keep `Conteo provisional:` notes and validation
warnings until the user confirms the physical counts. Total stock is still 6.

The user then explicitly authorized migrating remaining active product codes to
the random format, keeping products/bags/characteristics distinct and pushing the
result. The migration assigned 186 new IDs, retained the two relay IDs, preserved
all 177 stock rows, locations and counts, and added nine independent catalog stubs
for previously orphaned stock. No similar-looking legacy codes were merged.
`details.csv` now has an optional `previous_code` column for old-code searches,
historical references and image fallback. Preserve it on edits. New products leave
it blank. Never use it as a merge key; multiple distinct variants may share a legacy
reference. Historical/auxiliary CSVs intentionally retain old references and are
not authoritative stock sources. Complete stub descriptions only from user evidence.

For new additions, Type and Subtype are dependent dropdowns populated from the
approved catalog, with "Crear nuevo…" text inputs for new choices. Render these
outside the submission form to refresh subtypes immediately, and clear the selected
subtype when the type changes. New categories become shared choices only after
the addition PR is merged; do not add a separate taxonomy service or database.
Manufacturer on new additions is an optional searchable selectbox with
`accept_new_options=True`, using approved nonempty manufacturer names as suggestions.
Deduplicate suggestions case-insensitively without modifying existing catalog rows.
