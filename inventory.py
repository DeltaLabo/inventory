"""Read-only CSV catalog helpers. Importing this module never writes data."""

from pathlib import Path
from io import StringIO

import pandas as pd


DETAIL_COLUMNS = ("code", "type", "subtype", "manufacturer", "model", "description", "value", "package", "info")
LOCATION_COLUMNS = ("code", "location", "sublocation", "units", "available")


def load_data(root):
    return tuple(
        _parse_frame((Path(root) / name).read_text(encoding="utf-8-sig"), name, columns)
        for name, columns in (("details.csv", DETAIL_COLUMNS), ("locations.csv", LOCATION_COLUMNS))
    )


def _parse_frame(text, name, columns):
    frame = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False)
    missing = set(columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{name}: faltan columnas: {', '.join(sorted(missing))}")
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
        issues.append(f"Código duplicado en catálogo: {code}. Verificar la identidad antes de usar sus existencias.")
    for code in sorted(set(locations["code"]) - set(details["code"])):
        issues.append(f"{code}: tiene existencias pero no tiene ficha de catálogo.")
    for code in sorted(set(details["code"]) - set(locations["code"])):
        issues.append(f"{code}: sin ubicación ni existencias registradas.")
    for column in ("code", "type", "subtype", "description"):
        for index in details.index[details[column].eq("")]:
            issues.append(f"Catálogo, registro {index + 1} ({details.at[index, 'code']}): falta {column}.")
    numeric = locations[["units", "available"]].apply(pd.to_numeric, errors="coerce")
    valid = numeric.notna().all(axis=1) & numeric.ge(0).all(axis=1)
    valid &= numeric.mod(1).eq(0).all(axis=1)
    valid &= numeric["available"].le(numeric["units"])
    for index in locations.index[~valid]:
        issues.append(f"{locations.at[index, 'code']}: cantidades inválidas en ubicación {locations.at[index, 'location']} / {locations.at[index, 'sublocation']}.")
    for index in locations.index[locations[["code", "location", "sublocation"]].eq("").any(axis=1)]:
        issues.append(f"Ubicaciones, registro {index + 1}: falta código, ubicación o compartimento.")
    repeated = locations.duplicated(["code", "location", "sublocation"], keep=False)
    for code in locations.loc[repeated, "code"].unique():
        issues.append(f"{code}: ubicación repetida; verificar sus cantidades.")
    return issues


def build_inventory(details, locations):
    # Combine display values for ambiguous codes, then join each stock row once.
    # This does not resolve or alter the underlying product identities.
    def distinct_values(values):
        return " / ".join(dict.fromkeys(value for value in values if value))

    catalog = details.groupby("code", as_index=False, sort=False).agg(distinct_values)
    merged = catalog.merge(locations, on="code", how="outer", indicator=True)
    merged["status"] = merged["_merge"].astype(str).map({
        "left_only": "Sin ubicación; cantidad desconocida",
        "right_only": "Sin ficha de catálogo; revisar código", "both": "",
    })
    merged = merged.drop(columns="_merge").fillna("")
    duplicates = set(details.loc[details["code"].duplicated(keep=False), "code"])
    merged.loc[merged["code"].isin(duplicates), "status"] = "Código ambiguo; verificar ficha y existencias"
    merged["type"] = merged["type"].replace("", "Sin clasificar")
    merged["subtype"] = merged["subtype"].replace("", "Sin clasificar")
    merged["description"] = merged["description"].replace("", "Descripción pendiente")
    return merged.sort_values(["code", "location", "sublocation"], kind="stable").reset_index(drop=True)


def filter_inventory(inventory, search="", item_type="Todos", subtype="Todos"):
    result = inventory
    if item_type != "Todos":
        result = result[result["type"].eq(item_type)]
    if subtype != "Todos":
        result = result[result["subtype"].eq(subtype)]
    if result.empty:
        return result
    term = search.strip().casefold()
    if term:
        text = result.astype(str).agg(" ".join, axis=1).str.casefold()
        result = result[text.str.contains(term, regex=False, na=False)]
    return result


if __name__ == "__main__":
    import sys

    try:
        details, locations = load_data(Path(__file__).resolve().parent)
        issues = validate_data(details, locations)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        print(f"No se pudo validar: {error}")
        sys.exit(1)
    for issue in issues:
        print(issue)
    if not issues:
        print("Inventario válido.")
    sys.exit(1 if issues else 0)
