"""Invite code system — runtime auth for the Telegram bot."""
import os
import secrets
import string

from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


async def setup(pool: AsyncConnectionPool) -> None:
    global _pool
    _pool = pool
    async with _pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS authorized_users (
                id SERIAL PRIMARY KEY,
                telegram_user_id BIGINT UNIQUE,
                invite_code VARCHAR(32) UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                redeemed_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)


def generate_invite_code(length: int = 8) -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


async def is_authorized(user_id: int) -> bool:
    admin_ids = {x.strip() for x in os.getenv("ADMIN_TELEGRAM_USER_IDS", "").split(",") if x.strip()}
    if str(user_id) in admin_ids:
        return True
    async with _pool.connection() as conn:
        result = await conn.execute(
            "SELECT 1 FROM authorized_users WHERE telegram_user_id = %s AND is_active = TRUE",
            (user_id,),
        )
        return await result.fetchone() is not None


async def validate_code(code: str) -> bool:
    async with _pool.connection() as conn:
        result = await conn.execute(
            "SELECT 1 FROM authorized_users WHERE invite_code = %s AND redeemed_at IS NULL AND is_active = TRUE",
            (code,),
        )
        return await result.fetchone() is not None


async def redeem_code(user_id: int, code: str) -> bool:
    """Atomically claim a code for a user. Returns False if code is invalid, expired, or already used."""
    try:
        async with _pool.connection() as conn:
            result = await conn.execute(
                """
                UPDATE authorized_users
                SET telegram_user_id = %s, redeemed_at = NOW()
                WHERE invite_code = %s AND redeemed_at IS NULL AND is_active = TRUE
                RETURNING id
                """,
                (user_id, code),
            )
            return await result.fetchone() is not None
    except Exception:
        return False
