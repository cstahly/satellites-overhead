#!/usr/bin/env python3
"""Create, list, and revoke SDR mobile API bearer tokens."""

import argparse
import json

from sdr_runtime import ALLOWED_SCOPES, create_api_token, list_api_tokens, revoke_api_token


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a token and print its secret once")
    create.add_argument("--name", required=True)
    create.add_argument(
        "--scope",
        action="append",
        choices=ALLOWED_SCOPES,
        dest="scopes",
        help="repeat for multiple scopes; defaults to *",
    )

    subparsers.add_parser("list", help="list redacted token metadata")

    revoke = subparsers.add_parser("revoke", help="revoke a token by id")
    revoke.add_argument("token_id")

    args = parser.parse_args()
    if args.command == "create":
        result = create_api_token(args.name, args.scopes or ["*"])
    elif args.command == "list":
        result = list_api_tokens()
    else:
        result = revoke_api_token(args.token_id)
        if result is None:
            parser.error(f"token not found: {args.token_id}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
