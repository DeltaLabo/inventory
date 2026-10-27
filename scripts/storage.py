"""Storage registry and removal previews. Historical ledgers are never changed."""

import json

from scripts.inventory import bag_key


STORAGE_COLUMNS = ("location", "sublocation")


def storage_rows(registered, locations):
    """Include existing occupied storage without requiring a data migration."""
    result = {}
    for row in [*registered, *locations]:
        box, bag = row["location"], row["sublocation"]
        if box:
            result.setdefault((box, ""), {"location": box, "sublocation": ""})
            if bag:
                result.setdefault((box, bag_key(bag)), {"location": box, "sublocation": bag})
    return list(result.values())


def removal_preview(snapshot, action, target):
    if action not in ("delete_product", "delete_box", "delete_bag", "delete_stock"):
        raise ValueError("Select a valid removal action.")
    code, box, bag = (target.get(key, "") for key in ("code", "location", "sublocation"))
    if ((action in ("delete_product", "delete_stock") and not code)
            or (action != "delete_product" and not box)
            or (action in ("delete_bag", "delete_stock") and not bag)):
        raise ValueError("Select the device, box and bag required for this removal.")

    def matches(row):
        if action == "delete_product":
            return row["code"] == code
        return (row["location"] == box
                and (action == "delete_box" or bag_key(row["sublocation"]) == bag_key(bag))
                and (action != "delete_stock" or row["code"] == code))

    affected = {
        "details": [row for row in snapshot["details"] if action == "delete_product" and row["code"] == code],
        "locations": [row for row in snapshot["locations"] if matches(row)],
        "storage": [row for row in snapshot["storage"] if action in ("delete_box", "delete_bag") and matches(row)],
    }
    if not any(affected.values()):
        raise ValueError("The selected record no longer exists. Refresh the preview.")
    # Stable equality ignores CSV row order while retaining every field and duplicate.
    return {name: sorted(rows, key=lambda row: json.dumps(row, sort_keys=True)) for name, rows in affected.items()}
