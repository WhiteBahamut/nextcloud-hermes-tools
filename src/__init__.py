"""nextcloud-tools: a Hermes Agent directory plugin exposing the `nextcloud` toolset.

Repo root == plugin directory: ``cp -r /workspace ~/.hermes/plugins/nextcloud-tools``
installs it for one profile. Credentials come from that profile's ``.env``
as ``NC_SERVER_URL`` / ``NC_USER`` / ``NC_APP_PASSWORD`` (preferred; the
``TALK_*`` names work as fallback), read profile-scoped
via ``agent.secret_scope.get_secret_str`` — never ``os.getenv``.
"""

TOOLSET = "nextcloud"


def register(ctx):
    from . import (
        client,
        guardrails,
        tools_cal,
        tools_contacts,
        tools_files,
        tools_misc,
        tools_notes,
        tools_search,
        tools_shares,
        tools_talk,
    )

    client.configure(ctx)
    disabled = {str(t) for t in (ctx.get_config("disabled_tools", []) or [])}
    for module in (
        tools_files,
        tools_search,
        tools_shares,
        tools_talk,
        tools_cal,
        tools_contacts,
        tools_notes,
        tools_misc,
    ):
        for name, schema, handler in module.TOOLS:
            if name in disabled:
                continue
            ctx.register_tool(
                name=name,
                toolset=TOOLSET,
                schema=schema,
                handler=handler,
                check_fn=client.configured,
                requires_env=list(client.KNOWN_ENV),
                description=schema["description"],
            )
    ctx.register_hook("pre_tool_call", guardrails.guard)
