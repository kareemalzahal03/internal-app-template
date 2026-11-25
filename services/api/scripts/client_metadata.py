"""Prints what to register with a provider for the app at a given origin."""

import argparse

from app.core.auth import client_metadata

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_url", help="the app's origin, such as https://app.example.com")
    args = parser.parse_args()
    print(client_metadata(args.app_url).model_dump_json(indent=2))
