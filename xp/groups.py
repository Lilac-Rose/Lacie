from discord import app_commands

# Public XP commands: /xp rank, /xp top, /xp calculate, /xp sync
xp_group = app_commands.Group(name="xp", description="XP commands")

# Admin XP commands: /xpadmin set, /xpadmin add, /xpadmin remove, /xpadmin backup, etc.
xp_admin_group = app_commands.Group(name="xpadmin", description="Admin XP management commands")