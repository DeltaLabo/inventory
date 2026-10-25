"""Calculate an addition or edit against current data without writing anything."""

import re

from scripts.github_inventory import EDITABLE_FIELDS, positive_integer, read_rows, required, stock_units, unique_product, write_rows
from scripts.inventory import DETAIL_COLUMNS, LOCATION_COLUMNS


def request_changes(request, details_text, locations_text):
    detail_columns, details = read_rows(details_text, DETAIL_COLUMNS)
    location_columns, locations = read_rows(locations_text, LOCATION_COLUMNS)
    code = required(request.get("code", ""), "Product code", 80)
    required(request.get("person", ""), "Recorded by", 100)
    changes = {}
    if request["action"] == "addition":
        quantity = positive_integer(request["quantity"])
        location = required(request["location"], "Box", 80)
        sublocation = required(request["sublocation"], "Bag", 80)
        if request.get("existing_code") is None:
            if not re.fullmatch(r"[A-Z]{4}[0-9]{4}", code):
                raise ValueError("New product ID has an invalid format.")
            if any(row["code"].strip() == code for row in details + locations):
                raise ValueError("The new product ID is already registered. Review the request; stock was not added.")
            item = request["item"]
            if item.get("code") != code:
                raise ValueError("The requested product ID does not match its record.")
            product = {name: str(item.get(name, "")).strip() for name in detail_columns}
            for name in ("description", "type", "subtype"):
                required(product[name], name.title())
            details.append(product)
            changes["data/details.csv"] = write_rows(detail_columns, details)
        else:
            if request["existing_code"] != code:
                raise ValueError("The requested restock product ID does not match.")
            unique_product(details, code)
        matches = [row for row in locations if (row["code"].strip(), row["location"].strip(), row["sublocation"].strip()) == (code, location, sublocation)]
        if len(matches) > 1:
            raise ValueError("The requested box and bag are duplicated. Review the stock rows.")
        if request.get("existing_code") and not matches and any(row["code"].strip() == code for row in locations):
            raise ValueError("The product box or bag changed after submission. Review the request before applying it.")
        if matches:
            matches[0]["units"] = str(stock_units(matches[0]) + quantity)
        else:
            locations.append(dict.fromkeys(location_columns, "") | {
                "code": code, "location": location, "sublocation": sublocation, "units": str(quantity),
            })
        changes["data/locations.csv"] = write_rows(location_columns, locations)
    elif request["action"] == "edit":
        required(request.get("reason", ""), "Reason for correction")
        product = unique_product(details, code)
        audit = request.get("product_changes", {})
        for name, delta in audit.items():
            if name not in EDITABLE_FIELDS:
                raise ValueError("Product IDs and historical aliases cannot be edited by a request.")
            if product[name].strip() != str(delta["before"]).strip():
                raise ValueError(f"The record changed after you opened the form ({name}). Select the product again before editing.")
            product[name] = str(delta["after"]).strip()
        if audit:
            for name in ("description", "type", "subtype"):
                required(product[name], name.title())
            changes["data/details.csv"] = write_rows(detail_columns, details)
        stock_audit = request.get("stock_changes", {})
        if stock_audit:
            original = request.get("original_location")
            if not original or original.get("code") != code:
                raise ValueError("The original stock location is missing or mismatched.")
            key = (code, original["location"], original["sublocation"])
            matches = [row for row in locations if tuple(row[name].strip() for name in ("code", "location", "sublocation")) == key]
            if len(matches) != 1:
                raise ValueError("The original stock location changed or is ambiguous. Review the request.")
            row = matches[0]
            for name, delta in stock_audit.items():
                if name not in ("location", "sublocation", "units"):
                    raise ValueError("Unsupported stock field in request.")
                if row[name].strip() != str(delta["before"]).strip():
                    raise ValueError(f"Stock changed after you opened the form ({name}). Select the product again before editing.")
                row[name] = str(delta["after"]).strip()
            required(row["location"], "Box", 80)
            required(row["sublocation"], "Bag", 80)
            stock_units(row)
            destination = (code, row["location"].strip(), row["sublocation"].strip())
            if any(other is not row and tuple(other[name].strip() for name in ("code", "location", "sublocation")) == destination for other in locations):
                raise ValueError("The destination already has stock for this product. Rows cannot be merged automatically.")
            changes["data/locations.csv"] = write_rows(location_columns, locations)
        if not changes:
            raise ValueError("The request has no changes to apply.")
    else:
        raise ValueError("Unsupported inventory request action.")
    return changes
