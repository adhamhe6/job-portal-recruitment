import pytest

from tests.fixtures_resumes import backend_pdf
from tests.helpers import register_candidate
from tests.resume_helpers import upload

pytestmark = pytest.mark.e2e


async def test_smoke(client):
    cand = await register_candidate(client)
    r = await upload(client, cand, backend_pdf(), "jane.pdf")
    print(r.status_code, r.text[:2000])
    assert r.status_code == 202
    rid = r.json()["id"]
    g = await client.get(f"/api/v1/resumes/{rid}", headers=cand["h"])
    print(g.json())
    e = await client.get(f"/api/v1/resumes/{rid}/extracted", headers=cand["h"])
    print(e.status_code, e.text[:3000])
