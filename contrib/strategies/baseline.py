"""The reigning engine-lane champion: provenance-aware ranking.

Promoted from a contrib submission (PR #567, +0.05 composite over the
identity baseline). The logic ships in the package as
``vouch.strategies.provenance``; this file re-exports it so the gate's
``--champion contrib/strategies/baseline.py`` keeps pointing at whatever
currently reigns. Dethrone it by opening a PR that adds one new file
under ``contrib/strategies/`` and clears the margin band.

A strategy is real ranking code. It receives the query and an over-fetched
candidate pool (data only - no KB, no disk, no network) and returns the ids in
the order the reader should see them; the top ``limit`` survive the cut.
Ordering is authoritative but bounded: ids you invent are ignored, and any
candidate you drop is appended at the tail before the cut - so you can
de-prioritise a candidate out of the pack, but never fabricate a result or
shrink the pack.
"""

from vouch.strategies.provenance import rank

__all__ = ["rank"]
