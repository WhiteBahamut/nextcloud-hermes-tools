"""WebDAV helpers: multistatus (207) parsing with wildcard-namespace tags.

Prop names are matched by local name (``{*}tag``-style), so namespace prefixes
(``d:``, ``oc:``, ``cal:``, ``card:``, ...) don't matter.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import unquote


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _prop_value(elem) -> object:
    name = _local(elem.tag)
    if name == "resourcetype":
        return any(_local(child.tag) == "collection" for child in elem)
    if name == "systemtags":
        return [(child.text or "").strip() for child in elem if _local(child.tag) == "systemtag"]
    text = (elem.text or "").strip()
    return text if text else None


def parse_multistatus(xml_text: str) -> list:
    """Parse a multistatus body -> [{"href": str, "props": {localname: value}}]."""
    root = ET.fromstring(xml_text)
    out = []
    for resp in root.iter():
        if _local(resp.tag) != "response":
            continue
        href = ""
        props = {}
        for child in resp:
            lname = _local(child.tag)
            if lname == "href":
                href = (child.text or "").strip()
            elif lname == "propstat":
                for prop in child:
                    if _local(prop.tag) == "prop":
                        for p in prop:
                            props[_local(p.tag)] = _prop_value(p)
        out.append({"href": href, "props": props})
    return out


def user_path(href: str, dav_prefix: str) -> str:
    """Map a DAV response href back to a user-facing path ('/a/b'), URL-decoded."""
    path = unquote(href).rstrip("/")
    prefix = dav_prefix.rstrip("/")
    if prefix and path.startswith(prefix):
        path = path[len(prefix):] or "/"
    return path or "/"


def entry_from_response(resp: dict, dav_prefix: str) -> dict:
    """One multistatus response -> a plain entry dict."""
    props = resp["props"]
    path = user_path(resp["href"], dav_prefix)
    size = props.get("getcontentlength")
    return {
        "path": path,
        "name": path.rstrip("/").rsplit("/", 1)[-1],
        "size": int(size) if size and str(size).isdigit() else 0,
        "mtime": props.get("getlastmodified"),
        "content_type": props.get("getcontenttype"),
        "etag": props.get("getetag"),
        "is_dir": props.get("resourcetype") is True,
        "fileid": props.get("fileid"),
        "tags": props.get("systemtags") or [],
    }


# PROPFIND body requesting every prop the tool modules use (files + cal + card).
PROPFIND_ALL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" '
    'xmlns:cal="urn:ietf:params:xml:ns:caldav" xmlns:card="urn:ietf:params:xml:ns:carddav">'
    "<d:prop>"
    "<d:getcontentlength/><d:getlastmodified/><d:getcontenttype/><d:resourcetype/><d:getetag/>"
    "<oc:fileid/><oc:systemtags/>"
    "<cal:calendar-data/><card:address-data/>"
    "</d:prop></d:propfind>"
)
