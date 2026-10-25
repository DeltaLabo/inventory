"""Public branding and navigation shared by the separate DeltaLAB apps."""

import os
from urllib.parse import urlsplit

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError


ADMIN_URL = "https://deltalab-admi.streamlit.app/"
SCHOOL = "Electromechanical Engineering School - Tecnológico de Costa Rica"


def administration_url():
    value = os.environ.get("ADMIN_APP_URL")
    if value is None:
        try:
            value = st.secrets.get("ADMIN_APP_URL", "")
        except (FileNotFoundError, StreamlitSecretNotFoundError):
            value = ""
    value = str(value).strip() or ADMIN_URL
    try:
        parsed = urlsplit(value)
        parsed.port
        if (parsed.scheme in ("https", "http") and parsed.hostname
                and not parsed.username and not parsed.password
                and not any(char.isspace() for char in value)):
            return value
    except ValueError:
        pass
    return ADMIN_URL


def admin_back_button():
    """Open the portal outside Community Cloud's sandboxed app iframe."""
    st.link_button("Back to administration", administration_url(), icon=":material/arrow_back:")


def app_header(title, logo_path, *, description=None, back=True):
    """Keep the title and description left, with the flat logo on the right."""
    st.html("""
        <style>
        @media (max-width: 640px) {
            .st-key-deltalab_header [data-testid="stImage"],
            .st-key-deltalab_header img { max-width: 100px; }
        }
        </style>
    """)
    with st.container(key="deltalab_header"):
        text, logo = st.columns([4, 1], gap="medium", vertical_alignment="center")
        with text:
            st.title(title)
            st.caption(SCHOOL)
            if description:
                st.write(description)
        with logo:
            with st.container(horizontal=True, horizontal_alignment="right"):
                st.image(str(logo_path), width=150)
    if back:
        admin_back_button()
