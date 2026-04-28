#!/usr/bin/env python3
"""Banana Claude -- Token Rotation Manager

Manages a pool of API keys. When the active key hits daily quota,
automatically rotates to the next available key.

Storage: ~/.banana/tokens.json
Usage:
    token_manager.py list
    token_manager.py add KEY [--name LABEL]
    token_manager.py remove KEY_OR_INDEX
    token_manager.py active        -- show current active token
    token_manager.py reset         -- clear exhausted status on all tokens
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

TOKENS_FILE = Path.home() / ".banana" / "tokens.json"


def load_tokens() -> list[dict]:
    if not TOKENS_FILE.exists():
        return []
    with open(TOKENS_FILE) as f:
        return json.load(f)


def save_tokens(tokens: list[dict]) -> None:
    TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def get_active_key() -> str | None:
    """Return the first non-exhausted key, or None if all are exhausted."""
    tokens = load_tokens()
    today = str(date.today())
    for token in tokens:
        if token.get("exhausted_date") != today:
            return token["key"]
    return None


def mark_exhausted(key: str) -> str | None:
    """Mark key as exhausted today, return next available key or None."""
    tokens = load_tokens()
    today = str(date.today())
    found = False
    for token in tokens:
        if token["key"] == key:
            token["exhausted_date"] = today
            found = True
            break
    if found:
        save_tokens(tokens)
    # Return next available
    for token in tokens:
        if token.get("exhausted_date") != today:
            return token["key"]
    return None


def add_token(key: str, name: str | None = None) -> None:
    tokens = load_tokens()
    # Avoid duplicates
    for t in tokens:
        if t["key"] == key:
            print(f"Token already exists: {name or key[:12]}...")
            return
    idx = len(tokens) + 1
    tokens.append({
        "index": idx,
        "name": name or f"token_{idx}",
        "key": key,
        "exhausted_date": None,
    })
    save_tokens(tokens)
    print(f"Added token {idx}: {name or f'token_{idx}'} ({key[:12]}...)")


def remove_token(identifier: str) -> None:
    tokens = load_tokens()
    before = len(tokens)
    tokens = [t for t in tokens
              if t["key"] != identifier and str(t["index"]) != identifier and t["name"] != identifier]
    if len(tokens) == before:
        print(f"Token not found: {identifier}")
        return
    # Re-index
    for i, t in enumerate(tokens):
        t["index"] = i + 1
    save_tokens(tokens)
    print(f"Removed token: {identifier}")


def list_tokens() -> None:
    tokens = load_tokens()
    today = str(date.today())
    if not tokens:
        print("No tokens configured. Use: token_manager.py add KEY")
        return
    print(f"{'#':<4} {'Name':<15} {'Key':<20} {'Status'}")
    print("-" * 55)
    for t in tokens:
        status = "✗ exhausted today" if t.get("exhausted_date") == today else "✓ active"
        print(f"{t['index']:<4} {t['name']:<15} {t['key'][:16]}...  {status}")


def reset_tokens() -> None:
    tokens = load_tokens()
    for t in tokens:
        t["exhausted_date"] = None
    save_tokens(tokens)
    print(f"Reset {len(tokens)} tokens — all marked as active.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    if cmd == "list":
        list_tokens()
    elif cmd == "add":
        if len(args) < 2:
            print("Usage: token_manager.py add KEY [--name LABEL]")
            sys.exit(1)
        key = args[1]
        name = None
        if "--name" in args:
            name = args[args.index("--name") + 1]
        add_token(key, name)
    elif cmd == "remove":
        if len(args) < 2:
            print("Usage: token_manager.py remove KEY_OR_INDEX")
            sys.exit(1)
        remove_token(args[1])
    elif cmd == "active":
        key = get_active_key()
        if key:
            tokens = load_tokens()
            t = next(t for t in tokens if t["key"] == key)
            print(f"Active: [{t['index']}] {t['name']} ({key[:12]}...)")
        else:
            print("All tokens exhausted. Wait until tomorrow or add new tokens.")
    elif cmd == "reset":
        reset_tokens()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
