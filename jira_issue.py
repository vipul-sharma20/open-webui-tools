import base64
import json
from typing import Any, Awaitable, Callable, Dict, List

import requests
from pydantic import BaseModel, Field

EMIT_EVENTS = False


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Awaitable[None]]):
        self.event_emitter = event_emitter

    async def emit_status(self, description: str, done: bool, error: bool = False):
        await self.event_emitter(
            {
                "data": {
                    "description": f"{done and (error and '❌' or '✅') or '🔎'} {description}",
                    "status": done and "complete" or "in_progress",
                    "done": done,
                },
                "type": "status",
            }
        )

    async def emit_message(self, content: str):
        await self.event_emitter({"data": {"content": content}, "type": "message"})

    async def emit_source(self, name: str, url: str, content: str, html: bool = False):
        await self.event_emitter(
            {
                "type": "citation",
                "data": {
                    "document": [content],
                    "metadata": [{"source": url, "html": html}],
                    "source": {"name": name},
                },
            }
        )


class Jira:
    def __init__(self, username: str, api_key: str, base_url: str):
        self.base_url = base_url
        self.headers = self.authenticate(username, api_key)

    def authenticate(self, username: str, api_key: str):
        auth_string = f"{username}:{api_key}"
        encoded_auth_string = base64.b64encode(auth_string.encode("utf-8")).decode(
            "utf-8"
        )
        return {
            "Authorization": "Basic " + encoded_auth_string,
            "Content-Type": "application/json",
        }

    def get(self, endpoint: str, params: Dict[str, Any] = None):
        url = f"{self.base_url}/rest/api/3/{endpoint}"
        response = requests.get(url, params=params, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def get_issue(self, issue_id: str):
        endpoint = f"issue/{issue_id}"
        result = self.get(
            endpoint,
            {"fields": "summary,description,status", "expand": "renderedFields"},
        )

        comments = self.get_comments(issue_id)

        return {
            "title": result["fields"]["summary"],
            "description": result["renderedFields"]["description"],
            "status": result["fields"]["status"]["name"],
            "link": f"{self.base_url}/browse/{issue_id}",
            "comments": comments,
        }

    def get_comments(self, issue_id: str) -> List[Dict[str, str]]:
        """
        Fetches comments for a Jira issue.
        """
        endpoint = f"issue/{issue_id}/comment"
        result = self.get(endpoint)

        comments = []
        for comment in result.get("comments", []):
            comments.append(
                {
                    "author": comment["author"]["displayName"],
                    "body": comment["body"],
                    "created": comment["created"],
                }
            )

        return comments


class Tools:
    def __init__(self):
        self.valves = self.Valves()

    class Valves(BaseModel):
        username: str = Field("<user>@<org>.ai", description="Your username here")
        api_key: str = Field("<key>", description="Your API key here")
        base_url: str = Field(
            "https://<org>.atlassian.net/",
            description="Your Jira base URL here",
        )

    async def get_issue(
        self,
        issue_id: str,
        __event_emitter__: Callable[[dict], Awaitable[None]],
        __user__: dict = {},
    ):
        """
        Get a Jira issue by its ID. The response includes the title, description as HTML, status, link to the issue, and comments.
        :param issue_id: The ID of the issue.
        :return: A response in JSON format (title, description, status, link, comments).
        """
        jira = Jira(self.valves.username, self.valves.api_key, self.valves.base_url)
        event_emitter = EventEmitter(__event_emitter__)
        try:
            if EMIT_EVENTS:
                await event_emitter.emit_status(f"Getting issue {issue_id}", False)

            response = jira.get_issue(issue_id)

            # Emit issue details
            if EMIT_EVENTS:
                await event_emitter.emit_source(
                    response["title"], response["link"], response["description"], True
                )

            # Emit comments if available
            if response["comments"]:
                comments_content = "\n\n".join(
                    [
                        f"**{comment['author']}** ({comment['created']}): {comment['body']}"
                        for comment in response["comments"]
                    ]
                )
                if EMIT_EVENTS:
                    await event_emitter.emit_message(f"Comments:\n\n{comments_content}")

            if EMIT_EVENTS:
                await event_emitter.emit_status(f"Got issue {issue_id}", True)
            return json.dumps(response, indent=2)
        except Exception as e:
            if EMIT_EVENTS:
                await event_emitter.emit_status(
                    f"Failed to get issue {issue_id}: {e}", True, True
                )
            return f"Error: {e}"
