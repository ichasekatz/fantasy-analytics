"""Shared CSS injection for consistent dashboard styling."""

from __future__ import annotations

import streamlit as st


def inject_css() -> None:
    st.markdown("""
    <style>
    div[data-testid="metric-container"] {
        background: linear-gradient(135deg, #1A1F2E 0%, #252B3B 100%);
        border: 1px solid #2D3550;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 20px rgba(0,0,0,0.4);
    }
    div[data-testid="metric-container"] label {
        font-size: 0.75rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #8892A4 !important;
    }
    div[data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.8rem;
        font-weight: 700;
        color: #FF6B35 !important;
    }
    h1 {
        font-weight: 800 !important;
        letter-spacing: -0.02em;
        background: linear-gradient(90deg, #FF6B35, #FF9A5C);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    button[data-baseweb="tab"] {
        font-weight: 600 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        border-bottom: 3px solid #FF6B35 !important;
    }
    div[data-testid="stDataFrame"] {
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid #2D3550;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0D1117 0%, #161B27 100%);
        border-right: 1px solid #2D3550;
    }
    hr {
        border-color: #2D3550 !important;
        margin: 1.5rem 0 !important;
    }
    details summary {
        font-weight: 600;
    }
    .stApp > header {
        background: transparent;
    }
    div[data-testid="stSelectbox"] > div > div {
        border-color: #2D3550 !important;
    }
    div[data-testid="stTextInput"] > div > div {
        border-color: #2D3550 !important;
    }
    </style>
    """, unsafe_allow_html=True)
