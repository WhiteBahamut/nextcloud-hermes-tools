/* nextcloud-tools dashboard tab: lists all nc_* tools with per-tool enable/disable and approval-gate toggle.
 * Plain IIFE bundle — no build step, no imports. React and UI components come
 * from window.__HERMES_PLUGIN_SDK__; registration name must match manifest.json.
 * Layout/styling lives in dist/style.css (.nc-* classes) and uses only theme
 * CSS vars, so colors always follow the user-selected dashboard theme.
 */
(function () {
  "use strict";
  if (!window.__HERMES_PLUGINS__ || !window.__HERMES_PLUGIN_SDK__) return;

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useMemo = SDK.hooks.useMemo;
  var useToast = SDK.hooks.useToast;
  var cn = SDK.utils.cn;
  var Card = SDK.components.Card;
  var CardHeader = SDK.components.CardHeader;
  var CardTitle = SDK.components.CardTitle;
  var CardContent = SDK.components.CardContent;
  var Badge = SDK.components.Badge;
  var Button = SDK.components.Button; // fallback toggle on hosts without Checkbox
  var Checkbox = SDK.components.Checkbox;
  var Toast = SDK.components.Toast;
  var Tabs = SDK.components.Tabs;
  var TabsList = SDK.components.TabsList;
  var TabsTrigger = SDK.components.TabsTrigger;
  var Select = SDK.components.Select;
  var SelectOption = SDK.components.SelectOption;
  var Separator = SDK.components.Separator;
  var Input = SDK.components.Input;

  var API = "/api/plugins/nextcloud-tools";

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
    ["comments", "nc_comments", "Comments"],
    ["ocs", "nc_ocs", "OCS"]
  ];

  function categoryOf(name) {
    for (var i = 0; i < CATEGORIES.length; i++) {
      if (name.indexOf(CATEGORIES[i][1]) === 0) return CATEGORIES[i][0];
    }
    return "other";
  }

  /* Badge tone per gate class (Badge takes `tone`, not `variant`). */
  var GATE_TONE = {
    read: "secondary",
    write: "default",
    destructive: "destructive",
    mixed: "outline"
  };

  function NextcloudToolsPage() {
    var toolsState = useState([]);
    var tools = toolsState[0];
    var setTools = toolsState[1];
    var errState = useState(null);
    var error = errState[0];
    var setError = errState[1];
    var busyState = useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];
    var queryState = useState("");
    var query = queryState[0];
    var setQuery = queryState[1];
    var gateState = useState("all");
    var gateFilter = gateState[0];
    var setGateFilter = gateState[1];
    var toastState = useToast ? useToast() : null; // older hosts: inline error paragraph

    function notify(msg, tone) {
      if (toastState && toastState.showToast) toastState.showToast(msg, tone);
      else setError(tone === "error" ? msg : null);
    }

    useEffect(function () {
      var cancelled = false;
      SDK.fetchJSON(API + "/tools")
        .then(function (data) {
          if (!cancelled) setTools(data.tools || []);
        })
        .catch(function (err) {
          if (!cancelled) notify(String((err && err.message) || err), "error");
        });
      return function () {
        cancelled = true;
      };
    }, []);

    function toggle(t) {
      if (busy) return; // one PUT at a time — concurrent writes race on the same config key
      setBusy(true);
      setError(null);
      SDK.fetchJSON(API + "/tools/" + encodeURIComponent(t.name), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !t.enabled })
      })
        .then(function (res) {
          var disabled = {};
          (res.disabled_tools || []).forEach(function (n) {
            disabled[n] = true;
          });
          setTools(function (prev) {
            return prev.map(function (x) {
              var copy = Object.assign({}, x);
              copy.enabled = !disabled[x.name];
              return copy;
            });
          });
          notify((!t.enabled ? "Enabled " : "Disabled ") + t.name, "success");
        })
        .catch(function (err) {
          notify("Error: " + String((err && err.message) || err), "error"); // keep old state on error
        })
        .finally(function () {
          setBusy(false);
        });
    }

    function toggleGuardrails(t) {
      if (busy) return; // one PUT at a time — concurrent writes race on the same config key
      setBusy(true);
      setError(null);
      SDK.fetchJSON(API + "/tools/" + encodeURIComponent(t.name) + "/guardrails", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !t.guarded })
      })
        .then(function (res) {
          var ungated = {};
          (res.ungated_tools || []).forEach(function (n) {
            ungated[n] = true;
          });
          setTools(function (prev) {
            return prev.map(function (x) {
              var copy = Object.assign({}, x);
              copy.guarded = !ungated[x.name];
              return copy;
            });
          });
          notify((t.guarded ? "Ungated " : "Gated ") + t.name, "success");
        })
        .catch(function (err) {
          notify("Error: " + String((err && err.message) || err), "error"); // keep old state on error
        })
        .finally(function () {
          setBusy(false);
        });
    }

    var memo = useMemo(function () {
      var counts = { other: 0 };
      var enabledCount = 0;
      var guardedCount = 0;
      var gateSet = {};
      var i, t, cat;
      for (i = 0; i < CATEGORIES.length; i++) counts[CATEGORIES[i][0]] = 0;
      for (i = 0; i < tools.length; i++) {
        t = tools[i];
        cat = categoryOf(t.name);
        counts[cat] = (counts[cat] || 0) + 1;
        if (t.enabled) enabledCount++;
        if (t.guarded) guardedCount++;
        if (t.gate) gateSet[t.gate] = true;
      }
      var gates = Object.keys(gateSet).sort();
      var q = query.toLowerCase();
      var visible = tools.filter(function (t2) {
        if (gateFilter !== "all" && t2.gate !== gateFilter) return false;
        if (q && (t2.name + " " + (t2.description || "")).toLowerCase().indexOf(q) === -1) return false;
        return true;
      });
      return {
        counts: counts,
        enabledCount: enabledCount,
        guardedCount: guardedCount,
        gates: gates,
        visible: visible
      };
    }, [tools, query, gateFilter]);

    var total = tools.length;
    var ungatedCount = total - memo.guardedCount;

    function toggleControl(props) {
      if (Checkbox) return React.createElement(Checkbox, props);
      // older host without Checkbox: outlined sm Button as the toggle
      return React.createElement(
        Button,
        { size: "sm", outlined: true, onClick: props.onCheckedChange },
        props.checked ? "On" : "Off"
      );
    }

    function renderRow(t) {
      return React.createElement(
        "div",
        { key: t.name, className: "nc-row" },
        toggleControl({
          checked: t.enabled,
          disabled: busy,
          "aria-label": "Enable " + t.name,
          onCheckedChange: function () {
            toggle(t);
          }
        }),
        React.createElement("span", { className: "nc-name", title: t.description || t.name }, t.name),
        React.createElement("span", { className: "nc-desc" }, t.description || ""),
        React.createElement(Badge, { tone: GATE_TONE[t.gate] || "outline" }, t.gate),
        React.createElement(
          "span",
          { className: "nc-gate" },
          "gate",
          toggleControl({
            checked: t.guarded,
            disabled: busy,
            "aria-label": "Approval gate " + t.name,
            onCheckedChange: function () {
              toggleGuardrails(t);
            }
          })
        )
      );
    }

    function renderTabs() {
      return React.createElement(Tabs, { defaultValue: "all" }, function (active, setActive) {
        var inTab =
          active === "all"
            ? memo.visible
            : memo.visible.filter(function (t) {
                return categoryOf(t.name) === active;
              });
        var triggers = [
          React.createElement(
            TabsTrigger,
            { key: "all", value: "all", active: active === "all", onClick: function () { setActive("all"); } },
            "All (" + total + ")"
          )
        ];
        CATEGORIES.forEach(function (c) {
          if (memo.counts[c[0]] > 0) {
            triggers.push(
              React.createElement(
                TabsTrigger,
                { key: c[0], value: c[0], active: active === c[0], onClick: function () { setActive(c[0]); } },
                c[2] + " (" + memo.counts[c[0]] + ")"
              )
            );
          }
        });
        if (memo.counts.other > 0) {
          triggers.push(
            React.createElement(
              TabsTrigger,
              { key: "other", value: "other", active: active === "other", onClick: function () { setActive("other"); } },
              "Other (" + memo.counts.other + ")"
            )
          );
        }
        return React.createElement(
          React.Fragment,
          null,
          React.createElement(TabsList, null, triggers),
          React.createElement(
            "div",
            { className: "nc-list" },
            inTab.length === 0
              ? React.createElement("p", { className: "nc-empty" }, "No tools match the current filters.")
              : inTab.map(function (t) {
                  return renderRow(t);
                })
          )
        );
      });
    }

    return React.createElement(
      "div",
      { className: cn("flex", "flex-col", "gap-4") },
      toastState ? React.createElement(Toast, { toast: toastState.toast }) : null,
      React.createElement(
        Card,
        null,
        React.createElement(
          CardHeader,
          { className: "flex flex-row flex-wrap items-center justify-between gap-2" },
          React.createElement(CardTitle, null, "Nextcloud tools"),
          React.createElement(
            "div",
            { className: "nc-summary" },
            React.createElement(Badge, { tone: "secondary" }, memo.enabledCount + "/" + total + " enabled"),
            React.createElement(Badge, { tone: "default" }, memo.guardedCount + " gated"),
            React.createElement(
              Badge,
              { tone: ungatedCount ? "warning" : "secondary" },
              ungatedCount + " ungated"
            )
          )
        ),
        React.createElement(
          CardContent,
          null,
          error && !toastState
            ? React.createElement("p", { className: "text-sm text-destructive" }, "Error: " + error)
            : null,
          React.createElement(
            "p",
            { className: "text-sm text-muted-foreground" },
            tools.length +
              " tools. Enable/disable applies on the next agent start / plugin reload; gate changes apply immediately."
          ),
          React.createElement(
            "div",
            { className: "nc-toolbar" },
            React.createElement(Input, {
              className: "nc-search",
              placeholder: "Filter tools…",
              value: query,
              "aria-label": "Filter tools",
              onChange: function (e) {
                setQuery(e.target.value);
              }
            }),
            React.createElement(
              Select,
              {
                className: "nc-gatefilter",
                value: gateFilter,
                onValueChange: function (v) {
                  setGateFilter(v);
                }
              },
              React.createElement(SelectOption, { value: "all" }, "All gates"),
              memo.gates.map(function (g) {
                return React.createElement(SelectOption, { key: g, value: g }, g);
              })
            )
          ),
          React.createElement(Separator, null),
          total === 0
            ? React.createElement("p", { className: "nc-empty" }, "Loading tools…")
            : renderTabs()
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("nextcloud-tools", NextcloudToolsPage);
})();
