"""Explicit delivery utility, never called by the analytical pipeline automatically."""

import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def send_teams_report(run: dict, role: str, webhook_url: str):
    """Send to a Teams Workflow configured to receive Adaptive Card webhook payloads.

    The workflow URL is a credential; inject at runtime and never persist or log it.
    Deploying users must explicitly opt into delivery and configure approved recipients.
    """
    if role not in run["weekly_reports"]:
        raise ValueError("Unknown report audience")
    if urlparse(webhook_url).scheme != "https":
        raise ValueError("Teams Workflow delivery requires HTTPS")
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "weight": "Bolder",
                            "text": f"InventoryPulse · {role}",
                            "wrap": True,
                        },
                        {"type": "TextBlock", "text": run["weekly_reports"][role], "wrap": True},
                        {
                            "type": "TextBlock",
                            "text": f"Cutoff: {run['as_of_date']} · Run: {run['run_id']}",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": "Estimated opportunity only. Approval does not imply realized cash.",
                            "wrap": True,
                        },
                    ],
                },
            }
        ],
    }
    request = Request(
        webhook_url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return response.status
