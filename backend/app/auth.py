"""Simple API-key role authentication for prototype officer endpoints."""

import os
from typing import Literal

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()


def require_role(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> Literal["officer", "admin"]:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    officer_key = os.getenv("OFFICER_API_KEY")
    admin_key = os.getenv("ADMIN_API_KEY")
    if admin_key and x_api_key == admin_key:
        return "admin"
    if officer_key and x_api_key == officer_key:
        return "officer"
    raise HTTPException(status_code=401, detail="Invalid API key")
