"""
Krankenfahrt — AI-first medical transport dispatch.

Three Telegram bots replace the human dispatcher:
- @FahrGast    — Patient: book trips, get live tracking
- @FahrLenker  — Driver: receive assignments, one-tap status
- @FahrtenChef — Owner: dashboard, manual override, analytics

Architecture: Single asyncio process, three PTB Applications,
shared Tortoise ORM / SQLite, DeepSeek for NLU, OR-Tools for routing.
"""

__version__ = "0.1.0"
