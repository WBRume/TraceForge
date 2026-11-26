from collections import defaultdict

from sqlalchemy import literal, select, union_all

from app.domains.task.models.task import TaskType
from app.domains.workspace_canvas import sources, tree_children

# Bound each subquery before hydrating assets. Wide sibling groups are left
# intact for manual expansion rather than represented by a partial sample.
CHILD_LIMIT = 6
TREE_LIMIT = 12
DEPTH_LIMIT = 4
QUERY_BATCH = 48


def _probe_children(db, workspace_id, kinds, dates, parents):
    reads = []
    for asset in parents:
        ref = asset.reference
        if ref.kind == "requirement" and asset.details.created_at and not dates.contains(asset.details.created_at):
            continue
        for kind, column, query in tree_children.child_queries(
            db,
            workspace_id,
            kinds,
            ref.kind,
            ref.id,
            dates,
            diagnosis=asset.details.task_type == TaskType.DIAGNOSIS.value,
        ):
            candidates = query.with_entities(column.label("child_id")).filter(column.is_not(None))
            if ref.kind == "case":
                candidates = candidates.distinct().order_by(column)
            bounded = candidates.limit(CHILD_LIMIT + 1).subquery()
            reads.append(select(literal(asset.node_id), literal(kind), bounded.c.child_id))
    results = defaultdict(dict)
    for offset in range(0, len(reads), QUERY_BATCH):
        for parent, kind, identifier in db.execute(union_all(*reads[offset : offset + QUERY_BATCH])):
            ref = sources.reference_for(kind, identifier)
            child = sources.catalog_node_id(ref)
            if parent != child:
                results[parent][child] = ref
    return results


def read_preview(db, workspace_id, kinds, calendar, dates, roots):
    assets = {asset.node_id: asset for asset in roots}
    frontier = {asset.node_id: asset.node_id for asset in roots}
    tree_sizes = {root: {root} for root in frontier}
    children = {}
    for _ in range(DEPTH_LIMIT):
        probes = _probe_children(db, workspace_id, kinds, dates, [assets[node] for node in frontier])
        requested = {}
        pending = {}
        for parent, root in sorted(frontier.items(), key=lambda entry: len(probes.get(entry[0], {}))):
            branch = probes.get(parent, {})
            if not branch or len(branch) > CHILD_LIMIT or len(tree_sizes[root] | branch.keys()) > TREE_LIMIT:
                continue
            tree_sizes[root].update(branch)
            ordered = sorted(branch, key=lambda node: (branch[node].kind, branch[node].id))
            children[parent] = ordered
            for node in ordered:
                if node not in assets:
                    requested[node] = branch[node]
                    pending.setdefault(node, root)
        if not requested:
            break
        loaded = sources.assets_for_references(db, workspace_id, requested.values())
        found = {asset.node_id: asset for asset in sources.assign_quarters(loaded, calendar)}
        assets.update((node, found[node]) for node in requested if node in found)
        frontier = {node: root for node, root in pending.items() if node in found}
        if not frontier:
            break
    return list(assets.values()), {
        parent: [node for node in branch if node in assets] for parent, branch in children.items()
    }
