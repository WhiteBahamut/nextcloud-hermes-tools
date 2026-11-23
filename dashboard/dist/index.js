/* nextcloud-tools dashboard tab: modern overview + settings UI for all nc_* tools.
 *
 * Plain IIFE bundle — no build step, no imports, ES5-style (var/function, string
 * concat) so it runs as-is in the browser. React and UI components come from
 * window.__HERMES_PLUGIN_SDK__; registration name must match manifest.json.
 *
 * Host contract (verified against pinned Hermes tag, @nous-research/ui):
 *  - components: Card, CardHeader, CardTitle, CardContent, Badge (tone prop:
 *    default|secondary|outline|destructive|success|warning), Button (boolean
 *    flags destructive/ghost/invert/outlined + size xs|sm|default|icon),
 *    Checkbox (Radix: checked/onCheckedChange), Input, Toast({toast}).
 *  - hooks: useState/useEffect/useMemo/useToast; utils.cn; SDK.fetchJSON (auth
 *    injecting, throws on !ok, parses JSON) with a native-fetch fallback here.
 *  - theme CSS vars are the --color-* family (+ --radius, --theme-font-mono);
 *    style.css adds unprefixed shadcn-style fallbacks so other hosts still theme.
 *
 * Wire contract with dashboard/plugin_api.py (never rename one side only):
 *  GET /api/plugins/nextcloud-tools/tools
 *      -> {"tools": [{"name", "description", "parameters", "gate", "enabled", "guarded"}]}
 *  PUT /tools/{name}            body {"enabled": bool}
 *  PUT /tools/{name}/guardrails body {"enabled": bool}   (enabled = gate ON)
 * After every PUT the list is refetched (GET is authoritative).
 */
(function () {
  "use strict";
  if (!window.__HERMES_PLUGINS__ || !window.__HERMES_PLUGIN_SDK__) return;

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var h = React.createElement;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useMemo = SDK.hooks.useMemo;
  var useToast = SDK.hooks.useToast;
  /* cn fallback for hosts without SDK.utils — keeps the whole tab from dying at load */
  var cn =
    SDK.utils && typeof SDK.utils.cn === "function"
      ? SDK.utils.cn
      : function () {
          var out = [];
          for (var i = 0; i < arguments.length; i++) if (arguments[i]) out.push(arguments[i]);
          return out.join(" ");
        };
  /* always call exactly one hook: older hosts without useToast get a no-op returning null */
  var useToastSafe =
    typeof useToast === "function"
      ? useToast
      : function () {
          return null;
        };
  var Card = SDK.components.Card;
  var CardHeader = SDK.components.CardHeader;
  var CardTitle = SDK.components.CardTitle;
  var CardContent = SDK.components.CardContent;
  var Badge = SDK.components.Badge;
  var Button = SDK.components.Button; // fallback toggle on hosts without Checkbox
  var Checkbox = SDK.components.Checkbox;
  var Toast = SDK.components.Toast;
  var Input = SDK.components.Input;

  var API = "/api/plugins/nextcloud-tools";
  var EXPANDED_KEY = "nc-tools-expanded-v1"; // localStorage: which rows are open

  /* SDK.fetchJSON injects the session token; fall back to plain fetch on hosts
   * that predate it (still throws on !ok, still parses JSON). */
  var fetchJSON =
    typeof SDK.fetchJSON === "function"
      ? SDK.fetchJSON
      : function (url, opts) {
          return fetch(url, opts).then(function (r) {
            if (!r.ok) throw new Error(r.status + " " + r.statusText);
            return r.json();
          });
        };

  /* Ordered [id, name-prefix, label]; first prefix match wins, else "other". */
  var CATEGORIES = [
    ["files", "nc_file_", "Files"],
    ["search", "nc_search", "Search"],
    ["shares", "nc_share_", "Shares"],
    ["talk", "nc_talk_", "Talk"],
    ["cal", "nc_cal_", "Calendar"],
    ["tasks", "nc_task_", "Tasks"],
    ["contacts", "nc_contact_", "Contacts"],
    ["notes", "nc_note_", "Notes"],
    ["activity", "nc_activity", "Activity"],
    ["notifications", "nc_notifications", "Notifications"],
    ["tags", "nc_tag_", "Tags"],
    ["trash", "nc_trash_", "Trashbin"],
    ["comments", "nc_comment", "Comments"],
    ["ocs", "nc_ocs", "OCS"]
  ];

  function categoryOf(name) {
    for (var i = 0; i < CATEGORIES.length; i++) {
      if (name.indexOf(CATEGORIES[i][1]) === 0) return CATEGORIES[i][0];
    }
    return "other";
  }

  function categoryLabel(id) {
    for (var i = 0; i < CATEGORIES.length; i++) {
      if (CATEGORIES[i][0] === id) return CATEGORIES[i][2];
    }
    return "Other";
  }

  /* Badge tone per gate class (Badge takes `tone`, not `variant`). */
  var GATE_TONE = {
    read: "secondary",
    write: "default",
    destructive: "destructive",
    mixed: "outline"
  };
  var GATE_LABEL = { read: "Read", write: "Write", destructive: "Destructive", mixed: "Mixed" };
  var GATE_ORDER = ["read", "write", "destructive", "mixed"];

  /* Quick-filter pills in the toolbar. [id, label, title] — "destructive" also
   * matches "mixed" (nc_ocs/nc_comments gate per args), same as the warning banner. */
  var QUICK_FILTERS = [
    ["all", "All", "Show all tools"],
    ["disabled", "Disabled", "Show only disabled tools"],
    ["ungated", "Ungated", "Show only ungated tools (no approval prompt)"],
    ["destructive", "Destructive", "Show destructive or mixed tools"]
  ];

  function loadExpanded() {
    try {
      var raw = window.localStorage.getItem(EXPANDED_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function saveExpanded(map) {
    try {
      window.localStorage.setItem(EXPANDED_KEY, JSON.stringify(map));
    } catch (e) {
      /* private mode etc. — expansion just won't persist */
    }
  }

  /* Code-doc type label for one parameter spec: type, anyOf union, or "any". */
  function paramType(spec) {
    if (!spec || typeof spec !== "object") return "any";
    if (spec.type) return String(spec.type);
    if (Array.isArray(spec.anyOf)) {
      return spec.anyOf
        .map(function (branch) {
          if (branch && Array.isArray(branch.enum)) {
            return branch.enum.map(function (v) { return JSON.stringify(v); }).join(" | ");
          }
          return branch && branch.type ? String(branch.type) : "any";
        })
        .join(" | ");
    }
    return "any";
  }

  /* The exact call signature: required params bare, optional ones rendered as name=default. */
  function signatureOf(t) {
    var params = (t.parameters && t.parameters.properties) || {};
    var required = (t.parameters && t.parameters.required) || [];
    var names = Object.keys(params);
    if (names.length === 0) return t.name + "()";
    var parts = names.map(function (p) {
      if (required.indexOf(p) !== -1) return p;
      var spec = params[p] || {};
      if (Object.prototype.hasOwnProperty.call(spec, "default")) {
        return p + "=" + JSON.stringify(spec.default);
      }
      return p;
    });
    return t.name + "(" + parts.join(", ") + ")";
  }

  function NextcloudToolsPage() {
    var toolsState = useState([]);
    var tools = toolsState[0];
    var setTools = toolsState[1];
    var loadingState = useState(true);
    var loading = loadingState[0];
    var setLoading = loadingState[1];
    var errState = useState(null);
    var error = errState[0];
    var setError = errState[1];
    var busyNameState = useState(null); // name of the tool with an in-flight PUT (one at a time)
    var busyName = busyNameState[0];
    var setBusyName = busyNameState[1];
    var queryState = useState("");
    var query = queryState[0];
    var setQuery = queryState[1];
    var gateState = useState("all");
    var gateFilter = gateState[0];
    var setGateFilter = gateState[1];
    var quickState = useState("all");
    var quick = quickState[0];
    var setQuick = quickState[1];
    var catState = useState("all"); // active category pill ("all" = every tool)
    var category = catState[0];
    var setCategory = catState[1];
    var expandedState = useState(loadExpanded); // map tool name -> bool; survives reload via localStorage
    var expanded = expandedState[0];
    var setExpanded = expandedState[1];
    var confirmState = useState(null); // tool name pending "ungate destructive?" confirmation
    var confirmUngate = confirmState[0];
    var setConfirmUngate = confirmState[1];
    var copiedState = useState(null); // tool name whose signature was just copied
    var copied = copiedState[0];
    var setCopied = copiedState[1];
    var toastState = useToastSafe(); // null on older hosts: inline error paragraph instead

    function notify(msg, tone) {
      if (toastState && toastState.showToast) toastState.showToast(msg, tone);
      else setError(tone === "error" ? msg : null);
    }

    function fetchTools() {
      return fetchJSON(API + "/tools", { cache: "no-store" }).then(function (data) {
        return data.tools || [];
      });
    }

    function load() {
      setLoading(true);
      setError(null);
      fetchTools()
        .then(function (list) {
          setTools(list);
          setLoading(false);
        })
        .catch(function (err) {
          var msg = String((err && err.message) || err);
          setError(msg);
          setLoading(false);
          notify("Error: " + msg, "error");
        });
    }

    useEffect(function () {
      load();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(
      function () {
        saveExpanded(expanded);
      },
      [expanded]
    );

    /* One PUT at a time — concurrent writes race on the same config key.
     * After the PUT resolves, refetch: the GET payload is authoritative. */
    function saveToggle(t, suffix, body, verb) {
      if (busyName) return;
      setBusyName(t.name);
      setError(null);
      fetchJSON(API + "/tools/" + encodeURIComponent(t.name) + suffix, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
        .then(function () {
          return fetchTools();
        })
        .then(function (list) {
          setTools(list);
          notify(verb + " " + t.name, "success");
        })
        .catch(function (err) {
          notify("Error: " + String((err && err.message) || err), "error"); // keep old state on error
        })
        .finally(function () {
          setBusyName(null);
        });
    }

    function toggleEnabled(t) {
      var enable = !t.enabled;
      saveToggle(t, "", { enabled: enable }, (enable ? "Enabled " : "Disabled ") + t.name + " (next agent start)");
    }

    /* Ungating a destructive/mixed tool needs an inline confirmation first.
     * A repeat click on the toggle itself CANCELS the confirm — only the
     * confirm-strip button may ungate (no double-click bypass). */
    function requestToggleGate(t) {
      if (t.guarded && (t.gate === "destructive" || t.gate === "mixed")) {
        setConfirmUngate(confirmUngate === t.name ? null : t.name);
        return;
      }
      setConfirmUngate(null);
      var gate = !t.guarded;
      saveToggle(t, "/guardrails", { enabled: gate }, (gate ? "Gated " : "Ungated ") + t.name + " (immediate)");
    }

    var memo = useMemo(
      function () {
        var counts = { other: 0 };
        var enabledCount = 0;
        var guardedCount = 0;
        var destructiveUngated = 0;
        var gateCounts = {};
        var i, t, cat;
        for (i = 0; i < CATEGORIES.length; i++) counts[CATEGORIES[i][0]] = 0;
        for (i = 0; i < tools.length; i++) {
          t = tools[i];
          cat = categoryOf(t.name);
          counts[cat] = (counts[cat] || 0) + 1;
          if (t.enabled) enabledCount++;
          if (t.guarded) guardedCount++;
          if ((t.gate === "destructive" || t.gate === "mixed") && !t.guarded) destructiveUngated++;
          if (t.gate) gateCounts[t.gate] = (gateCounts[t.gate] || 0) + 1;
        }
        var gates = GATE_ORDER.filter(function (g) {
          return gateCounts[g];
        });
        var disabledCount = tools.length - enabledCount;
        var destructiveCount = (gateCounts.destructive || 0) + (gateCounts.mixed || 0);
        var q = query.toLowerCase();
        /* One predicate for every filter dimension; `skip` leaves that
         * dimension out — used to compute faceted counts: each pill group's
         * numbers reflect the other groups' selections, never its own. */
        function pass(t2, skip) {
          if (skip !== "category" && category !== "all" && categoryOf(t2.name) !== category) return false;
          if (skip !== "gate" && gateFilter !== "all" && t2.gate !== gateFilter) return false;
          if (skip !== "quick") {
            if (quick === "disabled" && t2.enabled) return false;
            if (quick === "ungated" && t2.guarded) return false;
            if (quick === "destructive" && t2.gate !== "destructive" && t2.gate !== "mixed") return false;
          }
          if (skip !== "query" && q) {
            var hay = (
              t2.name +
              " " +
              (t2.description || "") +
              " " +
              categoryLabel(categoryOf(t2.name)) +
              " " +
              (t2.gate || "")
            ).toLowerCase();
            if (hay.indexOf(q) === -1) return false;
          }
          return true;
        }
        var visible = tools.filter(function (t2) {
          return pass(t2, null);
        });
        /* Faceted pill counts: category / gate / state numbers each ignore
         * their own group's selection, so selecting a pill re-counts the
         * other two groups correctly. */
        var catPillCounts = { other: 0 };
        var catPillTotal = 0;
        var gatePillCounts = {};
        var gatePillTotal = 0;
        var quickPillCounts = { all: 0, disabled: 0, ungated: 0, destructive: 0 };
        for (i = 0; i < CATEGORIES.length; i++) catPillCounts[CATEGORIES[i][0]] = 0;
        for (i = 0; i < tools.length; i++) {
          t = tools[i];
          if (pass(t, "category")) {
            catPillTotal++;
            cat = categoryOf(t.name);
            catPillCounts[cat] = (catPillCounts[cat] || 0) + 1;
          }
          if (pass(t, "gate")) {
            gatePillTotal++;
            if (t.gate) gatePillCounts[t.gate] = (gatePillCounts[t.gate] || 0) + 1;
          }
          if (pass(t, "quick")) {
            quickPillCounts.all++;
            if (!t.enabled) quickPillCounts.disabled++;
            if (!t.guarded) quickPillCounts.ungated++;
            if (t.gate === "destructive" || t.gate === "mixed") quickPillCounts.destructive++;
          }
        }
        /* "All tools" groups the visible tools under per-category section headers. */
        var groups = [];
        for (i = 0; i < CATEGORIES.length; i++) {
          var id = CATEGORIES[i][0];
          var inCat = visible.filter(function (t3) {
            return categoryOf(t3.name) === id;
          });
          if (inCat.length) groups.push({ id: id, label: CATEGORIES[i][2], tools: inCat });
        }
        var rest = visible.filter(function (t3) {
          return categoryOf(t3.name) === "other";
        });
        if (rest.length) groups.push({ id: "other", label: "Other", tools: rest });
        return {
          counts: counts,
          enabledCount: enabledCount,
          guardedCount: guardedCount,
          ungatedCount: tools.length - guardedCount,
          disabledCount: disabledCount,
          destructiveCount: destructiveCount,
          destructiveUngated: destructiveUngated,
          gateCounts: gateCounts,
          gates: gates,
          catPillCounts: catPillCounts,
          catPillTotal: catPillTotal,
          gatePillCounts: gatePillCounts,
          gatePillTotal: gatePillTotal,
          quickPillCounts: quickPillCounts,
          visible: visible,
          groups: groups
        };
      },
      [tools, query, category, gateFilter, quick]
    );

    var total = tools.length;
    var busy = busyName !== null;

    /* One pill for every nav filter — same class, same aria pattern. Pills show
     * faceted counts (the other groups' selections applied, its own ignored) and
     * are disabled at 0 so a pill can never be selected into an empty result;
     * the group's "All …" pill always stays enabled as the reset path. */
    function filterPill(id, count, label, title, active, onPick) {
      var isAll = id === "all";
      return h(
        Button,
        {
          key: id,
          size: "sm",
          ghost: !active,
          outlined: active,
          className: cn("nc-chip", active && "nc-chip-on"),
          title: title,
          disabled: !isAll && count === 0,
          "aria-pressed": active ? "true" : "false",
          onClick: function () {
            onPick(id);
          }
        },
        label + " (" + count + ")"
      );
    }

    function toggleControl(props) {
      if (Checkbox) return h(Checkbox, props);
      // older host without Checkbox: outlined sm Button as the toggle
      return h(Button, { size: "sm", outlined: true, onClick: props.onCheckedChange }, props.checked ? "On" : "Off");
    }

    function toggleWithLabel(label, checked, aria, onChange) {
      return h(
        "span",
        { className: "nc-toggle" },
        toggleControl({
          checked: checked,
          disabled: busy,
          "aria-label": aria,
          onCheckedChange: onChange
        }),
        h("span", { className: "nc-toggle-label" }, label)
      );
    }

    function toggleExpanded(name) {
      // functional update: survives batched events, no stale-closure overwrite
      setExpanded(function (prev) {
        var next = Object.assign({}, prev);
        next[name] = !prev[name];
        return next;
      });
    }

    function setAllExpanded(value) {
      setExpanded(function (prev) {
        var next = Object.assign({}, prev);
        memo.visible.forEach(function (t) {
          next[t.name] = value;
        });
        return next;
      });
    }

    function copySignature(t) {
      var text = signatureOf(t);
      try {
        if (window.navigator.clipboard && window.navigator.clipboard.writeText) {
          // "Copied" only shows when the write actually succeeded
          window.navigator.clipboard.writeText(text).then(
            function () {
              setCopied(t.name);
            },
            function () {}
          );
        }
      } catch (e) {
        /* clipboard unavailable — no copied feedback */
      }
    }

    /* Inline confirmation strip shown when ungating a destructive/mixed tool. */
    function renderConfirm(t) {
      return h(
        "div",
        { className: "nc-confirm", role: "alert" },
        h(
          "span",
          { className: "nc-confirm-text" },
          "Ungate " + t.name + "? It is a " + (GATE_LABEL[t.gate] || t.gate || "").toLowerCase() +
            " tool — the agent could then call it without an approval prompt."
        ),
        h(
          Button,
          {
            size: "sm",
            destructive: true,
            onClick: function () {
              setConfirmUngate(null);
              saveToggle(t, "/guardrails", { enabled: false }, "Ungated " + t.name + " (immediate)");
            }
          },
          "Ungate without approval"
        ),
        h(
          Button,
          { size: "sm", ghost: true, onClick: function () { setConfirmUngate(null); } },
          "Cancel"
        )
      );
    }

    /* Expanded doc panel: full description, copyable call signature, parameter rows. */
    function renderDetail(t) {
      var params = (t.parameters && t.parameters.properties) || {};
      var required = (t.parameters && t.parameters.required) || [];
      var names = Object.keys(params);
      return h(
        "div",
        { className: "nc-detail", role: "region", "aria-label": t.name + " details" },
        h("p", { className: "nc-detail-desc" }, t.description || "No description available."),
        h(
          "div",
          { className: "nc-sig-row" },
          h("code", { className: "nc-signature" }, signatureOf(t)),
          h(
            Button,
            {
              size: "sm",
              ghost: true,
              className: "nc-copy",
              "aria-label": "Copy signature for " + t.name,
              onClick: function () {
                copySignature(t);
              }
            },
            copied === t.name ? "Copied ✓" : "Copy"
          )
        ),
        names.length === 0
          ? h("p", { className: "nc-noparams" }, "No parameters.")
          : h(
              "div",
              { className: "nc-params" },
              names.map(function (p) {
                var spec = params[p] || {};
                var isReq = required.indexOf(p) !== -1;
                return h(
                  "div",
                  { key: p, className: "nc-param" },
                  h(
                    "div",
                    { className: "nc-param-head" },
                    h("code", { className: "nc-param-name" }, p),
                    h("code", { className: "nc-param-type" }, paramType(spec)),
                    isReq ? h(Badge, { tone: "default", className: "nc-req" }, "required") : null,
                    Object.prototype.hasOwnProperty.call(spec, "default")
                      ? h("code", { className: "nc-param-default" }, "default: " + JSON.stringify(spec.default))
                      : null
                  ),
                  spec.description ? h("p", { className: "nc-param-desc" }, spec.description) : null
                );
              })
            )
      );
    }

    function renderRow(t) {
      var isOpen = !!expanded[t.name];
      var saving = busyName === t.name;
      var confirming = confirmUngate === t.name;
      return h(
        React.Fragment,
        { key: t.name },
        h(
          "div",
          { className: cn("nc-row", saving && "nc-row-busy", !t.enabled && "nc-row-off") },
          // every row expands — even with a missing/empty parameters payload (older
          // plugin_api still mounted on the host), the panel still shows the full
          // description and the bare nc_name() signature
          h(
            Button,
            {
              size: "sm",
              ghost: true,
              className: "nc-expand",
              "aria-expanded": isOpen ? "true" : "false",
              "aria-label": (isOpen ? "Hide" : "Show") + " details for " + t.name,
              onClick: function () {
                toggleExpanded(t.name);
              }
            },
            isOpen ? "▾" : "▸"
          ),
          h(
            "div",
            { className: "nc-tool" },
            h("span", { className: "nc-name", title: t.name }, t.name),
            h("span", { className: "nc-desc", title: t.description || "" }, t.description || "")
          ),
          h(Badge, { tone: GATE_TONE[t.gate] || "outline", className: "nc-gatebadge nc-gate-" + (t.gate || "mixed") }, t.gate || "mixed"),
          h(
            "div",
            { className: "nc-cell-enabled" },
            toggleWithLabel("Enabled", t.enabled, "Enable " + t.name, function () {
              toggleEnabled(t);
            }),
            saving ? h("span", { className: "nc-saving" }, "saving…") : null
          ),
          h(
            "div",
            { className: "nc-cell-gate" },
            toggleWithLabel("Approval gate", t.guarded, "Approval gate " + t.name, function () {
              requestToggleGate(t);
            })
          )
        ),
        confirming ? renderConfirm(t) : null,
        isOpen ? renderDetail(t) : null
      );
    }

    function renderColumnHeader() {
      return h(
        "div",
        { className: "nc-cols", "aria-hidden": "true" },
        h("span", { className: "nc-col-expand" }, ""),
        h("span", { className: "nc-col-tool" }, "Tool"),
        h("span", { className: "nc-col-gate" }, "Gate"),
        h("span", { className: "nc-col-enabled" }, "Enabled"),
        h("span", { className: "nc-col-approval" }, "Approval gate")
      );
    }

    /* The list section: list bar over the list (count left, actions top right),
     * column header, then the rows — grouped under category headers for
     * "All tools", flat for a single category pill. */
    function renderList() {
      var listBody;
      if (memo.visible.length === 0) {
        listBody = h(
          "p",
          { className: "nc-empty" },
          total === 0 ? "No tools registered." : "No tools match the current filters."
        );
      } else if (category === "all") {
        listBody = memo.groups.map(function (g) {
          return h(
            "div",
            { key: g.id, className: "nc-group" },
            h(
              "div",
              { className: "nc-group-head" },
              h("span", { className: "nc-group-label" }, g.label),
              h("span", { className: "nc-group-count" }, String(g.tools.length))
            ),
            h("div", { className: "nc-list" }, g.tools.map(renderRow))
          );
        });
      } else {
        listBody = h("div", { className: "nc-list" }, memo.visible.map(renderRow));
      }
      return h(
        React.Fragment,
        null,
        // list bar over the list: result count left, actions top right
        total > 0
          ? h(
              "div",
              { className: "nc-listbar" },
              h(
                "span",
                { className: "nc-count", "aria-live": "polite" },
                "Showing " + memo.visible.length + " of " + total + " tools"
              ),
              h(
                "div",
                { className: "nc-actions" },
                h(
                  Button,
                  { size: "sm", ghost: true, className: "nc-action", onClick: function () { setAllExpanded(true); }, "aria-label": "Expand all visible tools" },
                  "Expand all"
                ),
                h(
                  Button,
                  { size: "sm", ghost: true, className: "nc-action", onClick: function () { setAllExpanded(false); }, "aria-label": "Collapse all visible tools" },
                  "Collapse all"
                ),
                h(
                  Button,
                  {
                    size: "sm",
                    ghost: true,
                    className: "nc-action",
                    disabled: loading,
                    "aria-label": "Reload tool list",
                    onClick: function () {
                      if (!loading) load();
                    }
                  },
                  loading ? "Loading…" : "Reload"
                )
              )
            )
          : null,
        total > 0 ? renderColumnHeader() : null, // no header for the "No tools registered." state
        h("div", { className: "nc-listwrap" }, listBody)
      );
    }

    function renderSkeleton() {
      var rows = [];
      for (var i = 0; i < 6; i++) rows.push(h("div", { key: i, className: "nc-skel" }));
      return h("div", { className: "nc-list nc-list-skel" }, rows);
    }

    function renderErrorPanel() {
      return h(
        "div",
        { className: "nc-error", role: "alert" },
        h("p", { className: "nc-error-text" }, "Could not load the tool list: " + (error || "unknown error")),
        h(Button, { size: "sm", outlined: true, onClick: load }, "Retry")
      );
    }

    function renderStat(label, value, mod) {
      return h(
        "div",
        { className: cn("nc-stat", mod && "nc-stat-" + mod) },
        h("span", { className: "nc-stat-value" }, String(value)),
        h("span", { className: "nc-stat-label" }, label)
      );
    }

    var gateLine = memo.gates
      .map(function (g) {
        return memo.gateCounts[g] + " " + (GATE_LABEL[g] || g).toLowerCase();
      })
      .join(" · ");

    return h(
      "div",
      { className: cn("flex", "flex-col", "gap-4", "nc-root") },
      toastState ? h(Toast, { toast: toastState.toast }) : null,
      h(
        Card,
        null,
        h(
          CardHeader,
          { className: "nc-header" },
          h(
            "div",
            { className: "nc-titleblock" },
            h(CardTitle, null, "Nextcloud tools"),
            h(
              "p",
              { className: "nc-lede" },
              "Overview and per-tool settings for the " + total + " nc_* tools exposed to the agent."
            )
          ),
          h(
            "div",
            { className: "nc-stats" },
            renderStat("Tools", total, null),
            renderStat("Enabled", memo.enabledCount, memo.enabledCount === total ? "ok" : null),
            renderStat("Approval-gated", memo.guardedCount, null),
            renderStat("Ungated", memo.ungatedCount, memo.ungatedCount > 0 ? "warn" : "ok")
          ),
          // gate-class breakdown directly below the counter cards, full width
          total > 0 && gateLine ? h("p", { className: "nc-gateline" }, gateLine) : null
        ),
        h(
          CardContent,
          { className: "nc-content" },
          error && !toastState
            ? h("p", { className: "nc-inline-error" }, "Error: " + error)
            : null,
          memo.destructiveUngated > 0
            ? h(
                "div",
                { className: "nc-banner", role: "alert" },
                memo.destructiveUngated +
                  " destructive or mixed tool" + (memo.destructiveUngated > 1 ? "s are" : " is") +
                  " ungated — the agent can call " + (memo.destructiveUngated > 1 ? "them" : "it") + " without an approval prompt."
              )
            : null,
          h(
            "details",
            { className: "nc-help" },
            h("summary", null, "How do “Enabled” and “Approval gate” work?"),
            h(
              "p",
              { className: "nc-help-text" },
              "Each row has two switches. “Enabled” registers the tool for the agent or leaves it out — this applies on the next agent start / plugin reload. “Approval gate” is on by default: while it is on, write and destructive calls to the tool ask for your approval before they run (applies immediately); turning it off lets the agent call the tool without an approval prompt. A tool stays gated unless it is listed in the ungated_tools setting. The ▸ button at the start of a row expands it to show the tool's full description, call signature, and parameters."
            )
          ),
          h(
            "div",
            { className: "nc-nav" },
            h(
              "div",
              { className: "nc-navrow" },
              h(Input, {
                className: "nc-search",
                placeholder: "Search tools, categories, gates…",
                value: query,
                "aria-label": "Search tools",
                onChange: function (e) {
                  setQuery(e.target.value);
                }
              })
            ),
            h(
              "div",
              { className: "nc-navrow" },
              h("span", { className: "nc-filterlabel" }, "Category"),
              h(
                "div",
                { className: "nc-chips", role: "group", "aria-label": "Filter by category" },
                [filterPill("all", memo.catPillTotal, "All tools", "Show all tools", category === "all", setCategory)]
                  .concat(
                    CATEGORIES.filter(function (c) {
                      return memo.counts[c[0]] > 0;
                    }).map(function (c) {
                      return filterPill(c[0], memo.catPillCounts[c[0]] || 0, c[2], "Show only " + c[2].toLowerCase() + " tools", category === c[0], setCategory);
                    })
                  )
                  .concat(
                    memo.counts.other > 0
                      ? [filterPill("other", memo.catPillCounts.other || 0, "Other", "Show only other tools", category === "other", setCategory)]
                      : []
                  )
              )
            ),
            h(
              "div",
              { className: "nc-navrow" },
              h("span", { className: "nc-filterlabel" }, "Gate"),
              h(
                "div",
                { className: "nc-chips", role: "group", "aria-label": "Filter by gate class" },
                [filterPill("all", memo.gatePillTotal, "All gates", "Show all gate classes", gateFilter === "all", setGateFilter)].concat(
                  memo.gates.map(function (g) {
                    return filterPill(
                      g,
                      memo.gatePillCounts[g] || 0,
                      GATE_LABEL[g] || g,
                      "Show only " + (GATE_LABEL[g] || g).toLowerCase() + " tools",
                      gateFilter === g,
                      setGateFilter
                    );
                  })
                )
              )
            ),
            h(
              "div",
              { className: "nc-navrow" },
              h("span", { className: "nc-filterlabel" }, "State"),
              h(
                "div",
                { className: "nc-chips", role: "group", "aria-label": "Quick filters" },
                QUICK_FILTERS.map(function (f) {
                  return filterPill(f[0], memo.quickPillCounts[f[0]] || 0, f[1], f[2], quick === f[0], setQuick);
                })
              )
            )
          ),
          loading && total === 0
            ? renderSkeleton()
            : total === 0 && error
              ? renderErrorPanel()
              : renderList()
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("nextcloud-tools", NextcloudToolsPage);
})();
