"""Render entrypoint with separate user and administrator panel accounts."""
import zeus_bot
from panel_auth import install_panel_auth
from group_owner import install_group_owner

app = zeus_bot.app
install_panel_auth(app, zeus_bot)

install_group_owner(app, zeus_bot)
