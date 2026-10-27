"""Read only staff IDs and names from the private Staff directory."""

import csv
from io import StringIO

import os
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


DIRECTORY_PATH = "data/input/staff.csv"


class StaffDirectoryError(ValueError):
    pass


def parse_staff(text):
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if not {"id", "nombre"}.issubset(reader.fieldnames or []):
        raise StaffDirectoryError("The staff directory is missing ID or name columns.")
    names = {}
    for row in reader:
        code, name = ((row.get(field) or "").strip() for field in ("id", "nombre"))
        if not code or not name or len(code) > 100 or len(name) > 300 or any(c in code + name for c in "\r\n\x00"):
            raise StaffDirectoryError("The staff directory contains an incomplete or invalid entry.")
        if code in names:
            raise StaffDirectoryError("The staff directory contains duplicate IDs.")
        names[code] = name
    if not names:
        raise StaffDirectoryError("The staff directory is empty.")
    return tuple(sorted(names.items(), key=lambda item: (item[1].casefold(), item[0])))


def directory_settings():
    def get(name, default=""):
        if name in os.environ:
            return os.environ[name]
        try:
            return str(st.secrets.get(name, default))
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            return default
    repository = get("STAFF_REPOSITORY", get("ASSISTANTS_REPOSITORY", "DeltaLabo/staff")).strip()
    # Existing deployment secrets may still contain the repository's former name.
    if repository.casefold() == "deltalabo/assistants":
        repository = "DeltaLabo/staff"
    return (get("STAFF_TOKEN", get("ASSISTANTS_TOKEN")) or get("GITHUB_TOKEN"),
            repository,
            get("STAFF_BRANCH", get("ASSISTANTS_BRANCH", "main")))


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def _load_staff(token, repository, branch):
    # Import lazily: the GitHub writer also validates staff selections.
    from scripts.github_inventory import GitHubError, GitHubInventory

    if not token:
        raise StaffDirectoryError("Configure STAFF_TOKEN with read access to the private Staff repository.")
    try:
        client = GitHubInventory(token, repository, branch)
        sha = client.head()
        text = client.read_file(DIRECTORY_PATH, sha, optional=True)
        if text is None:
            text = client.read_file("data/input/assistants.csv", sha)
    except (GitHubError, ValueError):
        raise StaffDirectoryError("Could not read the private staff directory. Check STAFF_REPOSITORY (default: DeltaLabo/staff) and ensure STAFF_TOKEN (or the legacy ASSISTANTS_TOKEN) has Contents: Read access to that repository, then refresh the list.") from None
    try:
        return parse_staff(text)
    except csv.Error:
        raise StaffDirectoryError("The staff directory is not a valid CSV file.") from None


def load_staff():
    return _load_staff(*directory_settings())


def refresh_staff():
    _load_staff.clear()


def staff_name(code, expected_name):
    if not code:
        raise StaffDirectoryError("Select a staff member from the directory.")
    name = dict(load_staff()).get(code)
    if not name or name != expected_name:
        raise StaffDirectoryError("The staff selection is no longer valid. Refresh the list and select your name again.")
    return name
