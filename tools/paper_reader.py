"""
title: Paper Reader
description: Queue a research paper link (arXiv or PDF) for a full deep-read report from the paper digest service.
version: 1.0.0
license: MIT
"""

# Open WebUI tool (tool id: paper_reader). Install: python scripts/install-paper-tool.py
#
# It only sends the link to the paper-digest service's queue (POST /queue, bearer key in the
# valve). The service reads the paper, saves a chat in the "Papers" folder and sends a phone push.
# Nothing is fetched here and the key is never returned.

import re

import requests
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        queue_url: str = Field(
            default="http://paper-digest:8095/queue", description="Queue endpoint of the paper-digest service."
        )
        queue_key: str = Field(default="", description="Bearer key (PAPER_QUEUE_KEY in compose/.env).")

    def __init__(self):
        self.valves = self.Valves()

    def read_paper(self, url: str) -> str:
        """
        Queue a research paper for a full deep-read report. Use this when the user pastes a link to a paper
        (an arXiv page or PDF, or another PDF URL) and asks to read, summarise, explain or report on it.
        The report is written in the background (about 20 to 30 minutes) and the user gets a phone push
        with a link to a new chat. Reply briefly that it is queued; do not try to read the paper yourself.
        :param url: The paper link, starting with http:// or https://.
        """
        url = (url or "").strip()
        if not re.match(r"^https?://\S+$", url):
            return "That is not a link. Ask the user for the paper's http(s) URL."
        if not self.valves.queue_key:
            return "The paper queue key is not set in this tool's settings (valve queue_key)."
        try:
            r = requests.post(
                self.valves.queue_url,
                json={"url": url},
                headers={"Authorization": f"Bearer {self.valves.queue_key}"},
                timeout=15,
            )
        except Exception as e:
            return f"Could not reach the paper service ({type(e).__name__}). Try again later."
        if r.status_code == 200:
            return "Queued; you'll get a push when the report is ready."
        if r.status_code == 401:
            return "The paper service rejected the key. Check the queue_key setting of this tool."
        return f"The paper service answered {r.status_code}; the paper was not queued."
