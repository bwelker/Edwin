#!/usr/bin/env python3
"""
Edwin Neo4j MCP Server

Exposes the Edwin knowledge graph (curated org/deal graph) to Claude Code.
Search is BM25 fulltext via Neo4j's native Lucene indexes -- no embeddings,
no Graphiti, no external API dependencies. Provides entity lookup,
relationship traversal, raw Cypher, and health stats.

Fulltext indexes used:
  - node_name_and_summary  (Entity: name, summary)
  - edge_name_and_fact     (RELATES_TO: name, fact)
"""

import difflib
import json
import os
import re
import sqlite3
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load credentials
load_dotenv(os.path.expanduser("~/.edwin/credentials/neo4j/env"))

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "changeme")


def _get_neo4j_driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# Lucene special characters that must be escaped in fulltext query strings
_LUCENE_SPECIALS = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def _lucene_escape(query: str) -> str:
    """Escape Lucene special syntax so user text is treated as plain terms."""
    return _LUCENE_SPECIALS.sub(r"\\\1", query)


# Write-operation detection for read-only enforcement
WRITE_PATTERNS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+\{|FOREACH)\b",
    re.IGNORECASE,
)

# -- Provenance / tiered-merge guardrails -------------------------------------

# Relationship types are interpolated into Cypher -- restrict to safe identifiers.
REL_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

# Entity-merge thresholds, calibrated against a live graph's entity names.
# The most-similar pairs of DISTINCT real entities tend to land just under
# 0.96 (e.g. near-identical surnames like 'Jon Carter' vs 'Jon Carver', or
# product-name casing variants that are genuinely the same thing), so
# auto-merge is reserved for normalization-equivalent names (score >= 0.96 --
# in practice case/whitespace variants like 'Acme Corp'/'ACME CORP' = 1.0).
# Token-containment pairs ('Sam' vs 'Sam Rivera' = 0.85) land in the
# ambiguous band and queue for review: the graph legitimately holds distinct
# token-containment pairs ('Acme' vs 'Acme Legal', 'Project X' vs
# 'Project X firmware'). Below 0.75 is clear-new ('Sam' vs 'Sam Patterson' =
# 0.47, 'Jane Doe' vs 'Jamie Doe' = 0.73 -- genuinely distinct people).
MERGE_HIGH_THRESHOLD = 0.96   # >= this: treat as the same entity
MERGE_AMBIGUOUS_THRESHOLD = 0.75  # >= this (and < HIGH): queue for human review

PENDING_MERGES_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "kg" / "pending-merges.jsonl"
RESOLVED_MERGES_FILE = PENDING_MERGES_FILE.with_name("pending-merges-resolved.jsonl")

PRE_PROVENANCE_REF = "pre-provenance:backup"

# -- Identity-registry bridge --------------------------------------------------
#
# The identity registry (tools/identity/registry.py, sqlite) is the AUTHORITY
# for person identity. String similarity cannot see alias-class identity
# (e.g. a maiden-name/married-name pair scoring well below the ambiguous
# threshold), so for Person entities the registry is consulted BEFORE the
# similarity tiers: a registered person with a neo4j_uuid alias short-circuits
# straight to that graph node.

REGISTRY_DB = Path(__file__).resolve().parent.parent.parent / "data" / "identity" / "registry.db"


def _registry_connect(readonly: bool = True) -> sqlite3.Connection | None:
    """Open the identity registry. Returns None if the DB doesn't exist --
    the server must keep working without the registry."""
    if not REGISTRY_DB.exists():
        return None
    if readonly:
        conn = sqlite3.connect(f"file:{REGISTRY_DB}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(REGISTRY_DB))
    conn.row_factory = sqlite3.Row
    return conn


def _registry_resolve_person(name: str) -> dict | None:
    """Resolve a name to exactly one registered person (category='person')
    via exact case-insensitive name-alias match. Returns
    {person_id, display_name, neo4j_uuids: [...]} or None when the registry
    is absent, has no match, or has MULTIPLE candidate people (ambiguous
    registry state must not short-circuit the tiers)."""
    conn = _registry_connect(readonly=True)
    if conn is None:
        return None
    try:
        people = conn.execute(
            "SELECT DISTINCT p.id, p.display_name "
            "FROM aliases a JOIN canonical_people p ON a.canonical_id = p.id "
            "WHERE a.alias_type = 'name' AND a.alias_value = ? COLLATE NOCASE "
            "AND p.category = 'person'",
            (name.strip(),),
        ).fetchall()
        if len(people) != 1:
            return None
        person = people[0]
        uuids = [
            r["alias_value"]
            for r in conn.execute(
                "SELECT alias_value FROM aliases "
                "WHERE canonical_id = ? AND alias_type = 'neo4j_uuid' "
                "ORDER BY created_at, rowid",
                (person["id"],),
            )
        ]
        return {"person_id": person["id"], "display_name": person["display_name"], "neo4j_uuids": uuids}
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _registry_add_alias(person_id: str, alias_type: str, alias_value: str, source: str) -> bool:
    """Write an alias into the registry (INSERT OR IGNORE -- the alias PK is
    (type, value), so a value already registered elsewhere is left alone).
    Returns True if a row was inserted."""
    conn = _registry_connect(readonly=False)
    if conn is None:
        return False
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) "
            "VALUES (?, ?, ?, ?)",
            (person_id, alias_type, alias_value, source),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _name_similarity(a: str, b: str) -> float:
    """Combined name similarity: difflib ratio on casefolded names, with a
    floor of 0.85 when every token of the shorter name is an exact token of
    the longer one (the 'Sam' vs 'Sam Rivera' shape -- ambiguous by design)."""
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return 1.0
    ratio = difflib.SequenceMatcher(None, al, bl).ratio()
    ta, tb = set(al.split()), set(bl.split())
    if ta and tb:
        shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if shorter <= longer:
            ratio = max(ratio, 0.85)
    return ratio


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_today() -> str:
    """Today's date in the host's local timezone -- 'today' for valid_at
    defaults means the user's today, not UTC's."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _resolve_entities_exact(session, name: str) -> list:
    """Exact case-insensitive entity name match. Returns [{uuid, name, summary}]."""
    rows = session.run(
        "MATCH (n:Entity) WHERE toLower(n.name) = toLower($name) "
        "RETURN n.uuid AS uuid, n.name AS name, n.summary AS summary",
        name=name.strip(),
    )
    return [{"uuid": r["uuid"], "name": r["name"], "summary": r["summary"]} for r in rows]


mcp = FastMCP("edwin-neo4j")


@mcp.tool()
async def kg_search(query: str, num_results: int = 10) -> str:
    """BM25 fulltext search over relationship facts in the knowledge graph (Lucene index on RELATES_TO name+fact). Returns facts (relationship edges) with source and target entities, ranked by relevance. No embeddings involved."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            results = session.run(
                "CALL db.index.fulltext.queryRelationships('edge_name_and_fact', $q) "
                "YIELD relationship AS r, score "
                "WITH r, score, startNode(r) AS a, endNode(r) AS b "
                "RETURN r.fact AS fact, r.name AS name, type(r) AS rel_type, "
                "a.uuid AS source_node_uuid, a.name AS source_name, "
                "b.uuid AS target_node_uuid, b.name AS target_name, "
                "r.created_at AS created_at, r.valid_at AS valid_at, "
                "r.invalid_at AS invalid_at, r.episodes AS episodes, score "
                "ORDER BY score DESC LIMIT $limit",
                q=_lucene_escape(query),
                limit=num_results,
            )
            items = []
            for r in results:
                items.append(
                    {
                        "fact": r["fact"],
                        "name": r["name"],
                        "rel_type": r["rel_type"],
                        "source_node_uuid": r["source_node_uuid"],
                        "source_name": r["source_name"],
                        "target_node_uuid": r["target_node_uuid"],
                        "target_name": r["target_name"],
                        "created_at": str(r["created_at"]) if r["created_at"] else None,
                        "valid_at": str(r["valid_at"]) if r["valid_at"] else None,
                        "invalid_at": str(r["invalid_at"]) if r["invalid_at"] else None,
                        "episodes": r["episodes"] or [],
                        "score": r["score"],
                    }
                )
            return json.dumps({"results": items, "count": len(items)})
    except Exception as e:
        return json.dumps({"error": str(e), "results": [], "count": 0})
    finally:
        driver.close()


@mcp.tool()
async def kg_search_nodes(query: str, num_results: int = 10) -> str:
    """BM25 fulltext search over entity nodes (Lucene index on Entity name+summary). Returns entities with names, summaries, and labels, plus matching relationship facts. No embeddings involved."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            node_results = session.run(
                "CALL db.index.fulltext.queryNodes('node_name_and_summary', $q) "
                "YIELD node AS n, score "
                "RETURN n.uuid AS uuid, n.name AS name, n.summary AS summary, "
                "labels(n) AS labels, n.created_at AS created_at, score "
                "ORDER BY score DESC LIMIT $limit",
                q=_lucene_escape(query),
                limit=num_results,
            )
            nodes = []
            for n in node_results:
                nodes.append(
                    {
                        "uuid": n["uuid"],
                        "name": n["name"],
                        "summary": n["summary"],
                        "labels": n["labels"],
                        "created_at": str(n["created_at"]) if n["created_at"] else None,
                        "score": n["score"],
                    }
                )

            edge_results = session.run(
                "CALL db.index.fulltext.queryRelationships('edge_name_and_fact', $q) "
                "YIELD relationship AS r, score "
                "WITH r, score, startNode(r) AS a, endNode(r) AS b "
                "RETURN r.fact AS fact, r.name AS name, type(r) AS rel_type, "
                "a.uuid AS source_node_uuid, b.uuid AS target_node_uuid, "
                "r.valid_at AS valid_at, score "
                "ORDER BY score DESC LIMIT $limit",
                q=_lucene_escape(query),
                limit=num_results,
            )
            edges = []
            for e in edge_results:
                edges.append(
                    {
                        "fact": e["fact"],
                        "name": e["name"],
                        "rel_type": e["rel_type"],
                        "source_node_uuid": e["source_node_uuid"],
                        "target_node_uuid": e["target_node_uuid"],
                        "valid_at": str(e["valid_at"]) if e["valid_at"] else None,
                        "score": e["score"],
                    }
                )

            return json.dumps(
                {
                    "nodes": nodes,
                    "edges": edges,
                    "node_count": len(nodes),
                    "edge_count": len(edges),
                }
            )
    except Exception as e:
        return json.dumps({"error": str(e), "nodes": [], "edges": []})
    finally:
        driver.close()


@mcp.tool()
async def kg_entity_lookup(name: str) -> str:
    """Look up a specific entity by name (case-insensitive; exact matches rank above prefix matches, prefix above substring). Returns the entity's summary, labels, and relationships of every type."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            # Find entity: exact > prefix > contains, case-insensitive
            entity = session.run(
                "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($name) "
                "WITH n, CASE "
                "  WHEN toLower(n.name) = toLower($name) THEN 0 "
                "  WHEN toLower(n.name) STARTS WITH toLower($name) THEN 1 "
                "  ELSE 2 END AS rank "
                "RETURN n.uuid as uuid, n.name as name, n.summary as summary, n.labels as labels "
                "ORDER BY rank, size(n.name) LIMIT 5",
                name=name,
            )
            entities = []
            for r in entity:
                # Get relationships of every type for this entity
                rels = session.run(
                    "MATCH (n:Entity {uuid: $uuid})-[r]-(other:Entity) "
                    "RETURN r.name as rel_name, r.fact as fact, other.name as other_name, "
                    "type(r) as rel_type, "
                    "CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END as direction "
                    "LIMIT 20",
                    uuid=r["uuid"],
                )
                relationships = [
                    {
                        "name": rel["rel_name"],
                        "type": rel["rel_type"],
                        "fact": rel["fact"],
                        "other_entity": rel["other_name"],
                        "direction": rel["direction"],
                    }
                    for rel in rels
                ]
                entities.append(
                    {
                        "uuid": r["uuid"],
                        "name": r["name"],
                        "summary": r["summary"],
                        "labels": r["labels"],
                        "relationships": relationships,
                    }
                )
            return json.dumps({"entities": entities, "count": len(entities)})
    except Exception as e:
        return json.dumps({"error": str(e), "entities": [], "count": 0})
    finally:
        driver.close()


@mcp.tool()
async def kg_relationships(entity_name: str, direction: str = "both", limit: int = 20) -> str:
    """Get all relationships (every relationship type) for a named entity. Direction: 'outgoing', 'incoming', or 'both'. Returns facts connecting this entity to others."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            if direction == "outgoing":
                pattern = "(n:Entity)-[r]->(other:Entity)"
            elif direction == "incoming":
                pattern = "(n:Entity)<-[r]-(other:Entity)"
            else:
                pattern = "(n:Entity)-[r]-(other:Entity)"

            results = session.run(
                f"MATCH {pattern} WHERE toLower(n.name) CONTAINS toLower($name) "
                "RETURN r.name as rel_name, type(r) as rel_type, r.fact as fact, other.name as other_name, "
                "CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END as direction, "
                "r.valid_at as valid_at, r.invalid_at as invalid_at "
                f"LIMIT {min(limit, 50)}",
                name=entity_name,
            )
            rels = []
            for r in results:
                rels.append(
                    {
                        "name": r["rel_name"],
                        "type": r["rel_type"],
                        "fact": r["fact"],
                        "other_entity": r["other_name"],
                        "direction": r["direction"],
                        "valid_at": str(r["valid_at"]) if r["valid_at"] else None,
                        "invalid_at": str(r["invalid_at"]) if r["invalid_at"] else None,
                    }
                )
            return json.dumps({"relationships": rels, "count": len(rels)})
    except Exception as e:
        return json.dumps({"error": str(e), "relationships": [], "count": 0})
    finally:
        driver.close()


@mcp.tool()
async def kg_query(cypher: str) -> str:
    """Execute a read-only Cypher query against the knowledge graph. Write operations (CREATE, MERGE, DELETE, SET, REMOVE, DROP) are blocked."""
    if WRITE_PATTERNS.search(cypher):
        return json.dumps(
            {
                "error": "Write operations are not allowed. This tool only supports read-only queries (MATCH, RETURN, WITH, UNWIND, etc.).",
                "blocked": True,
            }
        )

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            result = session.run(cypher)
            records = []
            for r in result:
                record = {}
                for key in r.keys():
                    val = r[key]
                    if hasattr(val, "__dict__"):
                        record[key] = str(val)
                    elif isinstance(val, (list, dict)):
                        record[key] = val
                    else:
                        record[key] = val
                records.append(record)
            return json.dumps(
                {"results": records, "count": len(records)}, default=str
            )
    except Exception as e:
        return json.dumps({"error": str(e), "results": [], "count": 0})
    finally:
        driver.close()


@mcp.tool()
async def kg_add_fact(
    source_name: str,
    target_name: str,
    rel_type: str,
    fact: str,
    source_ref: str,
    valid_at: str = "",
) -> str:
    """Add a provenance-stamped fact edge between two existing entities. This is the preferred write path for relationships. source_ref is REQUIRED: a file path, message id, meeting id, or 'user:YYYY-MM-DD' for direct statements. valid_at (ISO date, default today) is when the fact became true in the world. If an active edge of the same rel_type already exists between the pair with a DIFFERENT fact text, that edge is invalidated (invalid_at stamped, never deleted) and linked to the new edge via supersedes/superseded_by uuids. Identical fact = no-op. Entities must already exist (use kg_add_entity first)."""
    if not source_ref or not source_ref.strip():
        return json.dumps({"error": "source_ref is required: file path, message id, meeting id, or 'user:YYYY-MM-DD'", "success": False})
    if not REL_TYPE_RE.match(rel_type):
        return json.dumps({"error": f"rel_type must match {REL_TYPE_RE.pattern} (e.g. RELATES_TO, HOLDS_ROLE)", "success": False})
    if not fact or not fact.strip():
        return json.dumps({"error": "fact text is required", "success": False})

    now_iso = _utc_now_iso()
    valid_at = valid_at.strip() or _local_today()

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            src = _resolve_entities_exact(session, source_name)
            tgt = _resolve_entities_exact(session, target_name)
            for label, matches, name in (("source", src, source_name), ("target", tgt, target_name)):
                if not matches:
                    return json.dumps({"error": f"{label} entity not found by exact name: {name!r}. Create it first with kg_add_entity.", "success": False})
                if len(matches) > 1:
                    return json.dumps({"error": f"{label} name {name!r} matches multiple entities: {matches}. Disambiguate first.", "success": False})

            src_uuid, tgt_uuid = src[0]["uuid"], tgt[0]["uuid"]

            # Active edges of this type between the pair
            active = list(session.run(
                f"MATCH (a:Entity {{uuid: $src}})-[r:{rel_type}]->(b:Entity {{uuid: $tgt}}) "
                "WHERE r.invalid_at IS NULL "
                "RETURN elementId(r) AS eid, r.uuid AS uuid, r.fact AS fact",
                src=src_uuid, tgt=tgt_uuid,
            ))

            for r in active:
                if (r["fact"] or "").strip().lower() == fact.strip().lower():
                    return json.dumps({
                        "success": True, "action": "noop_duplicate",
                        "message": "An active edge with identical fact text already exists.",
                        "edge_uuid": r["uuid"],
                    })

            new_uuid = str(uuid_module.uuid4())
            superseded = []
            for r in active:
                # Contradiction: invalidate the old edge (never delete/overwrite),
                # backfilling a uuid if the old edge predates uuid stamping.
                old_uuid = r["uuid"] or str(uuid_module.uuid4())
                session.run(
                    "MATCH ()-[r]->() WHERE elementId(r) = $eid "
                    "SET r.uuid = $old_uuid, r.invalid_at = datetime($now), "
                    "r.invalidation_reason = 'superseded by contradicting fact', "
                    "r.superseded_by = $new_uuid",
                    eid=r["eid"], old_uuid=old_uuid, now=now_iso, new_uuid=new_uuid,
                )
                superseded.append({"uuid": old_uuid, "fact": r["fact"]})

            create_params = {
                "src": src_uuid, "tgt": tgt_uuid, "uuid": new_uuid,
                "name": rel_type, "fact": fact.strip(), "source_ref": source_ref.strip(),
                "now": now_iso, "valid_at": valid_at,
            }
            supersedes_clause = ""
            if superseded:
                supersedes_clause = ", r.supersedes = $supersedes"
                old_uuids = [s["uuid"] for s in superseded]
                create_params["supersedes"] = old_uuids[0] if len(old_uuids) == 1 else old_uuids
            session.run(
                f"MATCH (a:Entity {{uuid: $src}}), (b:Entity {{uuid: $tgt}}) "
                f"CREATE (a)-[r:{rel_type}]->(b) "
                "SET r.uuid = $uuid, r.name = $name, r.fact = $fact, "
                "r.source_ref = $source_ref, r.created_at = datetime($now), "
                f"r.valid_at = datetime($valid_at){supersedes_clause}",
                **create_params,
            )
            return json.dumps({
                "success": True,
                "action": "created_superseding" if superseded else "created",
                "edge_uuid": new_uuid,
                "source": src[0]["name"], "target": tgt[0]["name"],
                "rel_type": rel_type, "valid_at": valid_at, "source_ref": source_ref.strip(),
                "superseded": superseded,
            })
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})
    finally:
        driver.close()


@mcp.tool()
async def kg_add_entity(name: str, entity_type: str, summary: str, source_ref: str) -> str:
    """Add an entity with provenance, guarded by identity-registry lookup then tiered merge logic. source_ref is REQUIRED (file path, message id, meeting id, or 'user:YYYY-MM-DD'). For Person entities, the identity registry (data/identity/registry.db) is consulted FIRST: a name that resolves to a registered person linked to a graph node short-circuits to that node (action=resolved_via_registry) -- this catches alias-class identity (e.g. a maiden name resolving to the person's married name) that string similarity cannot. Otherwise: exact name match (case-insensitive) or near-identical name (similarity >= 0.96) APPENDS the new summary to the existing entity -- no duplicate created. Ambiguous similarity (0.75-0.96, e.g. 'Sam' vs 'Sam Rivera'): NOTHING is created or merged; the candidate is queued to data/kg/pending-merges.jsonl for human review -- use the existing entity provisionally or wait. Clearly new names create a fresh entity. entity_type becomes a node label (e.g. Person, Organization, Project)."""
    if not source_ref or not source_ref.strip():
        return json.dumps({"error": "source_ref is required: file path, message id, meeting id, or 'user:YYYY-MM-DD'", "success": False})
    if not name or not name.strip():
        return json.dumps({"error": "name is required", "success": False})
    if entity_type and not LABEL_RE.match(entity_type):
        return json.dumps({"error": f"entity_type must match {LABEL_RE.pattern} (e.g. Person, Organization, Project)", "success": False})

    name = name.strip()
    now_iso = _utc_now_iso()
    today = _local_today()
    annotated_summary = f"[{today}, {source_ref.strip()}] {summary.strip()}"

    # Identity-registry short-circuit (Person entities only): the registry is
    # the authority for person identity. If it resolves the incoming name to a
    # registered person who already has a neo4j_uuid alias, use that graph node
    # directly -- alias-class identity (e.g. a maiden name resolving to the
    # person's married name) that string similarity cannot see. Registry
    # misses fall through to the similarity tiers unchanged.
    registry_person = None
    if entity_type and entity_type.strip().lower() == "person":
        registry_person = _registry_resolve_person(name)

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            if registry_person and registry_person["neo4j_uuids"]:
                for reg_uuid in registry_person["neo4j_uuids"]:
                    row = session.run(
                        "MATCH (n:Entity {uuid: $uuid}) RETURN n.uuid AS uuid, n.name AS name",
                        uuid=reg_uuid,
                    ).single()
                    if row:
                        session.run(
                            "MATCH (n:Entity {uuid: $uuid}) "
                            "SET n.summary = CASE WHEN n.summary IS NULL OR n.summary = '' "
                            "THEN $add ELSE n.summary + '\n' + $add END",
                            uuid=row["uuid"], add=annotated_summary,
                        )
                        return json.dumps({
                            "success": True,
                            "action": "resolved_via_registry",
                            "entity_uuid": row["uuid"], "entity_name": row["name"],
                            "registry_person_id": registry_person["person_id"],
                            "registry_person_name": registry_person["display_name"],
                            "message": (
                                f"Identity registry resolved {name!r} to "
                                f"{registry_person['display_name']!r} ({registry_person['person_id']}); "
                                f"summary appended to existing entity {row['name']!r}."
                            ),
                        })
                # Registered uuid(s) point at nodes that no longer exist --
                # treat as unlinked and fall through to the tiers.

            all_entities = [
                {"uuid": r["uuid"], "name": r["name"]}
                for r in session.run("MATCH (n:Entity) RETURN n.uuid AS uuid, n.name AS name")
                if r["name"]
            ]

            best_score, best = 0.0, None
            for ent in all_entities:
                s = _name_similarity(name, ent["name"])
                if s > best_score:
                    best_score, best = s, ent

            if best and best_score >= MERGE_HIGH_THRESHOLD:
                # Same entity: append new facts to the summary, never duplicate.
                session.run(
                    "MATCH (n:Entity {uuid: $uuid}) "
                    "SET n.summary = CASE WHEN n.summary IS NULL OR n.summary = '' "
                    "THEN $add ELSE n.summary + '\n' + $add END",
                    uuid=best["uuid"], add=annotated_summary,
                )
                result = {
                    "success": True,
                    "action": "updated_existing" if best_score == 1.0 else "merged_high_similarity",
                    "entity_uuid": best["uuid"], "entity_name": best["name"],
                    "similarity": round(best_score, 3),
                    "message": f"Matched existing entity {best['name']!r}; summary appended.",
                }
                if registry_person:
                    # Close the loop: register this graph node against the person
                    # so future writes short-circuit via the registry.
                    if _registry_add_alias(registry_person["person_id"], "neo4j_uuid", best["uuid"], "kg-write-path"):
                        result["registry_linked"] = registry_person["person_id"]
                return json.dumps(result)

            if best and best_score >= MERGE_AMBIGUOUS_THRESHOLD:
                # Ambiguous: queue for human review, do NOT create or merge.
                PENDING_MERGES_FILE.parent.mkdir(parents=True, exist_ok=True)
                entry = {
                    "candidate_name": name,
                    "existing_name": best["name"],
                    "existing_uuid": best["uuid"],
                    "similarity_signal": round(best_score, 3),
                    "candidate_summary": summary.strip(),
                    "entity_type": entity_type,
                    "source_ref": source_ref.strip(),
                    "date": today,
                }
                with open(PENDING_MERGES_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
                return json.dumps({
                    "success": True, "action": "queued_for_review",
                    "candidate_name": name,
                    "existing_name": best["name"], "existing_uuid": best["uuid"],
                    "similarity": round(best_score, 3),
                    "message": (
                        f"{name!r} is ambiguously similar to existing entity {best['name']!r} "
                        f"(similarity {best_score:.3f}). Nothing was created or merged; the candidate "
                        f"is queued in {PENDING_MERGES_FILE} for human review. Use the existing entity "
                        "provisionally, or wait for the merge decision."
                    ),
                })

            # Clearly new: create with provenance.
            new_uuid = str(uuid_module.uuid4())
            labels = ["Entity"] + ([entity_type] if entity_type else [])
            label_str = ":".join(labels)
            session.run(
                f"CREATE (n:{label_str}) "
                "SET n.uuid = $uuid, n.name = $name, n.summary = $summary, "
                "n.labels = $labels, n.created_at = datetime($now), n.source_ref = $source_ref",
                uuid=new_uuid, name=name, summary=annotated_summary,
                labels=labels, now=now_iso, source_ref=source_ref.strip(),
            )
            result = {
                "success": True, "action": "created",
                "entity_uuid": new_uuid, "entity_name": name,
                "closest_existing": best["name"] if best else None,
                "closest_similarity": round(best_score, 3) if best else None,
            }
            if registry_person:
                if _registry_add_alias(registry_person["person_id"], "neo4j_uuid", new_uuid, "kg-write-path"):
                    result["registry_linked"] = registry_person["person_id"]
            return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})
    finally:
        driver.close()


@mcp.tool()
async def kg_invalidate(
    reason: str,
    source_ref: str,
    edge_uuid: str = "",
    source_name: str = "",
    target_name: str = "",
    rel_type: str = "",
) -> str:
    """Explicitly invalidate a fact edge (the correction path). Sets invalid_at + invalidation_reason -- the edge is never deleted, preserving history. Target the edge by edge_uuid, OR by source_name + target_name + rel_type (invalidates all active edges of that type between the pair). reason and source_ref are REQUIRED."""
    if not reason or not reason.strip():
        return json.dumps({"error": "reason is required", "success": False})
    if not source_ref or not source_ref.strip():
        return json.dumps({"error": "source_ref is required: file path, message id, meeting id, or 'user:YYYY-MM-DD'", "success": False})
    if not edge_uuid and not (source_name and target_name and rel_type):
        return json.dumps({"error": "Provide edge_uuid, or all of source_name + target_name + rel_type.", "success": False})
    if rel_type and not REL_TYPE_RE.match(rel_type):
        return json.dumps({"error": f"rel_type must match {REL_TYPE_RE.pattern}", "success": False})

    now_iso = _utc_now_iso()
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            if edge_uuid:
                match = "MATCH ()-[r]->() WHERE r.uuid = $edge_uuid AND r.invalid_at IS NULL"
                params = {"edge_uuid": edge_uuid.strip()}
            else:
                match = (
                    f"MATCH (a:Entity)-[r:{rel_type}]->(b:Entity) "
                    "WHERE toLower(a.name) = toLower($src) AND toLower(b.name) = toLower($tgt) "
                    "AND r.invalid_at IS NULL"
                )
                params = {"src": source_name.strip(), "tgt": target_name.strip()}
            result = session.run(
                match + " SET r.invalid_at = datetime($now), r.invalidation_reason = $reason, "
                "r.invalidation_source_ref = $source_ref "
                "RETURN r.uuid AS uuid, r.fact AS fact",
                now=now_iso, reason=reason.strip(), source_ref=source_ref.strip(), **params,
            )
            invalidated = [{"uuid": r["uuid"], "fact": r["fact"]} for r in result]
            if not invalidated:
                return json.dumps({"error": "No active (non-invalidated) edge matched.", "success": False})
            return json.dumps({"success": True, "action": "invalidated", "count": len(invalidated), "edges": invalidated})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})
    finally:
        driver.close()


@mcp.tool()
async def kg_write(cypher: str, params: str = "{}") -> str:
    """Execute a raw write Cypher query (CREATE, MERGE, DELETE, SET). PREFER kg_add_fact / kg_add_entity / kg_invalidate -- raw writes bypass the provenance guardrails (source_ref stamping, contradiction invalidation, duplicate-entity merge queue). Use only for cleanup, label fixes, and structural maintenance that the structured tools cannot express. Params is a JSON string of query parameters."""
    driver = _get_neo4j_driver()
    try:
        query_params = json.loads(params) if params else {}
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid params JSON: {params}"})

    try:
        with driver.session() as session:
            result = session.run(cypher, **query_params)
            summary = result.consume()
            return json.dumps({
                "success": True,
                "counters": {
                    "nodes_created": summary.counters.nodes_created,
                    "nodes_deleted": summary.counters.nodes_deleted,
                    "relationships_created": summary.counters.relationships_created,
                    "relationships_deleted": summary.counters.relationships_deleted,
                    "properties_set": summary.counters.properties_set,
                    "labels_added": summary.counters.labels_added,
                    "labels_removed": summary.counters.labels_removed,
                },
            })
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})
    finally:
        driver.close()


@mcp.tool()
async def kg_stats() -> str:
    """Health check: Neo4j connectivity, node/edge counts by type."""
    status = {
        "neo4j": {"connected": False, "uri": NEO4J_URI},
        "search": {"mode": "bm25-fulltext", "embeddings": False},
    }

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            status["neo4j"]["connected"] = True

            # Count by label (nodes can carry multiple labels, e.g. Entity+Person)
            label_counts = {}
            for r in session.run(
                "MATCH (n) UNWIND labels(n) as label "
                "RETURN label, count(*) as c ORDER BY c DESC"
            ):
                label_counts[r["label"]] = r["c"]
            status["neo4j"]["node_counts"] = label_counts
            status["neo4j"]["total_nodes"] = session.run(
                "MATCH (n) RETURN count(n) as c"
            ).single()["c"]

            # Count by relationship type
            rel_counts = {}
            for r in session.run(
                "MATCH ()-[r]->() RETURN type(r) as t, count(r) as c ORDER BY c DESC"
            ):
                rel_counts[r["t"]] = r["c"]
            status["neo4j"]["relationship_counts"] = rel_counts
            status["neo4j"]["total_relationships"] = sum(rel_counts.values())

    except Exception as e:
        status["neo4j"]["error"] = str(e)
    finally:
        driver.close()

    return json.dumps(status)


if __name__ == "__main__":
    mcp.run(transport="stdio")
