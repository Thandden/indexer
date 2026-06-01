"""Google Indexing API helper.

Pings Google to crawl a URL via the Indexing API. Officially only for
JobPosting/BroadcastEvent, used here for any page (POC). Requires the service
account to be an OWNER of the URL's Search Console property — which we are,
since we own coffeeclubguide.site.

Same service-account JSON key as checker.py. Set SA_KEY to its path.
"""
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/indexing"]


def get_service(key_path=None):
    key_path = key_path or os.environ.get("SA_KEY")
    if not key_path or not os.path.exists(key_path):
        raise SystemExit("set SA_KEY to the service-account JSON key path")
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=SCOPES)
    return build("indexing", "v3", credentials=creds, cache_discovery=False)


def publish(service, url):
    """Notify Google that the URL was updated (URL_UPDATED). Returns the
    notifyTime on success; raises on API error."""
    resp = service.urlNotifications().publish(
        body={"url": url, "type": "URL_UPDATED"}).execute()
    return resp.get("urlNotificationMetadata", {}).get("latestUpdate", {}).get(
        "notifyTime")
