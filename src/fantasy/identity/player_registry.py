"""Player name identity registry.

Manages ``data/identity/player_aliases.json`` — a file mapping canonical player
names to their raw aliases so that the same player appearing under different
names across leagues or seasons can be merged.

Schema::

    {
      "canonical_players": [
        {
          "canonical_id": "cp_abc123",
          "display_name": "Odell Beckham Jr.",
          "position": "WR",
          "aliases": [
            {"raw_name": "OBJ", "source": "manual"},
            {"raw_name": "Odell Beckham", "source": "manual"}
          ]
        }
      ]
    }
"""

from __future__ import annotations

import hashlib
import json
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

_default_path = Path(__file__).parents[4] / "data" / "identity" / "player_aliases.json"

_empty_registry: dict = {"canonical_players": []}


def load_player_registry(path: Path = _default_path) -> dict:
    """Load the player alias registry from disk, returning empty skeleton if absent.

    Args:
        path: Path to player_aliases.json.

    Returns:
        Registry dict with key 'canonical_players'.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"canonical_players": []}


def save_player_registry(registry: dict, path: Path = _default_path) -> None:
    """Persist the player registry to disk.

    Args:
        registry: Registry dict to save.
        path: Destination path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def _canonical_id(name: str) -> str:
    """Generate a stable canonical ID from a display name.

    Args:
        name: Canonical display name.

    Returns:
        Short hex string prefixed with 'cp_'.
    """
    return "cp_" + hashlib.md5(name.lower().encode()).hexdigest()[:8]


def resolve_player_name(registry: dict, raw_name: str) -> str:
    """Return the canonical display name for a raw player name, or the raw name if unmapped.

    Args:
        registry: Player registry dict.
        raw_name: Raw player name as it appears in the data.

    Returns:
        Canonical display name, or raw_name if no mapping exists.
    """
    for entry in registry.get("canonical_players", []):
        aliases = {a["raw_name"] for a in entry.get("aliases", [])}
        aliases.add(entry["display_name"])
        if raw_name in aliases:
            return entry["display_name"]
    return raw_name


def build_name_lookup(registry: dict) -> dict[str, str]:
    """Build a flat {raw_name: canonical_display_name} lookup dict.

    Args:
        registry: Player registry dict.

    Returns:
        Dict mapping every raw alias and display name to its canonical display name.
    """
    lookup: dict[str, str] = {}
    for entry in registry.get("canonical_players", []):
        canonical = entry["display_name"]
        lookup[canonical] = canonical
        for alias in entry.get("aliases", []):
            lookup[alias["raw_name"]] = canonical
    return lookup


def merge_player_names(
    registry: dict,
    names: list[str],
    canonical_name: str,
    position: str = "",
) -> dict:
    """Merge multiple raw player names under one canonical name.

    If a canonical entry for ``canonical_name`` already exists, appends the new
    aliases to it. Otherwise creates a new entry.

    Args:
        registry: Existing registry dict (modified in place).
        names: List of raw names to merge (may include the canonical_name itself).
        canonical_name: The single display name to use going forward.
        position: Optional position hint (QB/RB/WR/TE/K/DST).

    Returns:
        Updated registry dict.
    """
    cid = _canonical_id(canonical_name)
    existing = {e["canonical_id"]: e for e in registry.get("canonical_players", [])}

    if cid not in existing:
        existing[cid] = {
            "canonical_id": cid,
            "display_name": canonical_name,
            "position": position,
            "aliases": [],
        }

    entry = existing[cid]
    current_aliases = {a["raw_name"] for a in entry["aliases"]}
    current_aliases.add(entry["display_name"])

    for name in names:
        if name != canonical_name and name not in current_aliases:
            entry["aliases"].append({"raw_name": name, "source": "manual"})
            current_aliases.add(name)

    registry["canonical_players"] = list(existing.values())
    return registry


def auto_suggest_player_merges(
    all_player_names: list[str],
    threshold: float = 0.82,
    max_suggestions: int = 50,
) -> list[dict]:
    """Fuzzy-match player names to suggest potential merges.

    Uses SequenceMatcher to find pairs of similar names. Prioritises pairs where
    one name contains the other (e.g. "Odell Beckham" / "Odell Beckham Jr.").

    Args:
        all_player_names: All unique player names across all data.
        threshold: Similarity threshold (0-1). Default 0.82.
        max_suggestions: Maximum pairs to return.

    Returns:
        List of dicts with keys: name_a, name_b, similarity (float, 0-1),
        reason (str hint about why they match).
    """
    names = sorted(set(all_player_names))
    suggestions: list[dict] = []

    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            sim = SequenceMatcher(None, a.lower(), b.lower()).ratio()
            if sim >= threshold:
                # Determine reason
                al, bl = a.lower(), b.lower()
                if al in bl or bl in al:
                    reason = "one name contains the other"
                elif sim >= 0.95:
                    reason = "near-identical spelling"
                else:
                    reason = f"similar names ({sim:.0%})"
                suggestions.append({"name_a": a, "name_b": b, "similarity": round(sim, 3), "reason": reason})

    suggestions.sort(key=lambda x: x["similarity"], reverse=True)
    return suggestions[:max_suggestions]


def apply_player_registry(
    df: pd.DataFrame,
    registry: dict,
    name_col: str = "player",
) -> pd.DataFrame:
    """Replace raw player names with canonical names from the registry.

    Rows whose player name has no mapping are left unchanged.

    Args:
        df: DataFrame containing a player name column.
        registry: Player registry dict.
        name_col: Name of the column containing player names.

    Returns:
        Copy of df with name_col values replaced by canonical names where mapped.
    """
    lookup = build_name_lookup(registry)
    if not lookup:
        return df
    out = df.copy()
    out[name_col] = out[name_col].map(lambda n: lookup.get(n, n))
    return out
