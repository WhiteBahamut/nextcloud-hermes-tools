/* nextcloud-tools dashboard tab: lists all nc_* tools with per-tool enable/disable.
 * Plain IIFE bundle — no build step, no imports. React and UI components come
 * from window.__HERMES_PLUGIN_SDK__; registration name must match manifest.json.
 */
(function () {
  "use strict";
  if (!window.__HERMES_PLUGINS__ || !window.__HERMES_PLUGIN_SDK__) return;

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var React = SDK.React;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var Card = SDK.components.Card;
  var CardHeader = SDK.components.CardHeader;
  var CardTitle = SDK.components.CardTitle;
  var CardContent = SDK.components.CardContent;
  var Badge = SDK.components.Badge;
  var Button = SDK.components.Button;

  var API = "/api/plugins/nextcloud-tools";

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

    useEffect(function () {
      var cancelled = false;
      SDK.fetchJSON(API + "/tools")
        .then(function (data) {
          if (!cancelled) setTools(data.tools || []);
        })
        .catch(function (err) {
          if (!cancelled) setError(String((err && err.message) || err));
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
        })
        .catch(function (err) {
          setError(String((err && err.message) || err)); // keep old state on error
        })
        .finally(function () {
          setBusy(false);
        });
    }

    return React.createElement(
      Card,
      null,
      React.createElement(
        CardHeader,
        null,
        React.createElement(CardTitle, null, "Nextcloud tools")
      ),
      React.createElement(
        CardContent,
        null,
        error
          ? React.createElement(
              "p",
              { className: "text-sm text-destructive" },
              "Error: " + error
            )
          : null,
        React.createElement(
          "p",
          { className: "text-sm text-muted-foreground" },
          tools.length +
            " tools. Changes apply on the next agent start / plugin reload."
        ),
        React.createElement(
          "div",
          { className: "mt-2 flex flex-col gap-2" },
          tools.map(function (t) {
            return React.createElement(
              "div",
              { key: t.name, className: "flex items-center gap-2" },
              React.createElement(
                "span",
                {
                  className: "flex-1 truncate font-mono text-sm",
                  title: t.description || t.name
                },
                t.name
              ),
              React.createElement(Badge, null, t.gate),
              React.createElement(
                Button,
                {
                  size: "sm",
                  variant: t.enabled ? "outline" : "default",
                  disabled: busy,
                  onClick: function () {
                    toggle(t);
                  }
                },
                t.enabled ? "Disable" : "Enable"
              )
            );
          })
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register("nextcloud-tools", NextcloudToolsPage);
})();
