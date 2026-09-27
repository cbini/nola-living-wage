from nola_lw.config import load_config


def test_config_has_required_keys():
    cfg = load_config()
    assert cfg["orleans"]["powsp"] == "022"
    assert cfg["cpi"]["target"] == "2025-12"
    assert cfg["checkpoint"]["wage_tolerance"] == 0.15
    assert len(cfg["pums"]["other_states"]) == 49
    assert len(set(cfg["pums"]["other_states"])) == 49
    assert "la" not in cfg["pums"]["other_states"]
    assert all(isinstance(v, str) for v in cfg["orleans"].values() if not isinstance(v, list))
    assert all(isinstance(v, str) for v in cfg["orleans"]["powpuma"])
