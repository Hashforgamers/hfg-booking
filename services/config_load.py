import os

def load_key_from_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()

