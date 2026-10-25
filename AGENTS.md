# Inventory context

This is a small Streamlit inventory with public browsing, password-protected
additions, edits and withdrawals via immediate atomic GitHub commits.
Keep it simple: no separate database or server. `app.py` is the only application
entry point; `inventory.py` has import-safe CSV helpers and validation,
`forms.py` holds the inventory forms, `purchases.py` holds the purchase list/form
and quotation export, `withdrawal_history.py` holds project withdrawal reports,
`request_application.py` calculates additions/edits without writes, and
`github_inventory.py` handles GitHub.
UI, messages, maintained descriptive inventory text and user documentation are English.
Preserve identifiers, brand names, URLs, physical labels and historical audit entries.

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
Existing products reuse their original IDs. The user explicitly replaced approval
with immediate saving: additions and edits use the addition password, write directly
to the latest configured branch, and create no PRs or GitHub Actions. Withdrawals change exactly one stock location and append
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

The top-level actions are Browse, Add, Edit, Withdraw, Purchases, History. Edits reuse the
addition password and save changes immediately with atomic audit receipts. Prefill the
form and freeze its original snapshot until another product/location is selected.
Compare only changed fields with the latest data before proposing an edit; preserve
unmodified fields and never overwrite intervening withdrawals. Record before/after
values, responsible person, and a required reason. IDs are immutable. Reject invalid
balances and destination-location collisions; never merge stock rows automatically.
Show the global "Data to review" panel only under Edit, not public browsing.

On 2026-10-22 the user explicitly authorized provisional relay counts and sharing
one compartment, while keeping the two variants distinct. SRD5VDCS was split into
GPQM1026 (4-relay module, provisional 4 units) and SINW1026 (2-relay module,
provisional 2 units), both A/12. Keep `Provisional count:` notes and validation
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
saved catalog, with "Create new…" text inputs for new choices. Render these
outside the submission form to refresh subtypes immediately, and clear the selected
subtype when the type changes. New categories become shared choices only after
the addition is saved; do not add a separate taxonomy service or database.
Manufacturer on new additions is an optional searchable selectbox with
`accept_new_options=True`, using saved nonempty manufacturer names as suggestions.
Deduplicate suggestions case-insensitively without modifying existing catalog rows.
Box on new products or first-time stock entry is a searchable selectbox with
`accept_new_options=True`, populated from nonempty saved stock locations.
New boxes become shared suggestions after saving the addition. Preserve existing
box labels and keep compartment entry separate.
When a new box/bag must be assigned, Bag is a nonnegative integer input. Place both
outside the submission form so an existing-occupancy warning updates immediately.
Check only the selected box, treating 01 and 1 as the same numeric compartment;
preserve an existing label for CSV references. The warning never blocks submission:
different product IDs may share a compartment and must not be merged.
Restocking an existing product automatically reuses its assigned box/compartment;
show a read-only caption, or select only among its already registered locations if
there are several. Ask for a new location only if none exists yet. Reject a stale
restock location in the backend instead of silently creating a different slot.
Use Box and Bag consistently in English UI labels, messages and documentation.
Keep the internal CSV/API column names `location` and `sublocation` unchanged.

Recorded by means the person who records an addition, performs a withdrawal, or
submits an edit; it is not the owner of an item or project. The user accepted this
purpose after clarification. Keep it on these forms unless explicitly changed.
Project or note remains optional on inventory additions. Project is required on
new withdrawals and purchase requests so they can be tracked by project. Purchase
requests also require requester and product link.

User workflow rule: different bags or physical characteristics mean independent
records; similar legacy codes/names are never sufficient evidence to merge them.
Conversely, different products can share a box/bag while keeping distinct IDs.

Refresh stock only clears the 15-second read cache and fetches GitHub;
it does not write balances or movements. There is no automatic polling. If the
remote read fails, show local read-only data with a warning and disable write forms.

Deployment was verified on Streamlit after secrets were configured by the user.
Never request, reveal or commit those secrets as part of routine maintenance.
Keep README aligned with implemented behavior and retain unresolved data warnings
in Edit. All application changes through the Box/Bag terminology update were
pushed to main; do not treat the nine placeholder records or provisional relay counts
as verified physical data. No overnight automation or additional work was requested.

English translation: keep legacy provisional-note detection for pending requests
created before translation. Display all validation warnings in English. Do not
translate entered audit history or change CSV/API field names as a language change.

Purchases use the existing withdrawal password (INVENTORY_WITHDRAW_PASSWORD),
never a new secret. Public users can view/download the complete quotation list;
only submitting requires the password. Require description, positive integer
quantity, Project, Requested by and a valid HTTP/HTTPS product URL without embedded
login details. Manufacturer, model/variant and notes are optional. Accept any supplier;
do not fetch user-supplied links. Preserve each request's project/person/quantity even
when links match; never merge projects or guess missing legacy project information.
Save purchase_requests.csv with UUID and UTC timestamp directly via an atomic,
non-forced GitHub commit. Retry concurrent changes, and recover uncertain writes
by the same request UUID without duplication or silently accepting changed details.
Purchase requests never modify stock or place orders. No approval or completion
workflow was requested. Legacy to_buy.csv stays independent; do not import it.
CSV exports include all requests and protect spreadsheet cells from interpreting
user-entered formulas. Purchase-list reads are cached 15 seconds, with manual refresh
and invalidation after save. If the list cannot be read, disable purchase submission.
Use mocked GitHub tests for validation, concurrency, uncertain writes, full export,
password reuse and form behavior. Do not submit real requests as a test.

History is a public read-only view of movements.csv, the existing separate ledger
committed atomically with stock updates. Filter by exact recorded project and show
totals per project/product plus individual movements and a filtered CSV download;
All projects exports the complete log. Never infer movements from stock balances,
merge distinct codes, or import usage_log.csv as authoritative withdrawal history.
Show old blank-project entries as No project recorded without rewriting them.
Keep their entered project/note text intact. Require Project for new withdrawals
in UI and backend; still recover an existing legacy retry with a blank project.
Descriptions in reports come from the current catalog, not historical snapshots;
retain missing/ambiguous catalog products by code and never multiply movements.
Use the shared spreadsheet_csv export helper to keep entered formulas as text.
Cache history reads for 15 seconds, offer refresh and invalidate after withdrawal.
Label local snapshots and surface read/quantity errors rather than silently dropping
movements or showing a failed remote fetch as an empty report. Preserve all existing
ledger data; tests must use mocked GitHub and must never make real withdrawals.

The user explicitly requested one stock quantity: locations.csv has columns
code,location,sublocation,units. Units means currently available stock, never a
lifetime received count. Additions increase units; withdrawals reduce units and
append the existing movement ledger atomically. Edit offers a single Units input.
The migration takes old available values as new units, preserving every code,
box/bag, zero and unknown balance; never copy old lifetime units over availability.
Both pandas and GitHub readers accept legacy two-column files, use available as
the remaining balance and drop it from normalized stock. Stock writes use only
units. Reject edit snapshots from the old two-column schema until the page is
refreshed. Existing available_after fields in historical movements/receipts remain
unchanged and display as Units after withdrawal; they are not live stock columns.
Review older pending stock PRs against current balances when merging the schema
change. Auxiliary legacy CSVs are not authoritative stock and remain independent.

Edit supports finding products by existing box and bag before choosing a record.
Keep Find in box and Find in bag independent, with All boxes/All bags defaults.
Sort numeric bags numerically; match zero-padded numeric labels without rewriting
their CSV values. Show matching contents and keep products sharing a bag distinct.
Filter the product dropdown to matching unique catalog IDs and scope stock-slot
selection to the matching box/bag, especially for products stored in several places.
Enable stock correction by default when filtering by storage. Reset stale product,
slot and form state when the target changes while preserving edit concurrency checks
and immediate-save authorization. With both filters cleared, unassigned catalog records
must remain editable. Do not infer identities, merge rows or change stock as a
side effect of browsing these filters. Cover shared bags and multiple stock slots
with mocked UI tests.

Immediate-write workflow supersedes all earlier PR-approval descriptions. New
additions and edits use GitHubInventory.add/edit, calculated against current data,
with schema-3 requests/UUID.json receipts and the affected CSVs in one commit.
Non-forced branch updates retry concurrent writes. The same operation UUID and
normalized payload recover an uncertain completed save without double counting;
changed payloads under a saved UUID are rejected. Preserve old merged PR receipts;
never replay them or assume that missing schema-3 metadata means unapplied stock.
Stock and catalog reads are invalidated after successful additions and edits.
New product ID reservation tags remain necessary for concurrent issuance; keep
historical tags too. No PR permission or workflow is required for new writes.
Use Contents Read/write for inventory and separate read-only administration access.

Assistant selections for withdrawals come from the private administration CSV via
authenticated API access. Read/cache only ID/name, never contact or banking fields.
The roster cache lasts five minutes with manual refresh. Require a registered ID
and its matching canonical name on new withdrawals; append assistant_id to the
ledger while preserving old rows. Existing completed retries can recover without
roster access. The shared password authorizes the action; selection is not identity
verification. Tests must mock both repositories and never create real test writes.
