# Inventory context

This is a small Streamlit inventory with public browsing, password-protected
additions via GitHub PR, and immediate withdrawals via atomic GitHub commits.
Keep it simple: no separate database or server. `app.py` is the only application
entry point; `inventory.py` has import-safe CSV helpers and validation,
`forms.py` holds the two protected forms, and `github_inventory.py` handles GitHub.
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

New product IDs are `I` + an uppercase UUID, generated from the submission ID.
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
