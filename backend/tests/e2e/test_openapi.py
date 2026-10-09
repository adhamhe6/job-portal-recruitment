"""The published API description: complete, consistent with the error envelope, and free of internal fields."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from httpx import AsyncClient

from app.main import OPENAPI_TAGS, app

pytestmark = pytest.mark.e2e

METHODS = ("get", "post", "put", "patch", "delete")
FORBIDDEN_RESPONSE_FIELDS = {
    "password", "password_hash", "hashed_password", "token_hash", "refresh_token", "embedding", "search_tsv", "skills_text", "search_text", "dedupe_key",
    "embedding_source_hash", "raw_cosine", "job_hash", "candidate_hash", "family_id", "storage_key",
}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return app.openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [(m.upper(), path, op) for path, item in spec["paths"].items() for m, op in item.items() if m in METHODS]


def resolve(spec: dict[str, Any], node: Any) -> Any:
    while isinstance(node, dict) and "$ref" in node:
        node = spec["components"]["schemas"][node["$ref"].rsplit("/", 1)[1]]
    return node


def reachable_property_names(spec: dict[str, Any], node: Any, seen: set[str] | None = None) -> set[str]:
    """Every property name that can appear in a JSON document described by ``node``."""
    seen = seen if seen is not None else set()
    names: set[str] = set()
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"].rsplit("/", 1)[1]
            if ref in seen:
                return names
            seen.add(ref)
            return reachable_property_names(spec, spec["components"]["schemas"][ref], seen)
        names |= set(node.get("properties", {}))
        for value in node.values():
            names |= reachable_property_names(spec, value, seen)
    elif isinstance(node, list):
        for value in node:
            names |= reachable_property_names(spec, value, seen)
    return names


def test_the_document_builds_and_describes_the_service(spec: dict[str, Any]) -> None:
    assert spec["openapi"].startswith("3.")
    assert spec["info"]["title"] == "TalentLens API" and spec["info"]["version"] and "not an automated hiring decision" in spec["info"]["description"]
    assert len(operations(spec)) >= 100
    assert "/health" in spec["paths"] and "/health/ready" in spec["paths"] and "/api/v1/auth/login" in spec["paths"]
    json.dumps(spec)  # serialisable


async def test_docs_pages_are_served(client: AsyncClient) -> None:
    assert (await client.get("/openapi.json")).json()["info"]["title"] == "TalentLens API"
    for page in ("/docs", "/redoc"):
        r = await client.get(page)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]


def test_every_operation_has_a_summary_and_a_known_tag(spec: dict[str, Any]) -> None:
    known = {t["name"] for t in OPENAPI_TAGS}
    problems = []
    for method, path, op in operations(spec):
        if not (op.get("summary") or "").strip():
            problems.append(f"{method} {path}: no summary")
        tags = op.get("tags") or []
        if not tags:
            problems.append(f"{method} {path}: no tag")
        problems += [f"{method} {path}: unknown tag {t}" for t in tags if t not in known]
    assert problems == []


def test_operation_ids_are_unique_and_every_operation_documents_a_success_response(spec: dict[str, Any]) -> None:
    ids = [op["operationId"] for _, _, op in operations(spec)]
    assert len(ids) == len(set(ids))
    for method, path, op in operations(spec):
        assert any(code.startswith("2") for code in op["responses"]), f"{method} {path} documents no success response"


def test_every_declared_tag_is_used_and_described(spec: dict[str, Any]) -> None:
    used = {t for _, _, op in operations(spec) for t in op["tags"]}
    declared = {t["name"]: t.get("description", "") for t in spec["tags"]}
    assert used == set(declared) and all(d.strip() for d in declared.values())


def test_path_parameters_are_declared_for_every_templated_path(spec: dict[str, Any]) -> None:
    for method, path, op in operations(spec):
        templated = set(re.findall(r"{(\w+)}", path))
        declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
        assert templated == declared, (method, path)


def test_documented_validation_errors_use_the_real_envelope(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    assert set(schemas["ErrorResponse"]["properties"]) == {"error"}
    assert set(schemas["ErrorBody"]["properties"]) == {"code", "message", "details", "request_id"}
    checked = 0
    for method, path, op in operations(spec):
        for code, response in op["responses"].items():
            if code in ("422",) and "content" in response:
                assert response["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}, (method, path)
                checked += 1
            if code.startswith(("4", "5")) and "content" in response:
                ref = response["content"]["application/json"]["schema"].get("$ref", "")
                assert ref.endswith("/ErrorResponse"), (method, path, code, ref)
    assert checked > 50


def test_no_response_schema_exposes_secrets_or_internal_fields(spec: dict[str, Any]) -> None:
    offenders = []
    for method, path, op in operations(spec):
        for code, response in op["responses"].items():
            for media in response.get("content", {}).values():
                names = reachable_property_names(spec, media.get("schema", {}))
                if names & FORBIDDEN_RESPONSE_FIELDS:
                    offenders.append((method, path, code, sorted(names & FORBIDDEN_RESPONSE_FIELDS)))
    assert offenders == []


def test_request_only_secrets_do_exist_but_only_on_requests(spec: dict[str, Any]) -> None:
    login = spec["paths"]["/api/v1/auth/login"]["post"]
    body = resolve(spec, login["requestBody"]["content"]["application/json"]["schema"])
    assert "password" in body["properties"]
    response = resolve(spec, login["responses"]["200"]["content"]["application/json"]["schema"])
    assert "password" not in reachable_property_names(spec, response)
    assert {"access_token", "token_type", "expires_in", "user"} <= set(response["properties"])


def test_authentication_is_described_as_a_bearer_flow(spec: dict[str, Any]) -> None:
    scheme = spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]
    assert scheme["type"] == "oauth2" and scheme["flows"]["password"]["tokenUrl"] == "/api/v1/auth/token"
    me = spec["paths"]["/api/v1/auth/me"]["get"]
    assert me["security"] == [{"OAuth2PasswordBearer": []}]
    assert "security" not in spec["paths"]["/api/v1/skills"]["get"], "public endpoints require no credentials"
    assert "security" not in spec["paths"]["/health"]["get"]


def test_list_endpoints_share_the_pagination_envelope(spec: dict[str, Any]) -> None:
    paged = ["/api/v1/users", "/api/v1/companies", "/api/v1/skills", "/api/v1/jobs", "/api/v1/search/jobs", "/api/v1/search/candidates", "/api/v1/applications", "/api/v1/notifications"]
    for path in paged:
        schema = resolve(spec, spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"])
        assert {"items", "page", "page_size", "total", "pages"} <= set(schema["properties"]), path
        params = {p["name"]: p for p in spec["paths"][path]["get"].get("parameters", [])}
        assert params["page"]["schema"]["minimum"] == 1 and params["page_size"]["schema"]["maximum"] == 100, path


def test_enumerated_inputs_are_documented_as_enums(spec: dict[str, Any]) -> None:
    params = {p["name"]: p for p in spec["paths"]["/api/v1/search/jobs"]["get"]["parameters"]}
    assert set(resolve(spec, params["sort"]["schema"])["enum"]) >= {"relevance", "newest", "salary_desc", "salary_asc", "deadline", "match", "title"}
    emp = params["employment_type"]["schema"]["items"]
    assert set(resolve(spec, emp)["enum"]) == {"FULL_TIME", "PART_TIME", "CONTRACT", "INTERNSHIP", "TEMPORARY"}
    rec = {p["name"]: p for p in spec["paths"]["/api/v1/recommendations/jobs"]["get"]["parameters"]}
    assert "enum" in resolve(spec, rec["workplace_type"]["schema"]["items"]), "recommendation filters are validated, not free text"
