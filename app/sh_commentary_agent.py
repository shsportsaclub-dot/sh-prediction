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
    te=language=="te"
    # extras first: a ball with byes / leg-byes is never a dot ball, even though runs_bat is 0
    byes=int(extras.get("bye") or extras.get("byes") or 0)
    legbyes=int(extras.get("legbye") or extras.get("legbyes") or extras.get("leg_bye") or 0)
    kind=str(ball.get("wicket_kind") or "").strip().lower()
    KIND_EN={"bowled":"bowled","caught":"caught","lbw":"leg before wicket","run out":"run out","stumped":"stumped","hit wicket":"hit wicket",
             "caught and bowled":"caught and bowled","retired out":"retired out","obstructing the field":"out obstructing the field",
             "timed out":"timed out","handled the ball":"out handling the ball","hit the ball twice":"out hitting the ball twice"}
    KIND_TE={"bowled":"బౌల్డ్","caught":"క్యాచ్ ఔట్","lbw":"ఎల్బీడబ్ల్యూ","run out":"రనౌట్","stumped":"స్టంప్డ్","hit wicket":"హిట్ వికెట్",
             "caught and bowled":"కాట్ అండ్ బౌల్డ్"}
    if ball.get("wicket"):
        how=(KIND_TE.get(kind) if te else KIND_EN.get(kind))
        add=f" ({extra_runs} అదనపు)" if te and extra_runs else (f" ({extra_runs} extra)" if extra_runs else "")
        if how:
            sentence=(f"{batter} అవుట్ — {how}.{add}" if te else f"Wicket! {batter} {how}.{add}")
        else:
            sentence=(f"{batter} అవుట్! వికెట్ పడింది.{add}" if te else f"Wicket falls! {batter} is dismissed.{add}")
    elif extras.get("wide"):
        sentence=(f"వైడ్ బాల్. {extra_runs} అదనపు పరుగులు." if te else f"Wide ball, {extra_runs} extra run(s).")
    elif extras.get("noball"):
        bat=f" {batter} {runs} పరుగులు." if te and runs else (f" {batter} adds {runs} off the bat." if runs else "")
        sentence=(f"నో బాల్. {extra_runs} అదనపు పరుగులు.{bat}" if te else f"No-ball, {extra_runs} extra run(s).{bat}")
    elif byes:
        sentence=(f"{byes} బై{'లు' if byes>1 else ''}." if te else f"{byes} bye{'s' if byes>1 else ''}.")
    elif legbyes:
        sentence=(f"{legbyes} లెగ్ బై{'లు' if legbyes>1 else ''}." if te else f"{legbyes} leg bye{'s' if legbyes>1 else ''}.")
    elif runs==6:
        sentence=(f"{batter} సిక్స్ కొట్టాడు!" if te else f"Six runs off {batter}'s bat!")
    elif runs==4:
        sentence=(f"{batter} నాలుగు పరుగులు సాధించాడు!" if te else f"Four runs for {batter}!")
    elif runs==0 and extra_runs==0:
        sentence=(f"{bowler} డాట్ బాల్ వేశాడు." if te else f"Dot ball from {bowler}.")
    elif runs==0:
        sentence=(f"{extra_runs} అదనపు పరుగులు." if te else f"{extra_runs} extra run(s).")
    else:
        sentence=(f"{batter} {runs} పరుగులు సాధించాడు." if te else f"{batter} takes {runs} run(s).")
    key=json.dumps([mid,ball.get("innings"),over,delivery,ball.get("event_id"),language],ensure_ascii=False)
    return {"match_id":mid,"event_id":hashlib.sha256(key.encode()).hexdigest(),"over":label,
            "language":language,"text":f"{label} — {sentence}",
            "origin":"SH original event commentary","verified":bool(ball.get("verified"))}

def normalize_feed_event(event):
    """Only facts needed for SH's independent commentary; ignore source prose."""
    allowed=("match_id","innings","over","ball","event_id","batter","bowler",
             "runs_bat","extras","wicket","wicket_kind","verified")
    return {k:event[k] for k in allowed if k in event}
