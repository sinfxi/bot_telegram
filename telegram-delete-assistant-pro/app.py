"""Render entrypoint with separate user and administrator panel accounts."""
import zeus_bot
from panel_auth import install_panel_auth

app = zeus_bot.app
install_panel_auth(app, zeus_bot)
