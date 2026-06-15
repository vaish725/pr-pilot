import argparse
from pr_pilot import server


def main():
    parser = argparse.ArgumentParser("pr-pilot CLI")
    parser.add_argument("--serve", action="store_true", help="Run the webhook server")
    args = parser.parse_args()
    if args.serve:
        server.app


if __name__ == "__main__":
    main()
