"""
Singleton Supabase client for the backend services.
Uses the service-role key for full access (bypasses RLS).
"""
from __future__ import annotations

import os
from functools import lru_cache

from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a cached Supabase client using the service-role key."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def get_supabase_anon() -> Client:
    """Return a Supabase client using the anon key (respects RLS)."""
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_ANON_KEY"]
    return create_client(url, key)
