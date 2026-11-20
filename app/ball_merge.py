"""SH ball merge agent: one clean ball-by-ball list from several providers (CricketData + SH Data Line).

Each delivery gets a provider-independent identity: (innings number, over, ball, extra kind, repeat count).
- The same delivery reported by two providers is kept once (the first provider in priority order wins).
- If two providers disagree about that delivery (runs / wicket), the first one is kept and the difference is counted
  as a conflict, so nothing is silently changed and nothing is invented.
"""
import re

_EXT = {"wd": "wd", "wide": "wd", "wides": "wd", "nb": "nb", "noball": "nb", "no_ball": "nb", "noballs": "nb",
        "b": "b", "bye": "b", "byes": "b", "lb": "lb", "leg_bye": "lb", "legbyes": "lb"}


def _inn(v, order):
    if isinstance(v, int):
        return v
    m = re.search(r"(\d+)\s*$", str(v or ""))
    if m:
        return int(m.group(1))
    return order.setdefault(str(v), len(order) + 1)


def keys(balls):
    """Identity for each ball in one provider's list (same order as the list)."""
    order, seen, out = {}, {}, []
    for b in balls or []:
        base = (_inn(b.get("inning"), order), int(b.get("over") or 0), int(b.get("ball") or 0), _EXT.get(str(b.get("extra") or "").lower(), ""))
        seen[base] = seen.get(base, 0) + 1
        out.append(base + (seen[base],))
    return out


def merge(*lists):
    """lists in priority order. Returns (merged balls sorted by identity, stats)."""
    best, stats = {}, {"duplicates": 0, "conflicts": 0, "added": [0] * len(lists)}
    for i, lst in enumerate(lists):
        for k, b in zip(keys(lst), lst or []):
            if k in best:
                stats["duplicates"] += 1
                o = best[k]
                if (int(o.get("runs") or 0), bool(o.get("wicket"))) != (int(b.get("runs") or 0), bool(b.get("wicket"))):
                    stats["conflicts"] += 1
                continue
            best[k] = b
            stats["added"][i] += 1
    order = lambda k: (k[0], k[1], k[2], 0 if k[3] in ("wd", "nb") else 1, k[3], k[4])   # wides/no-balls come before the legal ball with the same number
    return [best[k] for k in sorted(best, key=order)], stats
