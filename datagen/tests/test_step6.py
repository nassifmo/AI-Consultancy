"""Tests for step 6: named datasets, config inheritance, detectability and counterfactual truth."""

from pathlib import Path

import pytest

from datagen.build_datasets import DATASETS
from datagen.config_schema import load_config, read_config_dict
from datagen.generate import generate_all
from datagen.generator.truth import compare

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def dev():
    return generate_all(load_config(CONFIG_DIR / "default.yaml"))


@pytest.fixture(scope="module")
def confounded():
    return generate_all(load_config(CONFIG_DIR / "confounded.yaml"))


# ---------------------------------------------------------------- configs


@pytest.mark.parametrize("name", [n for n in DATASETS if n != "heldout"] + ["heldout.template"])
def test_every_dataset_config_is_valid(name):
    file = DATASETS.get(name, f"{name}.yaml")
    assert load_config(CONFIG_DIR / file)


def test_extends_deep_merges_and_replaces_lists():
    tiny = read_config_dict(CONFIG_DIR / "tiny.yaml")
    base = read_config_dict(CONFIG_DIR / "default.yaml")
    assert tiny["world"]["n_shipments"] == 30 and tiny["world"]["ports"] == base["world"]["ports"]
    null = read_config_dict(CONFIG_DIR / "null_effect.yaml")
    assert [a["name"] for a in null["design"]["arms"]] == ["agent_v1", "agent_v2"]
    assert "extends" not in null


def test_heldout_config_is_git_ignored():
    gitignore = (CONFIG_DIR.parents[1] / ".gitignore").read_text()
    assert "datagen/config/heldout.yaml" in gitignore


# ---------------------------------------------------------------- detectability


def test_compare_standard_error_for_rates():
    a = {"n": 1000, "verified_resolution_rate": 0.8}
    b = {"n": 1000, "verified_resolution_rate": 0.9}
    e = compare(a, b)["verified_resolution_rate"]
    assert e["se"] == pytest.approx((0.8 * 0.2 / 1000 + 0.9 * 0.1 / 1000) ** 0.5, rel=1e-3)
    assert e["mde_80"] == pytest.approx(2.8 * e["se"], rel=1e-3) and e["detectable"]


def test_dev_planted_integrator_effect_is_detectable(dev):
    c = dev.tables["planted_effects"][0]["comparisons"]["agent_v2_minus_agent_v1"]["difference"]
    for k in ("verified_resolution_rate", "first_answer_correct_rate", "human_minutes_per_enquiry"):
        assert c[k]["detectable"], k
    assert c["verified_resolution_rate"]["diff"] > 0


def test_dev_has_all_three_pairwise_comparisons(dev):
    assert set(dev.tables["planted_effects"][0]["comparisons"]) == {
        "agent_v1_minus_human_baseline", "agent_v2_minus_human_baseline", "agent_v2_minus_agent_v1"}


def test_null_effect_has_identical_arms_and_no_detectable_resolution_effect():
    g = generate_all(load_config(CONFIG_DIR / "null_effect.yaml"))
    c = g.tables["planted_effects"][0]["comparisons"]["agent_v2_minus_agent_v1"]
    assert c["identical_behaviour"] is True
    assert not c["difference"]["verified_resolution_rate"]["detectable"]


# ---------------------------------------------------------------- confounding


def test_delay_regime_raises_long_delays_after_rollout(confounded):
    from datetime import date

    ships = confounded.world.shipments
    after = [s for s in ships if s.planned_arrival.date() >= date(2026, 2, 15)]
    before = [s for s in ships if s.planned_arrival.date() < date(2026, 2, 15)]
    share = lambda xs: sum(s.delay_class == "long" for s in xs) / len(xs)
    assert share(after) > share(before) + 0.12


def test_counterfactual_truth_exists_and_differs_from_naive(confounded):
    pe = confounded.tables["planted_effects"][0]
    naive = pe["comparisons"]["agent_v1_minus_human_baseline"]["difference"]["human_minutes_per_enquiry"]["diff"]
    true = pe["counterfactual"]["after_rollout"]["causal_effects"]["agent_v1_minus_human_baseline"]
    assert true["human_minutes_per_enquiry"] < 0
    # The naive before/after difference is biased: it differs from the true effect by more than its own noise.
    se = pe["comparisons"]["agent_v1_minus_human_baseline"]["difference"]["human_minutes_per_enquiry"]["se"]
    assert abs(naive - true["human_minutes_per_enquiry"]) > 2 * se
    assert any("NOT causal" in n for n in pe["notes"])


def test_counterfactual_runs_share_the_same_world(confounded):
    """Counterfactual arms must see the same enquiries, or the 'true effect' is meaningless."""
    from datagen.generate import counterfactual_runs

    runs = counterfactual_runs(confounded.cfg, confounded.rules)
    originals = {arm: sorted((t.enquiry.received_at, t.enquiry.true_booking_ref)
                             for t in ts if t.enquiry.repeat_of is None) for arm, ts in runs.items()}
    first, *rest = originals.values()
    assert all(o == first for o in rest)
    assert {t.arm for t in runs["agent_v1"]} == {"agent_v1"}
