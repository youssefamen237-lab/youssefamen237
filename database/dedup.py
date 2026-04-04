# Merged into database/db.py
#
# All deduplication logic lives in database/db.py:
#
#   db.script_exists(hook, body)
#       → Computes SHA-256(hook + body) and queries the
#         scripts.content_hash UNIQUE column.
#
#   db.insert_script(...)
#       → Raises ValueError on duplicate content_hash before insert.
#
#   database/models.py defines the UNIQUE constraint at the schema level:
#       content_hash TEXT NOT NULL UNIQUE
#
# There is no separate dedup module — the deduplication is enforced
# at both the Python layer (db.script_exists) and the SQLite layer
# (UNIQUE constraint) for double protection.
