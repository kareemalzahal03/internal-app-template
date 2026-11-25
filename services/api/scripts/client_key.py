"""Prints a new key pair for `private_key_jwt`.

Line one is the private key, on one line, for the app's secret store only.
Line two is its public half as a JWK Set, for a provider that cannot fetch
it from the app and must be given it by hand.
"""

import json

from joserfc.jwk import RSAKey


def main() -> None:
    key = RSAKey.generate_key(2048, private=True)
    key.ensure_kid()
    print(json.dumps(key.as_dict(private=True), separators=(",", ":")))
    public = {**key.as_dict(private=False), "use": "sig", "alg": "RS256"}
    print(json.dumps({"keys": [public]}))


if __name__ == "__main__":
    main()
