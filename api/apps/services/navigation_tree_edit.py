"""Pure navigation edits. Stable node names are identities, not display labels."""

import copy
import json


def edit_navigation_rows(rows: list[dict], name: str, changes: dict) -> list[tuple[dict, dict]]:
    if not isinstance(changes, dict) or not changes or set(changes) - {"display_name", "description", "parent_name"}:
        raise ValueError("Use display_name, description and/or parent_name")
    normalized = copy.deepcopy(rows)
    for row in normalized:
        # Infinity decodes tag fields to lists; ES returns scalar type_kwd.
        kind = row.get("type_kwd")
        if isinstance(kind, (list, tuple)):
            row["type_kwd"] = kind[0] if kind else ""
        for field in ("depth_int", "doc_count_int"):
            if row.get(field) is not None:
                row[field] = int(row[field])

    def identity(row: dict) -> str:
        return row["doc_id"] if row.get("type_kwd") == "nav_doc" else row["name"]

    nodes = {}
    for row in normalized:
        key = identity(row)
        if key in nodes:
            raise ValueError("Tree contains duplicate node identities")
        nodes[key] = copy.deepcopy(row)
        nodes[key]["name"] = key
    if name not in nodes:
        aliases = [identity(row) for row in normalized if row["name"] == name]
        if len(aliases) == 1:
            name = aliases[0]
        elif len(aliases) > 1:
            raise ValueError("Ambiguous document node name; use doc_id")
    if name not in nodes:
        raise ValueError("Navigation node not found")
    node = nodes[name]
    payload = json.loads(node.get("content_with_weight") or "{}")
    for key, limit in (("display_name", 200), ("description", 20000)):
        if key in changes:
            value = changes[key]
            if not isinstance(value, str) or len(value) > limit or (key == "display_name" and not value.strip()):
                raise ValueError(f"Invalid {key}")
            payload[key] = value.strip()
    node["content_with_weight"] = json.dumps(payload, ensure_ascii=False)
    if "parent_name" in changes:
        parent = changes["parent_name"]
        if not isinstance(parent, str) or not parent:
            raise ValueError("Invalid parent_name")
        if parent == "root":
            if node.get("type_kwd") != "nav_cluster":
                raise ValueError("Documents must belong to a topic")
        elif parent not in nodes or nodes[parent].get("type_kwd") != "nav_cluster":
            raise ValueError("Target topic not found")
        node["parent_kwd"] = parent

    # Recompute membership/depth from actual edges, never from old membership.
    # This also removes stale document membership after previous UI deletions.
    children: dict[str, list[str]] = {}
    for key, row in nodes.items():
        parent = row.get("parent_kwd") or "root"
        if parent != "root" and (parent not in nodes or nodes[parent].get("type_kwd") != "nav_cluster"):
            raise ValueError("Tree contains an orphan node; regenerate the tree first")
        children.setdefault(parent, []).append(key)
    visiting, complete = set(), set()

    def visit(key: str, depth: int) -> list[str]:
        if key in visiting:
            raise ValueError("Cannot move a topic into itself or its descendants")
        if depth > 63:
            raise ValueError("Navigation tree exceeds maximum depth")
        visiting.add(key)
        row = nodes[key]
        row["depth_int"] = depth
        if row.get("type_kwd") == "nav_doc":
            docs = [row["doc_id"]]
        else:
            docs = list(dict.fromkeys(doc for child in children.get(key, []) for doc in visit(child, depth + 1)))
            row["doc_ids_kwd"], row["doc_count_int"] = docs, len(docs)
        visiting.remove(key)
        complete.add(key)
        return docs

    for key in children.get("root", []):
        visit(key, 0)
    if len(complete) != len(nodes):
        raise ValueError("Cannot move a topic into itself or its descendants")
    patches = []
    for baseline in normalized:
        updated = nodes[identity(baseline)]
        patch = {key: value for key, value in updated.items() if baseline.get(key) != value}
        if patch:
            patches.append((baseline, patch))
    return patches
