"""Independent pandas versions of calculations done in SQL.

Tests compare SQL results against these. They are written differently on
purpose (sorting and binary search instead of window functions), so a shared
mistake is unlikely.
"""

import numpy as np
import pandas as pd


def open_at_arrival(tickets: pd.DataFrame) -> pd.Series:
    """Tickets of the same assigned team that had arrived and were not yet
    resolved when each non-cancelled ticket arrived. Indexed by ticket_id."""
    active = tickets[tickets["status"] != "cancelled"].sort_values(["created_at", "ticket_id"])
    parts = []
    for _, group in active.groupby("assigned_team"):
        arrived_before = np.arange(len(group))
        resolved_times = np.sort(group["resolved_at"].dropna().to_numpy())
        resolved_by_then = np.searchsorted(resolved_times, group["created_at"].to_numpy(), side="right")
        parts.append(pd.Series(arrived_before - resolved_by_then, index=group["ticket_id"]))
    return pd.concat(parts)


def arrivals_in_previous(tickets: pd.DataFrame, group_column: str, window: pd.Timedelta) -> pd.Series:
    """Tickets in the same group created in [t - window, t), strictly before t."""
    parts = []
    for _, group in tickets.sort_values("created_at").groupby(group_column):
        times = group["created_at"].to_numpy()
        earliest = np.searchsorted(times, times - window.to_timedelta64(), side="left")
        strictly_before = np.searchsorted(times, times, side="left")
        parts.append(pd.Series(strictly_before - earliest, index=group["ticket_id"]))
    return pd.concat(parts)
