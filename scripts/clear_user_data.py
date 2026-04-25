"""Truncate user-related tables for a fresh dev DB (keeps platform_roles / permissions)."""

from sqlalchemy import text

from model import engine


def main() -> None:
    stmt = text(
        """
        TRUNCATE TABLE
          message_files,
          messages,
          file_attachments,
          chatrooms,
          workspaces,
          sessions,
          identity_providers,
          otp,
          users_platform_roles,
          users
        RESTART IDENTITY;
        """
    )
    with engine.begin() as conn:
        conn.execute(stmt)
    print("Cleared: users, sessions, OAuth/TOTP rows, workspaces, chat, messages, files.")


if __name__ == "__main__":
    main()
