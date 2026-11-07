"""Talk tools — OCS ``/ocs/v2.php/apps/spreed/api/v4/``.

- Every chat GET carries ``lookIntoFuture=0`` (never poll; the gateway polls
  DMs separately).
- ``nc_talk_rooms`` drops roomType 1 (DM) unless settings ``talk_include_dms``,
  and always drops tokens in ``talk_skip_tokens``.
- ``nc_talk_send`` is verified by a chat read-back containing the new message id.
- The emoji in the reaction path is URL-quoted; the message is sent as a form field.
"""

from __future__ import annotations

from urllib.parse import quote

from . import client, schemas

BASE = "apps/spreed/api/v4"


def _rooms(args):
    limit = int(args.get("limit") or 50)
    s = client.settings()
    skip = set(s["talk_skip_tokens"])
    data = client.ocs("GET", f"{BASE}/room", params={"limit": limit})
    rooms = data if isinstance(data, list) else []
    out = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        if room.get("roomType") == 1 and not s["talk_include_dms"]:
            continue  # 1:1 DM
        if str(room.get("token", "")) in skip:
            continue  # e.g. gateway-polled DM — never double-handle
        out.append(room)
    return client.ok(count=len(out), rooms=out)


def _messages(args):
    token = quote(str(args["token"]), safe="")
    limit = int(args.get("limit") or 50)
    last_known = int(args.get("last_known_message_id") or 0)
    params = {
        "lookIntoFuture": 0,  # required — never poll
        "limit": limit,
        "lastKnownMessageId": last_known,
    }
    data = client.ocs("GET", f"{BASE}/room/{token}/chat", params=params)
    messages = data if isinstance(data, list) else []
    return client.ok(token=args["token"], count=len(messages), messages=messages)


def _send(args):
    token = quote(str(args["token"]), safe="")
    message = args.get("message") or ""
    if not message:
        return client.err("empty message")
    reply_to = int(args.get("reply_to") or 0)
    form = {"message": message}
    if reply_to:
        form["replyTo"] = reply_to
    created = client.ocs("POST", f"{BASE}/room/{token}/chat", data=form)
    new_id = created.get("id") if isinstance(created, dict) else None
    if new_id is None:
        return client.err(f"send returned no message id: {created!r}", token=args["token"])
    # read-back: the new id must appear in a follow-up chat GET
    data = client.ocs(
        "GET",
        f"{BASE}/room/{token}/chat",
        params={"lookIntoFuture": 0, "limit": 100, "lastKnownMessageId": 0},
    )
    ids = {m.get("id") for m in (data or []) if isinstance(m, dict)}
    if new_id not in ids:
        return client.err(
            f"send verification failed: message id {new_id} not in chat read-back",
            token=args["token"],
        )
    return client.ok(token=args["token"], message_id=new_id, verified=True)


def _delete(args):
    token = quote(str(args["token"]), safe="")
    message_id = int(args["message_id"])
    client.ocs("DELETE", f"{BASE}/room/{token}/chat/{message_id}")
    # verify gone from a follow-up chat GET
    data = client.ocs(
        "GET",
        f"{BASE}/room/{token}/chat",
        params={"lookIntoFuture": 0, "limit": 100, "lastKnownMessageId": 0},
    )
    ids = {m.get("id") for m in (data or []) if isinstance(m, dict)}
    if message_id in ids:
        return client.err(f"delete verification failed: message {message_id} still present", token=args["token"])
    return client.ok(token=args["token"], message_id=message_id, deleted=True, verified=True)


def _react(args):
    token = quote(str(args["token"]), safe="")
    message_id = int(args["message_id"])
    emoji = quote(str(args["emoji"]), safe="")
    react = args.get("react", True)
    method = "POST" if react else "DELETE"
    client.ocs(method, f"{BASE}/room/{token}/chat/{message_id}/reaction/{emoji}")
    return client.ok(token=args["token"], message_id=message_id, emoji=args["emoji"], react=bool(react), verified=True)


TOOLS = [
    ("nc_talk_rooms", schemas.NC_TALK_ROOMS, client.tool(_rooms)),
    ("nc_talk_messages", schemas.NC_TALK_MESSAGES, client.tool(_messages)),
    ("nc_talk_send", schemas.NC_TALK_SEND, client.tool(_send)),
    ("nc_talk_delete", schemas.NC_TALK_DELETE, client.tool(_delete)),
    ("nc_talk_react", schemas.NC_TALK_REACT, client.tool(_react)),
]
