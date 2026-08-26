"""Possession chains.

Sequence models, pressing metrics and possession-value work all need the same thing: a stable
id that says "these events belong to one spell on the ball". Every vendor spells that
differently -- StatsBomb ships a chain counter, SkillCorner a phase index, Metrica and the
rugby feed nothing at all -- so this module normalises it once here rather than leaving each
downstream tool to reinvent it slightly differently.

Ids returned here are dense and 1-based **over the frame you passed in**, and are unique
across matches, so ``events.groupby(possessions(events))`` is always safe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .setpieces import extra_field

__all__ = ["add_possession", "possession_frame", "possession_spans", "possessions"]

#: ``extra`` keys, in preference order, that already hold a vendor possession/phase counter.
_SOURCE_KEYS = ("possession", "phase_index")

#: Restarts that always begin a new spell, used only when the source counts nothing itself.
_RESTARTS = frozenset(
    {"kick_off", "goal_kick", "throw_in", "corner", "free_kick", "penalty", "lineout", "scrum"}
)


def possessions(events: pd.DataFrame, *, derive: bool = True) -> pd.Series:
    """A possession id per row, as a nullable ``Int64`` Series aligned to ``events.index``.

    The vendor's own counter is used wherever there is one. Where there is not, and ``derive``
    is set, a chain is cut whenever the acting team changes or play restarts from a set piece,
    within a single match and period.

    Args:
        derive: when ``False``, rows from a source that counts nothing get ``<NA>`` instead of
            a derived id -- use this when you only trust vendor chains.
    """
    _require(events, ("match_id", "period", "t", "team_id"))
    if events.empty:
        return pd.Series([], dtype="Int64", index=events.index)

    raw = _source_ids(events)
    kind = pd.Series(np.where(raw.isna(), "derived", "source"), index=events.index)
    if derive:
        raw = raw.where(raw.notna(), _derived_ids(events))
    else:
        kind = kind.mask(raw.isna(), other="none")

    # One key per (match, source-or-derived, counter) so two matches never share an id and a
    # vendor counter can never collide with a derived one.
    keys = (
        events["match_id"].astype("string").fillna("").astype(str)
        + "|"
        + kind.astype(str)
        + "|"
        + raw.astype("string").fillna("").astype(str)
    )
    codes, _ = pd.factorize(keys, use_na_sentinel=False)
    out = pd.Series(codes + 1, index=events.index, dtype="Int64")
    return out.mask(raw.isna())


def _source_ids(events: pd.DataFrame) -> pd.Series:
    """The vendor counter, if this frame's ``extra`` carries one."""
    found = pd.Series(pd.NA, index=events.index, dtype="object")
    for key in _SOURCE_KEYS:
        values = extra_field(events, key)
        found = found.where(found.notna(), values)
    return found


def _derived_ids(events: pd.DataFrame) -> pd.Series:
    """Cut a new chain on a team change or a restart, within each match and period."""
    ordered = events.sort_values(["match_id", "period", "t"], kind="stable")

    team = ordered["team_id"].astype("string").fillna("").to_numpy(dtype=object)
    subtype = (
        ordered["subtype"].astype("string").str.lower().fillna("").to_numpy(dtype=object)
    )
    match_period = (
        ordered["match_id"].astype("string").fillna("").astype(str)
        + "|"
        + ordered["period"].astype("string").fillna("").astype(str)
    ).to_numpy(dtype=object)

    starts = np.zeros(len(ordered), dtype=bool)
    starts[0] = True
    starts[1:] = (team[1:] != team[:-1]) | (match_period[1:] != match_period[:-1])
    starts |= np.isin(subtype, list(_RESTARTS))

    counter = pd.Series(starts.cumsum(), index=ordered.index, dtype="object")
    return counter.reindex(events.index)


def add_possession(events: pd.DataFrame, *, derive: bool = True) -> pd.DataFrame:
    """``events`` plus ``possession`` and ``possession_team`` columns.

    Derived columns are deliberately not part of the canonical schema, so this returns a copy.
    ``possession_team`` is the vendor's own label where there is one, otherwise the team that
    started the chain.
    """
    out = events.copy()
    out["possession"] = possessions(events, derive=derive)

    vendor = extra_field(events, "possession_team").astype("string")
    first_team = (
        out.groupby("possession", dropna=True)["team"].transform("first").astype("string")
    )
    out["possession_team"] = vendor.where(vendor.notna(), first_team)
    return out


def possession_frame(events: pd.DataFrame, *, derive: bool = True) -> pd.DataFrame:
    """One row per possession: who had it, when, where it started and ended, how it finished.

    Columns: ``possession, match_id, competition, season, period, team_id, team, start_t,
    end_t, duration, n_events, start_x, start_y, end_x, end_y, final_type, final_outcome``.
    """
    _require(events, ("match_id", "period", "t", "team_id"))
    tagged = add_possession(events, derive=derive)
    tagged = tagged.loc[tagged["possession"].notna()]
    if tagged.empty:
        return pd.DataFrame(columns=list(_FRAME_COLUMNS))

    tagged = tagged.sort_values(["possession", "period", "t"], kind="stable")
    grouped = tagged.groupby("possession", sort=True)

    out = pd.DataFrame(
        {
            "possession": grouped["possession"].first(),
            "match_id": grouped["match_id"].first(),
            "competition": grouped["competition"].first(),
            "season": grouped["season"].first(),
            "period": grouped["period"].first(),
            "team_id": grouped["team_id"].first(),
            "team": grouped["possession_team"].first(),
            "start_t": grouped["t"].min(),
            "end_t": grouped["t"].max(),
            "n_events": grouped.size(),
            "start_x": grouped["x"].first(),
            "start_y": grouped["y"].first(),
            # The chain's last known touch point, which is what "where did it end up" means.
            "end_x": grouped["end_x"].last().fillna(grouped["x"].last()),
            "end_y": grouped["end_y"].last().fillna(grouped["y"].last()),
            "final_type": grouped["type"].last(),
            "final_outcome": grouped["outcome"].last(),
        }
    ).reset_index(drop=True)
    out["duration"] = out["end_t"].astype("Float64") - out["start_t"].astype("Float64")
    return out.loc[:, list(_FRAME_COLUMNS)]


_FRAME_COLUMNS = (
    "possession", "match_id", "competition", "season", "period", "team_id", "team",
    "start_t", "end_t", "duration", "n_events", "start_x", "start_y", "end_x", "end_y",
    "final_type", "final_outcome",
)


def possession_spans(
    events: pd.DataFrame,
    *,
    sides: dict[str, str] | None = None,
    derive: bool = True,
) -> pd.DataFrame:
    """Possession chains as time intervals: ``match_id, period, start_t, end_t, side``.

    This is the shape :func:`sportio.transform.normalize_direction` wants for its
    ``"possession"`` convention. ``side`` is ``"home"`` or ``"away"``.

    Args:
        sides: maps ``team_id`` to ``"home"``/``"away"``. Needed for any source whose team ids
            are not already those two words -- Metrica's are, StatsBomb's and SkillCorner's are
            vendor ids, and only the match metadata knows which is the home side.

    The intervals carry the events frame's own clock, so if you are pairing them with tracking
    make sure the two agree -- see ``metrica.period_starts`` for the one source where they do
    not by default.
    """
    frame = possession_frame(events, derive=derive)
    if frame.empty:
        return pd.DataFrame(columns=["match_id", "period", "start_t", "end_t", "side"])

    team_id = frame["team_id"].astype("string")
    if sides:
        side = team_id.map({str(k): v for k, v in sides.items()}).astype("string")
    else:
        lowered = team_id.str.lower()
        side = lowered.where(lowered.isin(("home", "away")))
        if side.isna().all():
            raise ValueError(
                "team ids are vendor-specific, so pass sides={team_id: 'home'|'away'} to say "
                f"which side is which; saw {sorted(set(team_id.dropna()))[:4]}"
            )

    out = frame.loc[:, ["match_id", "period", "start_t", "end_t"]].copy()
    out["side"] = side
    return out.loc[out["side"].notna()].reset_index(drop=True)


def _require(events: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [c for c in columns if c not in events.columns]
    if missing:
        raise KeyError(f"events frame is missing columns: {missing}")
