import argparse


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="nola-lw")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download all sources to data/raw/")
    f.add_argument("--refresh-mit", action="store_true", help="re-scrape MIT instead of using the committed snapshot")
    f.add_argument("--only", choices=["mit", "bls", "bea", "pums"], help="fetch one source")
    sub.add_parser("checkpoint", help="write data/out/checkpoint.md")
    sub.add_parser("all", help="fetch, then checkpoint")
    args = p.parse_args(argv)
    print(f"{args.cmd}: not implemented")
