from tests.factories import auth

_SCHEMA = {"fields": [
    {"type": "amount", "key": "total", "label": "Сумма", "currencies": ["KZT", "USD"]},
    {"type": "text", "key": "reason", "label": "Обоснование"},
    {"type": "static_text", "key": "hdr", "label": "H", "content": "заголовок"},
]}
_WF = {
    "nodes": [
        {"id": "s", "type": "start"},
        {"id": "a", "type": "approval", "assignee": {"kind": "user", "id": 9}, "mode": "any"},
        {"id": "ok", "type": "end_approved"}, {"id": "no", "type": "end_rejected"},
    ],
    "edges": [
        {"from": "s", "to": "a"}, {"from": "a", "to": "ok", "on": "approve"},
        {"from": "a", "to": "no", "on": "reject"},
    ],
}

META = ["Номер запроса", "Статус", "Отправлено", "Завершено", "Инициатор", "Текущий согласующий"]


async def _source_for(client, template_id):
    r = await client.get("/api/requests/v1/reference-sources/", headers=auth(1))
    return next((s for s in r.json() if s.get("template_id") == template_id), None)


async def test_template_creates_data_table(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Счёт"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    src = await _source_for(client, tid)
    assert src is not None
    assert src["columns"] == META


async def test_publish_updates_columns(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Счёт2"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF}, headers=auth(1, is_staff=True))
    src = await _source_for(client, tid)
    assert "Сумма" in src["columns"]
    assert "Обоснование" in src["columns"]
    assert "H" not in src["columns"]  # static_text is skipped


async def test_instance_syncs_row(client):
    r = await client.post("/api/requests/v1/templates/", json={"name": "Счёт3"}, headers=auth(1, is_staff=True))
    tid = r.json()["id"]
    await client.post(f"/api/requests/v1/templates/{tid}/versions/",
                      json={"schema_json": _SCHEMA, "workflow_json": _WF}, headers=auth(1, is_staff=True))
    sid = (await _source_for(client, tid))["id"]

    r = await client.post("/api/requests/v1/instances/", json={
        "template_id": tid,
        "form_values": {"total": {"currency": "KZT", "amount": 70000}, "reason": "камеры"},
    }, headers=auth(1))
    iid, code = r.json()["id"], r.json()["code"]
    await client.post(f"/api/requests/v1/instances/{iid}/submit/", headers=auth(1))

    rows = (await client.get(f"/api/requests/v1/reference-sources/{sid}/rows/", headers=auth(1))).json()
    assert len(rows) == 1  # upserted, not duplicated across create+submit
    d = rows[0]["data"]
    assert d["Номер запроса"] == code
    assert d["Статус"] == "На рассмотрении"
    assert d["Сумма"] == "70000 KZT"
    assert d["Обоснование"] == "камеры"
