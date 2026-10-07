import pytest
from tests.helpers import *
from tests.helpers_spine import *

async def test_probe(client):
    admin = await create_admin(client)
    rec = await register_employer(client, "Susp Co")
    job = await create_job(client, rec, publish=True)
    cand = await register_candidate(client)
    r = await client.patch(f"/api/v1/companies/{rec['company_id']}", headers=admin["h"], json={"status": "SUSPENDED"})
    print("PATCH", r.status_code)
    s = await client.get("/api/v1/search/jobs")
    print("search total", s.json()["total"])
    d = await client.get(f"/api/v1/jobs/{job['id']}")
    print("detail", d.status_code)
    a = await client.post("/api/v1/applications", headers=cand["h"], json={"job_id": job["id"]})
    print("apply", a.status_code)
    k = await client.get("/api/v1/skills", params={"q": "..."})
    print("skills ...", k.json()["total"])
    k = await client.get("/api/v1/skills", params={"q": "-"})
    print("skills -", k.json()["total"])
