import argparse

from nola_lw.config import load_config

SOURCES = ["mit", "bls", "bea", "pums"]


def fetch(cfg, only: str | None, refresh_mit: bool) -> None:
    for src in [only] if only else SOURCES:
        if src == "mit":
            from nola_lw.fetch import mit
            print("mit:", mit.scrape(cfg, refresh=refresh_mit))
        elif src == "bls":
            from nola_lw.fetch import bls
            print("bls:", bls.fetch_cpi(cfg))
        elif src == "bea":
            from nola_lw.fetch import bea
            print("bea:", *bea.fetch_zips(cfg))
        elif src == "pums":
            from nola_lw.fetch import pums
            print("pums:", *pums.fetch_bulk(cfg))
            print("pums:", pums.fetch_other_states(cfg))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nola-lw")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download all sources to data/raw/")
    f.add_argument("--refresh-mit", action="store_true", help="re-scrape MIT instead of using the committed snapshot")
    f.add_argument("--only", choices=SOURCES, help="fetch one source")
    sub.add_parser("checkpoint", help="write data/out/checkpoint.md")
    a = sub.add_parser("all", help="fetch, then checkpoint")
    a.add_argument("--refresh-mit", action="store_true")
    args = p.parse_args(argv)
    cfg = load_config()
    if args.cmd in ("fetch", "all"):
        fetch(cfg, getattr(args, "only", None), args.refresh_mit)
    if args.cmd in ("checkpoint", "all"):
        from nola_lw.checkpoint import write_report
        print("checkpoint:", write_report(cfg))
