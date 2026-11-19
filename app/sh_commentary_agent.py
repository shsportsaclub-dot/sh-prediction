"""SH Prediction original live-line commentary engine.

Consumes licensed structured ball events (not third-party commentary text).
Safe to import into the existing SH Prediction server. Persist returned events
using the existing match event database before publishing to SSE clients.
"""
import hashlib
import json

def commentary(ball, language="en"):
    mid=str(ball.get("match_id") or "").strip()
    over=ball.get("over")
    delivery=ball.get("ball")
    if not mid or over is None or delivery is None:
        raise ValueError("match_id, over and ball required")
    if language not in ("en","te"):
        raise ValueError("unsupported language")
    runs=int(ball.get("runs_bat",0))
    if runs<0 or runs>6:raise ValueError("invalid runs")
    extras=ball.get("extras") or {}
    if not isinstance(extras,dict):raise ValueError("invalid extras")
    extra_runs=sum(int(v) for v in extras.values() if isinstance(v,(int,float)))
    batter=str(ball.get("batter") or "Batter")[:100]
    bowler=str(ball.get("bowler") or "Bowler")[:100]
    label=f"{over}.{delivery}"
    if ball.get("wicket"):
        sentence=(f"{batter} అవుట్! వికెట్ పడింది." if language=="te" else f"Wicket falls! {batter} is dismissed.")
    elif extras.get("wide"):
        sentence=(f"వైడ్ బాల్. {extra_runs} అదనపు పరుగులు." if language=="te" else f"Wide ball, {extra_runs} extra run(s).")
    elif extras.get("noball"):
        sentence=(f"నో బాల్. {extra_runs} అదనపు పరుగులు." if language=="te" else f"No-ball, {extra_runs} extra run(s).")
    elif runs==6:
        sentence=(f"{batter} సిక్స్ కొట్టాడు!" if language=="te" else f"Six runs off {batter}'s bat!")
    elif runs==4:
        sentence=(f"{batter} నాలుగు పరుగులు సాధించాడు!" if language=="te" else f"Four runs for {batter}!")
    elif runs==0:
        sentence=(f"{bowler} డాట్ బాల్ వేశాడు." if language=="te" else f"Dot ball from {bowler}.")
    else:
        sentence=(f"{batter} {runs} పరుగులు సాధించాడు." if language=="te" else f"{batter} takes {runs} run(s).")
    key=json.dumps([mid,ball.get("innings"),over,delivery,ball.get("event_id"),language],ensure_ascii=False)
    return {"match_id":mid,"event_id":hashlib.sha256(key.encode()).hexdigest(),"over":label,
            "language":language,"text":f"{label} — {sentence}",
            "origin":"SH original event commentary","verified":bool(ball.get("verified"))}

def normalize_feed_event(event):
    """Only facts needed for SH's independent commentary; ignore source prose."""
    allowed=("match_id","innings","over","ball","event_id","batter","bowler",
             "runs_bat","extras","wicket","verified")
    return {k:event[k] for k in allowed if k in event}
