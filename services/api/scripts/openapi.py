"""Prints the app's OpenAPI schema, which the web app's client is generated from."""

import json

from app.main import app

if __name__ == "__main__":
    print(json.dumps(app.openapi(), indent=2))
