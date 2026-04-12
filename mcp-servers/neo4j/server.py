#!/usr/bin/env python3
"""
Edwin Neo4j/Graphiti MCP Server

Exposes the Edwin knowledge graph (powered by Graphiti) to Claude Code.
Provides hybrid search (BM25 + cosine + BFS + cross-encoder reranking),
entity lookup, relationship traversal, raw Cypher, and health stats.
"""

import asyncio
import json
import os
import re
import sys
from datetime import datetime

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load credentials
load_dotenv(os.path.expanduser("~/.edwin/credentials/openai/env"))
load_dotenv(os.path.expanduser("~/.edwin/credentials/neo4j/env"))

NEO4J_URI = os.getenv("NEO4J_URI", f"bolt://localhost:{os.getenv('EDWIN_NEO4J_PORT', '7690')}")
NEO4J_USER = os.getenv("NEO4J_USER", os.getenv("EDWIN_NEO4J_USER", "neo4j"))
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", os.getenv("EDWIN_NEO4J_PASS", "changeme"))

# Lazy-init Graphiti instance
_graphiti = None


async def get_graphiti():
    global _graphiti
    if _graphiti is None:
        from graphiti_core import Graphiti

        _graphiti = Graphiti(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    return _graphiti


def _get_neo4j_driver():
    from neo4j import GraphDatabase

    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# Write-operation detection for read-only enforcement
WRITE_PATTERNS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL\s+\{|FOREACH)\b",
    re.IGNORECASE,
)

mcp = FastMCP("edwin-neo4j")


@mcp.tool()
async def kg_search(query: str, num_results: int = 10) -> str:
    """Hybrid search across the knowledge graph. Uses BM25 + cosine similarity + graph traversal + cross-encoder reranking. Returns facts (relationship edges) with source and target entities."""
    try:
        g = await get_graphiti()
        results = await g.search(query, num_results=num_results)
        if not results:
            return json.dumps({"results": [], "count": 0})

        items = []
        for edge in results:
            items.append(
                {
                    "fact": edge.fact,
                    "name": edge.name,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "created_at": str(edge.created_at) if edge.created_at else None,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                    "invalid_at": str(edge.invalid_at) if edge.invalid_at else None,
                    "episodes": edge.episodes if hasattr(edge, "episodes") else [],
                }
            )
        return json.dumps({"results": items, "count": len(items)})
    except Exception as e:
        return json.dumps({"error": str(e), "results": [], "count": 0})


@mcp.tool()
async def kg_search_nodes(query: str, num_results: int = 10) -> str:
    """Search entity nodes in the knowledge graph. Returns entities with names, summaries, and labels. Uses Graphiti's advanced hybrid search."""
    try:
        g = await get_graphiti()
        from graphiti_core.search.search_config_recipes import (
            COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
        )

        results = await g.search_(
            query, config=COMBINED_HYBRID_SEARCH_CROSS_ENCODER
        )

        nodes = []
        for node in results.nodes:
            nodes.append(
                {
                    "uuid": node.uuid,
                    "name": node.name,
                    "summary": node.summary if hasattr(node, "summary") else None,
                    "labels": node.labels if hasattr(node, "labels") else None,
                    "created_at": str(node.created_at) if node.created_at else None,
                }
            )

        edges = []
        for edge in results.edges:
            edges.append(
                {
                    "fact": edge.fact,
                    "name": edge.name,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                    "valid_at": str(edge.valid_at) if edge.valid_at else None,
                }
            )

        return json.dumps(
            {
                "nodes": nodes[:num_results],
                "edges": edges[:num_results],
                "node_count": len(nodes),
                "edge_count": len(edges),
            }
        )
    except Exception as e:
        return json.dumps({"error": str(e), "nodes": [], "edges": []})


@mcp.tool()
async def kg_entity_lookup(name: str) -> str:
    """Look up a specific entity by name (case-insensitive fuzzy match). Returns the entity's summary, labels, and relationships."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            # Find entity
            entity = session.run(
                "MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($name) "
                "RETURN n.uuid as uuid, n.name as name, n.summary as summary, n.labels as labels "
                "ORDER BY size(n.name) LIMIT 5",
                name=name,
            )
            entities = []
            for r in entity:
                # Get relationships for this entity
                rels = session.run(
                    "MATCH (n:Entity {uuid: $uuid})-[r:RELATES_TO]-(other:Entity) "
                    "RETURN r.name as rel_name, r.fact as fact, other.name as other_name, "
                    "type(r) as rel_type, "
                    "CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END as direction "
                    "LIMIT 20",
                    uuid=r["uuid"],
                )
                relationships = [
                    {
                        "name": rel["rel_name"],
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
    """Get all relationships for a named entity. Direction: 'outgoing', 'incoming', or 'both'. Returns facts connecting this entity to others."""
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            if direction == "outgoing":
                pattern = "(n:Entity)-[r:RELATES_TO]->(other:Entity)"
            elif direction == "incoming":
                pattern = "(n:Entity)<-[r:RELATES_TO]-(other:Entity)"
            else:
                pattern = "(n:Entity)-[r:RELATES_TO]-(other:Entity)"

            results = session.run(
                f"MATCH {pattern} WHERE toLower(n.name) CONTAINS toLower($name) "
                "RETURN r.name as rel_name, r.fact as fact, other.name as other_name, "
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
async def kg_write(cypher: str, params: str = "{}") -> str:
    """Execute a write Cypher query (CREATE, MERGE, DELETE, SET). Use for entity merges, cleanup, label fixes, relationship management. Params is a JSON string of query parameters."""
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
    """Health check: Neo4j connectivity, node/edge counts by type, Graphiti status."""
    status = {
        "neo4j": {"connected": False, "uri": NEO4J_URI},
        "graphiti": {"available": False},
    }

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            status["neo4j"]["connected"] = True

            # Count by label
            label_counts = {}
            for r in session.run(
                "MATCH (n) RETURN labels(n)[0] as label, count(n) as c ORDER BY c DESC"
            ):
                label_counts[r["label"]] = r["c"]
            status["neo4j"]["node_counts"] = label_counts
            status["neo4j"]["total_nodes"] = sum(label_counts.values())

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

    # Check Graphiti
    try:
        g = await get_graphiti()
        status["graphiti"]["available"] = True
        status["graphiti"]["version"] = "0.28.2"
    except Exception as e:
        status["graphiti"]["error"] = str(e)

    return json.dumps(status)


if __name__ == "__main__":
    mcp.run(transport="stdio")
