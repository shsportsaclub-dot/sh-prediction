"""SH Cricket AI Assistant — grounded answers from the SH PREDICTION database.

Design:
* retrieve(): finds the facts in our own tables (matches, teams, venues, players, toss, results,
  published predictions, scorecards) plus a curated Laws knowledge base.
* AssistantModel: replaceable interface that turns retrieved facts into an answer. The default
  GroundedTemplateModel only states retrieved facts. A self-hosted or approved external model can be
  plugged in later by implementing answer(question, facts, language) — nothing else changes.
* If nothing relevant is stored, the answer says so. It never invents statistics.
"""
import os
import re

import engine

LAWS_EDITION = "MCC Laws of Cricket, 2017 Code (2026 edition, in force from 1 October 2026); ICC playing conditions where stated"
LAWS = [  # (keywords, law reference, plain-language summary written for SH PREDICTION)
    (("wide",), "Law 22 (Wide ball)", "A delivery is a wide if it passes too far from the striker for them to hit it with a normal cricket stroke from where they stand. One run is added to the batting side and the ball does not count in the over."),
    (("no ball", "no-ball", "noball"), "Law 21 (No ball)", "A no ball is called for an illegal delivery, for example the front foot landing with no part behind the popping crease. One run is added, the ball is re-bowled, and the striker cannot be out in most ways (run out is still possible)."),
    (("lbw", "leg before"), "Law 36 (Leg before wicket)", "The striker can be out LBW if the ball, not pitching outside leg stump, would have gone on to hit the wicket after striking the batter's body (not the bat), subject to where the impact was and whether a stroke was offered."),
    (("run out", "runout"), "Law 38 (Run out)", "A batter is run out when, while the ball is in play, their wicket is fairly put down by the fielding side while they are out of their ground."),
    (("stumped", "stumping"), "Law 39 (Stumped)", "The striker is stumped when the wicketkeeper puts down the wicket while the striker is out of their ground and not attempting a run."),
    (("caught", "catch"), "Law 33 (Caught)", "The striker is caught when a fielder takes a fair catch of a ball hit by the bat (or glove holding the bat) before it touches the ground."),
    (("bowled",), "Law 32 (Bowled)", "The striker is bowled when a fair delivery puts down their wicket, even after touching the bat or body."),
    (("hit wicket",), "Law 35 (Hit wicket)", "The striker is out hit wicket if they break their own wicket with the bat or body while receiving a delivery or setting off for a first run. The 2026 edition clarified this Law."),
    (("boundary", "four", "six"), "Law 19 (Boundaries)", "Four runs are scored when the ball reaches the boundary after touching the ground, six when it clears the boundary in the air. The 2026 edition changed how airborne boundary catches ('bunny-hop' catches) are judged."),
    (("super over",), "ICC playing conditions (Super Over)", "In ICC T20Is a tied match is decided by a Super Over; if that is also tied, further Super Overs are played. SH PREDICTION counts the Super Over winner as the match winner."),
    (("dls", "duckworth", "rain"), "ICC playing conditions (DLS method)", "In rain-reduced limited-overs matches the target is revised with the DLS method, which compares the resources (overs and wickets) each side had."),
    (("toss",), "Law 13 (Innings)", "The captains toss a coin before play; the winner chooses whether to bat or field first. SH PREDICTION treats the toss as a fair coin: 50% each."),
    (("tie", "result", "no result"), "Law 16 (The result)", "A match is won by the side scoring more runs; it is a tie when the scores are equal after all innings are complete. No result applies when play cannot produce a result."),
    (("over",), "Law 17 (The over)", "An over has six fair deliveries; wides and no balls do not count. The 2026 edition requires the last over of a day in multi-day cricket to be completed even if a wicket falls."),
    (("bat", "laminated"), "Law 5 (The bat)", "The 2026 edition allows laminated bats (Type D) in open-age recreational cricket, previously limited to junior cricket."),
]

class AssistantModel:
    name = "base"
    def answer(self, question, facts, language):
        raise NotImplementedError

class GroundedTemplateModel(AssistantModel):
    """States only retrieved facts. Works offline, costs nothing."""
    name = "sh-grounded-1"
    def answer(self, question, facts, language):
        if not facts:
            return ("I don't have verified data in SH PREDICTION for that yet. Try a team name or short code, a venue, "
                    "a match (e.g. 'UB vs EE'), or a Law such as 'LBW'.")
        return "\n".join(f["text"] for f in facts)

class NotConfiguredModel(AssistantModel):
    name = "external-not-configured"
    def answer(self, question, facts, language):
        raise RuntimeError("external assistant model is not configured; set SH_ASSISTANT_MODEL=grounded")

def get_model():
    return {"grounded": GroundedTemplateModel, "external": NotConfiguredModel}.get(os.getenv("SH_ASSISTANT_MODEL", "grounded"), GroundedTemplateModel)()

def _teams(c, q):
    found = []
    for t in c.execute("SELECT id,name,short_code,short_code_approved FROM teams"):
        code = t["short_code"] if t["short_code_approved"] else None
        name = t["name"].lower()
        if (len(name) >= 3 and re.search(r"(?<!\w)%s(?!\w)" % re.escape(name), q)) or (code and re.search(r"\b%s\b" % re.escape(code.lower()), q)):
            found.append(t)
    return found

def _label(t):
    return "%s (%s)" % (t["name"], t["short_code"]) if t["short_code"] and t["short_code_approved"] else t["name"]

def retrieve(c, question):
    q = " " + question.lower().strip() + " "
    facts = []
    teams = _teams(c, q)
    want_law = any(w in q for w in (" law", "rule", "what is", "explain", "how does"))
    for keys, ref, text in LAWS:
        if any(k in q for k in keys) and (want_law or not teams):
            facts.append({"kind": "law", "source": ref + " — " + LAWS_EDITION, "text": ref + ": " + text})
    if len(teams) >= 2:
        a, b = teams[0], teams[1]
        ms = c.execute("""SELECT m.*, r.winner_team_id, r.result_type, t.winner_team_id AS toss_winner FROM matches m
                          LEFT JOIN match_results r ON r.match_id=m.id LEFT JOIN toss_results t ON t.match_id=m.id
                          WHERE ((m.home_team_id=? AND m.away_team_id=?) OR (m.home_team_id=? AND m.away_team_id=?)) AND m.data_origin<>'demo'
                          ORDER BY m.start_utc""", (a["id"], b["id"], b["id"], a["id"])).fetchall()
        done = [m for m in ms if m["result_type"]]
        if ms:
            wa = sum(1 for m in done if m["winner_team_id"] == a["id"])
            wb = sum(1 for m in done if m["winner_team_id"] == b["id"])
            facts.append({"kind": "h2h", "source": "SH PREDICTION verified results",
                          "text": "Head-to-head in SH PREDICTION: %s won %d, %s won %d, other results %d (from %d stored matches)." % (_label(a), wa, _label(b), wb, len(done) - wa - wb, len(ms))})
            nxt = [m for m in ms if m["status"] == "scheduled"]
            if nxt:
                m = nxt[0]
                pub = c.execute("""SELECT p.prediction_type, t.name FROM predictions p JOIN prediction_publications pp ON pp.prediction_id=p.id
                                   LEFT JOIN teams t ON t.id=p.predicted_team_id WHERE p.match_id=? ORDER BY p.id""", (m["id"],)).fetchall()
                if pub:
                    facts.append({"kind": "prediction", "source": "Published SH PREDICTION picks",
                                  "text": "Published picks for the next meeting (%s): %s." % (m["start_utc"][:10], ", ".join("%s: %s" % (x[0], x[1]) for x in pub if x[1]))})
                else:
                    pm = engine.predict_match(c, m["id"])
                    home = a if a["id"] == m["home_team_id"] else b
                    facts.append({"kind": "model", "source": "SH AI pre-match model",
                                  "text": "SH AI gives %s a %.1f%% chance in the next meeting on %s (confidence: %s)." % (_label(home), pm["home_win_probability"], m["start_utc"][:10], pm["confidence_level"])})
    elif len(teams) == 1:
        t = teams[0]
        rs = c.execute("""SELECT r.winner_team_id, r.result_type FROM matches m JOIN match_results r ON r.match_id=m.id
                          WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.data_origin<>'demo' ORDER BY m.start_utc DESC LIMIT 10""", (t["id"], t["id"])).fetchall()
        if rs:
            w = sum(1 for r in rs if r["winner_team_id"] == t["id"])
            facts.append({"kind": "team", "source": "SH PREDICTION verified results",
                          "text": "%s: won %d of its last %d verified results in SH PREDICTION." % (_label(t), w, len(rs))})
        tw = c.execute("""SELECT COUNT(*) FROM toss_results tr JOIN matches m ON m.id=tr.match_id WHERE tr.winner_team_id=? AND m.data_origin<>'demo'""", (t["id"],)).fetchone()[0]
        tt = c.execute("""SELECT COUNT(*) FROM toss_results tr JOIN matches m ON m.id=tr.match_id WHERE (m.home_team_id=? OR m.away_team_id=?) AND m.data_origin<>'demo'""", (t["id"], t["id"])).fetchone()[0]
        if tt and "toss" in q:
            facts.append({"kind": "toss", "source": "SH PREDICTION verified tosses", "text": "%s won %d of %d verified tosses." % (_label(t), tw, tt)})
    for v in c.execute("SELECT * FROM venues"):
        if v["name"] and len(v["name"]) >= 3 and re.search(r"(?<!\w)%s(?!\w)" % re.escape(v["name"].lower()), q):
            st = engine.analytics(c)["venue"].get(v["name"])
            if st:
                facts.append({"kind": "venue", "source": "SH PREDICTION verified results",
                              "text": "%s: %d verified matches, batting first won %s%%." % (v["name"], st["matches"], st["batting_first_win_pct"])})
            proj = c.execute("""SELECT AVG(i.runs), COUNT(*) FROM innings i JOIN matches m ON m.id=i.match_id WHERE m.venue_id=? AND i.innings_no=1
                                AND i.completed=1 AND m.data_origin<>'demo'""", (v["id"],)).fetchone()
            if proj[1]:
                facts.append({"kind": "venue", "source": "SH PREDICTION scorecards",
                              "text": "Average first-innings total at %s: %d (%d innings)." % (v["name"], round(proj[0]), proj[1])})
    for p in c.execute("SELECT * FROM players"):
        if p["name"] and len(p["name"]) > 3 and re.search(r"(?<!\w)%s(?!\w)" % re.escape(p["name"].lower()), q):
            sts = c.execute("SELECT * FROM player_statistics WHERE player_id=?", (p["id"],)).fetchall()
            if sts:
                for s in sts:
                    facts.append({"kind": "player", "source": "SH PREDICTION player statistics",
                                  "text": "%s (%s): %s matches, %s runs, average %s, strike rate %s, %s wickets, economy %s." % (
                                      p["name"], s["format"], s["matches"], s["runs"], s["batting_avg"], s["strike_rate"], s["wickets"], s["economy"])})
            else:
                facts.append({"kind": "player", "source": "SH PREDICTION", "text": "%s is in our player list, but no verified statistics are stored yet." % p["name"]})
    if any(w in q for w in ("record", "highest total", "highest score", "highest innings")):
        r = c.execute("""SELECT i.runs, i.wickets, t.name, m.start_utc FROM innings i JOIN matches m ON m.id=i.match_id JOIN teams t ON t.id=i.batting_team_id
                         WHERE m.data_origin<>'demo' AND i.is_super_over=0 ORDER BY i.runs DESC LIMIT 1""").fetchone()
        if r:
            facts.append({"kind": "record", "source": "SH PREDICTION scorecards",
                          "text": "Highest stored innings total: %d/%d by %s on %s." % (r[0], r[1], r[2], r[3][:10])})
    return facts

def ask(c, question, language="en", user_id=None):
    question = (question or "").strip()
    if not 2 <= len(question) <= 500:
        raise ValueError("question must be 2-500 characters")
    facts = retrieve(c, question)
    model = get_model()
    text = model.answer(question, facts, language)
    c.execute("INSERT INTO assistant_queries(user_id,question,intent,grounded,language_code,created_at) VALUES(?,?,?,?,?,datetime('now'))",
              (user_id, question, ",".join(sorted({f["kind"] for f in facts})) or None, 1 if facts else 0, language))
    return {"answer": text, "grounded": bool(facts), "sources": sorted({f["source"] for f in facts}), "model": model.name,
            "language": "en", "language_note": None if language == "en" else "Answers are in English for now; names and numbers are kept as recorded."}
