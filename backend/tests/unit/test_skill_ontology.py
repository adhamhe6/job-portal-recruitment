"""Skill normalisation keys and the built-in ontology (pure logic, no database)."""

from __future__ import annotations

import re
from collections import Counter

import pytest

from app.matching.skills import ONTOLOGY, OntologySkill, skill_key


@pytest.mark.parametrize(
    ("variants", "expected"),
    [
        (["Node.js", "NodeJS", "node js", "Node JS", "node.JS", " NODE.JS ", "Ｎode.js"], "nodejs"),
        (["CI/CD", "ci cd", "CI-CD", "ci_cd", "cicd", "CI / CD"], "cicd"),
        (["Objective-C", "objective c", "Objective_C", "ObjectiveC"], "objectivec"),
        (["PostgreSQL", "postgresql", "PostgreSQL ", "Postgre SQL"], "postgresql"),
        (["PL/SQL", "pl sql", "PL-SQL"], "plsql"),
        (["Next.js", "nextjs", "Next JS"], "nextjs"),
        (["Machine Learning", "machine-learning", "machine_learning"], "machinelearning"),
    ],
)
def test_spelling_variants_collapse_to_one_key(variants: list[str], expected: str) -> None:
    assert {skill_key(v) for v in variants} == {expected}


def test_c_family_stays_distinct() -> None:
    keys = [skill_key(t) for t in ("C", "C++", "C#", "c ++", "c #")]
    assert keys == ["c", "c++", "c#", "c++", "c#"]
    assert len({"c", "c++", "c#"}) == 3


def test_dot_net_and_cicd_keys() -> None:
    assert skill_key(".NET") == "net"
    assert skill_key("ASP.NET") == "aspnet"
    assert skill_key("CI/CD") == skill_key("cicd")
    assert skill_key("R&D") == "randd"  # ampersand is spelled out so "A&B" and "A and B" agree
    assert skill_key("Q & A") == skill_key("Q and A")


def test_blank_and_punctuation_only_input_yields_empty_key() -> None:
    assert skill_key("") == ""
    assert skill_key("   ") == ""
    assert skill_key("...") == ""
    assert skill_key("-/_") == ""


def test_key_is_idempotent_and_case_insensitive() -> None:
    for s in ONTOLOGY:
        assert skill_key(skill_key(s.name)) == skill_key(s.name)
        assert skill_key(s.name.upper()) == skill_key(s.name.lower())


def test_ontology_is_non_trivial_and_well_formed() -> None:
    assert len(ONTOLOGY) >= 150
    names = [s.name for s in ONTOLOGY]
    assert len({n.casefold() for n in names}) == len(names), "duplicate canonical names"
    for s in ONTOLOGY:
        assert s.name.strip() == s.name and s.name
        assert s.category, f"{s.name} has no category"
        assert s.family is None or re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s.family), (
            f"bad family for {s.name}"
        )
        assert len(s.name) <= 100 and all(len(a) <= 100 for a in s.aliases)
        assert "~" not in s.name and not any("~" in a for a in s.aliases), (
            "ambiguity flag leaked into the data"
        )
        assert all(a == a.strip() and a for a in s.aliases)


def test_no_key_collisions_between_skills_and_aliases() -> None:
    owner: dict[str, str] = {}
    for s in ONTOLOGY:
        for term in (s.name, *s.aliases):
            key = skill_key(term)
            assert key, f"{term!r} normalises to an empty key"
            assert owner.setdefault(key, s.name) == s.name, f"{term!r} ({s.name}) collides with {owner[key]}"


def test_canonical_keys_are_unique() -> None:
    counts = Counter(s.key for s in ONTOLOGY)
    assert [k for k, n in counts.items() if n > 1] == []


@pytest.mark.parametrize(
    "name", ["Go", "Rust", "C", "R", "Ruby", "Swift", "Flask", "Excel", "Apache Spark", "Express", "Sketch"]
)
def test_ambiguous_terms_are_flagged(name: str) -> None:
    skill = next(s for s in ONTOLOGY if s.name == name)
    assert skill.ambiguous


@pytest.mark.parametrize(
    "name", ["Python", "PostgreSQL", "Docker", "Kubernetes", "FastAPI", "Node.js", "TypeScript"]
)
def test_unambiguous_terms_are_not_flagged(name: str) -> None:
    assert not next(s for s in ONTOLOGY if s.name == name).ambiguous


def test_aliases_resolve_to_expected_skills() -> None:
    index = {skill_key(t): s.name for s in ONTOLOGY for t in (s.name, *s.aliases)}
    assert index[skill_key("postgres")] == "PostgreSQL"
    assert index[skill_key("k8s")] == "Kubernetes"
    assert index[skill_key("golang")] == "Go"
    assert index[skill_key("nodejs")] == "Node.js"
    assert index[skill_key("csharp")] == "C#"
    assert index[skill_key("cpp")] == "C++"
    assert index[skill_key("js")] == "JavaScript"
    assert index[skill_key("continuous integration")] == "CI/CD"


def test_related_families_group_the_expected_skills() -> None:
    fam: dict[str, set[str]] = {}
    for s in ONTOLOGY:
        if s.family:
            fam.setdefault(s.family, set()).add(s.name)
    assert {"PostgreSQL", "MySQL", "MariaDB", "SQL Server", "SQLite", "Oracle Database"} <= fam[
        "relational-database"
    ]
    assert {"React", "Vue", "Angular", "Svelte"} <= fam["frontend-framework"]
    assert {"Django", "Flask", "FastAPI"} <= fam["python-web-framework"]
    # unrelated worlds are not in the same family
    pg_family = next(s.family for s in ONTOLOGY if s.name == "PostgreSQL")
    assert next(s.family for s in ONTOLOGY if s.name == "MongoDB") != pg_family
    assert next(s.family for s in ONTOLOGY if s.name == "Python") is None  # standalone skills have no family


def test_ontology_skill_dataclass_is_immutable() -> None:
    skill = ONTOLOGY[0]
    assert isinstance(skill, OntologySkill)
    with pytest.raises(AttributeError):
        skill.name = "other"  # type: ignore[misc]
