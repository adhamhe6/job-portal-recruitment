import uuid, pytest
from tests.helpers import *
from tests.helpers_spine import *
from tests.integration.test_matching_lifecycle import small_world, match_row, RANK

async def test_probe(client):
    w = await small_world(client)
    cid, jid = w["cand"]["candidate_id"], w["job"]["id"]
    before = await match_row(jid, cid)
    print("BEFORE", before.candidate_hash[:8], before.overall_score)
    await sql("UPDATE candidate_profiles SET years_experience = 1 WHERE id = :c", c=uuid.UUID(cid))
    print(await sql("SELECT years_experience FROM candidate_profiles WHERE id = :c", c=uuid.UUID(cid)))
    d = (await client.get(f"{RANK}/{jid}/candidates/{cid}", headers=w["rec"]["h"])).json()
    print("DETAIL", d["explanation"]["experience"], d["breakdown"])
    after = await match_row(jid, cid)
    print("AFTER", after.candidate_hash[:8], after.overall_score)
