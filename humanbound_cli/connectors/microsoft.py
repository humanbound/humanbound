# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""
Microsoft connector for AI service discovery.

Queries multiple Microsoft APIs using delegated permissions obtained via
device code flow. The CISO signs in once; MSAL handles multi-resource
token acquisition automatically.

Detection layers:
  1. Service Principals  (Graph API) — consented/registered AI apps
  2. Sign-in Logs        (Graph API) — active AI app usage
  3. Copilot Usage       (Graph API) — M365 Copilot adoption
  4. License Inventory   (Graph API) — AI-related SKUs
  5. Azure Resources     (ARM API)   — Azure OpenAI, Bot Service, AI Studio
"""

import logging
import re

import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com"
ARM_BASE = "https://management.azure.com"

# ── Scopes ────────────────────────────────────────────────────────────────

GRAPH_SCOPES = [
    "https://graph.microsoft.com/Application.Read.All",
    "https://graph.microsoft.com/AuditLog.Read.All",
    "https://graph.microsoft.com/Reports.Read.All",
    "https://graph.microsoft.com/Organization.Read.All",
    "https://graph.microsoft.com/User.ReadBasic.All",
]

ARM_SCOPES = ["https://management.azure.com/user_impersonation"]

# ── Known AI application IDs in Azure AD ──────────────────────────────────

KNOWN_AI_APPS = {
    "fb8d773d-7ef8-4ec0-a117-448f88e2020c": {
        "name": "Microsoft 365 Copilot",
        "category": "embedded_copilot",
        "testable": True,
    },
    "c986a076-2208-4e06-b170-257f002c9580": {
        "name": "Azure OpenAI Service",
        "category": "ai_platform",
        "testable": True,
    },
    "0365ff22-1783-4e08-8a1f-b98e13014839": {
        "name": "Bing Chat Enterprise",
        "category": "embedded_copilot",
        "testable": True,
    },
    "bb9bf476-dc3f-4a0e-bf2a-8222e11173b8": {
        "name": "Security Copilot",
        "category": "embedded_copilot",
        "testable": True,
    },
    "d2b17d21-c7b1-4ff2-98b0-adc06c4f9b6f": {
        "name": "Azure AI Studio",
        "category": "ai_platform",
        "testable": False,
    },
    "5765cfcc-b2f7-4b1d-9e0f-b79c0e3e5c3a": {
        "name": "GitHub Copilot",
        "category": "ai_dev_tool",
        "testable": False,
    },
}

# ── Display name patterns for fuzzy matching on service principals ────────

AI_DISPLAY_NAME_PATTERNS = [
    # Microsoft AI services
    {"pattern": "copilot studio", "category": "copilot_studio_agent", "testable": True},
    {"pattern": "power virtual agent", "category": "copilot_studio_agent", "testable": True},
    {"pattern": " pva", "category": "copilot_studio_agent", "testable": True},
    {"pattern": "copilot", "category": "embedded_copilot"},
    {"pattern": "azure openai", "category": "ai_platform"},
    {"pattern": "azure ai", "category": "ai_platform"},
    {"pattern": "azure machine learning openai", "category": "ai_platform"},
    {"pattern": "bot service", "category": "copilot_studio_agent", "testable": True},
    {"pattern": "bot framework", "category": "copilot_studio_agent", "testable": True},
    # Standalone AI providers
    {"pattern": "openai", "category": "standalone_ai", "testable": True},
    {"pattern": "anthropic", "category": "standalone_ai", "testable": True},
    {"pattern": "claude", "category": "standalone_ai", "testable": True},
    {"pattern": "gemini", "category": "standalone_ai"},
    {"pattern": "chatgpt", "category": "standalone_ai", "testable": True},
    # Dev tools
    {"pattern": "github copilot", "category": "ai_dev_tool"},
    # Other AI
    {"pattern": "salesforce einstein", "category": "embedded_copilot"},
    {"pattern": "hugging face", "category": "ai_platform"},
    {"pattern": "huggingface", "category": "ai_platform"},
    {"pattern": "grammarly", "category": "ai_assistant"},
    {"pattern": "cohere", "category": "ai_platform"},
    {"pattern": "perplexity", "category": "standalone_ai"},
    {"pattern": "midjourney", "category": "standalone_ai"},
    {"pattern": "jasper ai", "category": "standalone_ai"},
    {"pattern": "notion ai", "category": "embedded_copilot"},
    {"pattern": "bing chat", "category": "embedded_copilot"},
    # Chatbot / agent indicators
    {"pattern": "chatbot", "category": "copilot_studio_agent", "testable": True},
]

# ── AI-related license SKU part numbers ───────────────────────────────────

AI_LICENSE_PATTERNS = [
    {"pattern": "copilot", "category": "embedded_copilot"},
    {"pattern": "openai", "category": "ai_platform"},
    {"pattern": "github_copilot", "category": "ai_dev_tool"},
    {"pattern": "ai_builder", "category": "ai_platform"},
    {"pattern": "power_virtual", "category": "copilot_studio_agent"},
    {"pattern": "copilot_studio", "category": "copilot_studio_agent"},
]

# ── Azure resource type → service metadata ────────────────────────────────

ARM_RESOURCE_TYPES = {
    "microsoft.cognitiveservices/accounts": {
        "category": "ai_platform",
        "testable": True,
    },
    "microsoft.botservice/botservices": {
        "category": "copilot_studio_agent",
        "testable": True,
    },
    "microsoft.machinelearningservices/workspaces": {
        "category": "ai_platform",
        "testable": False,
    },
}

ARM_RESOURCE_GRAPH_QUERY = """
Resources
| where type in~ ('microsoft.cognitiveservices/accounts',
                   'microsoft.botservice/botservices',
                   'microsoft.machinelearningservices/workspaces')
| project name, type, location, kind, skuName=sku.name,
          resourceGroup, subscriptionId,
          publicNetworkAccess=properties.publicNetworkAccess,
          disableLocalAuth=properties.disableLocalAuth
"""

POWER_PLATFORM_RESOURCE_GRAPH_QUERY = """
PowerPlatformResources
| where type == 'microsoft.copilotstudio/agents'
| project name, type, location, properties
"""

# ── Helpers ───────────────────────────────────────────────────────────────

_STATUS_RANK = {"detected": 0, "consented": 1, "active": 2, "licensed": 3}


class _GraphAPIError(Exception):
    """Raised when a Graph/ARM API call returns a non-2xx status."""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body[:200]}")

    def is_auth_error(self) -> bool:
        if self.status_code in (401, 403):
            return True
        return (
            "InvalidAuthenticationToken" in self.body or "Authorization_RequestDenied" in self.body
        )


def _check_response(resp: requests.Response):
    """Raise _GraphAPIError for non-2xx responses (always captures body)."""
    if resp.status_code >= 400:
        raise _GraphAPIError(resp.status_code, resp.text)


_TRANSIENT_CODES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 2
_RETRY_DELAY = 3  # seconds


def _get_with_retry(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET with retry on transient errors (429, 5xx)."""
    import time

    kwargs.setdefault("timeout", 30)
    for attempt in range(_MAX_RETRIES + 1):
        resp = session.get(url, **kwargs)
        if resp.status_code not in _TRANSIENT_CODES or attempt == _MAX_RETRIES:
            return resp
        delay = _RETRY_DELAY * (attempt + 1)
        logger.info(
            "Transient %s on %s, retrying in %ss...", resp.status_code, url.split("?")[0], delay
        )
        time.sleep(delay)
    return resp


_DEDUP_STRIP_RE = re.compile(
    r"\b(microsoft|azure|app|service|rp|resource provider|resource)\b",
    re.IGNORECASE,
)


def _canonical_name(name: str) -> str:
    """Reduce a service name to a canonical key for deduplication."""
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    stripped = _DEDUP_STRIP_RE.sub("", spaced)
    return re.sub(r"\s+", "", stripped.lower())


def _match_pattern(display_name: str) -> dict | None:
    """Match a display name against AI patterns. Returns pattern dict or None."""
    dn_lower = display_name.lower()
    for pat in AI_DISPLAY_NAME_PATTERNS:
        if pat["pattern"] in dn_lower:
            return pat
    return None


# ── Connector ─────────────────────────────────────────────────────────────


class MicrosoftConnector:
    """Discovers AI services in a Microsoft tenant via device code flow."""

    def __init__(self, client_id: str, verbose: bool = False):
        self.client_id = client_id
        self.verbose = verbose
        self._graph_session = None
        self._arm_session = None
        self._raw_responses = {}  # layer_name → raw API response data

        self._msal_app = msal.PublicClientApplication(
            self.client_id,
            authority="https://login.microsoftonline.com/organizations",
        )

    def authenticate(self, callback=None):
        """Device code flow — user signs in via browser.

        After Graph auth, silently acquires ARM token using cached refresh token.
        """
        flow = self._msal_app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise PermissionError(
                f"Device code flow failed: {flow.get('error_description', 'Unknown error')}"
            )

        if callback:
            callback(flow)

        result = self._msal_app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            error_desc = result.get("error_description", result.get("error", "Unknown"))
            raise PermissionError(f"Sign-in failed: {error_desc}")

        self._graph_session = requests.Session()
        self._graph_session.headers.update(
            {
                "Authorization": f"Bearer {result['access_token']}",
                "Content-Type": "application/json",
            }
        )

        # Try to get ARM token silently (uses cached refresh token)
        self._init_arm_session()

        return flow

    def _init_arm_session(self):
        """Acquire ARM API token using MSAL token cache."""
        accounts = self._msal_app.get_accounts()
        if not accounts:
            return

        result = self._msal_app.acquire_token_silent(ARM_SCOPES, account=accounts[0])
        if result and "access_token" in result:
            self._arm_session = requests.Session()
            self._arm_session.headers.update(
                {
                    "Authorization": f"Bearer {result['access_token']}",
                    "Content-Type": "application/json",
                }
            )
        else:
            logger.info("Could not acquire ARM token — Azure resource detection skipped")

    def discover(self) -> tuple[list[dict], dict]:
        """Run all detection layers and return (services, metadata)."""
        if not self._graph_session:
            raise RuntimeError("Not authenticated. Call authenticate() first.")

        apis_queried = []
        apis_failed = []
        permissions_missing = []

        # ── Layer 1: Service Principals ────────────────────────────────
        sp_services = {}
        try:
            sp_services = self._query_service_principals()
            apis_queried.append("servicePrincipals")
        except _GraphAPIError as e:
            apis_failed.append("servicePrincipals")
            if e.is_auth_error():
                permissions_missing.append("Application.Read.All")
            logger.warning("servicePrincipals query failed: %s", e)
        except Exception as e:
            apis_failed.append("servicePrincipals")
            logger.warning("servicePrincipals query failed: %s", e)

        # ── Layer 2: Sign-in Logs (best-effort, requires AAD Premium) ──
        signin_data = {}
        try:
            signin_data = self._query_signin_logs()
            apis_queried.append("auditLogs/signIns")
        except (_GraphAPIError, Exception) as e:
            logger.info("signIns query skipped: %s", e)

        # ── Layer 3: Copilot Usage Report ──────────────────────────────
        copilot_data = {}
        try:
            copilot_data = self._query_copilot_usage()
            apis_queried.append("reports/copilotUsage")
        except _GraphAPIError as e:
            apis_failed.append("reports/copilotUsage")
            if e.is_auth_error():
                permissions_missing.append("Reports.Read.All")
            logger.warning("copilotUsage query failed: %s", e)
        except Exception as e:
            apis_failed.append("reports/copilotUsage")
            logger.warning("copilotUsage query failed: %s", e)

        # ── Layer 4: License Inventory ─────────────────────────────────
        license_services = {}
        try:
            license_services = self._query_licenses()
            apis_queried.append("subscribedSkus")
        except _GraphAPIError as e:
            apis_failed.append("subscribedSkus")
            if e.is_auth_error():
                permissions_missing.append("Organization.Read.All")
            logger.warning("subscribedSkus query failed: %s", e)
        except Exception as e:
            apis_failed.append("subscribedSkus")
            logger.warning("subscribedSkus query failed: %s", e)

        # ── Layer 5: Azure Resources (ARM) ─────────────────────────────
        arm_services = {}
        if self._arm_session:
            try:
                arm_services = self._query_azure_resources()
                apis_queried.append("resourceGraph")
            except _GraphAPIError as e:
                apis_failed.append("resourceGraph")
                if e.is_auth_error():
                    permissions_missing.append("Azure RBAC Reader role")
                logger.warning("ARM resource query failed: %s", e)
            except Exception as e:
                apis_failed.append("resourceGraph")
                logger.warning("ARM resource query failed: %s", e)
        else:
            apis_failed.append("resourceGraph (no token)")

        # ── Layer 6: Resolve confirmed access connections ──────────────
        if arm_services and self._arm_session and self._graph_session:
            confirmed = self._resolve_access_connections(arm_services)
            for agent_name, endpoint_names in confirmed.items():
                # Find the agent in arm_services by name match
                for key, svc in arm_services.items():
                    if svc["name"] == agent_name:
                        svc["evidence"]["access_connections"] = [
                            {"target": ep, "confirmed": True} for ep in endpoint_names
                        ]
                        break

        # ── Merge ──────────────────────────────────────────────────────
        services = self._merge_services(
            sp_services,
            signin_data,
            copilot_data,
            license_services,
            arm_services,
        )

        # ── Topology ──────────────────────────────────────────────────
        topology = self._build_topology(services)

        if not apis_queried:
            status = "failed"
        elif apis_failed:
            status = "partial"
        else:
            status = "complete"

        # Count Azure OpenAI inspection results
        azure_openai_inspected = 0
        azure_openai_inspection_failed = 0
        for svc in services:
            evidence = svc.get("evidence", {})
            if evidence.get("resource_type") == "microsoft.cognitiveservices/accounts":
                if (
                    evidence.get("models") is not None
                    or evidence.get("security", {}).get("content_filtering") is not None
                ):
                    azure_openai_inspected += 1
                else:
                    azure_openai_inspection_failed += 1

        metadata = {
            "status": status,
            "apis_queried": apis_queried,
            "apis_failed": apis_failed,
            "permissions_missing": permissions_missing,
            "azure_openai_inspected": azure_openai_inspected,
            "azure_openai_inspection_failed": azure_openai_inspection_failed,
            "topology": topology,
        }

        return services, metadata

    # ── Graph API queries ──────────────────────────────────────────────

    def _query_service_principals(self) -> dict:
        """Layer 1: Service principals — find AI-related apps."""
        services = {}
        raw_pages = []
        url = (
            f"{GRAPH_BASE}/v1.0/servicePrincipals"
            "?$top=999&$select=appId,displayName,publisherName,tags,servicePrincipalType"
        )

        while url:
            resp = _get_with_retry(self._graph_session, url)
            _check_response(resp)
            data = resp.json()
            if self.verbose:
                raw_pages.append(data)

            for sp in data.get("value", []):
                app_id = sp.get("appId", "")
                display_name = sp.get("displayName", "")
                publisher = sp.get("publisherName", "")
                tags = sp.get("tags", [])
                sp_type = sp.get("servicePrincipalType", "")

                # Check known AI app IDs
                if app_id in KNOWN_AI_APPS:
                    info = KNOWN_AI_APPS[app_id]
                    key = info["name"].lower()
                    services[key] = {
                        "name": info["name"],
                        "category": info["category"],
                        "status": "consented",
                        "evidence": {
                            "sources": ["service_principals"],
                            "app_id": app_id,
                            "publisher": publisher or info.get("publisher", ""),
                        },
                        "testable": info.get("testable", False),
                    }
                    continue

                # Check display name patterns
                pat = _match_pattern(display_name)
                if pat:
                    key = display_name.lower()
                    if key not in services:
                        services[key] = {
                            "name": display_name,
                            "category": pat["category"],
                            "status": "consented",
                            "evidence": {
                                "sources": ["service_principals"],
                                "app_id": app_id,
                                "publisher": publisher,
                                "tags": tags,
                            },
                            "testable": pat.get("testable", False),
                        }
                    continue

                # Check tags for bot indicators
                tags_lower = " ".join(tags).lower()
                if any(t in tags_lower for t in ("bot", "pva", "copilot", "virtual agent")):
                    key = display_name.lower()
                    if key not in services:
                        services[key] = {
                            "name": display_name,
                            "category": "copilot_studio_agent",
                            "status": "consented",
                            "evidence": {
                                "sources": ["service_principals"],
                                "app_id": app_id,
                                "publisher": publisher,
                                "tags": tags,
                                "detection": "tag_match",
                            },
                            "testable": True,
                        }

            url = data.get("@odata.nextLink")

        if self.verbose:
            self._raw_responses["servicePrincipals"] = raw_pages

        return services

    def _query_signin_logs(self) -> dict:
        """Layer 2: Sign-in logs — AI app usage activity.

        Uses server-side $filter on known AI app IDs so Graph only returns
        relevant sign-ins instead of the full audit log (which times out
        on large tenants).
        """
        activity = {}
        raw_pages = []

        # Build OData filter: appId in ('id1', 'id2', ...)
        quoted_ids = ", ".join(f"'{app_id}'" for app_id in KNOWN_AI_APPS)
        app_filter = f"appId in ({quoted_ids})"

        url = (
            f"{GRAPH_BASE}/v1.0/auditLogs/signIns"
            f"?$top=500&$filter={app_filter}"
            "&$select=appId,appDisplayName,userId,createdDateTime"
        )
        pages = 0

        while url and pages < 2:
            resp = _get_with_retry(self._graph_session, url)
            _check_response(resp)
            data = resp.json()
            if self.verbose:
                raw_pages.append(data)

            for entry in data.get("value", []):
                app_id = entry.get("appId", "")
                app_name = entry.get("appDisplayName", "")
                user_id = entry.get("userId", "")
                timestamp = entry.get("createdDateTime", "")

                is_ai = app_id in KNOWN_AI_APPS or _match_pattern(app_name) is not None
                if not is_ai:
                    continue

                key = app_name.lower()
                if key not in activity:
                    activity[key] = {
                        "app_name": app_name,
                        "app_id": app_id,
                        "unique_users": set(),
                        "total_sign_ins": 0,
                        "last_activity": "",
                    }

                activity[key]["unique_users"].add(user_id)
                activity[key]["total_sign_ins"] += 1
                if timestamp > activity[key]["last_activity"]:
                    activity[key]["last_activity"] = timestamp

            url = data.get("@odata.nextLink")
            pages += 1

        for key in activity:
            activity[key]["active_users"] = len(activity[key]["unique_users"])
            del activity[key]["unique_users"]

        if self.verbose:
            self._raw_responses["auditLogs/signIns"] = raw_pages

        return activity

    def _query_copilot_usage(self) -> dict:
        """Layer 3: M365 Copilot usage report."""
        url = f"{GRAPH_BASE}/beta/reports/getMicrosoft365CopilotUsageUserDetail(period='D30')"
        resp = _get_with_retry(self._graph_session, url)
        _check_response(resp)
        data = resp.json()

        if self.verbose:
            self._raw_responses["reports/copilotUsage"] = data

        licensed_users = 0
        active_users = 0
        for entry in data.get("value", []):
            licensed_users += 1
            if entry.get("lastActivityDate"):
                active_users += 1

        return {"licensed_users": licensed_users, "active_users": active_users}

    def _query_licenses(self) -> dict:
        """Layer 4: Subscribed SKUs — detect AI-related licenses."""
        services = {}
        url = f"{GRAPH_BASE}/v1.0/subscribedSkus?$select=skuPartNumber,prepaidUnits,consumedUnits,servicePlans"
        resp = _get_with_retry(self._graph_session, url)
        _check_response(resp)
        data = resp.json()

        if self.verbose:
            self._raw_responses["subscribedSkus"] = data

        for sku in data.get("value", []):
            sku_name = sku.get("skuPartNumber", "")
            sku_lower = sku_name.lower()

            # Check if this SKU matches any AI license pattern
            matched_pat = None
            for pat in AI_LICENSE_PATTERNS:
                if pat["pattern"] in sku_lower:
                    matched_pat = pat
                    break

            # Also check service plan names inside the SKU
            if not matched_pat:
                for plan in sku.get("servicePlans", []):
                    plan_name = plan.get("servicePlanName", "").lower()
                    for pat in AI_LICENSE_PATTERNS:
                        if pat["pattern"] in plan_name:
                            matched_pat = pat
                            break
                    if matched_pat:
                        break

            if not matched_pat:
                continue

            prepaid = sku.get("prepaidUnits", {})
            total_licenses = prepaid.get("enabled", 0)
            consumed = sku.get("consumedUnits", 0)

            # Make a human-readable name from the SKU part number
            display_name = sku_name.replace("_", " ").title()

            key = display_name.lower()
            services[key] = {
                "name": display_name,
                "category": matched_pat["category"],
                "status": "licensed",
                "evidence": {
                    "sources": ["license_inventory"],
                    "sku": sku_name,
                    "licensed_users": total_licenses,
                    "consumed_licenses": consumed,
                },
                "testable": matched_pat.get("testable", False),
            }

        return services

    # ── ARM API queries ────────────────────────────────────────────────

    def _query_model_catalog(self, sub_id: str, location: str) -> dict:
        """Query the model catalog for a given subscription and location.

        Returns a lookup dict keyed by (model_name, version) with lifecycle data.
        Uses the ARM models list API (one call per unique location).
        """
        from datetime import datetime, timezone

        catalog = {}
        url = (
            f"{ARM_BASE}/subscriptions/{sub_id}"
            f"/providers/Microsoft.CognitiveServices/locations/{location}"
            f"/models?api-version=2024-10-01"
        )

        try:
            resp = _get_with_retry(self._arm_session, url)
            _check_response(resp)
            data = resp.json()

            if self.verbose:
                self._raw_responses.setdefault("modelCatalog", []).append(
                    {
                        "location": location,
                        "models_count": len(data.get("value", [])),
                        "raw": data,
                    }
                )

            now = datetime.now(timezone.utc)

            for entry in data.get("value", []):
                model = entry.get("model", {})
                model_name = model.get("name", "")
                version = model.get("version", "")
                if not model_name:
                    continue

                vendor_status = model.get("lifecycleStatus", "")
                deprecation = model.get("deprecation", {})
                inference_deprecation = deprecation.get("inference", "")

                # Extract best retirement date from SKUs
                retirement_date = None
                deprecation_date = None
                for sku in entry.get("skus", []):
                    rd = sku.get("retirementDate", "")
                    dd = sku.get("deprecationDate", "")
                    if rd and (retirement_date is None or rd < retirement_date):
                        retirement_date = rd
                    if dd and (deprecation_date is None or dd < deprecation_date):
                        deprecation_date = dd

                # Use inference deprecation date as fallback
                if not deprecation_date and inference_deprecation:
                    deprecation_date = inference_deprecation

                # Normalize dates to ISO date strings (strip time component)
                dep_date_str = deprecation_date[:10] if deprecation_date else None
                ret_date_str = retirement_date[:10] if retirement_date else None

                # Compute vendor-agnostic status
                if ret_date_str:
                    try:
                        ret_dt = datetime.strptime(ret_date_str, "%Y-%m-%d").replace(
                            tzinfo=timezone.utc
                        )
                        if now >= ret_dt:
                            status = "retired"
                        else:
                            status = "deprecated" if vendor_status == "deprecated" else "active"
                    except ValueError:
                        status = "deprecated" if vendor_status == "deprecated" else "active"
                elif vendor_status == "deprecated":
                    status = "deprecated"
                else:
                    status = "active"

                catalog[(model_name, version)] = {
                    "status": status,
                    "deprecation_date": dep_date_str,
                    "retirement_date": ret_date_str,
                }

        except _GraphAPIError as e:
            logger.info(
                "Model catalog query failed for %s/%s (HTTP %s)", sub_id, location, e.status_code
            )
        except Exception as e:
            logger.info("Model catalog query failed for %s/%s: %s", sub_id, location, e)

        return catalog

    def _inspect_cognitive_services(self, resource: dict) -> dict:
        """Inspect an Azure Cognitive Services account for deployments and RAI policies.

        Makes two ARM REST calls per resource. Each independently try/caught
        so a 403 on one doesn't block the other.

        Returns:
            {"deployments": [...], "content_filtering": {...}}
        """
        sub_id = resource.get("subscriptionId", "")
        rg = resource.get("resourceGroup", "")
        name = resource.get("name", "")
        api_version = "2024-10-01"
        base_path = (
            f"{ARM_BASE}/subscriptions/{sub_id}/resourceGroups/{rg}"
            f"/providers/Microsoft.CognitiveServices/accounts/{name}"
        )

        result = {"deployments": [], "content_filtering": {}, "_raw": {}}

        # ── Deployments ───────────────────────────────────────────────
        try:
            url = f"{base_path}/deployments?api-version={api_version}"
            resp = _get_with_retry(self._arm_session, url)
            _check_response(resp)
            raw_deployments = resp.json()
            if self.verbose:
                result["_raw"]["deployments"] = raw_deployments
            for dep in raw_deployments.get("value", []):
                props = dep.get("properties", {})
                model = props.get("model", {})
                sku = dep.get("sku", {})
                result["deployments"].append(
                    {
                        "name": dep.get("name", ""),
                        "model": model.get("name", ""),
                        "version": model.get("version", ""),
                        "sku_name": sku.get("name", ""),
                        "sku_capacity": sku.get("capacity"),
                    }
                )
        except _GraphAPIError as e:
            logger.info("Deployments query failed for %s (HTTP %s)", name, e.status_code)
        except Exception as e:
            logger.info("Deployments query failed for %s: %s", name, e)

        # ── RAI Policies ──────────────────────────────────────────────
        try:
            url = f"{base_path}/raiPolicies?api-version={api_version}"
            resp = _get_with_retry(self._arm_session, url)
            _check_response(resp)
            raw_rai = resp.json()
            if self.verbose:
                result["_raw"]["raiPolicies"] = raw_rai
            policies = raw_rai.get("value", [])

            has_content_filters = False
            prompt_shield_enabled = False
            protected_material = False
            custom_blocklist_count = 0
            filter_details = {}

            for policy in policies:
                props = policy.get("properties", {})

                # Content filters (hate, sexual, violence, self_harm)
                for rule in props.get("contentFilters", []):
                    category = rule.get("name", "")
                    if rule.get("enabled", False):
                        has_content_filters = True
                        severity = rule.get("severityThreshold", "")
                        filter_details[category] = severity

                # Prompt Shield / Jailbreak detection
                if props.get("promptShieldEnabled") or props.get("jailbreakEnabled"):
                    prompt_shield_enabled = True

                # Protected material detection
                if props.get("protectedMaterialEnabled"):
                    protected_material = True

                # Custom blocklists
                blocklists = props.get("customBlocklists", [])
                custom_blocklist_count += len(blocklists)

            result["content_filtering"] = {
                "has_content_filters": has_content_filters,
                "prompt_shield_enabled": prompt_shield_enabled,
                "protected_material": protected_material,
                "custom_blocklist_count": custom_blocklist_count,
                "filter_details": filter_details,
            }
        except _GraphAPIError as e:
            logger.info("RAI policies query failed for %s (HTTP %s)", name, e.status_code)
        except Exception as e:
            logger.info("RAI policies query failed for %s: %s", name, e)

        return result

    def _inspect_bot_service(self, resource: dict) -> dict:
        """Inspect an Azure Bot Service for properties and channel configuration.

        Makes two ARM REST calls per resource. Each independently try/caught
        so a 403 on one doesn't block the other.

        Returns:
            {"properties": {...}, "channels": [...]}
        """
        sub_id = resource.get("subscriptionId", "")
        rg = resource.get("resourceGroup", "")
        name = resource.get("name", "")
        api_version = "2023-09-15-preview"
        base_path = (
            f"{ARM_BASE}/subscriptions/{sub_id}/resourceGroups/{rg}"
            f"/providers/Microsoft.BotService/botServices/{name}"
        )

        result = {"properties": {}, "channels": [], "_raw": {}}

        # ── Bot Properties ─────────────────────────────────────────────
        try:
            url = f"{base_path}?api-version={api_version}"
            resp = _get_with_retry(self._arm_session, url)
            _check_response(resp)
            data = resp.json()
            if self.verbose:
                result["_raw"]["botProperties"] = data
            # Bot Service double-nests: properties.properties
            props = data.get("properties", {})
            result["properties"] = {
                "display_name": props.get("displayName", ""),
                "endpoint": props.get("endpoint", ""),
                "msa_app_id": props.get("msaAppId", ""),
                "msa_app_type": props.get("msaAppType", ""),
                "disable_local_auth": props.get("disableLocalAuth", False),
                "public_network_access": props.get("publicNetworkAccess", "Enabled"),
                "description": props.get("description", ""),
                "bot_kind": data.get("kind", ""),
                "storage_resource_id": props.get("storageResourceId", ""),
            }
        except _GraphAPIError as e:
            logger.info("Bot properties query failed for %s (HTTP %s)", name, e.status_code)
        except Exception as e:
            logger.info("Bot properties query failed for %s: %s", name, e)

        # ── Bot Channels ───────────────────────────────────────────────
        try:
            url = f"{base_path}/channels?api-version={api_version}"
            resp = _get_with_retry(self._arm_session, url)
            _check_response(resp)
            raw_channels = resp.json()
            if self.verbose:
                result["_raw"]["botChannels"] = raw_channels
            for ch in raw_channels.get("value", []):
                ch_props = ch.get("properties", {})
                # Channel properties are also nested under properties.properties
                inner_props = ch_props.get("properties", {})
                channel_name = ch_props.get("channelName", ch.get("name", ""))

                channel_info = {
                    "name": channel_name,
                    "is_enabled": inner_props.get("isEnabled", True),
                }

                # WebChat and DirectLine have security-relevant fields
                if channel_name in ("WebChatChannel", "DirectLineChannel"):
                    sites = inner_props.get("sites", [])
                    is_secure = (
                        all(s.get("isSecureSiteEnabled", False) for s in sites) if sites else False
                    )
                    trusted_origins = []
                    for s in sites:
                        trusted_origins.extend(s.get("trustedOrigins", []))
                    channel_info["is_secure_site_enabled"] = is_secure
                    channel_info["trusted_origins"] = trusted_origins

                result["channels"].append(channel_info)
        except _GraphAPIError as e:
            logger.info("Bot channels query failed for %s (HTTP %s)", name, e.status_code)
        except Exception as e:
            logger.info("Bot channels query failed for %s: %s", name, e)

        return result

    def _query_azure_resources(self) -> dict:
        """Layer 5: Azure Resource Graph — AI-related resources."""
        services = {}
        model_catalog_cache = {}  # (sub_id, location) → catalog dict

        url = f"{ARM_BASE}/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01"
        body = {
            "query": ARM_RESOURCE_GRAPH_QUERY,
            "options": {"resultFormat": "objectArray"},
        }

        resp = self._arm_session.post(url, json=body, timeout=30)
        _check_response(resp)
        data = resp.json()

        if self.verbose:
            self._raw_responses["resourceGraph"] = data

        for row in data.get("data", []):
            name = row.get("name", "")
            res_type = row.get("type", "").lower()
            location = row.get("location", "")
            kind = row.get("kind", "")
            sku_name = row.get("skuName", "")
            resource_group = row.get("resourceGroup", "")

            type_info = ARM_RESOURCE_TYPES.get(res_type, {})
            if not type_info:
                continue

            # ── Resource filtering ─────────────────────────────────────
            # ML Hubs are infrastructure, not agents — skip
            if res_type == "microsoft.machinelearningservices/workspaces" and kind == "Hub":
                continue
            # Cognitive Services that aren't AI/OpenAI — skip (e.g. ContentSafety, TextAnalytics)
            if res_type == "microsoft.cognitiveservices/accounts" and kind not in (
                "AIServices",
                "OpenAI",
                "",
            ):
                continue

            # Build descriptive name
            if kind:
                display_name = f"{name} ({kind})"
            else:
                type_label = res_type.split("/")[-1]
                display_name = f"{name} ({type_label})"

            evidence = {
                "sources": ["azure_resources"],
                "resource_type": res_type,
                "location": location,
                "kind": kind,
                "sku": sku_name,
                "resource_group": resource_group,
                "subscription_id": row.get("subscriptionId", ""),
                "raw_name": name,
            }

            # ML Projects are in-development workloads — tag for low-risk override
            if res_type == "microsoft.machinelearningservices/workspaces" and kind == "Project":
                evidence["stage"] = "in_development"

            # ML Workspaces — security from Resource Graph properties only
            if res_type == "microsoft.machinelearningservices/workspaces":
                evidence["security"] = {
                    "public_access": row.get("publicNetworkAccess") != "Disabled"
                    if row.get("publicNetworkAccess") is not None
                    else None,
                    "local_auth_disabled": row.get("disableLocalAuth"),
                    "content_filtering": None,
                    "injection_protection": None,
                    "channel_secure": None,
                    "trusted_origins": None,
                }

            # Deep inspection for Cognitive Services (Azure OpenAI)
            if res_type == "microsoft.cognitiveservices/accounts":
                inspection = self._inspect_cognitive_services(row)
                if self.verbose:
                    self._raw_responses.setdefault("cognitiveServices/inspect", []).append(
                        {
                            "resource": name,
                            "raw": inspection.get("_raw", {}),
                        }
                    )

                # Build generic security schema from vendor-specific data
                cf = inspection.get("content_filtering", {})
                evidence["security"] = {
                    "public_access": row.get("publicNetworkAccess") != "Disabled"
                    if row.get("publicNetworkAccess") is not None
                    else None,
                    "local_auth_disabled": row.get("disableLocalAuth"),
                    "content_filtering": cf.get("has_content_filters", False) if cf else None,
                    "injection_protection": cf.get("prompt_shield_enabled", False) if cf else None,
                    "channel_secure": None,
                    "trusted_origins": None,
                }

                # Query model catalog for lifecycle data (cached per location)
                cache_key = (row.get("subscriptionId", ""), location)
                if cache_key not in model_catalog_cache:
                    model_catalog_cache[cache_key] = self._query_model_catalog(
                        cache_key[0],
                        cache_key[1],
                    )
                catalog = model_catalog_cache[cache_key]

                # Generic model list for vendor-agnostic display
                evidence["models"] = []
                for dep in inspection.get("deployments", []):
                    model_name = dep.get("model", dep.get("name", ""))
                    version = dep.get("version", "")
                    lifecycle = catalog.get((model_name, version))

                    model_entry = {
                        "name": model_name,
                        "version": version,
                        "sku": dep.get("sku_name", ""),
                        "capacity": dep.get("sku_capacity"),
                    }
                    if lifecycle:
                        model_entry["lifecycle"] = lifecycle
                    else:
                        model_entry["lifecycle"] = {
                            "status": "active",
                            "deprecation_date": None,
                            "retirement_date": None,
                        }
                    evidence["models"].append(model_entry)

            # Deep inspection for Bot Service
            if res_type == "microsoft.botservice/botservices":
                inspection = self._inspect_bot_service(row)
                if self.verbose:
                    self._raw_responses.setdefault("botService/inspect", []).append(
                        {
                            "resource": name,
                            "raw": inspection.get("_raw", {}),
                        }
                    )
                # Use display name from bot properties when available
                bot_display = inspection["properties"].get("display_name")
                if bot_display:
                    display_name = bot_display

                # Build generic security schema from vendor-specific data
                props = inspection.get("properties", {})
                channels = inspection.get("channels", [])
                channel_secure = None
                trusted_origins = None
                for ch in channels:
                    if ch.get("name") in ("WebChatChannel", "DirectLineChannel"):
                        channel_secure = ch.get("is_secure_site_enabled", False)
                        trusted_origins = ch.get("trusted_origins", [])

                evidence["security"] = {
                    "public_access": props.get("public_network_access") != "Enabled"
                    if props.get("public_network_access") is not None
                    else (
                        row.get("publicNetworkAccess") != "Disabled"
                        if row.get("publicNetworkAccess") is not None
                        else None
                    ),
                    "local_auth_disabled": props.get("disable_local_auth"),
                    "content_filtering": None,
                    "injection_protection": None,
                    "channel_secure": channel_secure,
                    "trusted_origins": trusted_origins,
                }

                # Generic channel list for vendor-agnostic display
                evidence["channels"] = [
                    {
                        "name": ch.get("name", "").replace("Channel", ""),
                        "enabled": ch.get("is_enabled", True),
                    }
                    for ch in channels
                ]
                evidence["auth_type"] = props.get("msa_app_type", "")

                # Generic linked resources for topology
                storage_id = props.get("storage_resource_id", "")
                if storage_id:
                    evidence["linked_storage"] = (
                        storage_id.split("/")[-1] if "/" in storage_id else storage_id
                    )
                evidence["identity_id"] = props.get("msa_app_id", "")

            key = display_name.lower()
            services[key] = {
                "name": display_name,
                "category": type_info["category"],
                "status": "active",
                "evidence": evidence,
                "testable": type_info.get("testable", False),
            }

        # ── Copilot Studio agents (PowerPlatformResources table) ───────
        try:
            pp_body = {
                "query": POWER_PLATFORM_RESOURCE_GRAPH_QUERY,
                "options": {"resultFormat": "objectArray"},
            }
            pp_resp = self._arm_session.post(url, json=pp_body, timeout=30)
            _check_response(pp_resp)
            pp_data = pp_resp.json()

            if self.verbose:
                self._raw_responses["powerPlatformResources"] = pp_data

            for row in pp_data.get("data", []):
                agent_name = row.get("name", "")
                props = row.get("properties", {})
                if isinstance(props, str):
                    import json as _json

                    try:
                        props = _json.loads(props)
                    except Exception:
                        props = {}

                display_name = props.get("displayName", agent_name)
                location = row.get("location", "")
                environment_id = props.get("environmentId", "")

                evidence = {
                    "sources": ["azure_resources"],
                    "resource_type": "microsoft.copilotstudio/agents",
                    "location": location,
                    "environment_id": environment_id,
                    "agent_id": agent_name,
                    "created_at": props.get("createdAt", ""),
                    "modified_at": props.get("modifiedAt", ""),
                    "owner_id": props.get("ownerId", ""),
                    "security": {
                        "public_access": None,
                        "local_auth_disabled": None,
                        "content_filtering": None,
                        "injection_protection": None,
                        "channel_secure": None,
                        "trusted_origins": None,
                    },
                    "channels": [{"name": "Microsoft 365", "enabled": True}],
                    "auth_type": "Cloud Identity",
                }

                key = display_name.lower()
                if key not in services:
                    services[key] = {
                        "name": display_name,
                        "category": "copilot_studio_agent",
                        "status": "active",
                        "evidence": evidence,
                        "testable": True,
                    }
        except _GraphAPIError as e:
            logger.info(
                "PowerPlatformResources query failed (HTTP %s) — Copilot Studio agents skipped",
                e.status_code,
            )
        except Exception as e:
            logger.info(
                "PowerPlatformResources query failed: %s — Copilot Studio agents skipped", e
            )

        # ── Resolve owner IDs to display names ─────────────────────────
        owner_ids = [
            svc["evidence"].get("owner_id", "")
            for svc in services.values()
            if svc["evidence"].get("owner_id")
        ]
        if owner_ids:
            names = self._resolve_user_names(owner_ids)
            for svc in services.values():
                oid = svc["evidence"].get("owner_id", "")
                if oid and oid in names:
                    svc["evidence"]["owner_name"] = names[oid]

        return services

    def _resolve_user_names(self, user_ids: list) -> dict:
        """Resolve user IDs to display names via Graph API.

        Calls GET /users/{id} per unique ID. Requires User.ReadBasic.All.
        Returns {id: displayName} dict. Silently skips failures.
        """
        if not user_ids or not self._graph_session:
            return {}

        unique_ids = list({uid for uid in user_ids if uid})
        if not unique_ids:
            return {}

        result = {}
        for uid in unique_ids:
            try:
                url = f"{GRAPH_BASE}/v1.0/users/{uid}?$select=id,displayName"
                resp = _get_with_retry(self._graph_session, url)
                _check_response(resp)
                data = resp.json()
                name = data.get("displayName", "")
                if name:
                    result[uid] = name
            except Exception:
                continue  # skip unresolvable IDs (service accounts, deleted users, etc.)

        return result

    # ── Access connection resolution ──────────────────────────────────

    def _resolve_access_connections(self, services: dict) -> dict:
        """Resolve which agents have confirmed access to which AI endpoints.

        Uses identity → resource access verification (vendor-specific).
        Returns {agent_name: [endpoint_name, ...]} for confirmed connections.
        Silently degrades if access verification unavailable.
        """
        # 1. Collect agent identities (msaAppId → agent names)
        agent_identities = {}
        for svc in services.values():
            identity = svc["evidence"].get("identity_id", "")
            if identity and svc.get("category") == "copilot_studio_agent":
                agent_identities.setdefault(identity, []).append(svc["name"])

        if not agent_identities:
            return {}

        # 2. Resolve app IDs to service principal object IDs via Graph API
        sp_to_agents = {}  # {objectId: [agent_name, ...]}
        sp_map = {}  # for verbose logging
        for app_id, agent_names in agent_identities.items():
            try:
                url = f"{GRAPH_BASE}/v1.0/servicePrincipals(appId='{app_id}')?$select=id,appId"
                resp = _get_with_retry(self._graph_session, url)
                _check_response(resp)
                data = resp.json()
                object_id = data.get("id", "")
                if object_id:
                    sp_to_agents[object_id] = agent_names
                    sp_map[app_id] = object_id
            except Exception as e:
                logger.info("SP resolution failed for appId %s: %s", app_id, e)
                continue

        if not sp_to_agents:
            return {}

        # 3. For each AI endpoint, query access assignments via ARM API
        connections = {}
        all_assignments = []
        for svc in services.values():
            if svc.get("category") != "ai_platform":
                continue

            ev = svc["evidence"]
            sub_id = ev.get("subscription_id", "")
            rg = ev.get("resource_group", "")
            res_type = ev.get("resource_type", "")
            endpoint_name = svc["name"]

            # Build ARM resource ID from evidence
            if res_type == "microsoft.cognitiveservices/accounts":
                # Extract raw name (strip kind suffix like " (OpenAI)")
                raw_name = ev.get("raw_name", endpoint_name.split(" (")[0])
                resource_id = (
                    f"/subscriptions/{sub_id}/resourceGroups/{rg}"
                    f"/providers/Microsoft.CognitiveServices/accounts/{raw_name}"
                )
            else:
                continue  # Only query role assignments for cognitive services

            if not sub_id or not rg:
                continue

            try:
                url = (
                    f"{ARM_BASE}{resource_id}"
                    "/providers/Microsoft.Authorization/roleAssignments"
                    "?api-version=2022-04-01&$filter=atScope()"
                )
                resp = _get_with_retry(self._arm_session, url)
                _check_response(resp)
                data = resp.json()
                assignments = data.get("value", [])

                if self.verbose:
                    all_assignments.append(
                        {
                            "endpoint": endpoint_name,
                            "resource_id": resource_id,
                            "assignments_count": len(assignments),
                        }
                    )

                for assignment in assignments:
                    props = assignment.get("properties", {})
                    principal_id = props.get("principalId", "")
                    principal_type = props.get("principalType", "")

                    if principal_type != "ServicePrincipal":
                        continue
                    if principal_id not in sp_to_agents:
                        continue

                    for agent_name in sp_to_agents[principal_id]:
                        connections.setdefault(agent_name, []).append(endpoint_name)

            except _GraphAPIError as e:
                if e.status_code == 403:
                    logger.info(
                        "Access verification unavailable for %s (403) — "
                        "user lacks Authorization.Read permission",
                        endpoint_name,
                    )
                else:
                    logger.info(
                        "Access verification failed for %s (HTTP %s)",
                        endpoint_name,
                        e.status_code,
                    )
            except Exception as e:
                logger.info("Access verification failed for %s: %s", endpoint_name, e)

        if self.verbose:
            self._raw_responses["accessConnections"] = {
                "sp_resolutions": sp_map,
                "role_assignments": all_assignments,
                "confirmed_connections": connections,
            }

        return connections

    # ── Merge + deduplicate ────────────────────────────────────────────

    def _merge_services(
        self,
        sp_services: dict,
        signin_data: dict,
        copilot_data: dict,
        license_services: dict,
        arm_services: dict,
    ) -> list[dict]:
        """Merge results from all layers into a unified, deduplicated list."""
        merged = dict(sp_services)

        # Enrich with sign-in activity (Layer 2)
        for key, activity in signin_data.items():
            if key in merged:
                svc = merged[key]
                evidence = svc["evidence"]
                if "sign_in_logs" not in evidence.get("sources", []):
                    evidence["sources"].append("sign_in_logs")
                evidence["active_users"] = activity["active_users"]
                evidence["sign_in_count"] = activity["total_sign_ins"]
                evidence["last_activity"] = activity["last_activity"]
                if _STATUS_RANK.get(svc["status"], 0) < _STATUS_RANK["active"]:
                    svc["status"] = "active"
            else:
                pat = _match_pattern(activity["app_name"])
                info = KNOWN_AI_APPS.get(activity["app_id"], {})
                category = info.get("category") or (pat["category"] if pat else "standalone_ai")

                merged[key] = {
                    "name": activity["app_name"],
                    "category": category,
                    "status": "active",
                    "evidence": {
                        "sources": ["sign_in_logs"],
                        "app_id": activity["app_id"],
                        "active_users": activity["active_users"],
                        "sign_in_count": activity["total_sign_ins"],
                        "last_activity": activity["last_activity"],
                    },
                    "testable": info.get("testable", False)
                    or (pat.get("testable", False) if pat else False),
                }

        # Enrich Copilot entry with usage data (Layer 3)
        if copilot_data:
            copilot_key = "microsoft 365 copilot"
            if copilot_key in merged:
                svc = merged[copilot_key]
                evidence = svc["evidence"]
                if "copilot_usage_report" not in evidence.get("sources", []):
                    evidence["sources"].append("copilot_usage_report")
                evidence["licensed_users"] = copilot_data["licensed_users"]
                if copilot_data.get("active_users"):
                    evidence["active_users"] = copilot_data["active_users"]
                svc["status"] = "licensed"
            elif copilot_data.get("licensed_users", 0) > 0:
                merged[copilot_key] = {
                    "name": "Microsoft 365 Copilot",
                    "category": "embedded_copilot",
                    "status": "licensed",
                    "evidence": {
                        "sources": ["copilot_usage_report"],
                        "licensed_users": copilot_data["licensed_users"],
                        "active_users": copilot_data.get("active_users", 0),
                    },
                    "testable": True,
                }

        # Add license inventory entries (Layer 4)
        for key, svc in license_services.items():
            if key not in merged:
                merged[key] = svc
            else:
                existing = merged[key]
                if "license_inventory" not in existing["evidence"].get("sources", []):
                    existing["evidence"]["sources"].append("license_inventory")
                existing["evidence"]["sku"] = svc["evidence"].get("sku")
                existing["evidence"]["licensed_users"] = svc["evidence"].get("licensed_users")
                existing["evidence"]["consumed_licenses"] = svc["evidence"].get("consumed_licenses")
                if _STATUS_RANK.get(existing["status"], 0) < _STATUS_RANK["licensed"]:
                    existing["status"] = "licensed"

        # Add Azure resource entries (Layer 5)
        for key, svc in arm_services.items():
            if key not in merged:
                merged[key] = svc
            else:
                existing = merged[key]
                if "azure_resources" not in existing["evidence"].get("sources", []):
                    existing["evidence"]["sources"].append("azure_resources")
                existing["evidence"]["resource_type"] = svc["evidence"].get("resource_type")
                existing["evidence"]["location"] = svc["evidence"].get("location")

        # ── Deduplicate by canonical name ──────────────────────────────
        deduped = {}
        for svc in merged.values():
            canon = _canonical_name(svc["name"])
            if canon in deduped:
                existing = deduped[canon]
                # Keep the longer (more descriptive) name
                if len(svc["name"]) > len(existing["name"]):
                    existing["name"] = svc["name"]
                # Merge evidence sources
                for src in svc["evidence"].get("sources", []):
                    if src not in existing["evidence"]["sources"]:
                        existing["evidence"]["sources"].append(src)
                # Promote status
                if _STATUS_RANK.get(svc["status"], 0) > _STATUS_RANK.get(existing["status"], 0):
                    existing["status"] = svc["status"]
                # Merge numeric evidence
                for field in (
                    "active_users",
                    "licensed_users",
                    "sign_in_count",
                    "consumed_licenses",
                ):
                    new_val = svc["evidence"].get(field)
                    old_val = existing["evidence"].get(field)
                    if new_val and (not old_val or new_val > old_val):
                        existing["evidence"][field] = new_val
                # Merge timestamps
                new_ts = svc["evidence"].get("last_activity", "")
                old_ts = existing["evidence"].get("last_activity", "")
                if new_ts and new_ts > (old_ts or ""):
                    existing["evidence"]["last_activity"] = new_ts
                # Testable if any source says testable
                existing["testable"] = existing.get("testable", False) or svc.get("testable", False)
            else:
                deduped[canon] = svc

        return list(deduped.values())

    # ── Topology ───────────────────────────────────────────────────────

    @staticmethod
    def _build_topology(services: list) -> dict:
        """Build a resource topology graph from merged services.

        Returns {"nodes": [...], "edges": [...]} describing connections
        between agents, channels, AI endpoints, models, storage, and identities.
        """
        nodes = []
        edges = []
        seen_nodes = set()

        def _add_node(node_id, name, node_type, category):
            if node_id not in seen_nodes:
                seen_nodes.add(node_id)
                nodes.append(
                    {
                        "id": node_id,
                        "name": name,
                        "type": node_type,
                        "category": category,
                    }
                )

        # Check if any agents exist — topology is only useful with cross-resource connections
        has_agents = any(
            svc.get("category") == "copilot_studio_agent"
            and (
                svc.get("evidence", {}).get("channels")
                or svc.get("evidence", {}).get("identity_id")
                or svc.get("evidence", {}).get("resource_group")
                or svc.get("evidence", {}).get("access_connections")
            )
            for svc in services
        )

        # Index AI endpoints by resource_group for co-location matching
        endpoint_by_rg = {}
        for svc in services:
            ev = svc.get("evidence", {})
            if svc.get("category") == "ai_platform":
                rg = ev.get("resource_group", "")
                node_id = f"endpoint:{svc['name']}"
                _add_node(node_id, svc["name"], "ai_endpoint", svc.get("category", "ai_platform"))
                if rg:
                    endpoint_by_rg.setdefault(rg, []).append(node_id)

                # Endpoint → Model edges only when agents exist (otherwise the
                # Endpoints section already shows models in a richer table)
                if has_agents:
                    for m in ev.get("models", []):
                        model_name = m.get("name", "")
                        if model_name:
                            model_id = f"model:{node_id}:{model_name}"
                            lifecycle = m.get("lifecycle", {})
                            _add_node(model_id, model_name, "model", "deployment")
                            # Attach lifecycle to the node for display
                            for n in nodes:
                                if n["id"] == model_id:
                                    n["lifecycle"] = lifecycle
                                    break
                            edges.append(
                                {
                                    "source": node_id,
                                    "target": model_id,
                                    "relation": "uses_model",
                                    "secure": True,
                                    "detail": m.get("sku", ""),
                                }
                            )

        # Process agents (services with channels, identity, or resource group)
        for svc in services:
            ev = svc.get("evidence", {})
            channels = ev.get("channels", [])
            if svc.get("category") != "copilot_studio_agent":
                continue
            # Include agent if it has channels, identity, resource group, or access connections
            if not (
                channels
                or ev.get("identity_id")
                or ev.get("resource_group")
                or ev.get("access_connections")
            ):
                continue

            agent_id = f"agent:{svc['name']}"
            _add_node(agent_id, svc["name"], "agent", svc.get("category", "copilot_studio_agent"))
            sec = ev.get("security", {})
            rg = ev.get("resource_group", "")

            # Agent → Channels
            channel_secure = sec.get("channel_secure")
            for ch in channels:
                if not ch.get("enabled", True):
                    continue
                ch_name = ch.get("name", "")
                ch_id = f"channel:{agent_id}:{ch_name}"
                _add_node(ch_id, ch_name, "channel", "channel")

                # Mark insecure if security dict says channels are not secure
                secure = True
                detail = ""
                if channel_secure is False:
                    secure = False
                    detail = "Secure Site disabled"

                edges.append(
                    {
                        "source": agent_id,
                        "target": ch_id,
                        "relation": "has_channel",
                        "secure": secure,
                        "detail": detail,
                    }
                )

            # Agent → AI Endpoint (confirmed access or co-located fallback)
            access_conns = ev.get("access_connections", [])
            confirmed_targets = {c["target"] for c in access_conns if c.get("confirmed")}

            if confirmed_targets:
                # Use confirmed connections
                for ep_svc in services:
                    if (
                        ep_svc.get("category") == "ai_platform"
                        and ep_svc["name"] in confirmed_targets
                    ):
                        ep_node_id = f"endpoint:{ep_svc['name']}"
                        if ep_node_id not in seen_nodes:
                            _add_node(ep_node_id, ep_svc["name"], "ai_endpoint", "ai_platform")
                        edges.append(
                            {
                                "source": agent_id,
                                "target": ep_node_id,
                                "relation": "uses_model",
                                "secure": True,
                                "detail": "confirmed access",
                            }
                        )
            elif rg and rg in endpoint_by_rg:
                # Fallback: co-located resource group (unconfirmed)
                for ep_id in endpoint_by_rg[rg]:
                    edges.append(
                        {
                            "source": agent_id,
                            "target": ep_id,
                            "relation": "uses_model",
                            "secure": True,
                            "detail": "co-located (unconfirmed)",
                        }
                    )

            # Agent → Storage
            linked_storage = ev.get("linked_storage", "")
            if linked_storage:
                storage_node_id = f"storage:{linked_storage}"
                _add_node(storage_node_id, linked_storage, "storage", "storage")
                edges.append(
                    {
                        "source": agent_id,
                        "target": storage_node_id,
                        "relation": "uses_storage",
                        "secure": True,
                        "detail": "",
                    }
                )

            # Agent → Service Principal (identity)
            identity = ev.get("identity_id", "")
            if identity:
                identity_node_id = f"identity:{identity}"
                _add_node(identity_node_id, identity, "identity", "service_principal")
                edges.append(
                    {
                        "source": agent_id,
                        "target": identity_node_id,
                        "relation": "uses_identity",
                        "secure": True,
                        "detail": ev.get("auth_type", ""),
                    }
                )

        return {"nodes": nodes, "edges": edges}
