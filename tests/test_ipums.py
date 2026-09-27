from pathlib import Path

from nola_lw.config import load_config
from nola_lw.fetch.ipums import orleans_powpumas, read_composition

FIX = Path(__file__).parent / "fixtures" / "ipums_county_pwpuma.csv"


def test_orleans_powpuma_from_composition():
    cfg = load_config()
    comp = read_composition(FIX)
    assert orleans_powpumas(comp, cfg) == {"powpumas": ["02400"], "counties": ["071"]}
