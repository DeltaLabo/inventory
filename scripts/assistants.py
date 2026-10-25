"""Read only assistant IDs and names from the private administration directory."""

import csv
from io import StringIO

import os
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


DIRECTORY_PATH = "data/asistentes.csv"


class AssistantDirectoryError(ValueError):
    pass


def parse_assistants(text):
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if not {"id", "nombre"}.issubset(reader.fieldnames or []):
        raise AssistantDirectoryError("The assistant directory is missing ID or name columns.")
    names = {}
    for row in reader:
        code, name = ((row.get(field) or "").strip() for field in ("id", "nombre"))
        if not code or not name or len(code) > 100 or len(name) > 100 or any(c in code + name for c in "\r\n\x00"):
            raise AssistantDirectoryError("The assistant directory contains an incomplete or invalid entry.")
        if code in names:
            raise AssistantDirectoryError("The assistant directory contains duplicate IDs.")
        names[code] = name
    if not names:
        raise AssistantDirectoryError("The assistant directory is empty.")
    return tuple(sorted(names.items(), key=lambda item: (item[1].casefold(), item[0])))


def directory_settings():
    def get(name, default=""):
        if name in os.environ:
            return os.environ[name]
        try:
            return str(st.secrets.get(name, default))
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            return default
    return (get("ADMINISTRATION_TOKEN") or get("GITHUB_TOKEN"),
            get("ADMINISTRATION_REPOSITORY", "DeltaLabo/administration"),
            get("ADMINISTRATION_BRANCH", "main"))


@st.cache_data(ttl=300, max_entries=4, show_spinner=False)
def _load_assistants(token, repository, branch):
    # Import lazily: the GitHub writer also validates assistant selections.
    from scripts.github_inventory import GitHubError, GitHubInventory

    if not token:
        raise AssistantDirectoryError("Configure ADMINISTRATION_TOKEN with read access to the private administration repository.")
    try:
        client = GitHubInventory(token, repository, branch)
        text = client.read_file(DIRECTORY_PATH, client.head())
    except (GitHubError, ValueError):
        raise AssistantDirectoryError("Could not read the private assistant directory. Check the administration token's repository access, then refresh the list.") from None
    try:
        return parse_assistants(text)
    except csv.Error:
        raise AssistantDirectoryError("The assistant directory is not a valid CSV file.") from None


def load_assistants():
    return _load_assistants(*directory_settings())


def refresh_assistants():
    _load_assistants.clear()


def assistant_name(code, expected_name):
    if not code:
        raise AssistantDirectoryError("Select an assistant from the directory.")
    name = dict(load_assistants()).get(code)
    if not name or name != expected_name:
        raise AssistantDirectoryError("The assistant selection is no longer valid. Refresh the list and select your name again.")
    return name
