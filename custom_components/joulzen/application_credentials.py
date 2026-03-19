"""Application credentials for the Joulzen integration (Supabase OAuth2)."""
from homeassistant.components.application_credentials import (
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant

from .const import OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, SUPABASE_URL


async def async_get_authorization_server(
    hass: HomeAssistant,
) -> AuthorizationServer:
    """Return the Supabase OAuth2 authorization server."""
    return AuthorizationServer(
        authorize_url=f"{SUPABASE_URL}/auth/v1/oauth/authorize",
        token_url=f"{SUPABASE_URL}/auth/v1/oauth/token",
    )


async def async_get_default_credentials(
    hass: HomeAssistant,
) -> ClientCredential:
    """Return bundled credentials — users don't need to provide their own."""
    return ClientCredential(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
    )
