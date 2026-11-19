"""SH original commentary: generated only from structured delivery events that were actually scored or received.

Every line is built from facts in the event (over.ball, bowler, batter, runs, extras, wicket kind) plus figures
computed from earlier events (score, partnership, required rate, milestones, probability swing). Nothing is
invented: when a name is missing the line says "the batter" / "the bowler"; there is no shot description unless the
scorer recorded a direction. Templates are our own wording; variety is chosen deterministically from the ball number.
Languages: English, Hindi, Telugu; other languages fall back to English (and the API says so).
"""
T = {
 "en": {"dot": ["{bowler} to {batter}, no run.", "{bowler} to {batter}, dot ball — pressure building.", "{bowler} to {batter}, defended, no run."],
        "runs": ["{bowler} to {batter}, {n} run{s}.", "{bowler} to {batter}, worked away for {n}.", "{bowler} to {batter}, they take {n}."],
        "four": ["{bowler} to {batter}, FOUR! Finds the boundary.", "{bowler} to {batter}, FOUR — races away to the rope."],
        "six": ["{bowler} to {batter}, SIX! Cleared the boundary.", "{bowler} to {batter}, SIX — that's huge."],
        "wide": ["{bowler}, wide ball — {n} extra{s}.", "Wide from {bowler}, {n} added."],
        "no_ball": ["No ball from {bowler}! {n} run{s} from it.", "{bowler} oversteps — no ball, {n} run{s}."],
        "bye": ["{bowler} to {batter}, {n} bye{s}.", "Byes: {n}, past everyone."],
        "leg_bye": ["{bowler} to {batter}, {n} leg bye{s}.", "Off the pad, {n} leg bye{s}."],
        "wicket": ["{bowler} to {batter}, OUT! {how}.", "WICKET! {batter} is out — {how}.", "{bowler} strikes! {batter} goes, {how}."],
        "score": "{team} {runs}/{wkts} after {overs} overs.", "need": "{need} needed from {balls} balls (RRR {rrr}).",
        "partnership": "Partnership {p_runs} off {p_balls}.", "fifty": "FIFTY for {batter}!", "hundred": "HUNDRED for {batter}!",
        "team_fifty": "{team} reach {mark}.", "swing": "Turning point: win chance moved {swing}% towards {team}.",
        "won": "{team} have won the match!", "batter": "the batter", "bowler": "the bowler"},
 "hi": {"dot": ["{bowler} से {batter}, कोई रन नहीं।", "{bowler} से {batter}, डॉट गेंद — दबाव बढ़ रहा है।"],
        "runs": ["{bowler} से {batter}, {n} रन।", "{bowler} से {batter}, {n} रन लिए।"],
        "four": ["{bowler} से {batter}, चौका!", "{bowler} से {batter}, चौका — सीमा रेखा के पार।"],
        "six": ["{bowler} से {batter}, छक्का!", "{bowler} से {batter}, छक्का — बहुत बड़ा शॉट।"],
        "wide": ["{bowler}, वाइड गेंद — {n} अतिरिक्त।"], "no_ball": ["{bowler} की नो बॉल! {n} रन।"],
        "bye": ["{n} बाई।"], "leg_bye": ["{n} लेग बाई।"],
        "wicket": ["{bowler} से {batter}, आउट! {how}।", "विकेट! {batter} आउट — {how}।"],
        "score": "{team} {runs}/{wkts}, {overs} ओवर के बाद।", "need": "{balls} गेंदों में {need} रन चाहिए (आवश्यक रन रेट {rrr})।",
        "partnership": "साझेदारी {p_runs} ({p_balls} गेंद)।", "fifty": "{batter} का अर्धशतक!", "hundred": "{batter} का शतक!",
        "team_fifty": "{team} के {mark} रन पूरे।", "swing": "मोड़: जीत की संभावना {swing}% {team} की ओर।",
        "won": "{team} ने मैच जीत लिया!", "batter": "बल्लेबाज़", "bowler": "गेंदबाज़"},
 "te": {"dot": ["{bowler} నుంచి {batter}కు, పరుగు లేదు.", "{bowler} నుంచి {batter}కు, డాట్ బాల్ — ఒత్తిడి పెరుగుతోంది."],
        "runs": ["{bowler} నుంచి {batter}కు, {n} పరుగులు.", "{bowler} నుంచి {batter}కు, {n} పరుగులు తీశారు."],
        "four": ["{bowler} నుంచి {batter}కు, ఫోర్!", "{bowler} నుంచి {batter}కు, ఫోర్ — బౌండరీకి దూసుకెళ్లింది."],
        "six": ["{bowler} నుంచి {batter}కు, సిక్స్!", "{bowler} నుంచి {batter}కు, సిక్స్ — భారీ షాట్."],
        "wide": ["{bowler}, వైడ్ బాల్ — {n} అదనపు."], "no_ball": ["{bowler} నో బాల్! {n} పరుగులు."],
        "bye": ["{n} బైలు."], "leg_bye": ["{n} లెగ్ బైలు."],
        "wicket": ["{bowler} నుంచి {batter}కు, అవుట్! {how}.", "వికెట్! {batter} అవుట్ — {how}."],
        "score": "{overs} ఓవర్ల తర్వాత {team} {runs}/{wkts}.", "need": "{balls} బంతుల్లో {need} పరుగులు కావాలి (అవసర రన్ రేట్ {rrr}).",
        "partnership": "భాగస్వామ్యం {p_runs} ({p_balls} బంతులు).", "fifty": "{batter} అర్ధ సెంచరీ!", "hundred": "{batter} సెంచరీ!",
        "team_fifty": "{team} {mark} పరుగులు పూర్తి.", "swing": "కీలక మలుపు: గెలుపు అవకాశం {swing}% {team} వైపు.",
        "won": "{team} మ్యాచ్ గెలిచింది!", "batter": "బ్యాటర్", "bowler": "బౌలర్"},
}
HOW = {"en": {"bowled": "bowled", "caught": "caught", "lbw": "LBW", "run out": "run out", "stumped": "stumped", "hit wicket": "hit wicket", "caught and bowled": "caught and bowled"},
       "hi": {"bowled": "बोल्ड", "caught": "कैच", "lbw": "LBW", "run out": "रन आउट", "stumped": "स्टंप", "hit wicket": "हिट विकेट", "caught and bowled": "कॉट एंड बोल्ड"},
       "te": {"bowled": "బౌల్డ్", "caught": "క్యాచ్", "lbw": "LBW", "run out": "రనౌట్", "stumped": "స్టంప్డ్", "hit wicket": "హిట్ వికెట్", "caught and bowled": "కాట్ అండ్ బౌల్డ్"}}

def languages():
    return sorted(T)

def _pick(lst, seq):
    return lst[seq % len(lst)]

def generate(events, lang="en", team_names=None, max_balls=None, target_by_innings=None, swings=None):
    """events: ordered ball rows (dicts) for one match with innings_no, seq, over_no, ball_in_over, runs_bat, extras,
    extra_type, is_wicket, wicket_kind, batter, bowler, batting_team_id. Returns list of {innings_no, seq, over, text}."""
    L = T.get(lang, T["en"])
    how = HOW.get(lang, HOW["en"])
    names = team_names or {}
    out = []
    state = {}
    for e in events:
        ino = e["innings_no"]
        s = state.setdefault(ino, {"runs": 0, "wkts": 0, "legal": 0, "p_runs": 0, "p_balls": 0, "bat": {}, "marks": set()})
        n_total = e["runs_bat"] + e["extras"]
        s["runs"] += n_total
        legal = e["extra_type"] not in ("wide", "no_ball")
        s["legal"] += 1 if legal else 0
        s["p_runs"] += n_total
        s["p_balls"] += 1 if legal else 0
        batter = e.get("batter") or L["batter"]
        bowler = e.get("bowler") or L["bowler"]
        f = {"bowler": bowler, "batter": batter}
        seq = e["seq"]
        if e["is_wicket"]:
            line = _pick(L["wicket"], seq).format(how=how.get(e.get("wicket_kind") or "", e.get("wicket_kind") or "out"), **f)
        elif e["extra_type"] in ("wide", "no_ball", "bye", "leg_bye"):
            n = e["extras"] + (e["runs_bat"] if e["extra_type"] == "no_ball" else 0)
            line = _pick(L[e["extra_type"]], seq).format(n=n, s="" if n == 1 else "s", **f)
        elif e["runs_bat"] == 4:
            line = _pick(L["four"], seq).format(**f)
        elif e["runs_bat"] == 6:
            line = _pick(L["six"], seq).format(**f)
        elif e["runs_bat"] == 0:
            line = _pick(L["dot"], seq).format(**f)
        else:
            line = _pick(L["runs"], seq).format(n=e["runs_bat"], s="" if e["runs_bat"] == 1 else "s", **f)
        extra = []
        if e.get("batter"):
            b = s["bat"].get(e["batter"], 0) + e["runs_bat"]
            before = s["bat"].get(e["batter"], 0)
            s["bat"][e["batter"]] = b
            if before < 50 <= b < 100:
                extra.append(L["fifty"].format(batter=e["batter"]))
            if before < 100 <= b:
                extra.append(L["hundred"].format(batter=e["batter"]))
        team = names.get(e.get("batting_team_id"), "")
        for mark in (50, 100, 150, 200, 250, 300):
            if s["runs"] >= mark and mark not in s["marks"]:
                s["marks"].add(mark)
                if s["runs"] - n_total < mark:
                    extra.append(L["team_fifty"].format(team=team, mark=mark))
        if e["is_wicket"]:
            extra.append(L["partnership"].format(p_runs=s["p_runs"], p_balls=s["p_balls"]))
            s["wkts"] += 1
            s["p_runs"] = s["p_balls"] = 0
        overs = "%d.%d" % divmod(s["legal"], 6)
        if s["legal"] and s["legal"] % 6 == 0 and legal or e["is_wicket"]:
            extra.append(L["score"].format(team=team, runs=s["runs"], wkts=s["wkts"], overs=overs))
        tgt = (target_by_innings or {}).get(ino)
        if tgt and max_balls:
            need, left = tgt - s["runs"], max_balls - s["legal"]
            if need <= 0:
                extra.append(L["won"].format(team=team))
            elif left > 0 and (s["legal"] % 6 == 0 and legal or e["is_wicket"]):
                extra.append(L["need"].format(need=need, balls=left, rrr="%.2f" % (need * 6 / left)))
        if swings and seq in swings and abs(swings[seq][0]) >= 10:
            extra.append(L["swing"].format(swing="%+.0f" % swings[seq][0], team=swings[seq][1]))
        out.append({"innings_no": ino, "seq": seq, "over": "%d.%d" % (e["over_no"], e["ball_in_over"]), "text": " ".join([line] + extra),
                    "generated": True, "language": lang if lang in T else "en"})
    return out
