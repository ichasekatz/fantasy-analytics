"""Waiver wire and trade analytics from transaction history."""

from __future__ import annotations

import json

import pandas as pd


def _filter_transactions(
    transactions_df: pd.DataFrame,
    season: int | None,
    league_id: str | None,
) -> pd.DataFrame:
    """Apply season and league filters to a transactions DataFrame.

    Args:
        transactions_df: Transactions DataFrame.
        season: Season to keep, or None for all.
        league_id: League to keep, or None for all.

    Returns:
        Filtered copy.
    """
    out = transactions_df.copy()
    if season is not None:
        out = out[out["season"] == season]
    if league_id is not None:
        out = out[out["league_id"] == league_id]
    return out


def _extract_parties(parties_str: str | None) -> tuple[str, str]:
    """Parse parties JSON string to extract add owner and drop owner.

    The parties field is a JSON list of dicts. Each dict has at minimum
    'type' ('add'/'drop') and either 'owner' or 'name' key.

    Args:
        parties_str: Raw JSON string from the parties column.

    Returns:
        Tuple of (add_owner, drop_owner). Empty strings on parse failure.
    """
    if not parties_str:
        return "", ""
    try:
        parties = json.loads(parties_str)
    except (json.JSONDecodeError, TypeError):
        return "", ""

    add_owner = ""
    drop_owner = ""
    for party in parties:
        if not isinstance(party, dict):
            continue
        ptype = party.get("type", "")
        name = party.get("owner") or party.get("name") or party.get("teamName") or ""
        if ptype == "add" and not add_owner:
            add_owner = str(name)
        elif ptype == "drop" and not drop_owner:
            drop_owner = str(name)
    return add_owner, drop_owner


def _extract_trade_owners(parties_str: str | None) -> str:
    """Parse parties JSON string for a trade to get comma-separated owner names.

    Args:
        parties_str: Raw JSON string from the parties column.

    Returns:
        Comma-separated owner names, or empty string on failure.
    """
    if not parties_str:
        return ""
    try:
        parties = json.loads(parties_str)
    except (json.JSONDecodeError, TypeError):
        return ""

    names: list[str] = []
    seen: set[str] = set()
    for party in parties:
        if not isinstance(party, dict):
            continue
        name = str(party.get("owner") or party.get("name") or party.get("teamName") or "")
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return ", ".join(names)


def parse_transaction_parties(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """Expand the parties JSON column into owner_add, owner_drop, trade_owners columns.

    For add/drop transactions, populates owner_add and owner_drop.
    For trade transactions, populates trade_owners (comma-separated).

    Args:
        transactions_df: Transactions DataFrame with a 'parties' column.

    Returns:
        Original DataFrame with added columns: owner_add, owner_drop, trade_owners.
    """
    if transactions_df.empty:
        return transactions_df.assign(owner_add="", owner_drop="", trade_owners="")

    df = transactions_df.copy()
    add_owners = []
    drop_owners = []
    trade_owners_list = []

    for _, row in df.iterrows():
        ttype = str(row.get("type", ""))
        parties_str = str(row.get("parties", "")) if row.get("parties") is not None else ""

        if ttype in ("add/drop", "add", "drop"):
            ao, do = _extract_parties(parties_str)
            add_owners.append(ao)
            drop_owners.append(do)
            trade_owners_list.append("")
        elif ttype == "trade":
            add_owners.append("")
            drop_owners.append("")
            trade_owners_list.append(_extract_trade_owners(parties_str))
        else:
            add_owners.append("")
            drop_owners.append("")
            trade_owners_list.append("")

    df["owner_add"] = add_owners
    df["owner_drop"] = drop_owners
    df["trade_owners"] = trade_owners_list
    return df


def waiver_activity(
    transactions_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Per-manager waiver and free-agent activity summary.

    Args:
        transactions_df: Transactions DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: owner, season, total_adds, total_drops,
        net_adds, add_drop_transactions, free_agent_adds.
    """
    empty = pd.DataFrame(
        columns=["owner", "season", "total_adds", "total_drops",
                 "net_adds", "add_drop_transactions", "free_agent_adds"]
    )
    df = _filter_transactions(transactions_df, season, league_id)
    df = parse_transaction_parties(df)

    add_rows = df[df["type"].isin(("add", "add/drop")) & (df["owner_add"] != "")].copy()
    drop_rows = df[df["type"].isin(("drop", "add/drop")) & (df["owner_drop"] != "")].copy()

    if add_rows.empty and drop_rows.empty:
        return empty

    group_cols = ["owner_add", "season"] if season is None else ["owner_add"]
    add_counts = add_rows.groupby(group_cols).size().rename("total_adds").reset_index()
    add_counts = add_counts.rename(columns={"owner_add": "owner"})

    group_cols_d = ["owner_drop", "season"] if season is None else ["owner_drop"]
    drop_counts = drop_rows.groupby(group_cols_d).size().rename("total_drops").reset_index()
    drop_counts = drop_counts.rename(columns={"owner_drop": "owner"})

    merge_on = ["owner", "season"] if season is None else ["owner"]
    result = add_counts.merge(drop_counts, on=merge_on, how="outer").fillna(0)
    result["total_adds"] = result["total_adds"].astype(int)
    result["total_drops"] = result["total_drops"].astype(int)
    result["net_adds"] = result["total_adds"] - result["total_drops"]

    # add_drop_transactions: rows of type 'add/drop' by this owner
    adp_rows = df[df["type"] == "add/drop"]
    adp_counts = adp_rows.groupby(group_cols).size().rename("add_drop_transactions").reset_index()
    adp_counts = adp_counts.rename(columns={"owner_add": "owner"})
    result = result.merge(adp_counts, on=merge_on, how="left").fillna(0)
    result["add_drop_transactions"] = result["add_drop_transactions"].astype(int)

    # free_agent_adds: adds NOT part of an add/drop (pure adds)
    fa_rows = df[df["type"] == "add"]
    fa_counts = fa_rows.groupby(group_cols).size().rename("free_agent_adds").reset_index()
    fa_counts = fa_counts.rename(columns={"owner_add": "owner"})
    result = result.merge(fa_counts, on=merge_on, how="left").fillna(0)
    result["free_agent_adds"] = result["free_agent_adds"].astype(int)

    return result


def trade_history(
    transactions_df: pd.DataFrame,
    season: int | None = None,
    league_id: str | None = None,
) -> pd.DataFrame:
    """All trade transactions with parsed parties and players.

    Args:
        transactions_df: Transactions DataFrame.
        season: Filter to season, or None for all.
        league_id: Filter to league, or None for all.

    Returns:
        DataFrame with columns: season, week, timestamp, league_id,
        trade_owners, players_involved.
    """
    empty = pd.DataFrame(
        columns=["season", "week", "timestamp", "league_id", "trade_owners", "players_involved"]
    )
    df = _filter_transactions(transactions_df, season, league_id)
    trades = df[df["type"] == "trade"].copy()
    if trades.empty:
        return empty

    trades = parse_transaction_parties(trades)

    def _summarize_players(players_str: str | None) -> str:
        """Extract player names from players JSON column."""
        if not players_str:
            return ""
        try:
            players = json.loads(str(players_str))
            if isinstance(players, list):
                return ", ".join(str(p.get("name", p) if isinstance(p, dict) else p) for p in players)
        except (json.JSONDecodeError, TypeError):
            pass
        return str(players_str)

    trades["players_involved"] = trades["players"].apply(_summarize_players)
    cols = ["season", "week", "timestamp", "league_id", "trade_owners", "players_involved"]
    return trades[[c for c in cols if c in trades.columns]].reset_index(drop=True)


def transaction_timeline(
    transactions_df: pd.DataFrame,
    season: int,
    league_id: str | None = None,
) -> pd.DataFrame:
    """Week-by-week transaction counts per manager.

    Args:
        transactions_df: Transactions DataFrame.
        season: Season to analyze (required).
        league_id: Filter to league, or None.

    Returns:
        DataFrame with columns: week, owner, adds, drops, trades.
    """
    empty = pd.DataFrame(columns=["week", "owner", "adds", "drops", "trades"])
    df = _filter_transactions(transactions_df, season, league_id)
    if df.empty:
        return empty

    df = parse_transaction_parties(df)

    rows = []
    owners: set[str] = set()
    owners.update(df[df["owner_add"] != ""]["owner_add"].tolist())
    owners.update(df[df["owner_drop"] != ""]["owner_drop"].tolist())
    owners.update(
        o.strip()
        for s in df[df["trade_owners"] != ""]["trade_owners"].tolist()
        for o in s.split(",")
        if o.strip()
    )

    for week in sorted(df["week"].dropna().unique()):
        week_df = df[df["week"] == week]
        for owner in owners:
            adds = int(((week_df["type"].isin(("add", "add/drop"))) & (week_df["owner_add"] == owner)).sum())
            drops = int(((week_df["type"].isin(("drop", "add/drop"))) & (week_df["owner_drop"] == owner)).sum())
            trades = int(week_df["trade_owners"].str.contains(owner, na=False, regex=False).sum())
            if adds or drops or trades:
                rows.append({"week": int(week), "owner": owner, "adds": adds, "drops": drops, "trades": trades})

    return pd.DataFrame(rows) if rows else empty
