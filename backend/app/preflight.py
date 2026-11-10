"""Safe, value-free startup checks for the demo launcher."""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

def _configured(name: str) -> bool:
    value = os.getenv(name, "").strip()
    if not value:
        return False
    lowered = value.lower()
    placeholders = ("replace", "your_", "placeholder", "changeme", "example", "<", ">")
    return not any(part in lowered for part in placeholders)


def main() -> int:
    backend_dir = Path(__file__).resolve().parents[1]
    load_dotenv(backend_dir / ".env", override=False)
    # Import after dotenv so DATABASE_URL from backend/.env is honored.
    from .database import engine

    if _configured("SARVAM_API_KEY"):
        print("OK    SARVAM_API_KEY is configured")
    else:
        print("WARN  SARVAM_API_KEY is missing or a placeholder; voice input/output will use browser fallbacks")

    officer_ok = _configured("OFFICER_API_KEY")
    admin_ok = _configured("ADMIN_API_KEY")
    keys_distinct = os.getenv("OFFICER_API_KEY", "").strip() != os.getenv("ADMIN_API_KEY", "").strip()
    if officer_ok and admin_ok and keys_distinct:
        print("OK    Officer and admin API keys are configured and distinct")
    else:
        print("WARN  Officer/admin keys are missing, placeholders, or identical; set distinct keys in backend/.env")

    demo = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
    print(f"OK    DEMO_MODE={'true' if demo else 'false'}")

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        print("OK    Database is reachable")
    except Exception as exc:
        print(f"WARN  Database is not reachable ({type(exc).__name__})")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
