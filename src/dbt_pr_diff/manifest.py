import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelSpec:
    unique_id: str
    name: str
    schema: str
    alias: str
    keys: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)


def load(target_dir: Path) -> dict:
    return json.loads((Path(target_dir) / "manifest.json").read_text())


def _meta(obj: dict) -> dict:
    return {**(obj.get("meta") or {}), **((obj.get("config") or {}).get("meta") or {})}


def _keys(manifest: dict, node: dict) -> list[str]:
    declared = _meta(node).get("diff_key")
    if declared:
        return [declared] if isinstance(declared, str) else list(declared)
    for test in manifest["nodes"].values():
        if (
            test["resource_type"] == "test"
            and test.get("attached_node") == node["unique_id"]
            and (test.get("test_metadata") or {}).get("name") == "unique"
            and test.get("column_name")
        ):
            return [test["column_name"]]
    return []


def spec(manifest: dict, unique_id: str) -> ModelSpec:
    node = manifest["nodes"][unique_id]
    metrics = [
        name
        for name, col in node.get("columns", {}).items()
        if _meta(col).get("diff_metric")
    ]
    return ModelSpec(
        unique_id=unique_id,
        name=node["name"],
        schema=node["schema"],
        alias=node.get("alias") or node["name"],
        keys=_keys(manifest, node),
        metrics=metrics,
    )


def model_ids(manifest: dict) -> set[str]:
    return {
        uid
        for uid, node in manifest["nodes"].items()
        if node["resource_type"] == "model"
        and (node.get("config") or {}).get("materialized") != "ephemeral"
    }
