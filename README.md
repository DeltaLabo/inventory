# Delta LAB Inventory

A simple Streamlit inventory with public browsing, additions and corrections
submitted for approval, and immediate withdrawals. The interface and documentation
are in English. GitHub stores the data; no separate database or server is required.

Live app: [Delta LAB Inventory](https://deltalab-inventory.streamlit.app/).

## Run locally

From this repository:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

`app.py` is the only application entry point. Select it as the main file in
Streamlit Cloud. CSV paths are resolved relative to the source files.

## Using the app

- **Browse:** search and filter without a password, download matching records,
  and optionally view product images.
- **Add:** use the addition password to register a new product or restock an
  existing one. Enter the quantity and the person recording the addition.
  New products receive a permanent ID automatically. A GitHub pull request is
  created; stock changes only after it is approved and **merged**.
- **Edit:** use the addition password to correct an existing product's description,
  classification, manufacturer, model or specifications. Enable **Correct box,
  bag or quantities** to correct those fields. Enter who recorded the correction
  and why. The ID stays fixed. Corrections also require a merged pull request.
  Find the record with **Find in box** and **Find in bag**. Either filter can be
  left on All; bag numbers sort numerically and match zero-padded labels such as
  `01` and `1` without changing the stored labels. The matching contents appear
  in a table and the product dropdown contains only those matches. Products sharing
  a bag remain separate. When a box or bag is selected, stock correction is enabled
  by default and limited to the matching locations of the selected product. Clear
  both filters to find catalog records with no registered stock location.
- **Withdraw:** use the shared withdrawal password, select a product and its box
  and bag, and enter the quantity, project and person recording it. The balance and movement
  are saved immediately in one GitHub commit, without waiting for approval.
- **Purchases:** view and download the full shared quotation list without a password.
  To submit a request, use the same password as Withdraw. Requests are saved directly
  in GitHub and appear in the shared list immediately, without a pull request.
- **History:** view withdrawals without a password, filter by project, see product
  totals and inspect individual movements. Download selected history as CSV;
  choose **All projects** for the complete log.

### Withdrawals by project

`movements.csv` is the separate withdrawal ledger. Each withdrawal is recorded in
the same commit as its stock reduction, retaining project, person, quantity, product
code, box, bag, UTC timestamp and remaining balance. **History** reads this ledger;
it does not infer withdrawals from current balances or the old `usage_log.csv`.
New withdrawals require **Project**. Older entries without a project remain unchanged
and can be selected under **No project recorded**. Existing project/note text is
preserved as entered; the app does not guess project assignments.

The history shows product totals separately for each project, followed by individual
withdrawals. Current catalog descriptions are shown as a convenience; codes remain
visible even if a product is missing from the catalog or its ID is ambiguous.
Descriptions are not historical snapshots. Product totals count units withdrawn,
not current stock or purchases, and never combine distinct product IDs.

**Refresh withdrawal history** clears its 15-second read cache. Saving a withdrawal
also clears both history and stock caches. Without GitHub, the view identifies its
local snapshot; a failed history read shows an error rather than an empty report.

### Purchase requests and quotations

Use **Purchases** to request items from Amazon, Temu, AliExpress, MicroJPM or any
other supplier. **Description**, **Quantity requested**, **Project**, **Requested by**
and **Product link** are required. Paste an HTTP or HTTPS link to the exact product
or variant. Manufacturer, model/variant and specifications/notes are optional.
Project is required for purchases even when it is implied by an inventory box.
No additional secret is needed: **Withdrawal password** authorizes purchase requests.

The full list keeps every request, its project, requester, quantity and product link.
Requests for the same product remain separate so project allocations are retained.
**Download full quotation list (CSV)** exports all requests with English column names,
ready to open in a spreadsheet for quotation work. Links are clickable in the app.
User-entered spreadsheet formulas are exported as text. **Refresh purchase list**
fetches the latest GitHub list; reads otherwise use a 15-second cache. Saving a
request clears that cache. The screen does not poll automatically.

This records purchase requests, not orders, approvals or additions to physical stock.
There is no automatic deletion or purchased-status workflow. Use **Request another
purchase** after success. Retry the same form and data after an uncertain write;
its UUID prevents duplicate requests. Concurrent submissions preserve one another.
The CSV and requester/project information are public, like the inventory repository.
The legacy `to_buy.csv` is independent and is not automatically imported, since its
old rows lack project and requester information.

For a new product, **Type** and **Subtype** are dropdowns populated from the approved
catalog. Subtypes depend on the selected type. Choose **Create new…** to enter a
missing type or subtype. New choices become shared options after the addition is
merged. **Manufacturer** is optional: search existing names or type a new name
and press Enter.

**Box** also supports searching existing boxes or entering a new one with Enter.
**Bag** is a nonnegative integer. An occupied bag produces a warning that allows
you to continue: different products can share a bag while retaining separate IDs.
New boxes become shared options after the addition is merged.

When restocking an existing product, its box and bag are reused automatically.
If several combinations are already registered, choose among those. A new box
and bag are requested only when the product has no registered stock location yet.

**Recorded by** means the person adding units, making a withdrawal or requesting
a correction. Enter a name or initials; this is not the item's owner or project
owner. The password authorizes the operation, while this field records who did it.
**Project or note** on additions is optional. **Project** is required for new withdrawals
and purchase requests so they can be tracked by project. Names and notes are stored in the public
repository; enter only the information needed for the record.

Different bags or physical characteristics mean separate product records. Similar
names or old codes do not establish that products are identical. Different products,
such as two-relay and four-relay modules, can share a box and bag without being merged.

Withdrawals are blocked for ambiguous product IDs, duplicate box/bag records,
invalid balances or insufficient stock. Other inventory remains available.

## Enable the protected forms

Create a fine-grained GitHub token limited to `DeltaLabo/inventory`, with
**Contents: Read and write** and **Pull requests: Read and write** permissions.
Its account needs access to create branches, pull requests and ID reservation
tags, and update the configured inventory branch. A repository deploy key does
not replace this token: the app uses the GitHub API.

Repository rules must permit the immediate withdrawal commits. If every change
to `main` must go through a pull request, adjust the deployment or workflow first.

In the Streamlit app settings, add these entries under **Secrets** using your own
values for the placeholders:

```toml
GITHUB_TOKEN = "YOUR_PRIVATE_GITHUB_TOKEN"
INVENTORY_REPOSITORY = "DeltaLabo/inventory"
INVENTORY_BRANCH = "main"
INVENTORY_ADD_PASSWORD = "YOUR_ADDITION_PASSWORD"
INVENTORY_WITHDRAW_PASSWORD = "YOUR_SHARED_WITHDRAWAL_PASSWORD"
```

Choose different passwords. Share the withdrawal password with laboratory users
as needed. Keep the token private and give the addition password only to people
authorized to submit additions and edits. Never enter the token in an app form.
For local use, put these settings in `.streamlit/secrets.toml`, which is excluded
from Git. Environment variables with the same names take precedence.
Never reuse the old published password or use the placeholders literally.

Without a token, Browse uses the local CSV snapshot and protected forms are
disabled. With a token, the app reads the configured GitHub branch and caches a
snapshot for 15 seconds. **Refresh stock** clears that read cache and fetches
GitHub again; it does not change quantities or record movements. A successful
withdrawal also clears the cache. The cache lifetime applies to the next read;
the screen does not poll or refresh automatically in the background.
If GitHub cannot be read, the app shows the local snapshot with a warning and
disables writes.

If saving fails with an uncertain result, retry the same form with the same data.
Its request ID allows an already saved operation to be recovered without duplication.
After success, use **Record another addition**, **Record another withdrawal** or
**Edit another product** for a different operation. Reloading the browser or opening
another session starts new requests: check the records before repeating an operation
whose outcome is unknown.

## Review additions and corrections

Follow the link returned by the app to review the pull request. Check the product
details, person recording it, box, bag and quantities; approve and merge to accept.
Use restocking for more units of an existing product so its ID is retained.

New product IDs contain **four random uppercase letters and four digits**, for
example `KQZT1026`. The digits indicate the month and year the ID was assigned in
Costa Rica (`1026` means October 2026), not the purchase or manufacturing date.
The ID stays fixed when details change or a new month begins. The app checks existing
codes and atomically reserves a GitHub tag `inventory-ids/<code>` to avoid collisions
between pending or simultaneous submissions. Keep these tags; reserved IDs are
never reused. Request and movement IDs are separate UUIDs.

On October 22, 2026, 186 active codes were migrated to this format, retaining the
two relay IDs already assigned. The optional `previous_code` field preserves old
references for searching and image lookup. Similar codes were not merged. Nine
stock records without catalog entries received separate incomplete catalog records.
All 177 stock rows, boxes, bags and quantities were preserved.

Addition proposals save catalog/stock changes on a separate branch and a receipt
in `requests/<id>.json`. They do not change `main` until merged. A closed, unmerged
request does not add stock. If other changes affect the same stock row, resolve
the merge conflict against current balances, adding the requested units without
replacing later withdrawals with an old balance.

Corrections use `inventory/edit-<id>` branches. Receipts include the previous and
proposed values and a required reason. Only fields changed in the form are replaced;
unchanged fields are retained. The app compares changed fields against the latest
data before creating the proposal. If they have changed since the form was opened,
select the product again and review the updated values. IDs cannot be changed and
stock rows cannot be merged automatically. Check later withdrawals when resolving
any merge conflict involving quantities.

## Data files and validation

- `details.csv`: product records with unique permanent codes. Keep codes as text.
  `previous_code` is an optional historical reference, never a merge key; multiple
  distinct products can share it. Leave it empty for new products.
- `locations.csv`: one row per product code, box and bag. `units` is the current
  available quantity, a nonnegative integer. Additions increase it and withdrawals
  decrease it. There is no separate `available` stock column. Internal
  column names remain `location` and `sublocation` for compatibility.
- `to_buy.csv`: an independent shopping list.
- `purchase_requests.csv`: shared purchase requests with UUID, UTC timestamp,
  description, manufacturer, model, quantity, required project and requester, product
  link and optional notes. Saved directly to GitHub without changing inventory stock.
- `smd.csv` and `not_found.csv`: auxiliary lists awaiting reconciliation. They keep
  their old references and are not imported automatically or used to change stock.
- `usage_log.csv`: historical records retained as entered. They do not explain all
  current balances and must not be used to recalculate stock.
- `movements.csv`: created in GitHub on the first withdrawal. It records the request
  ID, UTC timestamp, product, box, bag, quantity, person, project and remaining balance.
  It is committed atomically with the stock update.
- `requests/`: receipts for additions and corrections, incorporated when each PR merges.

The single-quantity migration used each old `available` value as the new `units`,
preserving remaining balances, zeroes, product IDs and box/bag labels. It did not
restore quantities already withdrawn or infer unknown quantities. Readers also
accept the old two-column stock format, taking `available` as the current balance;
subsequent stock writes produce the single-quantity format. Refresh an edit form
opened before this migration before correcting stock. Review any older pending
stock PR against the latest balances and keep only the current `units` column
when resolving merge conflicts.

The historical ledger field `available_after` is retained for compatibility and
shown as **Units after withdrawal**. It records the remaining quantity at the time
of that movement, not a second live stock balance. Existing movements and receipts
are preserved.

Validate CSV changes with:

```powershell
python inventory.py
```

Validation reports unresolved data and exits with code 1 while issues remain.
**Data to review** displays the same issues only under **Edit**. Products without
a box or bag retain blank, unknown quantities rather than zero. Stock without a
catalog record remains visible as **Unclassified**. Duplicate catalog codes are
marked ambiguous without multiplying stock rows.

Missing descriptions, specifications and balances require physical evidence.
Do not invent them to clear warnings. User-authorized provisional counts carry an
information note beginning with `Provisional count:` and remain flagged until
verified. Older notes with the original Spanish prefix are also recognized so
pending requests do not silently lose their warnings.

Two relay variants currently share box A, bag 12: `GPQM1026` is the four-relay
module with 4 provisional units, and `SINW1026` is the two-relay module with 2
provisional units. The user authorized this temporary allocation; a physical count
is still needed. Update the balances and provisional notes after confirmation.

The app never writes inventory CSVs to Streamlit's temporary disk. GitHub stores
all changes. Withdrawals recheck the latest balance, affect one box/bag and retry
concurrent updates without forcing Git history. Additions and corrections use
independent review branches. These operations do not rewrite historical withdrawals.

## Images

Images are optional and come from `DeltaLabo/inventory_pictures`, directory
`inventory_images_ready`, using PNG or JPG filenames matching a product code.
If the current code has no image, the app tries `previous_code` to retain existing
photos. Enable **Show images** to display up to 12 products per page. Lookups have
bounded timeouts and are cached for one hour.

## Checks and maintenance

```powershell
python -m unittest discover -s tests -v
```

Tests mock GitHub and never submit real pull requests or stock movements. They cover
passwords, forms, approval, retries and concurrent withdrawals; category creation,
manufacturer and box suggestions, nonblocking occupied-bag warnings, automatic
restocking locations, random ID reservations, legacy searches/images, and provisional
count warning compatibility.
Purchase checks also cover required projects and links, use of the withdrawal
password, full quotation exports, safe spreadsheet text, concurrent submissions,
retry recovery, read failures and preservation of physical inventory.

Use English for the interface, documentation and maintained descriptive inventory
text. Preserve product identifiers, brands, links, physical box/bag labels and audit
history as recorded. Previous application versions remain in Git history.

Configuration references: [Streamlit secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
[GitHub trees](https://docs.github.com/en/rest/git/trees),
[GitHub references](https://docs.github.com/en/rest/git/refs).
