"""GitHub-backed inventory changes. No local CSVs or credentials are written."""

import base64
import csv
import json
from datetime import datetime, timezone
from io import StringIO
import re
from urllib.parse import quote
from uuid import UUID

import requests

from inventory import DETAIL_COLUMNS, LOCATION_COLUMNS, parse_data


MOVEMENT_COLUMNS = (
    "id", "timestamp", "code", "location", "sublocation", "quantity",
    "person", "project", "available_after",
)


class GitHubError(Exception):
    pass


class Conflict(GitHubError):
    pass


def positive_integer(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit() or int(value) <= 0:
        raise ValueError("La cantidad debe ser un entero mayor que cero.")
    return int(value)


def required(value, label, limit=300):
    value = str(value).strip()
    if not value or len(value) > limit or any(c in value for c in "\r\n\x00"):
        raise ValueError(f"{label}: completar un valor de una sola línea (máximo {limit} caracteres).")
    return value


def read_rows(text, columns):
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if not set(columns).issubset(reader.fieldnames or []):
        raise ValueError("El archivo de inventario no tiene las columnas esperadas.")
    rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError("Hay filas con columnas de más; corregir el CSV antes de registrar cambios.")
    # Preserve all existing fields and text, including optional extra columns.
    return list(reader.fieldnames), [{key: value or "" for key, value in row.items()} for row in rows]


def write_rows(columns, rows):
    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def unique_product(details, code):
    matches = [row for row in details if row["code"].strip() == code]
    if len(matches) != 1:
        raise ValueError("El producto no existe o su código es ambiguo. Primero debe revisarse el catálogo.")
    return matches[0]


def stock_counts(row):
    values = [row[name].strip() for name in ("units", "available")]
    if any(not value.isascii() or not value.isdigit() for value in values):
        raise ValueError("Las existencias de esta ubicación requieren revisión.")
    units, available = map(int, values)
    if available > units:
        raise ValueError("Las existencias de esta ubicación requieren revisión.")
    return units, available


class GitHubInventory:
    def __init__(self, token, repository="DeltaLabo/inventory", branch="main"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("El repositorio debe tener el formato propietario/nombre.")
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
            raise GitHubError("GitHub no confirmó la operación. Reintente el mismo formulario; no se duplicará una operación ya guardada.") from None
        if optional and response.status_code == 404:
            return None
        if response.status_code in (409, 422):
            raise Conflict("El inventario cambió o GitHub rechazó el cambio. Actualice y vuelva a intentarlo.")
        if not 200 <= response.status_code < 300:
            raise GitHubError(f"No se pudo completar la operación en GitHub (HTTP {response.status_code}).")
        try:
            return response.json()
        except ValueError:
            raise GitHubError("GitHub devolvió una respuesta no válida. Reintente el mismo formulario.") from None

    def head(self, branch=None, optional=False):
        ref = quote(branch or self.branch, safe="/")
        result = self._request("GET", f"/git/ref/heads/{ref}", optional=optional)
        return result["object"]["sha"] if result else None

    def read_file(self, path, sha, optional=False):
        result = self._request("GET", f"/contents/{quote(path, safe='/')}", params={"ref": sha}, optional=optional)
        if result is None:
            return None
        if result.get("encoding") != "base64":
            raise GitHubError("El archivo supera el tamaño admitido por esta aplicación.")
        try:
            return base64.b64decode(result["content"]).decode("utf-8-sig")
        except (ValueError, UnicodeError):
            raise GitHubError("El archivo no tiene un formato de texto válido.") from None

    def snapshot(self):
        sha = self.head()
        return parse_data(self.read_file("details.csv", sha), self.read_file("locations.csv", sha))

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

    def _pull_request(self, branch):
        owner = self.repository.split("/")[0]
        prs = self._request("GET", "/pulls", params={"head": f"{owner}:{branch}", "state": "all", "per_page": 1})
        return prs[0] if prs else None

    def propose_addition(self, request_id, item, quantity, location, sublocation, person, project="", existing_code=None):
        operation = UUID(request_id).hex
        branch = f"inventory/add-{operation}"
        quantity = positive_integer(quantity)
        location = required(location, "Ubicación", 80)
        sublocation = required(sublocation, "Compartimento", 80)
        person = required(person, "Responsable", 100)
        project = str(project).strip()[:300]
        if self.head(branch, optional=True):
            previous = self._pull_request(branch)
            if previous:
                return previous["html_url"]
            # Recover a branch saved before a PR-creation timeout.
        else:
            parent = self.head()
            detail_columns, details = read_rows(self.read_file("details.csv", parent), DETAIL_COLUMNS)
            location_columns, locations = read_rows(self.read_file("locations.csv", parent), LOCATION_COLUMNS)
            changes = {}
            if existing_code:
                product = unique_product(details, existing_code)
                code = product["code"].strip()
            else:
                code = "I" + operation.upper()
                if any(row["code"].strip() == code for row in details + locations):
                    raise ValueError("El identificador ya existe. Inicie una nueva solicitud.")
                product = {name: str(item.get(name, "")).strip() for name in detail_columns}
                product["code"] = code
                for name, label in (("description", "Descripción"), ("type", "Tipo"), ("subtype", "Subtipo")):
                    product[name] = required(product[name], label)
                details.append(product)
                changes["details.csv"] = write_rows(detail_columns, details)
            matches = [row for row in locations if (row["code"].strip(), row["location"].strip(), row["sublocation"].strip()) == (code, location, sublocation)]
            if len(matches) > 1:
                raise ValueError("La ubicación está duplicada. Primero debe revisarse el inventario.")
            if matches:
                units, available = stock_counts(matches[0])
                matches[0].update(units=str(units + quantity), available=str(available + quantity))
            else:
                locations.append(dict.fromkeys(location_columns, "") | {
                    "code": code, "location": location, "sublocation": sublocation,
                    "units": str(quantity), "available": str(quantity),
                })
            changes["locations.csv"] = write_rows(location_columns, locations)
            changes[f"requests/{operation}.json"] = json.dumps({
                "id": operation, "code": code, "quantity": quantity,
                "location": location, "sublocation": sublocation,
                "person": person, "project": project,
            }, ensure_ascii=False, indent=2) + "\n"
            commit = self._commit(parent, changes, f"Proponer ingreso de {quantity} unidades: {code}")
            try:
                self._request("POST", "/git/refs", payload={"ref": f"refs/heads/{branch}", "sha": commit})
            except Conflict:
                previous = self._pull_request(branch)
                if previous:
                    return previous["html_url"]
                raise
        # The persisted request is authoritative when recovering a previous attempt.
        branch_head = self.head(branch)
        saved = json.loads(self.read_file(f"requests/{operation}.json", branch_head))
        result = self._request("POST", "/pulls", payload={
            "title": f"Ingreso de inventario: {saved['code']} (+{saved['quantity']})",
            "head": branch, "base": self.branch,
            "body": (
                f"Solicitud de ingreso enviada por {saved['person']}.\n\n"
                f"- Producto: `{saved['code']}`\n- Cantidad: {saved['quantity']}\n"
                f"- Ubicación: {saved['location']} / {saved['sublocation']}\n"
                f"- Proyecto o nota: {saved['project'] or 'Sin especificar'}\n\n"
                "Las existencias se incorporan al fusionar esta solicitud. "
                "Si hay conflictos, revisar los saldos actuales antes de fusionar."
            ),
        })
        return result["html_url"]

    def withdraw(self, request_id, code, location, sublocation, quantity, person, project=""):
        operation = UUID(request_id).hex
        quantity = positive_integer(quantity)
        person = required(person, "Responsable", 100)
        location = required(location, "Ubicación", 80)
        sublocation = required(sublocation, "Compartimento", 80)
        project = str(project).strip()[:300]
        expected = {"id": operation, "code": code, "location": location, "sublocation": sublocation,
                    "quantity": str(quantity), "person": person, "project": project}
        for attempt in range(3):
            parent = self.head()
            history_text = self.read_file("movements.csv", parent, optional=True)
            columns, history = read_rows(history_text, MOVEMENT_COLUMNS) if history_text is not None else (list(MOVEMENT_COLUMNS), [])
            previous = next((row for row in history if row["id"] == operation), None)
            if previous:
                if any(previous[key] != value for key, value in expected.items()):
                    raise ValueError("Esta solicitud ya fue registrada con otros datos. Inicie otro retiro.")
                return int(previous["available_after"])
            _, details = read_rows(self.read_file("details.csv", parent), DETAIL_COLUMNS)
            unique_product(details, code)
            location_columns, locations = read_rows(self.read_file("locations.csv", parent), LOCATION_COLUMNS)
            matches = [row for row in locations if (row["code"].strip(), row["location"].strip(), row["sublocation"].strip()) == (code, location, sublocation)]
            if len(matches) != 1:
                raise ValueError("La ubicación no existe o está duplicada. Primero debe revisarse el inventario.")
            _, available = stock_counts(matches[0])
            if quantity > available:
                raise ValueError(f"Solo hay {available} unidades disponibles en esta ubicación.")
            remaining = available - quantity
            matches[0]["available"] = str(remaining)
            history.append(dict.fromkeys(columns, "") | expected | {
                "timestamp": datetime.now(timezone.utc).isoformat(), "available_after": str(remaining),
            })
            commit = self._commit(parent, {
                "locations.csv": write_rows(location_columns, locations),
                "movements.csv": write_rows(columns, history),
            }, f"Registrar retiro {operation}: {code} (-{quantity})")
            try:
                self._request("PATCH", f"/git/refs/heads/{quote(self.branch, safe='/')}", payload={"sha": commit, "force": False})
                return remaining
            except Conflict:
                # Another writer may have changed main. Re-read balances and the
                # operation ID before recomputing, never force-push a stale balance.
                if attempt == 2:
                    raise
        raise GitHubError("No se pudo guardar el retiro. Vuelva a intentarlo.")
