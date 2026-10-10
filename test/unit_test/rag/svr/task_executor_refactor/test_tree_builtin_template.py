"""The Tree preset must be saveable without unused entity type errors."""
from pathlib import Path

import yaml


def test_tree_has_no_placeholder_entity_or_relation_types():
    root = Path(__file__).resolve().parents[5]
    preset = yaml.safe_load((root / "api/db/init_data/compilation_templates/tree.yaml").read_text(encoding="utf-8"))
    assert preset["config"]["entity"]["fields"] == []
    assert preset["config"]["relation"]["fields"] == []
    assert "{cluster_content}" in preset["config"]["raptor"]["prompt"]
