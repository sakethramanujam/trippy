#!/usr/bin/env python3
"""End-to-end check against a running Trippy server (stdlib only).

    python3 deploy/e2e_check.py http://localhost:8000

Creates accounts, so point it at a throwaway server: the first signup takes over existing data.
The server needs TRIPPY_DEV_MODE=1 for the password-reset step.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
RUN = str(int(time.time()))
results = []


def call(method, path, body=None, token=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode(errors="replace")


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def signup(tag):
    email = f"{tag}-{RUN}@example.org"
    s, b = call("POST", "/auth/signup", {"email": email, "password": "correct horse 9", "name": tag.title()})
    return email, s, b


s, b = call("GET", "/health")
check("health", s == 200, str(b))
s, _ = call("GET", "/trips/")
check("no token -> 401", s == 401, str(s))

a_email, s, a = signup("alice")
check("signup A (first account claims existing data)", s == 201, str(a.get("claimed") if isinstance(a, dict) else a))
A = a["access_token"]
counts = {p: len(call("GET", p, token=A)[1]) for p in
          ("/trips/?limit=1000", "/rental_cars/?limit=1000", "/flights/", "/expenses/", "/groups/", "/users/")}
print("     A sees:", counts)
check("A sees the migrated trips", counts["/trips/?limit=1000"] > 0)

b_email, s, bb = signup("bob")
check("signup B", s == 201)
B = bb["access_token"]
s, trips_b = call("GET", "/trips/", token=B)
check("B sees no trips", s == 200 and trips_b == [], str(len(trips_b)))
check("B sees no rentals", call("GET", "/rental_cars/", token=B)[1] == [])
check("B sees no expenses", call("GET", "/expenses/", token=B)[1] == [])
a_trip = call("GET", "/trips/?limit=1", token=A)[1][0]["id"]
check("B gets 404 on A's trip", call("GET", f"/trips/{a_trip}", token=B)[0] == 404)
check("B can't delete A's trip", call("DELETE", f"/trips/{a_trip}", token=B)[0] == 404)

s, shared = call("POST", "/trips/", {"title": f"E2E shared {RUN}", "start_date": "2027-03-01T00:00",
                                     "end_date": "2027-03-05T00:00"}, token=A)
check("A creates a trip", s in (200, 201), str(s))
tid = shared["id"]
s, t = call("POST", f"/trips/{tid}/travelers", {"name": "Bob", "email": b_email}, token=A)
check("A invites B by email (existing account)", s == 200)
ids = call("GET", "/trips/", token=B)[1]
check("B now sees exactly the shared trip", [x["id"] for x in ids] == [tid], str([x["id"] for x in ids]))
check("B still 404 on A's other trip", call("GET", f"/trips/{a_trip}", token=B)[0] == 404)

c_email = f"carol-{RUN}@example.org"
s, _ = call("POST", f"/trips/{tid}/travelers", {"name": "Carol", "email": c_email}, token=A)
inv = call("GET", f"/trips/{tid}/invites", token=A)[1]
check("pending invite for a new email", s == 200 and any(i.get("email") == c_email for i in inv), str(inv)[:120])
s, c = call("POST", "/auth/signup", {"email": c_email, "password": "correct horse 9", "name": "Carol"})
check("C signs up and claims the invite", s == 201 and bool(c.get("claimed")), str(c.get("claimed")))
C = c["access_token"]
check("C sees the shared trip", [x["id"] for x in call("GET", "/trips/", token=C)[1]] == [tid])

me_a = call("GET", "/me", token=A)[1]["id"]
s, exp = call("POST", f"/trips/{tid}/expenses/", {"amount": 90, "description": "E2E dinner", "payer_id": me_a}, token=A)
check("A adds an expense on the shared trip", s == 200, str(s))
check("B sees the shared expense", any(e["id"] == exp["id"] for e in call("GET", "/expenses/", token=B)[1]))
D = signup("dave")[2]["access_token"]
check("outsider D sees no expenses", call("GET", "/expenses/", token=D)[1] == [])
check("outsider D can't edit the expense", call("PUT", f"/expenses/{exp['id']}", {"amount": 1}, token=D)[0] == 404)

s, li = call("POST", "/auth/login", {"email": b_email, "password": "correct horse 9"})
check("login", s == 200)
s, rf = call("POST", "/auth/refresh", {"refresh_token": li["refresh_token"]})
check("refresh", s == 200)
check("logout", call("POST", "/auth/logout", token=rf["access_token"])[0] in (200, 204))
check("refresh after logout fails", call("POST", "/auth/refresh", {"refresh_token": rf["refresh_token"]})[0] == 401)

s, fg = call("POST", "/auth/forgot", {"email": b_email})
tok = fg.get("dev_reset_token") if isinstance(fg, dict) else None
check("forgot password (dev mode returns the code)", s == 200 and bool(tok))
if tok:
    s, _ = call("POST", "/auth/reset", {"token": tok, "password": "new horse 10!"})
    check("reset with code", s == 200)
    check("login with new password", call("POST", "/auth/login", {"email": b_email, "password": "new horse 10!"})[0] == 200)
    check("code is single-use", call("POST", "/auth/reset", {"token": tok, "password": "x" * 12})[0] == 400)

ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//e2e//EN\r\nBEGIN:VEVENT\r\nUID:e2e-" + RUN +
       "\r\nDTSTART:20270302T081500\r\nDTEND:20270302T113000\r\nSUMMARY:Flight UA 1234 SFO to SEA\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
s, pv = call("POST", "/import/preview", {"source": "ics", "text": ics}, token=C)
check("import preview (ics)", s == 200 and pv.get("new_count") == 1, str(pv)[:150])
items = [{"kind": i["kind"], "fields": i["fields"]} for i in pv.get("items", [])]
s, cm = call("POST", "/import/commit", {"items": items}, token=C)
check("import commit lands on the shared trip", s == 200 and cm["created"] and cm["created"][0]["trip_id"] == tid, str(cm)[:150])
s, pv2 = call("POST", "/import/preview", {"source": "ics", "text": ics}, token=A)
check("A sees it as a duplicate (shared trip)", s == 200 and pv2["new_count"] == 0)
s, pv3 = call("POST", "/import/preview", {"source": "ics", "text": ics}, token=D)
check("D (outsider) sees it as new", s == 200 and pv3["new_count"] == 1)

codes = [call("POST", "/auth/login", {"email": f"nobody-{RUN}@example.org", "password": "wrong password"})[0] for _ in range(11)]
check("login rate limit -> 429", 429 in codes, str(codes))

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
