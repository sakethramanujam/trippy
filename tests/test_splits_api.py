"""End-to-end API behaviour for split expenses, settling and groups."""


def split(client, trip, **body):
    return client.post(f"/trips/{trip}/expenses/split", json=body)


def ledger(client, trip):
    return client.get(f"/trips/{trip}/ledger").json()


def nets(led):
    return {p["user_id"]: p["net_cents"] for p in led["people"]}


def test_100_split_three_ways_sums_to_exactly_100(client, people):
    r = split(client, people["trip"], amount=100, description="Dinner", payer_id=people["a"],
              split_among=[people["a"], people["b"], people["c"]])
    assert r.status_code == 200, r.text
    e = r.json()
    assert e["amount_cents"] == 10000
    assert sum(s["amount_cents"] for s in e["splits"]) == 10000
    assert round(sum(s["amount_owed"] for s in e["splits"]), 2) == 100.00
    assert nets(ledger(client, people["trip"])) == {people["a"]: 6666, people["b"]: -3333, people["c"]: -3333}


def test_validation(client, people):
    t, a, b = people["trip"], people["a"], people["b"]
    assert split(client, t, amount=-5, description="x", payer_id=a, split_among=[a]).status_code == 400
    assert split(client, t, amount=10, description="x", payer_id=a, split_among=[a, a]).status_code == 400
    assert split(client, t, amount=10, description="x", payer_id=a, split_among=[999]).status_code == 400
    r = split(client, t, amount=50, description="x", payer_id=a, split_mode="exact",
              splits=[{"user_id": a, "value": 20}, {"user_id": b, "value": 20}])
    assert r.status_code == 400 and "short by $10.00" in r.json()["detail"]


def test_exact_percent_shares(client, people):
    t, a, b, c = people["trip"], people["a"], people["b"], people["c"]
    r = split(client, t, amount=50, description="Taxi", payer_id=b, split_mode="exact",
              splits=[{"user_id": a, "value": 12.5}, {"user_id": b, "value": 7.5}, {"user_id": c, "value": 30}])
    assert [s["amount_cents"] for s in r.json()["splits"]] == [1250, 750, 3000]
    r = split(client, t, amount=200, description="Hotel", payer_id=a, split_mode="percent",
              splits=[{"user_id": a, "value": 50}, {"user_id": b, "value": 25}, {"user_id": c, "value": 25}])
    assert [s["amount_cents"] for s in r.json()["splits"]] == [10000, 5000, 5000]
    r = split(client, t, amount=100, description="Airbnb", payer_id=c, split_mode="shares",
              splits=[{"user_id": a, "value": 1}, {"user_id": b, "value": 1}, {"user_id": c, "value": 1}])
    assert sum(s["amount_cents"] for s in r.json()["splits"]) == 10000
    led = ledger(client, t)
    assert sum(nets(led).values()) == 0


def test_edit_resplits_and_delete(client, people):
    t, a, b, c = people["trip"], people["a"], people["b"], people["c"]
    e = split(client, t, amount=90, description="Lunch", payer_id=a, split_among=[a, b, c]).json()
    r = client.put(f"/expenses/{e['id']}", json={"amount": 120})
    assert r.status_code == 200
    assert [s["amount_cents"] for s in r.json()["splits"]] == [4000, 4000, 4000]
    r = client.put(f"/expenses/{e['id']}", json={"split_among": [a, b]})
    assert [s["amount_cents"] for s in r.json()["splits"]] == [6000, 6000]
    r = client.put(f"/expenses/{e['id']}", json={"split_mode": "exact",
                   "splits": [{"user_id": b, "value": 100}, {"user_id": c, "value": 20}]})
    assert r.json()["split_mode"] == "exact"
    assert {s["user_id"]: s["amount_cents"] for s in r.json()["splits"]} == {b: 10000, c: 2000}
    r = client.put(f"/expenses/{e['id']}", json={"amount": 130})
    assert r.status_code == 400  # exact split needs new amounts
    r = client.put(f"/expenses/{e['id']}", json={"payer_id": b})
    assert r.json()["payer_id"] == b
    assert client.delete(f"/expenses/{e['id']}").status_code == 204
    assert client.delete(f"/expenses/{e['id']}").status_code == 404
    assert all(v == 0 for v in nets(ledger(client, t)).values())


def test_settle_pair_and_all_record_history(client, people):
    t, a, b, c = people["trip"], people["a"], people["b"], people["c"]
    split(client, t, amount=90, description="Dinner", payer_id=a, split_among=[a, b, c])
    r = client.post(f"/trips/{t}/settle", json={"from_user_id": b, "to_user_id": a})
    assert r.status_code == 200 and r.json()["amount_cents"] == 3000
    led = ledger(client, t)
    assert nets(led) == {a: 3000, b: 0, c: -3000}
    assert len(led["settlements"]) == 1
    assert client.post(f"/trips/{t}/settle", json={"from_user_id": b, "to_user_id": a}).status_code == 400
    # partial payment
    r = client.post(f"/trips/{t}/settle", json={"from_user_id": c, "to_user_id": a, "amount": 10})
    assert nets(ledger(client, t))[c] == -2000
    r = client.post(f"/trips/{t}/settle-all")
    assert [(s["from_user_id"], s["to_user_id"], s["amount_cents"]) for s in r.json()] == [(c, a, 2000)]
    led = ledger(client, t)
    assert all(v == 0 for v in nets(led).values())
    assert len(led["settlements"]) == 3 and led["total_cents"] == 9000  # history kept
    # balances endpoint keeps its old shape
    assert client.get(f"/trips/{t}/balances").json() == []


def test_remove_traveler_blocked_by_open_balance(client, people):
    t, a, b = people["trip"], people["a"], people["b"]
    split(client, t, amount=20, description="Snacks", payer_id=a, split_among=[a, b])
    r = client.delete(f"/trips/{t}/participants/{b}")
    assert r.status_code == 409 and "$10.00" in r.json()["detail"]
    client.post(f"/trips/{t}/settle", json={"from_user_id": b, "to_user_id": a})
    assert client.delete(f"/trips/{t}/participants/{b}").status_code == 200


def test_group_combines_trips_and_standalone_debts(client, people, db):
    t, a, b, c = people["trip"], people["a"], people["b"], people["c"]
    g = client.post(f"/trips/{t}/group", json={"name": "Crew"}).json()
    assert {m["id"] for m in g["members"]} == {a, b, c} and g["trips"] == [{"id": t, "title": "Tokyo"}]
    # trip: A paid 90 for everyone -> B owes A 30, C owes A 30
    split(client, t, amount=90, description="Dinner", payer_id=a, split_among=[a, b, c])
    # second trip in the same group: B paid 60 split with C -> C owes B 30
    from app import models
    trip2 = models.Trip(title="Kyoto", owner_id=b)
    trip2.participants.append(db.get(models.User, c))
    db.add(trip2)
    db.commit()
    # Ana isn't on Kyoto, so she can't see or move it; Ben (its owner, also in the group) can.
    assert client.put(f"/trips/{trip2.id}/group", json={"group_id": g["id"]}).status_code == 404
    client.acting_as = b
    assert client.put(f"/trips/{trip2.id}/group", json={"group_id": g["id"]}).status_code == 200
    split(client, trip2.id, amount=60, description="Ryokan", payer_id=b, split_among=[b, c])
    client.acting_as = None
    # standalone: C already owes B $30 from before; B owes A $15
    assert client.post(f"/groups/{g['id']}/debts", json={"from_user_id": c, "to_user_id": b, "amount": 30}).status_code == 200
    assert client.post(f"/groups/{g['id']}/debts", json={"from_user_id": b, "to_user_id": a, "amount": 15}).status_code == 200
    bal = client.get(f"/groups/{g['id']}/balances").json()
    assert {p["user_id"]: p["net_cents"] for p in bal["people"]} == {a: 7500, b: 1500, c: -9000}
    pair = {(r["from_user_id"], r["to_user_id"]): r for r in bal["pairwise"]}
    assert pair[(b, a)]["amount_cents"] == 4500
    assert {x["source"] for x in pair[(b, a)]["breakdown"]} == {"Tokyo", "IOUs"}
    assert pair[(c, b)]["amount_cents"] == 6000
    plan = [(p["from_user_id"], p["to_user_id"], p["amount_cents"]) for p in bal["simplified"]]
    assert plan == [(c, a, 7500), (c, b, 1500)]  # B no longer pays anyone
    # the trip-only ledger is unaffected by the other trip and the standalone IOUs
    assert nets(ledger(client, t)) == {a: 6000, b: -3000, c: -3000}
    # settle one suggestion, then all
    r = client.post(f"/groups/{g['id']}/settle", json={"from_user_id": c, "to_user_id": a})
    assert r.json()["amount_cents"] == 7500 and r.json()["group_id"] == g["id"]
    client.post(f"/groups/{g['id']}/settle-all")
    bal = client.get(f"/groups/{g['id']}/balances").json()
    assert bal["simplified"] == [] and len(bal["settlements"]) == 2
    assert all(p["net_cents"] == 0 for p in bal["people"])


def test_group_chain_and_member_rules(client, people):
    a, b, c = people["a"], people["b"], people["c"]
    g = client.post("/groups", json={"name": "Roommates", "member_ids": [a, b, c]}).json()
    client.post(f"/groups/{g['id']}/debts", json={"from_user_id": a, "to_user_id": b, "amount": 10})
    client.post(f"/groups/{g['id']}/debts", json={"from_user_id": b, "to_user_id": c, "amount": 10})
    bal = client.get(f"/groups/{g['id']}/balances").json()
    assert [(r["from_user_id"], r["to_user_id"], r["amount_cents"]) for r in bal["simplified"]] == [(a, c, 1000)]
    assert len(bal["pairwise"]) == 2
    # nothing to settle A->B in the simplified view, but the raw pairwise view still shows it
    assert client.post(f"/groups/{g['id']}/settle", json={"from_user_id": a, "to_user_id": b}).status_code == 400
    r = client.post(f"/groups/{g['id']}/settle", json={"from_user_id": a, "to_user_id": b, "mode": "pairwise"})
    assert r.status_code == 200 and r.json()["amount_cents"] == 1000
    bal = client.get(f"/groups/{g['id']}/balances").json()
    assert [(r["from_user_id"], r["to_user_id"], r["amount_cents"]) for r in bal["pairwise"]] == [(b, c, 1000)]
    assert client.delete(f"/settlements/{bal['settlements'][0]['id']}").status_code == 204
    assert client.post(f"/groups/{g['id']}/debts", json={"from_user_id": a, "to_user_id": 999, "amount": 5}).status_code == 400
    assert client.delete(f"/groups/{g['id']}/members/{a}").status_code == 409
    assert client.delete(f"/groups/{g['id']}").status_code == 409
    added = client.post(f"/groups/{g['id']}/members", json={"name": "Dee"}).json()
    assert "Dee" in {m["username"] for m in added["members"]}
    assert client.delete(f"/groups/{g['id']}?force=true").status_code == 204
    assert client.get("/groups").json() == []


def test_delete_trip_removes_its_settlements(client, people):
    t, a, b = people["trip"], people["a"], people["b"]
    split(client, t, amount=20, description="Snacks", payer_id=a, split_among=[a, b])
    client.post(f"/trips/{t}/settle-all")
    assert client.delete(f"/trips/{t}?force=true").status_code == 204
