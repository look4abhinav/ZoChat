from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parents[1] / "evals" / "datasets"


def test_classifier_dataset_loads():
    data = yaml.safe_load((BASE / "classifier.yaml").read_text())
    assert isinstance(data, list)
    names = [d["name"] for d in data]
    assert len(names) == len(set(names))


def test_support_dataset_loads():
    data = yaml.safe_load((BASE / "support.yaml").read_text())
    assert isinstance(data, list)
    names = [d["name"] for d in data]
    assert len(names) == len(set(names))
