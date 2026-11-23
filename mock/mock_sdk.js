/* Mock of the Hermes dashboard host SDK for LOCAL testing of the nextcloud-tools
 * dashboard tab (dashboard/dist/index.js). Not shipped to any host.
 *
 * Implements exactly the surface dist/index.js consumes from
 * window.__HERMES_PLUGIN_SDK__:
 *   React.createElement / React.Fragment
 *   hooks: useState / useEffect / useMemo / useToast
 *   utils.cn
 *   components: Card, CardHeader, CardTitle, CardContent, Badge (tone prop),
 *     Button (size + destructive/ghost/invert/outlined flags), Checkbox (Radix-style
 *     checked/onCheckedChange), Toast({toast}), Input
 *   fetchJSON (throws on !ok, parses JSON)
 * and window.__HERMES_PLUGINS__.register(name, component), which mounts the page.
 *
 * The "React" here is a tiny full-rebuild renderer with per-component-path hook
 * state; good enough for one page component. Focus/selection of the active input
 * is restored across rebuilds so the controlled search box stays usable.
 */
(function () {
  "use strict";

  /* ---------------- tiny react-ish core ---------------- */

  var Fragment = { __fragment: true };

  function createElement(type, props) {
    var children = [];
    for (var i = 2; i < arguments.length; i++) children.push(arguments[i]);
    return { type: type, props: props || {}, children: children };
  }

  var rootContainer = null;
  var rootComponent = null;
  var prevInstances = {};
  var curInstances = {};
  var currentInstance = null;
  var pendingEffects = [];
  var renderScheduled = false;

  function scheduleRender() {
    if (renderScheduled) return;
    renderScheduled = true;
    Promise.resolve().then(function () {
      renderScheduled = false;
      rerender();
    });
  }

  function depsChanged(prev, next) {
    if (!prev || !next) return true;
    if (prev.length !== next.length) return true;
    for (var i = 0; i < next.length; i++) if (prev[i] !== next[i]) return true;
    return false;
  }

  function useState(initial) {
    var inst = currentInstance;
    var i = inst.hookIndex++;
    if (!(i in inst.hooks)) {
      inst.hooks[i] = typeof initial === "function" ? initial() : initial;
    }
    function setState(v) {
      inst.hooks[i] = typeof v === "function" ? v(inst.hooks[i]) : v;
      scheduleRender();
    }
    return [inst.hooks[i], setState];
  }

  function useEffect(cb, deps) {
    var inst = currentInstance;
    var i = inst.hookIndex++;
    var slot = inst.hooks[i] || (inst.hooks[i] = { deps: undefined, cleanup: undefined });
    if (depsChanged(slot.deps, deps)) pendingEffects.push({ slot: slot, cb: cb, deps: deps });
  }

  function useMemo(cb, deps) {
    var inst = currentInstance;
    var i = inst.hookIndex++;
    var slot = inst.hooks[i];
    if (!slot || depsChanged(slot.deps, deps)) {
      slot = inst.hooks[i] = { deps: deps, value: cb() };
    }
    return slot.value;
  }

  function useToast() {
    var s = useState(null);
    var t = useState(null); // auto-dismiss timer id
    return {
      toast: s[0],
      showToast: function (msg, tone) {
        s[1]({ msg: String(msg), tone: tone || "default" });
        if (t[0]) clearTimeout(t[0]);
        t[1](
          setTimeout(function () {
            s[1](null);
          }, 3500)
        );
      }
    };
  }

  function flushEffects() {
    var list = pendingEffects;
    pendingEffects = [];
    for (var k = 0; k < list.length; k++) {
      var e = list[k];
      if (e.slot.cleanup) {
        try {
          e.slot.cleanup();
        } catch (err) {
          /* ignore cleanup errors in the mock */
        }
      }
      e.slot.deps = e.deps;
      var cleanup = e.cb();
      e.slot.cleanup = typeof cleanup === "function" ? cleanup : undefined;
    }
  }

  /* ---------------- dom rendering ---------------- */

  function setProp(el, tag, key, value) {
    if (key === "className") {
      el.setAttribute("class", value);
      return;
    }
    if (key === "htmlFor") {
      el.setAttribute("for", value);
      return;
    }
    if (key.slice(0, 2) === "on" && typeof value === "function") {
      var ev = key.slice(2).toLowerCase();
      // React's onChange on a text input fires per keystroke (the input event)
      if (tag === "input" && ev === "change" && el.type !== "checkbox") ev = "input";
      el["on" + ev] = value;
      return;
    }
    if (key === "value") {
      el.value = value == null ? "" : value;
      return;
    }
    if (key === "checked") {
      el.checked = !!value;
      return;
    }
    if (key === "disabled") {
      el.disabled = !!value;
      return;
    }
    if (value === true) {
      el.setAttribute(key, "");
      return;
    }
    if (value === false || value === null || value === undefined) return;
    el.setAttribute(key, String(value));
  }

  function append(parent, rendered) {
    if (!rendered) return;
    if (Array.isArray(rendered)) {
      for (var i = 0; i < rendered.length; i++) append(parent, rendered[i]);
      return;
    }
    if (Array.isArray(parent)) {
      parent.push(rendered); // collecting rendered children into a plain array
      return;
    }
    if (rendered.nodeType) parent.appendChild(rendered);
  }

  function renderNode(node, path) {
    if (node === null || node === undefined || node === false || node === true) return null;
    if (typeof node === "string" || typeof node === "number") return document.createTextNode(String(node));
    if (Array.isArray(node)) {
      var out = [];
      for (var i = 0; i < node.length; i++) {
        var r = renderNode(node[i], path + "/" + i);
        if (r) append(out, r);
      }
      return out;
    }
    var type = node.type;
    if (type === Fragment) return renderNode(node.children, path + "/f");
    if (typeof type === "function") {
      var inst = prevInstances[path] || { hooks: [], hookIndex: 0 };
      inst.hookIndex = 0;
      curInstances[path] = inst;
      var prev = currentInstance;
      currentInstance = inst;
      var out;
      try {
        out = type(Object.assign({}, node.props, { children: node.children }));
      } finally {
        currentInstance = prev;
      }
      return renderNode(out, path + "/c");
    }
    var el = document.createElement(type);
    var props = node.props || {};
    for (var key in props) {
      if (key === "children" || key === "key") continue;
      setProp(el, type, key, props[key]);
    }
    append(el, renderNode(node.children, path + "/k"));
    if (type === "select" && props.value != null) el.value = props.value; // after options exist
    return el;
  }

  function rerender() {
    if (!rootContainer || !rootComponent) return;
    curInstances = {};
    pendingEffects = [];
    // preserve focus across the full rebuild so controlled inputs stay usable
    var active = document.activeElement;
    var focus = null;
    if (
      active &&
      rootContainer.contains(active) &&
      (active.tagName === "INPUT" || active.tagName === "SELECT" || active.tagName === "TEXTAREA")
    ) {
      focus = {
        tag: active.tagName,
        aria: active.getAttribute("aria-label"),
        cls: active.className,
        start: active.selectionStart,
        end: active.selectionEnd
      };
    }
    var rendered = renderNode(createElement(rootComponent, {}), "");
    var frag = document.createDocumentFragment();
    append(frag, rendered);
    rootContainer.replaceChildren(frag);
    if (focus) {
      var sel = focus.aria
        ? focus.tag.toLowerCase() + '[aria-label="' + focus.aria + '"]'
        : focus.tag.toLowerCase() + "." + String(focus.cls).split(" ")[0];
      var el = rootContainer.querySelector(sel);
      if (el) {
        el.focus();
        try {
          if (focus.start != null && el.setSelectionRange) el.setSelectionRange(focus.start, focus.end);
        } catch (e) {
          /* not a text input — nothing to restore */
        }
      }
    }
    prevInstances = curInstances;
    curInstances = {};
    flushEffects();
  }

  /* ---------------- sdk components ---------------- */

  function passthrough(tag, baseClass, extra) {
    return function (props) {
      var p = {};
      for (var k in props) if (k !== "children") p[k] = props[k];
      p.className = (baseClass + " " + (props.className || "")).trim();
      if (extra) for (var e in extra) p[e] = extra[e];
      return createElement(tag, p, props.children);
    };
  }

  var Card = passthrough("div", "mock-card");
  var CardHeader = passthrough("div", "mock-card-header");
  var CardTitle = passthrough("div", "mock-card-title");
  var CardContent = passthrough("div", "mock-card-content");

  function Badge(props) {
    var tone = props.tone || "default";
    return createElement(
      "span",
      { className: "mock-badge mock-badge-" + tone + (props.className ? " " + props.className : ""), "data-tone": tone },
      props.children
    );
  }

  function Button(props) {
    var p = {};
    for (var k in props) if (k !== "children") p[k] = props[k];
    var cls = "mock-btn";
    if (props.size) cls += " mock-btn-" + props.size;
    var flags = ["ghost", "outlined", "destructive", "invert"];
    for (var i = 0; i < flags.length; i++) if (props[flags[i]]) cls += " mock-btn-" + flags[i];
    if (props.className) cls += " " + props.className;
    p.className = cls;
    return createElement("button", p, props.children);
  }

  function Checkbox(props) {
    return createElement("input", {
      type: "checkbox",
      className: "mock-checkbox" + (props.className ? " " + props.className : ""),
      checked: !!props.checked,
      disabled: !!props.disabled,
      "aria-label": props["aria-label"],
      onChange: function (e) {
        if (props.onCheckedChange) props.onCheckedChange(e.target.checked);
      }
    });
  }

  function Input(props) {
    var p = {};
    for (var k in props) if (k !== "children") p[k] = props[k];
    p.className = "mock-input" + (props.className ? " " + props.className : "");
    p.type = props.type || "text";
    return createElement("input", p);
  }

  function Toast(props) {
    var t = props && props.toast;
    if (!t) return null;
    return createElement("div", { className: "mock-toast mock-toast-" + (t.tone || "default"), role: "status" }, t.msg);
  }

  /* ---------------- sdk utils / fetch ---------------- */

  function cn() {
    var out = [];
    for (var i = 0; i < arguments.length; i++) if (arguments[i]) out.push(arguments[i]);
    return out.join(" ");
  }

  function fetchJSON(url, opts) {
    return fetch(url, opts || {}).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (body) {
          var msg = r.status + " " + r.statusText;
          try {
            var j = JSON.parse(body);
            if (j && j.detail) msg = r.status + ": " + j.detail;
          } catch (e) {
            /* not JSON — keep status line */
          }
          throw new Error(msg);
        });
      }
      return r.json();
    });
  }

  /* ---------------- host globals ---------------- */

  window.__HERMES_PLUGINS__ = {
    register: function (name, component) {
      rootComponent = component;
      rootContainer = document.getElementById("root");
      rerender();
    }
  };

  window.__HERMES_PLUGIN_SDK__ = {
    React: { createElement: createElement, Fragment: Fragment },
    hooks: { useState: useState, useEffect: useEffect, useMemo: useMemo, useToast: useToast },
    utils: { cn: cn },
    components: {
      Card: Card,
      CardHeader: CardHeader,
      CardTitle: CardTitle,
      CardContent: CardContent,
      Badge: Badge,
      Button: Button,
      Checkbox: Checkbox,
      Toast: Toast,
      Input: Input
    },
    fetchJSON: fetchJSON
  };
})();
