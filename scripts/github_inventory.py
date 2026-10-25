"""GitHub-backed inventory changes. No local CSVs or credentials are written."""

import base64
import csv
import json
from datetime import datetime, timezone
from io import StringIO
import re
import secrets
import string
from urllib.parse import quote, urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from scripts.inventory import DETAIL_COLUMNS, LOCATION_COLUMNS, parse_data
from scripts.assistants import assistant_name


MOVEMENT_COLUMNS = (
    "id", "timestamp", "code", "location", "sublocation", "quantity",
    "person", "project", "available_after",
)
EDITABLE_FIELDS = tuple(name for name in DETAIL_COLUMNS if name != "code")
PURCHASE_COLUMNS = (
    "id", "timestamp", "description", "manufacturer", "model", "quantity",
    "project", "person", "link", "notes",
)


def new_product_code(existing_codes, issued_at=None):
    """Four random uppercase letters plus registration month/year, never a name."""
    issued_at = issued_at or datetime.now(ZoneInfo("America/Costa_Rica"))
    suffix = issued_at.strftime("%m%y")
    occupied = set(existing_codes)
    for _ in range(100):
        code = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4)) + suffix
        if code not in occupied:
            return code
    raise ValueError("Could not assign an unused product ID. Please try again.")


class GitHubError(Exception):
    pass


class Conflict(GitHubError):
    pass


def positive_integer(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
        raise ValueError("Quantity must be a positive integer.")
    return int(value)


def required(value, label, limit=300):
    value = str(value).strip()
    if not value or len(value) > limit or any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{label}: enter a single-line value (maximum {limit} characters).")
    return value


def read_rows(text, columns):
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if not set(columns).issubset(reader.fieldnames or []):
        raise ValueError("The inventory file is missing required columns.")
    rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("Some rows have extra columns; correct the CSV before submitting changes.")
    # Preserve all existing fields and text, including optional extra columns.
    fields = list(reader.fieldnames)
    rows = [{key: value or "" for key, value in row.items()} for row in rows]
    if tuple(columns) == LOCATION_COLUMNS and "available" in fields:
        # Normalize old snapshots/proposals before any stock operation.
        fields.remove("available")
        for row in rows:
            row["units"] = row.pop("available")
    return fields, rows


def write_rows(columns, rows):
    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def unique_product(details, code):
    matches = [row for row in details if row["code"].strip() == code]
    if len(matches) != 1:
        raise ValueError("The product does not exist or its code is ambiguous. Review the catalog first.")
    return matches[0]


def stock_units(row):
    value = row["units"].strip()
    if not value.isascii() or not value.isdigit():
        raise ValueError("Stock counts for this box and bag need review.")
    return int(value)


class GitHubInventory:
    def __init__(self, token, repository="DeltaLabo/inventory", branch="main"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("The repository must use the owner/name format.")
        self.token = token
        self.repository = repository
        self.branch = branch
        self.base = f"https://api.github.com/repos/{repository}"

    def _request(self, method, path, *, payload=None, params=None, optional=False):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = requests.request(
                method, self.base + path, headers=headers, json=payload,
                params=params, timeout=(5, 20),
            )
        except requests.RequestException:
            raise GitHubError("GitHub did not confirm the operation. Retry the same form; an already saved operation will not be duplicated.") from None
        if optional and response.status_code == 404:
            return None
        if response.status_code in (409, 422):
            raise Conflict("Inventory changed or GitHub rejected the change. Refresh and try again.")
        if not 200 <= response.status_code < 300:
            raise GitHubError(f"Could not complete the GitHub operation (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise GitHubError("GitHub returned an invalid response. Retry the same form.") from None

    def head(self, branch=None, optional=False):
        ref = quote(branch or self.branch, safe="/")
        result = self._request("GET", f"/git/ref/heads/{ref}", optional=optional)
        return result["object"]["sha"] if result else None

    def read_file(self, path, sha, optional=False):
        result = self._request("GET", f"/contents/{quote(path, safe='/')}", params={"ref": sha}, optional=optional)
        if result is None:
            return None
        if result.get("encoding") != "base64":
            raise GitHubError("The file exceeds the size supported by this app.")
        try:
            return base64.b64decode(result["content"]).decode("utf-8-sig")
        except (ValueError, UnicodeError):
            raise GitHubError("The file is not valid UTF-8 text.") from None

    def snapshot(self):
        sha = self.head()
        return parse_data(self.read_file("data/details.csv", sha), self.read_file("data/locations.csv", sha))

    def purchase_snapshot(self):
        text = self.read_file("data/purchase_requests.csv", self.head(), optional=True)
        return read_rows(text, PURCHASE_COLUMNS)[1] if text is not None else []

    def withdrawal_snapshot(self):
        text = self.read_file("data/movements.csv", self.head(), optional=True)
        return read_rows(text, MOVEMENT_COLUMNS)[1] if text is not None else []

    def request_purchase(self, request_id, description, quantity, project, person, link,
                         manufacturer="", model="", notes=""):
        operation = UUID(request_id).hex
        link = required(link, "Product link", 2000)
        try:
            url = urlsplit(link)
            valid_link = (url.scheme in ("http", "https") and bool(url.hostname)
                          and not url.username and not url.password
                          and not any(c.isspace() for c in link))
            url.port  # Reject malformed port numbers too.
        except ValueError:
            valid_link = False
        if not valid_link:
            raise ValueError("Product link must be a valid http:// or https:// URL without spaces or login details.")
        expected = {
            "id": operation, "description": required(description, "Description"),
            "quantity": str(positive_integer(quantity)), "project": required(project, "Project"),
            "person": required(person, "Requested by", 100), "link": link,
        }
        for name, value in (("manufacturer", manufacturer), ("model", model), ("notes", notes)):
            expected[name] = required(value, name.title()) if str(value).strip() else ""
        for attempt in range(3):
            parent = self.head()
            text = self.read_file("data/purchase_requests.csv", parent, optional=True)
            columns, rows = read_rows(text, PURCHASE_COLUMNS) if text is not None else (list(PURCHASE_COLUMNS), [])
            previous = next((row for row in rows if row["id"] == operation), None)
            if previous:
                if any(previous[key] != value for key, value in expected.items()):
                    raise ValueError("This request was already recorded with different details. Start another purchase request.")
                return operation
            rows.append(dict.fromkeys(columns, "") | expected | {
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            commit = self._commit(parent, {
                "data/purchase_requests.csv": write_rows(columns, rows),
            }, f"Record purchase request {operation}")
            try:
                self._request("PATCH", f"/git/refs/heads/{quote(self.branch, safe='/')}",
                              payload={"sha": commit, "force": False})
                return operation
            except Conflict:
                if attempt == 2:
                    raise

    def _commit(self, parent, changes, message):
        commit = self._request("GET", f"/git/commits/{parent}")
        tree = self._request("POST", "/git/trees", payload={
            "base_tree": commit["tree"]["sha"],
            "tree": [
                {"path": path, "mode": "100644", "type": "blob", "content": content}
                for path, content in changes.items()
            ],
        })
        result = self._request("POST", "/git/commits", payload={
            "message": message, "tree": tree["sha"], "parents": [parent],
        })
        return result["sha"]

    def _reserve_product_code(self, parent, occupied):
        # An atomic Git ref creation arbitrates collisions between concurrent
        # submissions, including IDs on PRs that have not been merged yet.
        occupied = set(occupied)
        for _ in range(100):
            code = new_product_code(occupied)
            ref = f"tags/inventory-ids/{code}"
            try:
                self._request("POST", "/git/refs", payload={"ref": f"refs/{ref}", "sha": parent})
                return code
            except Conflict:
                if self._request("GET", f"/git/ref/{ref}", optional=True) is None:
                    raise
                occupied.add(code)
        raise ValueError("Could not reserve an unused product ID. Please try again.")

    def add(self, request_id, item, quantity, location, sublocation, person, project="", existing_code=None):
        product = {name: str(item.get(name, "")).strip() for name in DETAIL_COLUMNS if name != "code"}
        if existing_code is None:
            for name in ("description", "type", "subtype"):
                required(product[name], name.title())
        submission = {
            "action": "addition", "item": product if existing_code is None else None,
            "quantity": positive_integer(quantity), "location": required(location, "Box", 80),
            "sublocation": required(sublocation, "Bag", 80), "person": required(person, "Recorded by", 100),
            "project": str(project).strip()[:300], "existing_code": existing_code,
        }
        return self._save_change(request_id, submission)

    def edit(self, request_id, code, original_item, updated_item, person, reason,
             original_stock=None, updated_stock=None):
        if original_stock and "available" in original_stock:
            raise ValueError("The stock format changed. Refresh the page before editing quantities.")
        submission = {
            "action": "edit", "code": required(code, "Product code", 80),
            "original_item": {name: str(value).strip() for name, value in original_item.items()},
            "updated_item": {name: str(value).strip() for name, value in updated_item.items()},
            "person": required(person, "Recorded by", 100), "reason": required(reason, "Reason for correction"),
            "original_stock": {name: str(value).strip() for name, value in original_stock.items()} if original_stock else None,
            "updated_stock": {name: str(value).strip() for name, value in updated_stock.items()} if updated_stock is not None else None,
        }
        return self._save_change(request_id, submission)

    def _save_change(self, request_id, submission):
        from scripts.request_application import request_changes

        operation = UUID(request_id).hex
        receipt_path = f"data/requests/{operation}.json"
        code = submission.get("existing_code") or submission.get("code")
        for attempt in range(5):
            parent = self.head()
            previous = self.read_file(receipt_path, parent, optional=True)
            if previous is not None:
                saved = json.loads(previous)
                if saved.get("schema_version") != 3:
                    raise ValueError("This operation belongs to an older request. Start another operation; its stock will not be counted twice.")
                if saved.get("submission") != submission:
                    raise ValueError("This operation was already saved with different details. Start another operation.")
                return saved["result"]
            details_text = self.read_file("data/details.csv", parent)
            locations_text = self.read_file("data/locations.csv", parent)
            if submission["action"] == "addition":
                columns, details = read_rows(details_text, DETAIL_COLUMNS)
                _, locations = read_rows(locations_text, LOCATION_COLUMNS)
                if code is None:
                    code = self._reserve_product_code(parent, {row["code"].strip() for row in details + locations})
                product = None
                if submission["existing_code"] is None:
                    product = dict.fromkeys(columns, "") | submission["item"] | {"code": code}
                change = {"id": operation, "action": "addition", "code": code,
                          **{name: submission[name] for name in ("quantity", "location", "sublocation", "person", "project", "existing_code")},
                          "item": product}
            else:
                if submission["original_item"].get("code") != code:
                    raise ValueError("The original product ID does not match the selected product.")
                audit = {}
                for name, value in submission["updated_item"].items():
                    if name not in EDITABLE_FIELDS:
                        raise ValueError("The product ID cannot be edited.")
                    before = submission["original_item"].get(name, "")
                    if value != before:
                        audit[name] = {"before": before, "after": value}
                stock_audit = {}
                if submission["updated_stock"] is not None:
                    original = submission["original_stock"]
                    if not original or original.get("code") != code:
                        raise ValueError("Select the original box and bag for the product.")
                    for name, value in submission["updated_stock"].items():
                        if name not in ("location", "sublocation", "units"):
                            raise ValueError("The product ID cannot be edited.")
                        if value != original[name]:
                            stock_audit[name] = {"before": original[name], "after": value}
                change = {"id": operation, "action": "edit", "code": code, "person": submission["person"],
                          "reason": submission["reason"], "product_changes": audit, "stock_changes": stock_audit,
                          "original_location": submission["original_stock"]}
            changes = request_changes(change, details_text, locations_text)
            result = {"id": operation, "code": code, "action": submission["action"]}
            if submission["action"] == "addition":
                result["quantity"] = submission["quantity"]
            changes[receipt_path] = json.dumps({
                "schema_version": 3, "status": "applied", "id": operation,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "submission": submission, "request": change, "result": result,
            }, ensure_ascii=False, indent=2) + "\n"
            commit = self._commit(parent, changes, f"Save inventory {submission['action']} {operation}: {code}")
            try:
                self._request("PATCH", f"/git/refs/heads/{quote(self.branch, safe='/')}", payload={"sha": commit, "force": False})
                return result
            except Conflict:
                if attempt == 4:
                    raise

    def withdraw(self, request_id, code, location, sublocation, quantity, person, project="", *, assistant_id=None):
        operation = UUID(request_id).hex
        quantity = positive_integer(quantity)
        person = required(person, "Recorded by", 100)
        location = required(location, "Box", 80)
        sublocation = required(sublocation, "Bag", 80)
        project = str(project).strip()[:300]
        expected = {"id": operation, "code": code, "location": location, "sublocation": sublocation,
                    "quantity": str(quantity), "person": person, "project": project}
        if assistant_id is not None:
            expected["assistant_id"] = required(assistant_id, "Assistant ID", 100)
        for attempt in range(3):
            parent = self.head()
            history_text = self.read_file("data/movements.csv", parent, optional=True)
            columns, history = read_rows(history_text, MOVEMENT_COLUMNS) if history_text is not None else (list(MOVEMENT_COLUMNS), [])
            previous = next((row for row in history if row["id"] == operation), None)
            if previous:
                if any(previous.get(key, "") != value for key, value in expected.items()):
                    raise ValueError("This request was already recorded with different details. Start another withdrawal.")
                return int(previous["available_after"])
            required(project, "Project")
            assistant_name(assistant_id, person)
            if "assistant_id" not in columns:
                columns.append("assistant_id")
            _, details = read_rows(self.read_file("data/details.csv", parent), DETAIL_COLUMNS)
            unique_product(details, code)
            location_columns, locations = read_rows(self.read_file("data/locations.csv", parent), LOCATION_COLUMNS)
            matches = [row for row in locations if (row["code"].strip(), row["location"].strip(), row["sublocation"].strip()) == (code, location, sublocation)]
            if len(matches) != 1:
                raise ValueError("The box and bag combination does not exist or is duplicated. Review inventory first.")
            units = stock_units(matches[0])
            if quantity > units:
                raise ValueError(f"Only {units} units are available in this box and bag.")
            remaining = units - quantity
            matches[0]["units"] = str(remaining)
            history.append(dict.fromkeys(columns, "") | expected | {
                "timestamp": datetime.now(timezone.utc).isoformat(), "available_after": str(remaining),
            })
            commit = self._commit(parent, {
                "data/locations.csv": write_rows(location_columns, locations),
                "data/movements.csv": write_rows(columns, history),
            }, f"Record withdrawal {operation}: {code} (-{quantity})")
            try:
                self._request("PATCH", f"/git/refs/heads/{quote(self.branch, safe='/')}", payload={"sha": commit, "force": False})
                return remaining
            except Conflict:
                # Another writer may have changed main. Re-read balances and the
                # operation ID before recomputing, never force-push a stale balance.
                if attempt == 2:
                    raise
        raise GitHubError("Could not save the withdrawal. Please try again.")
