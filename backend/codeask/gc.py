"""Delete embeddings no chunk references, or delete one repo.

Run: python -m codeask.gc                         orphans older than 24 h
     python -m codeask.gc --all                   all orphans (including an interrupted
                                                  ingest's cache, which a re-run would reuse)
     python -m codeask.gc --delete-repo owner/name

Orphans are kept on re-ingest on purpose: switching back to an earlier chunking variant then
costs no Voyage calls. Deleting a repo removes its chunks and only the embeddings that nothing
else references.
"""

from __future__ import annotations

import argparse


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="include orphans newer than 24 h")
    group.add_argument("--delete-repo", metavar="OWNER/NAME")
    args = parser.parse_args()

    from codeask.store import Store, connect

    store = Store(connect("DATABASE_OWNER_URL"))  # deletes content: the owner (Q65); no --prod
    if args.delete_repo:
        found, deleted = store.delete_repo(args.delete_repo.lower())
        print(f"deleted {args.delete_repo} and {deleted} embeddings only it used" if found
              else f"{args.delete_repo} is not ingested")
        return
    deleted = store.gc(include_recent=args.all)
    print(f"deleted {deleted} orphaned embeddings")


if __name__ == "__main__":
    main()
