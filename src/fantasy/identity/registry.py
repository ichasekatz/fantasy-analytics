"""Canonical manager registry: load, save, resolve, and suggest merges."""

from __future__ import annotations

import difflib
import json
import uuid
from pathlib import Path

import pandas as pd

_empty_registry: dict = {"canonical_managers": []}

_merge_similarity_threshold = 0.80  # SequenceMatcher ratio for auto-suggest


def load_registry(identity_path: Path) -> dict:
    """Load the canonical manager registry from disk.

    Returns an empty registry skeleton if the file does not exist or is empty.

    Args:
        identity_path (Path): Path to manager_aliases.json.

    Returns:
        Registry dict with key 'canonical_managers'.
    """
    if not identity_path.exists():
        return {"canonical_managers": []}
    try:
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        if not isinstance(data.get("canonical_managers"), list):
            return {"canonical_managers": []}
        return data
    except (OSError, json.JSONDecodeError):
        return {"canonical_managers": []}


def save_registry(registry: dict, identity_path: Path) -> None:
    """Persist the canonical manager registry to disk.

    Args:
        registry (dict): Registry dict with key 'canonical_managers'.
        identity_path (Path): Path to manager_aliases.json.
    """
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_owner(registry: dict, league_id: str, raw_owner_id: str) -> str | None:
    """Resolve a raw owner ID to a canonical manager ID.

    Args:
        registry (dict): Loaded registry dict.
        league_id (str): The league the owner belongs to.
        raw_owner_id (str): The raw owner UUID from the export.

    Returns:
        canonical_id string if found, else None.
    """
    for manager in registry["canonical_managers"]:
        for alias in manager.get("aliases", []):
            if alias.get("league_id") == league_id and alias.get("raw_owner_id") == raw_owner_id:
                return manager["canonical_id"]
    return None


def resolve_owner_by_name(registry: dict, league_id: str, raw_name: str) -> tuple[str, str] | None:
    """Resolve a raw owner name to (canonical_id, display_name).

    Args:
        registry (dict): Loaded registry dict.
        league_id (str): The league the owner belongs to.
        raw_name (str): The raw owner display name from the export.

    Returns:
        (canonical_id, display_name) tuple if found, else None.
    """
    for manager in registry["canonical_managers"]:
        for alias in manager.get("aliases", []):
            if alias.get("league_id") == league_id and alias.get("raw_name") == raw_name:
                return manager["canonical_id"], manager["display_name"]
    return None


def build_name_lookup(registry: dict) -> dict[tuple[str, str], tuple[str, str]]:
    """Build a fast lookup from (league_id, raw_name) → (canonical_id, display_name).

    Args:
        registry (dict): Loaded registry dict.

    Returns:
        Dict mapping (league_id, raw_name) to (canonical_id, display_name).
    """
    lookup: dict[tuple[str, str], tuple[str, str]] = {}
    for manager in registry["canonical_managers"]:
        cid = manager["canonical_id"]
        dname = manager["display_name"]
        for alias in manager.get("aliases", []):
            key = (alias.get("league_id", ""), alias.get("raw_name", ""))
            lookup[key] = (cid, dname)
    return lookup


def get_canonical_display(registry: dict, canonical_id: str) -> str | None:
    """Return display_name for a canonical_id.

    Args:
        registry (dict): Loaded registry dict.
        canonical_id (str): Canonical manager ID.

    Returns:
        Display name string if found, else None.
    """
    for manager in registry["canonical_managers"]:
        if manager["canonical_id"] == canonical_id:
            return manager["display_name"]
    return None


def merge_owners(
    registry: dict,
    aliases: list[dict[str, str]],
    display_name: str,
) -> tuple[dict, str]:
    """Create a new canonical manager from a list of raw owner aliases.

    Each alias dict must have keys: league_id, raw_owner_id, raw_name.
    Existing canonical entries that contain any of these aliases are merged
    into the new one; their other aliases are preserved.

    Args:
        registry (dict): Loaded registry dict (mutated in place).
        aliases (list[dict]): Raw owner aliases to group under one canonical.
        display_name (str): Human-readable name for the new canonical manager.

    Returns:
        (updated_registry, new_canonical_id) tuple.
    """
    new_id = f"cm_{uuid.uuid4().hex[:8]}"

    # Collect all alias keys being merged
    alias_keys = {(a["league_id"], a["raw_owner_id"]) for a in aliases}

    # Remove these aliases from any existing canonical entries
    for manager in registry["canonical_managers"]:
        manager["aliases"] = [
            al for al in manager.get("aliases", [])
            if (al.get("league_id"), al.get("raw_owner_id")) not in alias_keys
        ]

    # Remove any canonical entries that are now empty
    registry["canonical_managers"] = [
        m for m in registry["canonical_managers"] if m.get("aliases")
    ]

    registry["canonical_managers"].append({
        "canonical_id": new_id,
        "display_name": display_name,
        "aliases": aliases,
    })
    return registry, new_id


def auto_suggest_merges(owners_df: pd.DataFrame) -> list[dict]:
    """Fuzzy-match owner names across leagues and within the same league to find duplicates.

    Compares every pair of unique (league_id, raw_name) combinations using
    difflib.SequenceMatcher. Returns pairs above the similarity threshold.

    Args:
        owners_df (pd.DataFrame): DataFrame with columns league_id, raw_owner_id,
            raw_name (as returned by enrich_owners or load_all_leagues owners table).

    Returns:
        List of dicts with keys: name_a, league_a, owner_id_a,
        name_b, league_b, owner_id_b, similarity.
        Sorted by similarity descending.
    """
    if owners_df.empty:
        return []

    # Deduplicate: one row per (league_id, raw_name)
    name_col = "raw_name" if "raw_name" in owners_df.columns else "name"
    id_col = "raw_owner_id" if "raw_owner_id" in owners_df.columns else "owner_id"
    league_col = "league_id" if "league_id" in owners_df.columns else None

    rows = owners_df[[league_col or id_col, id_col, name_col]].drop_duplicates().to_dict("records")

    suggestions = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            # Skip identical entries
            if a[id_col] == b[id_col] and (league_col and a[league_col] == b[league_col]):
                continue
            ratio = difflib.SequenceMatcher(None, a[name_col].lower(), b[name_col].lower()).ratio()
            if ratio >= _merge_similarity_threshold:
                suggestions.append({
                    "name_a": a[name_col],
                    "league_a": a.get(league_col, "") if league_col else "",
                    "owner_id_a": a[id_col],
                    "name_b": b[name_col],
                    "league_b": b.get(league_col, "") if league_col else "",
                    "owner_id_b": b[id_col],
                    "similarity": round(ratio, 3),
                })
    return sorted(suggestions, key=lambda x: x["similarity"], reverse=True)
