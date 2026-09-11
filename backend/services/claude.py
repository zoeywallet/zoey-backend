"""
Placeholder for a future Claude API integration (e.g. portfolio insights,
an in-app assistant, or narrative summaries of the dashboard data).

Not implemented yet — this file just reserves the shape so the eventual
integration has one obvious home instead of being bolted onto api/index.py
or the frontend.

When you do build this, the flow should be:

    Frontend  --(fetch to some new /api/... route)-->  FastAPI (this backend)
                                                              |
                                                              v
                                                     backend/services/claude.py
                                                              |
                                                              v
                                                        Anthropic's API

i.e. the frontend never talks to Anthropic directly and never sees an
Anthropic API key — the key lives only in a server-side environment
variable (e.g. ANTHROPIC_API_KEY, added to .env.example and to Vercel once
this is built), and the browser only ever calls your own /api/* routes.

    def get_client():
        import os
        # from anthropic import Anthropic  # add `anthropic` to requirements.txt
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        # return Anthropic(api_key=api_key)
"""

from __future__ import annotations
