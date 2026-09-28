from unittest.mock import patch

from app.security.auth import SupabaseJWTVerifier


def test_internal_jwks_url_keeps_public_issuer():
    with patch("app.security.auth.jwt.PyJWKClient") as jwks:
        verifier = SupabaseJWTVerifier("https://scribe-supabase.spaces.community",
                                      jwks_url="http://api-gw:8000/auth/v1/.well-known/jwks.json")

    assert verifier.issuer == "https://scribe-supabase.spaces.community/auth/v1"
    jwks.assert_called_once_with("http://api-gw:8000/auth/v1/.well-known/jwks.json",
                                 cache_keys=True, lifespan=600)
