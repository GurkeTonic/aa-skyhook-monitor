"""ESI client provider.

A single, reusable ESI client for the whole app. Instantiated at import time
(construction is lazy — the OpenAPI spec is only fetched on first ``.client``
access). Filtered to the Skyhook operations to keep memory low.

Public endpoints (e.g. GetSkyhooksRaidable) are called without a token —
the client still handles User-Agent, X-Compatibility-Date, ETags and rate limits.
"""

from esi.openapi_clients import ESIClientProvider

from aa_skyhook_monitor import (
    __app_name_useragent__,
    __esi_compatibility_date__,
    __github_url__,
    __version__,
)

esi = ESIClientProvider(
    compatibility_date=__esi_compatibility_date__,
    ua_appname=__app_name_useragent__,
    ua_version=__version__,
    ua_url=__github_url__,
    operations=[
        "GetCorporationsStructuresSkyhooksListing",
        "GetCorporationsStructuresSkyhooksDetail",
        "GetSkyhooksRaidable",
    ],
)
