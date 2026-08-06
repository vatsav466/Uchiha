#!/usr/bin/env python3
"""
reset_password.py — Re-encrypt user password(s) in the database using the
current password_salt so that login works correctly.

Use this when login returns 401 "Invalid Login Credentials" because the stored
passwords were encrypted with a different password_salt than the one the
running application uses (e.g. a DB migrated from an older deployment).

Modes
-----
Single user:
    /opt/venv/bin/python /opt/ceg/algo/api_manager/reset_password.py \
        admin 'C@g-2O25#N0x$PRd'

Reset ALL users whose stored password cannot be decrypted with the current
salt (only touches broken rows, leaves working passwords untouched):

    /opt/venv/bin/python /opt/ceg/algo/api_manager/reset_password.py \
        --all 'C@g-2O25#N0x$PRd'

Dry-run report of which users are broken, without changing anything:

    /opt/venv/bin/python /opt/ceg/algo/api_manager/reset_password.py --check

Arguments:
    username     — the username to update (e.g. admin)
    new_password — the plain-text password to set (must match what you type at login)
    --all        — apply new_password to every user whose stored password does
                   NOT decrypt with the current salt
    --check      — list users with undecryptable passwords (no changes)
"""
import sys
import asyncio
import os

# Ensure .alg_env is found (settings reads it from CWD)
os.chdir("/opt/ceg/algo/api_manager")
sys.path.insert(0, "/opt/ceg/algo")
sys.path.insert(0, "/opt/ceg/algo/api_manager")


def main():
    args = sys.argv[1:]
    if len(args) < 1:
        print(__doc__)
        sys.exit(1)

    if args[0] == "--check":
        asyncio.run(_check_all())
    elif args[0] == "--all":
        if len(args) < 2:
            print("Usage: reset_password.py --all '<new_password>'")
            sys.exit(1)
        asyncio.run(_reset_all(args[1]))
    else:
        if len(args) < 2:
            print("Usage: reset_password.py <username> '<new_password>'")
            sys.exit(1)
        asyncio.run(_reset(args[0], args[1]))


async def _db_engine():
    # Import after chdir so settings picks up the right .alg_env
    # urdhva_base.settings is the Settings singleton (re-exported from __init__.py)
    import urdhva_base
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    db_url = str(urdhva_base.settings.db_urls["postgres_async"][0])
    safe_url = db_url.split("@")[0].split("//")[0] + "//***@" + db_url.split("@")[-1]
    print(f"[info] Connecting to: {safe_url}")

    engine = create_async_engine(
        db_url,
        pool_size=2,
        max_overflow=0,
        connect_args={"timeout": 15},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def _decrypts(types, stored_pw) -> bool:
    try:
        types.Secret(str(stored_pw)).get_secret()
        return True
    except Exception:
        return False


async def _reset(username: str, new_password: str):
    import urdhva_base
    import urdhva_base.types as types
    from sqlalchemy import text

    salt = urdhva_base.settings.password_salt
    print(f"[info] password_salt in use: {repr(salt)}")

    engine, session_factory = await _db_engine()

    async with session_factory() as session:
        result = await session.execute(
            text(f"SELECT id, username, password FROM users WHERE lower(username) = lower(:u)"),
            {"u": username},
        )
        row = result.fetchone()
        if not row:
            print(f"[ERROR] User '{username}' not found in the 'users' table.")
            return

        user_id, db_username, stored_pw = row
        print(f"[info] Found user: id={user_id}, username={db_username!r}")
        print(f"[info] Stored password prefix: {str(stored_pw)[:30]}...")

        # ── Diagnose: try current salt ────────────────────────────────────────
        if await _decrypts(types, stored_pw):
            print(f"[ok]   Current stored password already decrypts with salt={repr(salt)!r}")
            if types.Secret(str(stored_pw)).get_secret() == new_password:
                print(f"[ok]   Stored password already matches new_password — nothing to update.")
                return
            else:
                print(f"[warn] Stored password decrypts to a DIFFERENT value; re-encrypting.")
        else:
            print(f"[warn] Stored password does NOT decrypt with the current salt; re-encrypting.")

        # ── Re-encrypt with current salt and update DB ────────────────────────
        # types.Secret.validate() encrypts any plain-text value with settings.password_salt
        encrypted = str(types.Secret.validate(new_password))
        print(f"[info] New encrypted value prefix: {encrypted[:30]}...")

        await session.execute(
            text("UPDATE users SET password = :pw WHERE id = :id"),
            {"pw": encrypted, "id": user_id},
        )
        await session.commit()
        print(f"\n[SUCCESS] Password for '{db_username}' has been reset.")
        print(f"          Login with: username={db_username!r}, password={new_password!r}")

    await engine.dispose()


async def _reset_all(new_password: str):
    import urdhva_base
    import urdhva_base.types as types
    from sqlalchemy import text

    salt = urdhva_base.settings.password_salt
    print(f"[info] password_salt in use: {repr(salt)}")
    print(f"[info] Resetting ALL users whose stored password does NOT decrypt with this salt.")

    engine, session_factory = await _db_engine()

    async with session_factory() as session:
        result = await session.execute(text("SELECT id, username, password FROM users"))
        rows = result.fetchall()

        encrypted = str(types.Secret.validate(new_password))
        updated, already_ok, skipped = 0, 0, 0

        for user_id, db_username, stored_pw in rows:
            if stored_pw is None or str(stored_pw) == "":
                skipped += 1
                continue
            if await _decrypts(types, stored_pw):
                already_ok += 1
                continue
            await session.execute(
                text("UPDATE users SET password = :pw WHERE id = :id"),
                {"pw": encrypted, "id": user_id},
            )
            updated += 1

        await session.commit()
        print(f"\n[SUMMARY] users processed: {len(rows)}")
        print(f"          reset (broken → new password): {updated}")
        print(f"          already decryptable (left untouched): {already_ok}")
        print(f"          empty/missing password (skipped): {skipped}")
        if updated:
            print(f"\n[SUCCESS] All users can now log in with password={new_password!r}")

    await engine.dispose()


async def _check_all():
    import urdhva_base
    import urdhva_base.types as types
    from sqlalchemy import text

    salt = urdhva_base.settings.password_salt
    print(f"[info] password_salt in use: {repr(salt)}")

    engine, session_factory = await _db_engine()

    async with session_factory() as session:
        result = await session.execute(text("SELECT id, username, password FROM users"))
        rows = result.fetchall()

        broken, ok = [], 0
        for user_id, db_username, stored_pw in rows:
            if stored_pw is None or str(stored_pw) == "":
                continue
            if await _decrypts(types, stored_pw):
                ok += 1
            else:
                broken.append((user_id, db_username))

        print(f"\n[CHECK] users that WILL fail login (undecryptable password): {len(broken)}")
        for user_id, db_username in broken:
            print(f"          id={user_id} username={db_username!r}")
        print(f"[CHECK] users with working passwords: {ok}")
        if broken:
            print("\n  Fix with: reset_password.py --all '<new_password>'")

    await engine.dispose()


if __name__ == "__main__":
    main()
