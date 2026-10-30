import time
import logging
import requests

from lfx.custom.custom_component.component import Component
from lfx.io import StrInput, SecretStrInput, Output
from lfx.schema.data import Data


_TOKEN_CACHE = {}
_TOKEN_CACHE_MAX_ENTRIES = 50

logger = logging.getLogger("genesys_cloud_auth")

VALID_GENESYS_REGIONS = {
 "mypurecloud.com",
 "mypurecloud.ie",
 "mypurecloud.com.au",
 "mypurecloud.jp",
 "mypurecloud.de",
 "usw2.pure.cloud",
 "cac1.pure.cloud",
 "euw2.pure.cloud",
 "apne2.pure.cloud",
 "apne3.pure.cloud",
 "apse2.pure.cloud",
 "sae1.pure.cloud",
 "mec1.pure.cloud",
}


class CustomComponent(Component):
 display_name = "Genesys Cloud Auth"
 description = "Returns a Genesys Cloud access token (client credentials, or a manual token for testing)."

 inputs = [
  StrInput(
   name="region",
   display_name="Genesys Region",
   value="mypurecloud.com",
  ),
  SecretStrInput(
   name="manual_token",
   display_name="Manual Token (testing only)",
   value="",
   info="Paste a Bearer token from your browser session for testing. Only active when ALLOW_MANUAL_TOKEN_TESTING=true in the server environment. Leave blank in production.",
   required=False,
  ),
  StrInput(
   name="client_id",
   display_name="OAuth Client ID",
   value="",
   required=False,
  ),
  SecretStrInput(
   name="client_secret",
   display_name="OAuth Client Secret",
   value="",
   required=False,
  ),
 ]

 outputs = [
  Output(display_name="Token", name="token", method="get_token"),
 ]

 def _validated_region(self):
  region = (self.region or "mypurecloud.com").strip().lower()
  if region not in VALID_GENESYS_REGIONS:
   logger.warning("Rejected invalid Genesys region input: %r", region)
   return None
  return region

 def _manual_token_allowed(self):
  import os
  return os.environ.get("ALLOW_MANUAL_TOKEN_TESTING", "false").strip().lower() == "true"

 def _evict_if_full(self):
  if len(_TOKEN_CACHE) <= _TOKEN_CACHE_MAX_ENTRIES:
   return
  now = time.time()
  expired_keys = [k for k, v in _TOKEN_CACHE.items() if v["expires_at"] <= now]
  for k in expired_keys:
   _TOKEN_CACHE.pop(k, None)
  if len(_TOKEN_CACHE) > _TOKEN_CACHE_MAX_ENTRIES:
   oldest_key = min(_TOKEN_CACHE, key=lambda k: _TOKEN_CACHE[k]["expires_at"])
   _TOKEN_CACHE.pop(oldest_key, None)

 def get_token(self) -> Data:
  region = self._validated_region()
  if region is None:
   return Data(data={"error": f"Invalid Genesys region. Must be one of: {', '.join(sorted(VALID_GENESYS_REGIONS))}"})

  manual = (self.manual_token or "").strip()
  if manual:
   if not self._manual_token_allowed():
    logger.warning("Manual token input was provided but ALLOW_MANUAL_TOKEN_TESTING is not enabled; ignoring.")
    return Data(data={"error": "Manual token testing is disabled in this environment."})
   logger.warning("Manual token path used for Genesys auth (testing mode).")
   if manual.lower().startswith("bearer "):
    manual = manual[7:].strip()
   return Data(data={
    "access_token": manual,
    "region": region,
    "source": "manual",
   })

  if not self.client_id or not self.client_secret:
   return Data(data={"error": "Provide either a Manual Token or Client ID + Client Secret."})

  cache_key = self.client_id
  cached = _TOKEN_CACHE.get(cache_key)
  if cached and cached["expires_at"] > time.time() + 30:
   logger.info("Genesys token cache hit for client_id ending '%s'", self.client_id[-4:])
   return Data(data={
    "access_token": cached["token"],
    "region": region,
    "source": "client_credentials_cached",
   })

  token_url = f"https://login.{region}/oauth/token"

  try:
   resp = requests.post(
    token_url,
    data={"grant_type": "client_credentials"},
    auth=(self.client_id, self.client_secret),
    timeout=15,
   )
   resp.raise_for_status()
   payload = resp.json()
  except requests.exceptions.RequestException as e:
   logger.error("Genesys token request failed (network/HTTP): %s", str(e))
   return Data(data={"error": "Token request failed due to a network or connection error."})
  except Exception as e:
   logger.error("Unexpected error during Genesys authentication: %s", str(e))
   return Data(data={"error": "An unexpected error occurred during authentication."})

  self._evict_if_full()
  _TOKEN_CACHE[cache_key] = {
   "token": payload["access_token"],
   "expires_at": time.time() + payload.get("expires_in", 3600),
  }
  logger.info("Genesys token retrieved for client_id ending '%s'", self.client_id[-4:])

  return Data(data={
   "access_token": payload["access_token"],
   "region": region,
   "source": "client_credentials",
  })