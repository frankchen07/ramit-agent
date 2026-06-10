"""Admin CLI for managing invite codes and authorized users.

Usage (local):
    python -m src.admin_cli --generate 5
    python -m src.admin_cli --list-users
    python -m src.admin_cli --revoke AB3KXJ2L
    python -m src.admin_cli --remove-user 123456789

Usage (against the Railway-deployed bot's database):
    DATABASE_URL=<DATABASE_PUBLIC_URL from Railway Postgres service> \\
        python -m src.admin_cli --generate 5

    (Railway's plain DATABASE_URL is the internal `postgres.railway.internal`
    host, which only resolves inside Railway's network — `railway run` won't
    help here since it executes locally. Use the Postgres service's
    DATABASE_PUBLIC_URL instead.)
"""
import argparse
import asyncio
import os

from dotenv import load_dotenv
from psycopg_pool import AsyncConnectionPool

from src.invite_system import generate_invite_code, setup as setup_invite_system

load_dotenv()


async def run(args: argparse.Namespace) -> None:
    db_url = os.environ["DATABASE_URL"]
    pool = AsyncConnectionPool(db_url, kwargs={"autocommit": True}, open=False)
    await pool.open()
    await setup_invite_system(pool)

    try:
        if args.generate:
            async with pool.connection() as conn:
                for _ in range(args.generate):
                    code = generate_invite_code()
                    await conn.execute(
                        "INSERT INTO authorized_users (invite_code) VALUES (%s) ON CONFLICT DO NOTHING",
                        (code,),
                    )
                    print(code)

        elif args.list_users:
            async with pool.connection() as conn:
                result = await conn.execute(
                    "SELECT telegram_user_id, invite_code, created_at, redeemed_at, is_active "
                    "FROM authorized_users ORDER BY created_at"
                )
                rows = await result.fetchall()
            if not rows:
                print("No users yet.")
            else:
                print(f"{'user_id':<15} {'code':<10} {'created':<22} {'redeemed':<22} active")
                print("-" * 80)
                for user_id, code, created, redeemed, active in rows:
                    uid = str(user_id) if user_id else "(unredeemed)"
                    red = str(redeemed)[:19] if redeemed else "-"
                    print(f"{uid:<15} {code:<10} {str(created)[:19]:<22} {red:<22} {active}")

        elif args.revoke:
            async with pool.connection() as conn:
                result = await conn.execute(
                    "UPDATE authorized_users SET is_active = FALSE WHERE invite_code = %s RETURNING id",
                    (args.revoke,),
                )
                if await result.fetchone():
                    print(f"Revoked {args.revoke}")
                else:
                    print(f"Code not found: {args.revoke}")

        elif args.remove_user is not None:
            async with pool.connection() as conn:
                await conn.execute(
                    "DELETE FROM authorized_users WHERE telegram_user_id = %s",
                    (args.remove_user,),
                )
                # Also wipe their LangGraph conversation history
                await conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = %s",
                    (str(args.remove_user),),
                )
                await conn.execute(
                    "DELETE FROM checkpoint_writes WHERE thread_id = %s",
                    (str(args.remove_user),),
                )
            print(f"Removed user {args.remove_user} and their conversation history.")

    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage ramit-agent invite codes and users")
    parser.add_argument("--generate", type=int, metavar="N", help="Generate N invite codes")
    parser.add_argument("--list-users", action="store_true", help="List all authorized users")
    parser.add_argument("--revoke", metavar="CODE", help="Deactivate an invite code")
    parser.add_argument("--remove-user", type=int, metavar="USER_ID", help="Remove user and their conversation history")
    args = parser.parse_args()

    if not any([args.generate, args.list_users, args.revoke, args.remove_user is not None]):
        parser.print_help()
        return

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
