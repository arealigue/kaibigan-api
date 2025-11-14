"""
Shared dependencies for Kaibigan API
"""
import os
from fastapi import Header, HTTPException, status
from typing import Annotated
from supabase import create_client, Client

# Initialize Supabase client
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
if not supabase_url or not supabase_key:
     raise Exception("Supabase URL and Service Key must be set in environment variables.")
supabase: Client = create_client(supabase_url, supabase_key)


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
        print(f"Auth Error: {e}") 
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Authentication error")
