from __future__ import annotations

from aseo.connectors.base import WebsiteConnector
from aseo.core.errors import ConnectorError


def get_connector(provider: str) -> WebsiteConnector:
    if provider == "wordpress":
        from aseo.connectors.wordpress import WordPressConnector

        return WordPressConnector()
    if provider == "shopify":
        from aseo.connectors.shopify import ShopifyConnector

        return ShopifyConnector()
    if provider == "github":
        from aseo.connectors.github import GitHubConnector

        return GitHubConnector()
    if provider == "public":
        from aseo.connectors.public import PublicConnector

        return PublicConnector()
    raise ConnectorError(f"Unknown connector provider '{provider}'", code="unknown_provider")
