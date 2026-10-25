"""Read-only CSV catalog helpers. Importing this module never writes data."""

from pathlib import Path
from io import StringIO

import pandas as pd


DETAIL_COLUMNS = ("code", "type", "subtype", "manufacturer", "model", "description", "value", "package", "info")
LOCATION_COLUMNS = ("code", "location", "sublocation", "units")


def load_data(root):
    return tuple(
        _parse_frame((Path(root) / name).read_text(encoding="utf-8-sig"), name, columns)
        for name, columns in (("details.csv", DETAIL_COLUMNS), ("locations.csv", LOCATION_COLUMNS))
    )


def _parse_frame(text, name, columns):
    frame = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False)
    if name == "locations.csv" and "available" in frame.columns:
        # Legacy files store the current balance in available, not units.
        frame["units"] = frame["available"]
        frame = frame.drop(columns="available")
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: missing columns: {', '.join(sorted(missing))}")
    for column in columns:
        frame[column] = frame[column].str.strip()
    return frame


def parse_data(details_text, locations_text):
    return tuple(_parse_frame(text, name, columns) for text, name, columns in (
        (details_text, "details.csv", DETAIL_COLUMNS),
        (locations_text, "locations.csv", LOCATION_COLUMNS),
    ))


def validate_data(details, locations):
    issues = []
    for code in details.loc[details["code"].duplicated(keep=False), "code"].unique():
        issues.append(f"Duplicate catalog code: {code}. Confirm product identity before using its stock.")
    for code in sorted(set(locations["code"]) - set(details["code"])):
        issues.append(f"{code}: has stock but no catalog record.")
    for code in sorted(set(details["code"]) - set(locations["code"])):
        issues.append(f"{code}: no registered box, bag or stock.")
    for column in ("code", "type", "subtype", "description"):
        for index in details.index[details[column].eq("")]:
            issues.append(f"Catalog, record {index + 1} ({details.at[index, 'code']}): missing {column}.")
    numeric = locations[["units"]].apply(pd.to_numeric, errors="coerce")
    valid = numeric.notna().all(axis=1) & numeric.ge(0).all(axis=1)
    valid &= numeric.mod(1).eq(0).all(axis=1)
    for index in locations.index[~valid]:
        issues.append(f"{locations.at[index, 'code']}: invalid quantities in box {locations.at[index, 'location']} / bag {locations.at[index, 'sublocation']}.")
    for index in locations.index[locations[["code", "location", "sublocation"]].eq("").any(axis=1)]:
        issues.append(f"Stock, record {index + 1}: missing code, box or bag.")
    repeated = locations.duplicated(["code", "location", "sublocation"], keep=False)
    for code in locations.loc[repeated, "code"].unique():
        issues.append(f"{code}: duplicate box and bag; verify quantities.")
    # Recognize older notes too, including pending requests created before translation.
    for code in details.loc[details["info"].str.startswith(("Provisional count:", "Conteo provisional:")), "code"]:
        issues.append(f"{code}: provisional count; verify quantities with a physical count and update the record note.")
    return issues


def build_inventory(details, locations):
    # Combine display values for ambiguous codes, then join each stock row once.
    # This does not resolve or alter the underlying product identities.
    def distinct_values(values):
        return " / ".join(dict.fromkeys(value for value in values if value))

    catalog = details.groupby("code", as_index=False, sort=False).agg(distinct_values)
    merged = catalog.merge(locations, on="code", how="outer", indicator=True)
    merged["status"] = merged["_merge"].astype(str).map({
        "left_only": "No box or bag; quantity unknown",
        "right_only": "No catalog record; check code", "both": "",
    })
    merged = merged.drop(columns="_merge").fillna("")
    duplicates = set(details.loc[details["code"].duplicated(keep=False), "code"])
    merged.loc[merged["code"].isin(duplicates), "status"] = "Code is ambiguous; verify record and stock"
    merged["type"] = merged["type"].replace("", "Unclassified")
    merged["subtype"] = merged["subtype"].replace("", "Unclassified")
    merged["description"] = merged["description"].replace("", "Description missing")
    return merged.sort_values(["code", "location", "sublocation"], kind="stable").reset_index(drop=True)


def bag_key(value):
    """Compare numeric bag labels without changing their stored text."""
    return str(int(value)) if value.isascii() and value.isdigit() else value


def filter_inventory(inventory, search="", item_type="All", subtype="All", box=None, bag=None):
    result = inventory
    if item_type != "All":
        result = result[result["type"].eq(item_type)]
    if subtype != "All":
        result = result[result["subtype"].eq(subtype)]
    if box is not None:
        result = result[result["location"].eq(box)]
    if bag is not None:
        result = result[result["sublocation"].map(bag_key).eq(bag_key(bag))]
    if result.empty:
        return result
    term = search.strip().casefold()
    if term:
        text = result.astype(str).agg(" ".join, axis=1).str.casefold()
        result = result[text.str.contains(term, regex=False, na=False)]
    return result


def spreadsheet_csv(frame):
    """Export entered values as text rather than executable spreadsheet formulas."""
    frame = frame.copy()
    for column in frame:
        frame[column] = frame[column].map(
            lambda value: "'" + str(value) if str(value).lstrip().startswith(("=", "+", "-", "@")) else value
        )
    return frame.to_csv(index=False).encode("utf-8-sig")


if __name__ == "__main__":
    import sys
    from scripts.paths import DATA_DIR

    try:
        details, locations = load_data(DATA_DIR)
        issues = validate_data(details, locations)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"Could not validate: {error}")
        sys.exit(1)
    for issue in issues:
        print(issue)
    if not issues:
        print("Inventory is valid.")
    sys.exit(1 if issues else 0)
