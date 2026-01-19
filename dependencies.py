"""
Shared dependencies for Kaibigan API
"""
import os
import logging
from fastapi import Header, HTTPException, status, Request
from typing import Annotated
from supabase import create_client, Client
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
if not supabase_url or not supabase_key:
     raise Exception("Supabase URL and Service Key must be set in environment variables.")
supabase: Client = create_client(supabase_url, supabase_key)

# Initialize Rate Limiter
def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def get_rate_limit_key(request: Request) -> str:
    """
    Returns the client key used for rate limiting.

    By default, we do NOT trust forwarded headers (spoofable). For deployments
    behind a trusted reverse proxy/load balancer (e.g., Render), set
    TRUST_PROXY_HEADERS=true so we key by the original client IP.
    """
    if _truthy_env("TRUST_PROXY_HEADERS"):
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # XFF can be a comma-separated list. First is the original client.
            client_ip = xff.split(",")[0].strip()
            if client_ip:
                return client_ip
    return get_remote_address(request)


limiter = Limiter(key_func=get_rate_limit_key)


async def get_user_profile(authorization: Annotated[str | None, Header()] = None):
    """
    Security dependency that validates JWT token and retrieves user profile.
    Returns the user's profile including tier information.
    """
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header missing")
    
    token_type, _, token = authorization.partition(' ')
    if token_type.lower() != 'bearer' or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token format")

    try:
        user_res = supabase.auth.get_user(token)
        user = user_res.user
        if not user:
            raise Exception("Invalid token")
        
        profile_res = supabase.table('profiles').select('*').eq('id', user.id).single().execute()
        profile = profile_res.data
        if not profile:
            raise Exception("Profile not found")
        
        return profile
    
    except Exception as e:
        logger.warning("Auth error during token validation: %s", e.__class__.__name__)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication error")
