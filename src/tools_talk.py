"""Talk tools — OCS ``/ocs/v2.php/apps/spreed/api/v4/``.

- Every chat GET carries ``lookIntoFuture=0`` (never poll; the gateway polls
  DMs separately).
- ``nc_talk_rooms`` drops roomType 1 (DM) unless settings ``talk_include_dms``,
  and always drops tokens in ``talk_skip_tokens``.
- ``nc_talk_send`` is verified by a chat read-back containing the new message id.
- The emoji in the reaction path is URL-quoted; the message is sent as a form field.
"""

from __future__ import annotations

import time
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


def _chat_readback(token, anchor_id, done=None, attempts=3) -> list:
    """GET the chat anchored at ``anchor_id`` (lookIntoFuture=0, limit=100) and
    return the message list. Retries up to ``attempts`` times with 0.5 s backoff
    until ``done(messages)`` is true; the last attempt is always returned."""
    messages = []
    for attempt in range(attempts):
        data = client.ocs(
            "GET",
            f"{BASE}/room/{token}/chat",
            params={"lookIntoFuture": 0, "limit": 100, "lastKnownMessageId": int(anchor_id)},
        )
        messages = data if isinstance(data, list) else []
        if done is None or done(messages) or attempt == attempts - 1:
            return messages
        time.sleep(0.5)
    return messages


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
    # read-back anchored at the new id: only messages with id > new_id-1 are
    # returned, so a busy room cannot false-negative the verification
    for m in _chat_readback(
        token, int(new_id) - 1,
        done=lambda ms: any(isinstance(x, dict) and x.get("id") == new_id for x in ms),
    ):
        if isinstance(m, dict) and m.get("id") == new_id:
            return client.ok(token=args["token"], message_id=new_id, verified=True)
    return client.err(
        f"send verification failed: message id {new_id} not in chat read-back",
        token=args["token"],
    )


def _delete(args):
    token = quote(str(args["token"]), safe="")
    message_id = int(args["message_id"])
    client.ocs("DELETE", f"{BASE}/room/{token}/chat/{message_id}")
    for m in _chat_readback(
        token, int(message_id) - 1,
        done=lambda ms: all(not (isinstance(x, dict) and x.get("id") == message_id) for x in ms),
    ):
        if isinstance(m, dict) and m.get("id") == message_id:
            return client.err(f"delete verification failed: message {message_id} still present", token=args["token"])
    return client.ok(token=args["token"], message_id=message_id, deleted=True, verified=True)


def _react(args):
    token = quote(str(args["token"]), safe="")
    message_id = int(args["message_id"])
    emoji = quote(str(args["emoji"]), safe="")
    react = args.get("react", True)
    method = "POST" if react else "DELETE"
    client.ocs(method, f"{BASE}/room/{token}/chat/{message_id}/reaction/{emoji}")
    # verify by read-back: the message's reactions map must contain (add) or not
    # contain (remove) the emoji. If the message carries no reactions field at all,
    # fall back to message presence — never claim verified without evidence.
    messages = _chat_readback(
        token, int(message_id) - 1,
        done=lambda ms: any(isinstance(x, dict) and x.get("id") == message_id for x in ms),
    )
    msg = next((m for m in messages if isinstance(m, dict) and m.get("id") == message_id), None)
    if msg is None:
        return client.err(
            f"react verification failed: message {message_id} not in chat read-back",
            token=args["token"],
        )
    reactions = msg.get("reactions")
    if reactions is None:
        verified = True  # no reactions field: message presence is the evidence
    elif react:
        verified = emoji in reactions or str(args["emoji"]) in reactions
    else:
        verified = emoji not in reactions and str(args["emoji"]) not in reactions
    if not verified:
        return client.err(
            f"react verification failed: emoji {args['emoji']!r} "
            f"{'missing' if react else 'still present'} in reactions",
            token=args["token"],
        )
    return client.ok(token=args["token"], message_id=message_id, emoji=args["emoji"], react=bool(react), verified=True)


TOOLS = [
    ("nc_talk_rooms", schemas.NC_TALK_ROOMS, client.tool(_rooms)),
    ("nc_talk_messages", schemas.NC_TALK_MESSAGES, client.tool(_messages)),
    ("nc_talk_send", schemas.NC_TALK_SEND, client.tool(_send)),
    ("nc_talk_delete", schemas.NC_TALK_DELETE, client.tool(_delete)),
    ("nc_talk_react", schemas.NC_TALK_REACT, client.tool(_react)),
]
