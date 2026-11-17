(function () {
  "use strict";

  window.__adbConsoleErrors = window.__adbConsoleErrors || [];
  window.addEventListener("error", function (event) {
    window.__adbConsoleErrors.push(String(event.message || event.error || "脚本错误"));
  });
  window.addEventListener("unhandledrejection", function (event) {
    window.__adbConsoleErrors.push("未处理的异步错误：" + String(event.reason));
  });

  var $ = function (selector, root) {
    return (root || document).querySelector(selector);
  };

  var $$ = function (selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  };

  var state = {
    activeSerial: null,
    manualSerial: false,
    lastStatus: null,
    devices: [],
    statusBusy: false,
    infoPaused: false,
    infoBusy: false,
    lastInfoError: "",
    screen: {
      running: false,
      statsTimer: null,
      lastUrl: null,
      lastTs: 0,
      failures: 0,
      pollTimer: null,
      tapTimer: null
    },
    log: {
      running: false,
      paused: false,
      since: 0,
      timer: null,
      busy: false,
      error: ""
    },
    packagesLoaded: false,
    pkgTimer: null,
    processes: [],
    shellHistory: [],
    deviceConnected: false,
    floating: false,
    mcp: {
      enabled: false,
      endpoint: "/mcp",
      tool_count: 0,
      warning: ""
    },
    dragDepth: 0
  };

  var STATE_TEXT = {
    device: "已连接",
    unauthorized: "未授权",
    offline: "离线",
    "no permissions": "无权限"
  };

  var KIND_TEXT = {
    pairing: "配对服务",
    connect: "无线调试",
    legacy: "传统无线调试",
    known: "已保存地址",
    other: "其他服务"
  };

  /* --------------------------------------------------------------------- */
  /* 基础工具                                                              */
  /* --------------------------------------------------------------------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function formatBytes(bytes) {
    var value = Number(bytes);
    if (!isFinite(value) || value < 0) return "—";
    if (value < 1024) return value + " B";
    if (value < 1048576) return (value / 1024).toFixed(1) + " KB";
    if (value < 1073741824) return (value / 1048576).toFixed(1) + " MB";
    return (value / 1073741824).toFixed(2) + " GB";
  }

  function formatRss(kb) {
    if (!kb) return "—";
    return (kb / 1024).toFixed(1) + " MB";
  }

  function clockText(date) {
    var value = date || new Date();
    var pad = function (number) {
      return number < 10 ? "0" + number : String(number);
    };
    return pad(value.getHours()) + ":" + pad(value.getMinutes()) + ":" + pad(value.getSeconds());
  }

  async function request(path, options) {
    var opts = options || {};
    var init = { method: opts.method || "GET", headers: {} };
    if (opts.form) {
      init.body = opts.form;
    } else if (opts.body !== undefined && opts.body !== null) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    try {
      var response = await fetch(path, init);
      var data;
      try {
        data = await response.json();
      } catch (parseError) {
        return {
          ok: false,
          stdout: "",
          stderr: "服务器返回 HTTP " + response.status + "，内容不是 JSON。",
          code: -1
        };
      }
      if (!data || typeof data !== "object") {
        return { ok: false, stdout: "", stderr: "服务器返回了空响应。", code: -1 };
      }
      return data;
    } catch (networkError) {
      return {
        ok: false,
        stdout: "",
        stderr: "无法连接本地服务器：" + networkError.message,
        code: -1
      };
    }
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        fallbackCopy(text);
      });
    }
    fallbackCopy(text);
    return Promise.resolve();
  }

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.top = "-1000px";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand("copy");
    } catch (error) {
      /* ignore */
    }
    area.remove();
  }

  var toastTimer = null;

  function toast(text, tone) {
    var node = $("#toast");
    if (!node) return;
    node.textContent = text;
    node.className = "toast" + (tone ? " tone-" + tone : "");
    node.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      node.hidden = true;
    }, 3200);
  }

  function showResult(container, res, options) {
    var opts = options || {};
    var stdout = res && res.stdout !== undefined && res.stdout !== null ? String(res.stdout) : "";
    var stderr = res && res.stderr !== undefined && res.stderr !== null ? String(res.stderr) : "";
    var code = res && typeof res.code === "number" ? res.code : -1;
    var ok = Boolean(res && res.ok);
    var title = opts.title || "结果";
    var command = opts.command || (res && res.command) || "";
    var noteParts = [];
    if (opts.note) noteParts.push(opts.note);
    if (res && res.interpreted) noteParts.push(res.interpreted);
    if (res && res.explanation) noteParts.push(res.explanation);

    container.hidden = false;
    container.textContent = "";

    var head = el("div", "output-head");
    head.appendChild(el("span", "output-title", title));
    var codeText = code >= 0 ? "退出码 " + code : "无退出码";
    head.appendChild(el("span", "badge " + (ok ? "badge-ok" : "badge-fail"), (ok ? "成功" : "失败") + " · " + codeText));
    var copyBtn = el("button", "copy-btn", "复制");
    copyBtn.type = "button";
    head.appendChild(copyBtn);
    container.appendChild(head);

    var copyParts = [];
    if (command) {
      container.appendChild(el("div", "cmd-line", "$ " + command));
      copyParts.push("$ " + command);
    }
    if (stdout) {
      container.appendChild(el("pre", "out-block", stdout));
      copyParts.push(stdout);
    }
    if (stderr) {
      container.appendChild(el("pre", "err-block", stderr));
      copyParts.push(stderr);
    }
    if (!stdout && !stderr) {
      container.appendChild(el("p", "muted", "无输出。"));
    }
    if (noteParts.length) {
      container.appendChild(el("p", "muted", noteParts.join(" ")));
    }
    if (opts.link && opts.link.href) {
      var link = el("a", "output-link", opts.link.text || "打开");
      link.href = opts.link.href;
      link.target = "_blank";
      link.rel = "noopener";
      container.appendChild(link);
    }

    var copyValue = copyParts.join("\n");
    copyBtn.addEventListener("click", async function () {
      await copyText(copyValue);
      copyBtn.textContent = "已复制";
      window.setTimeout(function () {
        copyBtn.textContent = "复制";
      }, 1200);
    });

    return container;
  }

  function notice(container, text) {
    container.hidden = false;
    container.textContent = "";
    container.appendChild(el("p", "muted", text));
  }

  async function runWith(button, busyLabel, fn) {
    if (!button) return fn();
    var original = button.textContent;
    button.disabled = true;
    if (busyLabel) button.textContent = busyLabel;
    try {
      return await fn();
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  function withSerial(extra) {
    var body = Object.assign({}, extra || {});
    if (state.activeSerial) body.serial = state.activeSerial;
    return body;
  }

  function serialQuery() {
    return state.activeSerial ? "?serial=" + encodeURIComponent(state.activeSerial) : "";
  }

  function firstLine(text) {
    var line = String(text || "").split("\n")[0];
    return line.length > 90 ? line.slice(0, 90) + "…" : line;
  }

  function askConfirm(options) {
    return new Promise(function (resolve) {
      var modal = $("#modal");
      var confirmBtn = $("#modal-confirm");
      var cancelBtn = $("#modal-cancel");
      $("#modal-title").textContent = options.title || "确认操作";
      $("#modal-text").textContent = options.message || "";
      confirmBtn.textContent = options.confirmLabel || "确认";
      confirmBtn.className = "btn " + (options.tone === "primary" ? "btn-primary" : "btn-danger");
      modal.hidden = false;
      confirmBtn.focus();

      function close(value) {
        modal.hidden = true;
        confirmBtn.onclick = null;
        cancelBtn.onclick = null;
        modal.onclick = null;
        document.removeEventListener("keydown", onKey);
        resolve(value);
      }

      function onKey(event) {
        if (event.key === "Escape") close(false);
      }

      confirmBtn.onclick = function () {
        close(true);
      };
      cancelBtn.onclick = function () {
        close(false);
      };
      modal.onclick = function (event) {
        if (event.target === modal) close(false);
      };
      document.addEventListener("keydown", onKey);
    });
  }

  function showChoices(options) {
    return new Promise(function (resolve) {
      var modal = $("#choice-modal");
      var box = $("#choice-options");
      $("#choice-title").textContent = options.title || "选择操作";
      $("#choice-text").textContent = options.text || "";
      box.textContent = "";
      var settled = false;

      function close(value) {
        if (settled) return;
        settled = true;
        modal.hidden = true;
        $("#choice-cancel").onclick = null;
        modal.onclick = null;
        document.removeEventListener("keydown", onKey);
        resolve(value);
      }

      function onKey(event) {
        if (event.key === "Escape") close(null);
      }

      (options.options || []).forEach(function (option) {
        var tone = option.tone === "primary" ? "btn-primary" : option.tone === "danger" ? "btn-danger" : "btn-secondary";
        var button = el("button", "btn " + tone + " choice-btn");
        button.type = "button";
        button.appendChild(el("span", "choice-label", option.label));
        if (option.hint) button.appendChild(el("span", "choice-hint", option.hint));
        button.addEventListener("click", function () {
          close(option.value);
        });
        box.appendChild(button);
      });

      $("#choice-cancel").onclick = function () {
        close(null);
      };
      modal.onclick = function (event) {
        if (event.target === modal) close(null);
      };
      document.addEventListener("keydown", onKey);
      modal.hidden = false;
    });
  }

  /* --------------------------------------------------------------------- */
  /* 标签页                                                                */
  /* --------------------------------------------------------------------- */

  function switchTab(name) {
    var target = name || "overview";
    var exists = $$(".tab").some(function (tab) {
      return tab.dataset.tab === target;
    });
    if (!exists) target = "overview";
    $$(".tab").forEach(function (tab) {
      tab.classList.toggle("is-active", tab.dataset.tab === target);
    });
    $$(".tab-panel").forEach(function (panel) {
      panel.hidden = panel.id !== "panel-" + target;
    });
    try {
      window.localStorage.setItem("adb-console-tab", target);
    } catch (error) {
      /* ignore */
    }
    if (target === "files") refreshPulls();
  }

  function initTabs() {
    $$(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        switchTab(tab.dataset.tab);
      });
    });
    var saved = "overview";
    try {
      saved = window.localStorage.getItem("adb-console-tab") || "overview";
    } catch (error) {
      /* ignore */
    }
    switchTab(saved);
  }

  /* --------------------------------------------------------------------- */
  /* 设备状态                                                              */
  /* --------------------------------------------------------------------- */

  async function loadStatus() {
    if (state.statusBusy) return;
    state.statusBusy = true;
    try {
      var res = await request("/api/status");
      state.lastStatus = res;
      renderStatus(res);
    } finally {
      state.statusBusy = false;
    }
  }

  function renderStatus(res) {
    var devices = res && Array.isArray(res.devices) ? res.devices : [];
    var ready = devices.filter(function (device) {
      return device.state === "device";
    });
    var unauthorized = devices.filter(function (device) {
      return device.state === "unauthorized";
    });
    var offline = devices.filter(function (device) {
      return device.state === "offline";
    });

    state.devices = devices;
    state.deviceConnected = ready.length > 0;
    updateFloatButton();
    var pill = $("#status-pill");
    var label = $("#status-text");
    pill.className = "pill";

    if (!res || !res.ok) {
      pill.classList.add("pill-red");
      label.textContent = "ADB 异常";
      label.title = (res && res.stderr) || "";
    } else if (ready.length > 0) {
      pill.classList.add("pill-green");
      label.textContent = ready.length === 1 ? "已连接" : ready.length + " 台设备";
      label.title = ready[0].serial;
    } else if (unauthorized.length > 0) {
      pill.classList.add("pill-amber");
      label.textContent = "未授权";
      label.title = "请在设备屏幕上允许调试授权。";
    } else if (offline.length > 0) {
      pill.classList.add("pill-amber");
      label.textContent = "离线";
      label.title = "设备已离线。";
    } else {
      label.textContent = "无设备";
      label.title = "";
    }

    if (res && res.adb) {
      $("#adb-path").textContent = res.adb;
      $("#meta-adb").textContent = res.adb;
    }

    var serialExists = devices.some(function (device) {
      return device.serial === state.activeSerial;
    });
    var activeIsReady = ready.some(function (device) {
      return device.serial === state.activeSerial;
    });
    var previousSerial = state.activeSerial;
    if (!serialExists) {
      state.activeSerial = ready.length ? ready[0].serial : devices.length ? devices[0].serial : null;
      state.manualSerial = false;
    } else if (!state.manualSerial && !activeIsReady && ready.length) {
      state.activeSerial = ready[0].serial;
    }

    var primary = devices.filter(function (device) {
      return device.serial === state.activeSerial;
    })[0] || devices[0] || null;

    $("#dev-model").textContent = primary && primary.model ? primary.model : "未连接";
    $("#dev-serial").textContent = primary ? primary.serial : "—";

    var stateNode = $("#dev-state");
    if (primary) {
      var stateKey = primary.state;
      var stateLabel = primary.state_text || STATE_TEXT[stateKey] || stateKey;
      stateNode.textContent = stateLabel;
      stateNode.className =
        "tag " + (stateKey === "device" ? "tag-ok" : stateKey === "unauthorized" || stateKey === "offline" ? "tag-warn" : "tag-quiet");
    } else {
      stateNode.textContent = "—";
      stateNode.className = "tag tag-quiet";
    }

    $("#dev-transport").textContent = primary
      ? primary.usb
        ? "USB"
        : primary.serial.indexOf(":") >= 0
          ? "无线连接"
          : "—"
      : "—";

    var pickerWrap = $("#dev-picker-wrap");
    var picker = $("#dev-picker");
    if (devices.length > 1) {
      pickerWrap.hidden = false;
      picker.textContent = "";
      devices.forEach(function (device) {
        var option = document.createElement("option");
        option.value = device.serial;
        option.textContent = device.serial + "（" + (STATE_TEXT[device.state] || device.state) + "）";
        option.selected = device.serial === state.activeSerial;
        picker.appendChild(option);
      });
    } else {
      pickerWrap.hidden = true;
    }

    renderDiscovery(res || {});
    renderScreenSerial();

    if (previousSerial !== state.activeSerial) {
      onSerialChanged(previousSerial === null);
    }
  }

  function onSerialChanged(initial) {
    if (state.screen.running) stopScreen(false);
    var image = $("#screen-img");
    image.hidden = true;
    image.removeAttribute("src");
    var placeholder = $("#screen-placeholder");
    placeholder.hidden = false;
    placeholder.textContent = "";
    placeholder.appendChild(el("p", null, initial ? "点击“开始”后显示当前设备画面。" : "设备已切换。点击“开始”显示当前设备画面。"));
    placeholder.appendChild(el("p", "hint", "实时流由后台持续取帧，点击画面会向设备发送轻触。"));
    $("#screen-res").textContent = "—";
    if (state.log.running || state.log.paused) stopLog(false);
    resetLogView("");
    state.log.since = 0;
    $("#log-count").textContent = "0 行";
    setLogError("");
    $("#log-state").textContent = "未运行";
    state.lastInfoError = "";
    loadInfo();
  }

  function renderDiscovery(res) {
    var known = Array.isArray(res.known) ? res.known.slice() : [];
    var mdns = Array.isArray(res.mdns) ? res.mdns : [];
    var devices = Array.isArray(res.devices) ? res.devices : [];
    var list = $("#discovery-list");
    list.textContent = "";

    $("#discovery-time").textContent = res.last_run ? "上次扫描：" + res.last_run : "尚未扫描";

    var discoveryError = $("#discovery-error");
    if (res.stderr) {
      discoveryError.hidden = false;
      discoveryError.textContent = res.stderr;
    } else {
      discoveryError.hidden = true;
      discoveryError.textContent = "";
    }

    var byAddress = {};
    known.forEach(function (entry) {
      if (entry && entry.address) byAddress[entry.address] = Object.assign({}, entry);
    });
    mdns.forEach(function (service) {
      if (!service.address) return;
      if (!byAddress[service.address]) {
        byAddress[service.address] = {
          address: service.address,
          kind: service.kind,
          service_text: service.service_text,
          source: "mdns",
          last_ok: null,
          last_output: "",
          explanation: ""
        };
      } else if (!byAddress[service.address].kind) {
        byAddress[service.address].kind = service.kind;
        byAddress[service.address].service_text = service.service_text;
      }
    });

    var items = Object.keys(byAddress).map(function (key) {
      return byAddress[key];
    });
    if (!items.length) {
      list.appendChild(el("li", "empty", "未发现可自动连接的设备。请确认手机与电脑在同一 Wi-Fi，并已开启无线调试。"));
      return;
    }

    items.sort(function (a, b) {
      var aDevice = devices.some(function (d) { return d.serial === a.address; });
      var bDevice = devices.some(function (d) { return d.serial === b.address; });
      if (aDevice !== bDevice) return aDevice ? -1 : 1;
      return String(a.address).localeCompare(String(b.address));
    });

    items.forEach(function (entry) {
      var device = devices.filter(function (item) {
        return item.serial === entry.address;
      })[0];
      var li = el("li");

      var main = el("div", "discovery-main");
      main.appendChild(el("span", "discovery-address", entry.address));
      main.appendChild(el("span", "tag", KIND_TEXT[entry.kind] || entry.service_text || "已保存地址"));

      var label = "待连接";
      var tone = "";
      if (device) {
        label = STATE_TEXT[device.state] || device.state;
        tone = device.state === "device" ? "tag-ok" : "tag-warn";
      } else if (entry.last_ok === true) {
        label = "已连接";
        tone = "tag-ok";
      } else if (entry.last_ok === false) {
        label = "连接失败";
        tone = "tag-fail";
      }
      main.appendChild(el("span", "tag " + tone, label));

      var needsPair = entry.kind !== "pairing" && !device && entry.last_ok !== true;
      if (entry.kind === "pairing" || needsPair) {
        var action = el("span", "discovery-actions");
        var pairBtn = el("button", "btn btn-secondary btn-xs", entry.kind === "pairing" ? "使用此配对端口" : "配对");
        pairBtn.type = "button";
        pairBtn.dataset.pairAddress = entry.address;
        pairBtn.dataset.pairKind = entry.kind || "";
        action.appendChild(pairBtn);
        main.appendChild(action);
      }
      li.appendChild(main);

      if (entry.last_output && !(device && device.state === "device")) {
        li.appendChild(el("div", "discovery-detail", entry.last_output));
      }

      var explanation = entry.explanation || "";
      if (device && device.state === "unauthorized") {
        explanation = "设备未授权：请在设备屏幕上允许调试授权后再试。";
      } else if (device && device.state === "offline") {
        explanation = "设备已离线：请检查无线网络或重新连接。";
      } else if (!device && entry.last_ok === false) {
        explanation = "连接失败：该设备可能尚未完成无线调试配对，或端口已变化。请使用左侧“使用配对码配对”，填入手机配对弹窗中的配对端口和 6 位配对码，配对成功后再连接。";
      }
      if (explanation && !(device && device.state === "device")) {
        li.appendChild(el("div", "discovery-explain", explanation));
      }
      list.appendChild(li);
    });
  }

  async function scanNow() {
    await runWith($("#btn-scan"), "扫描中…", async function () {
      var res = await request("/api/autoconnect", { method: "POST", body: {} });
      state.lastStatus = res;
      renderStatus(res);
      if (res && Array.isArray(res.attempts) && res.attempts.length === 0) {
        $("#discovery-time").textContent = (res.last_run ? "上次扫描：" + res.last_run : "") + "（10 秒内已尝试，未重复连接）";
      }
    });
  }

  function openPairForm(address, kind) {
    var parts = String(address || "").split(":");
    $("#ip").value = parts[0] || $("#ip").value;
    var box = $(".pair-box");
    if (box) box.open = true;
    if (kind === "pairing" && parts[1]) {
      $("#pair-port").value = parts[1];
    } else {
      $("#pair-port").value = "";
    }
    $("#pair-code").value = "";
    $("#pair-port").scrollIntoView({ behavior: "smooth", block: "center" });
    $("#pair-code").focus();
    if (kind !== "pairing") {
      notice($("#connect-output"), "请在手机“使用配对码配对设备”弹窗中查看配对端口和 6 位配对码，填入上方配对表单。");
    }
  }

  async function connectDevice() {
    var host = $("#ip").value.trim();
    var port = $("#port").value.trim();
    if (!host || !port) {
      notice($("#connect-output"), "请输入 IP 地址和无线调试端口。");
      return;
    }
    await runWith($("#btn-connect"), "连接中…", async function () {
      var res = await request("/api/connect", { method: "POST", body: { host: host, port: port } });
      showResult($("#connect-output"), res, {
        title: "无线连接",
        command: "adb connect " + host + ":" + port
      });
      await loadStatus();
      if (res.ok) loadInfo();
    });
  }

  async function pairDevice() {
    var host = $("#ip").value.trim();
    var port = $("#pair-port").value.trim();
    var code = $("#pair-code").value.trim();
    if (!host || !port || !code) {
      notice($("#connect-output"), "请填写 IP 地址、配对端口和 6 位配对码。");
      return;
    }
    await runWith($("#btn-pair"), "配对中…", async function () {
      var res = await request("/api/pair", { method: "POST", body: { host: host, port: port, code: code } });
      showResult($("#connect-output"), res, {
        title: "无线配对",
        command: "adb pair " + host + ":" + port + " " + code
      });
      await loadStatus();
    });
  }

  async function disconnectDevice() {
    await runWith($("#btn-disconnect"), "断开中…", async function () {
      var res = await request("/api/disconnect", { method: "POST", body: withSerial({}) });
      showResult($("#connect-output"), res, {
        title: "断开连接",
        command: "adb disconnect" + (state.activeSerial ? " " + state.activeSerial : "")
      });
      await loadStatus();
    });
  }

  /* --------------------------------------------------------------------- */
  /* 实时状态                                                              */
  /* --------------------------------------------------------------------- */

  async function loadInfo() {
    if (state.infoPaused || state.infoBusy) return;
    state.infoBusy = true;
    try {
      var res = await request("/api/device/info" + serialQuery());
      renderInfo(res);
    } finally {
      state.infoBusy = false;
    }
  }

  function stat(id, value) {
    var node = $(id);
    if (!node) return;
    node.textContent = value === undefined || value === null || value === "" ? "—" : String(value);
  }

  function renderInfo(res) {
    var info = res && res.info;
    $("#info-time").textContent = "更新于 " + clockText();

    if (!res || !res.ok || !info) {
      ["#st-battery", "#st-storage", "#st-memory", "#st-network", "#st-screen", "#st-uptime", "#st-focus", "#st-system", "#st-model", "#st-serial"].forEach(function (id) {
        stat(id, "—");
      });
      var errorText = (res && res.stderr) || "未读取到设备状态。";
      if (errorText !== state.lastInfoError) {
        state.lastInfoError = errorText;
        showResult($("#info-output"), res || { ok: false, stdout: "", stderr: errorText, code: -1 }, {
          title: "实时状态",
          command: "adb shell getprop / dumpsys"
        });
      }
      return;
    }

    state.lastInfoError = "";
    $("#info-output").hidden = true;
    $("#info-output").textContent = "";

    var battery = info.battery || {};
    var batteryText = battery.level !== null && battery.level !== undefined ? battery.level + "%" : "—";
    if (battery.status) batteryText += " · " + battery.status;
    if (battery.temperature_c !== null && battery.temperature_c !== undefined) batteryText += " · " + battery.temperature_c + "°C";
    stat("#st-battery", batteryText);
    stat("#st-storage", (info.storage && info.storage.text) || "—");
    stat("#st-memory", (info.memory && info.memory.text) || "—");
    var network = info.network || {};
    stat("#st-network", network.type ? network.type + (network.detail ? "（" + network.detail + "）" : "") : "—");
    var screen = info.screen || {};
    stat("#st-screen", screen.state ? screen.state + (screen.resolution ? " · " + screen.resolution : "") : "—");
    stat("#st-uptime", info.uptime || "—");
    var focus = info.focus || {};
    stat("#st-focus", focus.component || focus.package || "—");
    stat("#st-system", info.android ? "Android " + info.android + (info.sdk ? "（SDK " + info.sdk + "）" : "") : "—");
    var model = [info.manufacturer, info.model].filter(Boolean).join(" ");
    stat("#st-model", model || "—");
    stat("#st-serial", info.serial || state.activeSerial || "—");
  }

  /* --------------------------------------------------------------------- */
  /* 实时屏幕                                                              */
  /* --------------------------------------------------------------------- */

  function setScreenButtons(running) {
    $("#btn-screen-start").disabled = running;
    $("#btn-screen-stop").disabled = !running;
  }

  function updateScreenState(text, tone) {
    var node = $("#screen-state");
    node.textContent = text;
    node.className = "screen-state" + (tone ? " " + tone : "");
  }

  function renderScreenSerial() {
    $("#screen-serial").textContent = state.activeSerial || "";
  }

  async function startScreen() {
    if (state.screen.running) return;
    state.screen.running = true;
    state.screen.lastTs = 0;
    state.screen.failures = 0;
    setScreenButtons(true);
    updateScreenState("启动中…", "running");
    $("#screen-fps").textContent = "—";
    $("#screen-latency").textContent = "—";
    $("#screen-output").hidden = true;
    $("#screen-output").textContent = "";
    var placeholder = $("#screen-placeholder");
    placeholder.hidden = false;
    placeholder.textContent = "";
    placeholder.appendChild(el("p", null, "正在启动屏幕实时流…"));
    placeholder.appendChild(el("p", "hint", "后台持续取帧，帧率取决于设备截图速度。"));

    await request("/api/screen/start" + serialQuery(), { method: "POST", body: {} });
    if (!state.screen.running) return;
    updateScreenState("运行中", "running");

    if (state.screen.statsTimer) window.clearInterval(state.screen.statsTimer);
    state.screen.statsTimer = window.setInterval(pollScreenStats, 1000);
    screenPoll();
  }

  async function screenPoll() {
    if (!state.screen.running) return;
    try {
      var sq = serialQuery();
      var frameUrl = "/api/screen/frame" + (sq ? sq + "&" : "?") + "_=" + Date.now();
      var response = await fetch(frameUrl, { cache: "no-store" });
      var contentType = response.headers.get("content-type") || "";
      if (contentType.indexOf("image/") !== 0) {
        var errorData = await response.json().catch(function () {
          return { ok: false, stdout: "", stderr: "无法解析服务器的取帧响应。", code: -1 };
        });
        screenFailure(errorData);
        return;
      }
      var frameTs = response.headers.get("X-Frame-Ts") || "";
      var blob = await response.blob();
      state.screen.failures = 0;
      if (frameTs && frameTs === state.screen.lastTs) {
        /* 后台尚未产生新帧，直接进入下一轮 */
      } else {
        state.screen.lastTs = frameTs;
        var url = URL.createObjectURL(blob);
        var image = $("#screen-img");
        image.onload = function () {
          if (!state.screen.running) {
            URL.revokeObjectURL(url);
            return;
          }
          if (state.screen.lastUrl) URL.revokeObjectURL(state.screen.lastUrl);
          state.screen.lastUrl = url;
          image.hidden = false;
          $("#screen-placeholder").hidden = true;
        };
        image.onerror = function () {
          URL.revokeObjectURL(url);
        };
        image.src = url;
        var width = parseInt(response.headers.get("X-Device-Width") || "0", 10);
        var height = parseInt(response.headers.get("X-Device-Height") || "0", 10);
        if (width && height) $("#screen-res").textContent = width + " × " + height;
      }
    } catch (error) {
      state.screen.failures += 1;
      if (state.screen.failures >= 3) {
        screenFailure({ ok: false, stdout: "", stderr: "获取画面失败：" + error.message, code: -1 });
        return;
      }
    }
    if (!state.screen.running) return;
    state.screen.pollTimer = window.setTimeout(screenPoll, 120);
  }

  async function pollScreenStats() {
    if (!state.screen.running) return;
    var res = await request("/api/screen/stats" + serialQuery());
    if (!state.screen.running || !res || typeof res !== "object") return;
    if (res.fps) $("#screen-fps").textContent = res.fps + " 帧/秒";
    if (res.capture_ms) $("#screen-latency").textContent = res.capture_ms + " ms";
    if (res.width && res.height) $("#screen-res").textContent = res.width + " × " + res.height;
  }

  function screenFailure(res) {
    stopScreen(false);
    updateScreenState("错误", "error");
    $("#screen-fps").textContent = "—";
    $("#screen-latency").textContent = "—";
    var placeholder = $("#screen-placeholder");
    placeholder.hidden = false;
    placeholder.textContent = "";
    placeholder.appendChild(el("p", null, "无法获取设备画面。"));
    placeholder.appendChild(el("p", "hint", "请确认设备已连接并授权，然后重新开始。"));
    showResult($("#screen-output"), res, {
      title: "实时屏幕",
      command: "adb exec-out screencap -p"
    });
  }

  function stopScreen(showMessage) {
    state.screen.running = false;
    if (state.screen.statsTimer) {
      window.clearInterval(state.screen.statsTimer);
      state.screen.statsTimer = null;
    }
    if (state.screen.pollTimer) {
      window.clearTimeout(state.screen.pollTimer);
      state.screen.pollTimer = null;
    }
    var image = $("#screen-img");
    image.onload = null;
    image.onerror = null;
    if (image.src) {
      image.removeAttribute("src");
    }
    if (state.screen.lastUrl) {
      URL.revokeObjectURL(state.screen.lastUrl);
      state.screen.lastUrl = null;
    }
    state.screen.lastTs = 0;
    request("/api/screen/stop" + serialQuery(), { method: "POST", body: {} });
    setScreenButtons(false);
    updateScreenState("已停止");
    $("#screen-fps").textContent = "—";
    $("#screen-latency").textContent = "—";
    image.hidden = true;
    var placeholder = $("#screen-placeholder");
    placeholder.hidden = false;
    placeholder.textContent = "";
    placeholder.appendChild(el("p", null, showMessage ? "实时屏幕已停止。" : "点击“开始”后显示设备画面。"));
    placeholder.appendChild(el("p", "hint", "实时流由后台持续取帧，点击画面会向设备发送轻触。"));
  }

  async function sendScreenTap(event) {
    if (!state.screen.running) return;
    var image = $("#screen-img");
    var rect = image.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    var naturalWidth = image.naturalWidth || rect.width;
    var naturalHeight = image.naturalHeight || rect.height;
    var x = Math.round(((event.clientX - rect.left) / rect.width) * naturalWidth);
    var y = Math.round(((event.clientY - rect.top) / rect.height) * naturalHeight);
    if (x < 0 || y < 0 || x > naturalWidth || y > naturalHeight) return;

    var stageRect = $("#screen-stage").getBoundingClientRect();
    var dot = $("#screen-tap-dot");
    dot.hidden = false;
    dot.style.left = event.clientX - stageRect.left + "px";
    dot.style.top = event.clientY - stageRect.top + "px";
    if (state.screen.tapTimer) window.clearTimeout(state.screen.tapTimer);
    state.screen.tapTimer = window.setTimeout(function () {
      dot.hidden = true;
    }, 700);

    var res = await request("/api/tap", {
      method: "POST",
      body: withSerial({ x: x, y: y })
    });
    showResult($("#screen-output"), res, {
      title: "画面轻触",
      command: "adb shell input tap " + x + " " + y,
      note: "设备坐标：" + x + ", " + y
    });
  }

  async function toggleFullscreen() {
    var card = $("#screen-card");
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else if (card.requestFullscreen) {
        await card.requestFullscreen();
      }
    } catch (error) {
      notice($("#screen-output"), "浏览器未允许进入全屏。");
    }
  }

  function updateFullscreenButton() {
    $("#btn-screen-full").textContent = document.fullscreenElement ? "退出全屏" : "全屏";
  }

  async function saveScreen() {
    var res = await request("/api/screenshot", { method: "POST", body: withSerial({}) });
    showResult($("#screen-output"), res, {
      title: "截图保存",
      command: "adb exec-out screencap -p",
      link: res.ok && res.url ? { href: res.url, text: "打开截图" } : null
    });
    if (res.ok) toast("截图已保存到 screenshots/", "success");
    return res;
  }

  async function saveScreenFromOverview() {
    switchTab("screen");
    var button = $("#btn-shot");
    await runWith(button, "保存中…", saveScreen);
  }

  /* --------------------------------------------------------------------- */
  /* 浮动屏幕                                                              */
  /* --------------------------------------------------------------------- */

  function updateFloatButton() {
    var button = $("#btn-screen-float");
    if (!button) return;
    if (!state.deviceConnected) {
      if (state.floating) setFloating(false);
      button.disabled = true;
      button.textContent = "浮动";
      button.title = "连接设备后可浮动显示";
      return;
    }
    button.disabled = false;
    button.textContent = state.floating ? "取消浮动" : "浮动";
    button.title = state.floating ? "恢复固定位置" : "悬浮在页面顶层，可拖动";
  }

  function setFloating(on) {
    state.floating = Boolean(on);
    var card = $("#screen-card");
    card.classList.toggle("floating", state.floating);
    card.style.left = "";
    card.style.top = "";
    card.style.right = "";
    card.style.bottom = "";
    if (state.floating) {
      card.style.right = "24px";
      card.style.bottom = "24px";
    }
    updateFloatButton();
  }

  function initFloatDrag() {
    var handle = $(".screen-drag-handle");
    var card = $("#screen-card");
    if (!handle || !card) return;
    var dragging = false;
    var startX = 0;
    var startY = 0;
    var baseLeft = 0;
    var baseTop = 0;

    handle.addEventListener("pointerdown", function (event) {
      if (!state.floating) return;
      if (event.target.closest("button")) return;
      var rect = card.getBoundingClientRect();
      baseLeft = rect.left;
      baseTop = rect.top;
      card.style.left = rect.left + "px";
      card.style.top = rect.top + "px";
      card.style.right = "";
      card.style.bottom = "";
      startX = event.clientX;
      startY = event.clientY;
      dragging = true;
      handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });

    handle.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var rect = card.getBoundingClientRect();
      var left = baseLeft + event.clientX - startX;
      var top = baseTop + event.clientY - startY;
      var maxLeft = Math.max(0, window.innerWidth - rect.width);
      var maxTop = Math.max(0, window.innerHeight - 60);
      card.style.left = Math.min(Math.max(left, 0), maxLeft) + "px";
      card.style.top = Math.min(Math.max(top, 0), maxTop) + "px";
    });

    function endDrag() {
      dragging = false;
    }
    handle.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointercancel", endDrag);
  }

  /* --------------------------------------------------------------------- */
  /* 设置：ADB 路径与 MCP                                                   */
  /* --------------------------------------------------------------------- */

  async function loadMeta() {
    var res = await request("/api/meta");
    if (!res || !res.ok) return;
    $("#meta-dir").textContent = res.data_dir || "—";
    $("#meta-version").textContent = res.version || "—";
    if (res.adb_path) {
      $("#adb-path").textContent = res.adb_path;
      $("#meta-adb").textContent = res.adb_path;
    }
  }

  async function loadAdbConfig() {
    var res = await request("/api/adb/config");
    if (res && res.ok && res.adb_path) {
      $("#adb-path-input").value = res.adb_path;
      $("#adb-path").textContent = res.adb_path;
      $("#meta-adb").textContent = res.adb_path;
    }
  }

  async function testAdbPath() {
    await runWith($("#btn-adb-test"), "测试中…", async function () {
      var value = $("#adb-path-input").value.trim();
      var res = await request("/api/adb/test", {
        method: "POST",
        body: { adb_path: value }
      });
      showResult($("#adb-output"), res, {
        title: "ADB 测试",
        command: (res.adb_path || value || $("#adb-path").textContent) + " version"
      });
    });
  }

  async function browseAdbPath() {
    await runWith($("#btn-browse-adb"), "选择中…", async function () {
      var current = $("#adb-path-input").value.trim();
      var dir = "";
      if (current.indexOf("/") >= 0 || current.indexOf("\\") >= 0) {
        dir = current.replace(/[\\/][^\\/]*$/, "");
      }
      var res = await request("/api/adb/browse", {
        method: "POST",
        body: { initialdir: dir }
      });
      if (!res.ok) {
        notice($("#adb-output"), res.stderr || "无法打开文件选择框，请手动填写路径。");
        return;
      }
      if (res.path) {
        $("#adb-path-input").value = res.path;
        $("#adb-output").hidden = true;
        $("#adb-output").textContent = "";
        toast("已选择：" + res.path, "success");
      }
    });
  }

  async function saveAdbPath() {
    var value = $("#adb-path-input").value.trim();
    var output = $("#adb-output");
    if (!value) {
      notice(output, "请填写 adb 可执行文件路径或其所在目录，再保存。");
      return;
    }
    await runWith($("#btn-adb-save"), "保存中…", async function () {
      var res = await request("/api/adb/config", {
        method: "POST",
        body: { adb_path: value }
      });
      showResult(output, res, {
        title: "ADB 设置",
        command: (res.adb_path || value) + " version"
      });
      if (res.ok) {
        $("#adb-path").textContent = res.adb_path || value;
        $("#meta-adb").textContent = res.adb_path || value;
        toast("ADB 路径已更新", "success");
        await loadStatus();
      }
    });
  }

  async function loadMcpStatus() {
    var res = await request("/api/mcp/status");
    if (!res || !res.ok) return;
    state.mcp.enabled = Boolean(res.enabled);
    state.mcp.endpoint = res.endpoint || "/mcp";
    state.mcp.tool_count = res.tool_count || 0;
    state.mcp.warning = res.warning || "";
    renderMcp();
  }

  function renderMcp() {
    var enabled = state.mcp.enabled;
    var pill = $("#mcp-pill");
    pill.textContent = enabled ? "MCP 开" : "MCP 关";
    pill.className = "pill " + (enabled ? "pill-green" : "pill-quiet");
    pill.title = enabled ? "MCP 服务已启用，点击打开设置" : "MCP 服务已关闭，点击打开设置";

    $("#mcp-toggle").checked = enabled;
    var stateNode = $("#mcp-state");
    stateNode.textContent = enabled ? "已启用 · " + state.mcp.tool_count + " 个工具" : "已关闭";
    stateNode.className = "tag " + (enabled ? "tag-ok" : "tag-quiet");
    $("#mcp-endpoint").textContent = window.location.origin + state.mcp.endpoint;
    if (state.mcp.warning) $("#mcp-warning").textContent = state.mcp.warning;
    $("#meta-mcp").textContent = enabled ? "已启用（" + state.mcp.tool_count + " 个工具）" : "未开启";
  }

  async function setMcpEnabled(enabled) {
    var res = await request("/api/mcp/toggle", {
      method: "POST",
      body: { enabled: enabled, acknowledge_risk: enabled }
    });
    if (!res.ok) {
      showResult($("#mcp-output"), res, { title: "MCP 服务" });
      toast(res.stderr || "切换 MCP 失败", "error");
    } else {
      $("#mcp-output").hidden = true;
      $("#mcp-output").textContent = "";
      toast(enabled ? "MCP 服务已启用" : "MCP 服务已关闭", enabled ? "warn" : "success");
    }
    await loadMcpStatus();
  }

  async function onMcpToggleChange(event) {
    var want = event.target.checked;
    if (want) {
      event.target.checked = false;
      var confirmed = await askConfirm({
        title: "启用 MCP 服务",
        message:
          (state.mcp.warning || "AI 客户端将可以操作你的设备。") +
          "\n\n确认只在你信任的客户端上开启，并在用完后关闭。",
        confirmLabel: "我已了解风险，启用",
        tone: "danger"
      });
      if (!confirmed) {
        return;
      }
    }
    await setMcpEnabled(want);
  }

  function openSettings() {
    $("#settings-modal").hidden = false;
    loadAdbConfig();
    loadMcpStatus();
  }

  function closeSettings() {
    $("#settings-modal").hidden = true;
  }

  /* --------------------------------------------------------------------- */
  /* 日志                                                                  */
  /* --------------------------------------------------------------------- */

  function setLogButtons(running) {
    $("#btn-log-start").disabled = running;
    $("#btn-log-stop").disabled = !running;
    $("#btn-log-pause").disabled = !running && !state.log.paused;
  }

  function setLogError(text) {
    var node = $("#log-error");
    if (text) {
      node.hidden = false;
      node.textContent = text;
    } else {
      node.hidden = true;
      node.textContent = "";
    }
  }

  function resetLogView(text) {
    $("#log-view").textContent = text || "";
  }

  function appendLogText(text) {
    var view = $("#log-view");
    if (view.textContent === "尚未开始日志流。") view.textContent = "";
    view.appendChild(document.createTextNode(text + "\n"));
    while (view.childNodes.length > 60) {
      view.removeChild(view.firstChild);
    }
    if ($("#log-autoscroll").checked) view.scrollTop = view.scrollHeight;
  }

  async function startLog() {
    state.log.paused = false;
    state.log.since = 0;
    state.log.error = "";
    $("#btn-log-pause").textContent = "暂停显示";
    resetLogView("");
    setLogError("");
    $("#log-state").textContent = "启动中…";
    $("#log-count").textContent = "0 行";

    var res = await request("/api/logcat/stream/start", { method: "POST", body: withSerial({}) });
    state.log.running = Boolean(res.running);
    state.log.since = 0;
    setLogButtons(state.log.running);
    setLogError(res.stderr || "");
    $("#log-state").textContent = res.waiting ? "等待设备" : res.running ? "运行中" : res.stderr ? "错误" : "已停止";
    if (res.running) {
      scheduleLogPoll(300);
    }
  }

  function scheduleLogPoll(delay) {
    if (state.log.timer) window.clearTimeout(state.log.timer);
    state.log.timer = window.setTimeout(pollLog, delay);
  }

  async function pollLog() {
    if (!state.log.running || state.log.paused || state.log.busy) return;
    state.log.busy = true;
    try {
      var params = new URLSearchParams();
      params.set("since", String(state.log.since));
      params.set("limit", "500");
      var filter = $("#log-filter").value.trim();
      if (filter) params.set("filter", filter);
      params.set("level", $("#log-level").value);
      if (state.activeSerial) params.set("serial", state.activeSerial);

      var res = await request("/api/logcat/stream?" + params.toString());
      if (res.lines && res.lines.length) {
        var text = res.lines
          .map(function (line) {
            return line.text;
          })
          .join("\n");
        appendLogText(text);
      }
      if (typeof res.next === "number") state.log.since = res.next;
      state.log.running = Boolean(res.running);
      state.log.error = res.stderr || "";
      setLogError(state.log.error);
      $("#log-count").textContent = String(res.total || 0) + " 行";
      $("#log-state").textContent = res.waiting ? "等待设备" : res.running ? "运行中" : res.stderr ? "错误" : "已停止";
      setLogButtons(state.log.running);
      if (res.running && !state.log.paused) scheduleLogPoll(900);
    } finally {
      state.log.busy = false;
    }
  }

  async function stopLog() {
    if (state.log.timer) window.clearTimeout(state.log.timer);
    state.log.timer = null;
    state.log.paused = false;
    $("#btn-log-pause").textContent = "暂停显示";
    await request("/api/logcat/stream/stop", { method: "POST", body: {} });
    state.log.running = false;
    setLogButtons(false);
    $("#log-state").textContent = "已停止";
  }

  function toggleLogPause() {
    if (!state.log.running) return;
    state.log.paused = !state.log.paused;
    $("#btn-log-pause").textContent = state.log.paused ? "继续显示" : "暂停显示";
    $("#log-state").textContent = state.log.paused ? "已暂停显示" : "运行中";
    if (state.log.paused) {
      if (state.log.timer) window.clearTimeout(state.log.timer);
      state.log.timer = null;
    } else {
      pollLog();
    }
  }

  async function clearLog() {
    var res = await request("/api/logcat/clear", { method: "POST", body: withSerial({}) });
    resetLogView("");
    state.log.since = 0;
    $("#log-count").textContent = "0 行";
    if (res.stderr) {
      setLogError(res.stderr);
      $("#log-state").textContent = "清空失败";
    } else {
      setLogError("");
    }
  }

  function logFilterChanged() {
    if (!state.log.running) return;
    resetLogView("");
    state.log.since = 0;
    if (state.log.timer) window.clearTimeout(state.log.timer);
    state.log.timer = null;
    if (!state.log.paused) pollLog();
  }

  /* --------------------------------------------------------------------- */
  /* 应用与进程                                                            */
  /* --------------------------------------------------------------------- */

  async function loadPackages() {
    var params = new URLSearchParams();
    var filter = $("#pkg-filter").value.trim();
    if (filter) params.set("filter", filter);
    if ($("#pkg-third").checked) params.set("third_party", "1");
    if (state.activeSerial) params.set("serial", state.activeSerial);

    await runWith($("#btn-packages"), "加载中…", async function () {
      var res = await request("/api/packages" + (params.toString() ? "?" + params.toString() : ""));
      state.packagesLoaded = true;
      renderPackages(res);
    });
  }

  function renderPackages(res) {
    var list = $("#pkg-list");
    list.textContent = "";
    if (!res.ok) {
      showResult($("#pkg-output"), res, {
        title: "应用列表",
        command: "adb shell pm list packages"
      });
      $("#pkg-count").textContent = "0 个";
      list.appendChild(el("li", "empty", "未读取到应用列表。"));
      return;
    }
    $("#pkg-output").hidden = true;
    $("#pkg-output").textContent = "";
    var packages = Array.isArray(res.packages) ? res.packages : [];
    $("#pkg-count").textContent = res.count + " 个";
    if (!packages.length) {
      list.appendChild(el("li", "empty", "没有匹配的应用。"));
      return;
    }
    var fragment = document.createDocumentFragment();
    packages.forEach(function (pkg) {
      var li = el("li");
      li.appendChild(el("span", "pkg-name", pkg));
      var actions = el("span", "pkg-actions");
      [
        ["start", "启动", "btn-secondary"],
        ["stop", "停止", "btn-secondary"],
        ["clear", "清除数据", "btn-secondary"],
        ["uninstall", "卸载", "btn-danger"]
      ].forEach(function (spec) {
        var button = el("button", "btn " + spec[2] + " btn-xs", spec[1]);
        button.type = "button";
        button.dataset.act = spec[0];
        button.dataset.pkg = pkg;
        actions.appendChild(button);
      });
      li.appendChild(actions);
      fragment.appendChild(li);
    });
    list.appendChild(fragment);
  }

  async function runAppAction(action, pkg, button) {
    var titles = {
      start: "启动应用",
      stop: "停止应用",
      clear: "清除应用数据",
      uninstall: "卸载应用"
    };
    var commands = {
      start: "adb shell monkey -p " + pkg + " -c android.intent.category.LAUNCHER 1",
      stop: "adb shell am force-stop " + pkg,
      clear: "adb shell pm clear " + pkg,
      uninstall: "adb shell pm uninstall " + pkg
    };
    if (action === "clear" || action === "uninstall") {
      var confirmed = await askConfirm({
        title: titles[action],
        message:
          action === "clear"
            ? "要清除 " + pkg + " 的全部数据吗？此操作不可撤销。"
            : "要从设备卸载 " + pkg + " 吗？",
        confirmLabel: action === "clear" ? "清除数据" : "卸载"
      });
      if (!confirmed) return;
    }
    await runWith(button, "…", async function () {
      var res = await request("/api/app/" + action, {
        method: "POST",
        body: withSerial({ package: pkg })
      });
      showResult($("#pkg-output"), res, {
        title: titles[action],
        command: commands[action]
      });
      if (action === "uninstall" && res.ok) loadPackages();
    });
  }

  async function loadProcesses() {
    await runWith($("#btn-processes"), "读取中…", async function () {
      var res = await request("/api/processes" + serialQuery());
      if (!res.ok) {
        showResult($("#process-output"), res, {
          title: "进程列表",
          command: "adb shell ps -A"
        });
        state.processes = [];
        renderProcessRows();
        return;
      }
      $("#process-output").hidden = true;
      $("#process-output").textContent = "";
      state.processes = Array.isArray(res.processes) ? res.processes : [];
      renderProcessRows();
    });
  }

  function renderProcessRows() {
    var box = $("#process-list");
    var filter = $("#process-filter").value.trim().toLowerCase();
    var rows = state.processes.filter(function (process) {
      return !filter || String(process.name).toLowerCase().indexOf(filter) >= 0;
    });
    box.textContent = "";
    $("#process-count").textContent = rows.length + " 个";
    if (!rows.length) {
      box.appendChild(el("p", "empty", state.processes.length ? "没有匹配的进程。" : "尚未读取进程。"));
      return;
    }
    var fragment = document.createDocumentFragment();
    rows.forEach(function (process) {
      var row = el("div", "process-row");
      row.appendChild(el("span", "pid", process.pid));
      var name = el("span", "process-name", process.name);
      name.title = process.name;
      row.appendChild(name);
      row.appendChild(el("span", "process-rss", formatRss(process.rss_kb)));
      fragment.appendChild(row);
    });
    box.appendChild(fragment);
  }

  /* --------------------------------------------------------------------- */
  /* 安装 / 文件 / Shell                                                   */
  /* --------------------------------------------------------------------- */

  async function uploadInstall(file) {
    var form = new FormData();
    form.append("file", file);
    if (state.activeSerial) form.append("serial", state.activeSerial);
    var res = await request("/api/install", { method: "POST", form: form });
    showResult($("#install-output"), res, { title: "安装 APK" });
    return res;
  }

  async function installApk() {
    var fileInput = $("#install-file");
    var path = $("#install-path").value.trim();
    var output = $("#install-output");
    if (!fileInput.files || !fileInput.files.length) {
      if (!path) {
        notice(output, "请填写本机 APK 路径，或选择一个 .apk 文件。");
        return;
      }
    }
    await runWith($("#btn-install"), "安装中…", async function () {
      var res;
      if (fileInput.files && fileInput.files.length) {
        res = await uploadInstall(fileInput.files[0]);
      } else {
        res = await request("/api/install", {
          method: "POST",
          body: withSerial({ local: path })
        });
        showResult(output, res, { title: "安装 APK" });
      }
      if (res.ok) toast("安装完成", "success");
    });
  }

  function renderShellHistory() {
    var box = $("#shell-history");
    box.textContent = "";
    if (!state.shellHistory.length) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.appendChild(el("span", "muted", "历史记录"));
    state.shellHistory.slice(0, 12).forEach(function (command) {
      var chip = el("button", "chip", command);
      chip.type = "button";
      chip.title = command;
      chip.addEventListener("click", function () {
        $("#shell-cmd").value = command;
        $("#shell-cmd").focus();
      });
      box.appendChild(chip);
    });
  }

  function loadShellHistory() {
    try {
      var raw = window.localStorage.getItem("adb-console-shell-history");
      state.shellHistory = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(state.shellHistory)) state.shellHistory = [];
    } catch (error) {
      state.shellHistory = [];
    }
    renderShellHistory();
  }

  function rememberShell(command) {
    state.shellHistory = [command].concat(
      state.shellHistory.filter(function (item) {
        return item !== command;
      })
    ).slice(0, 20);
    try {
      window.localStorage.setItem("adb-console-shell-history", JSON.stringify(state.shellHistory));
    } catch (error) {
      /* ignore */
    }
    renderShellHistory();
  }

  async function runShell() {
    var input = $("#shell-cmd");
    var command = input.value.trim();
    if (!command) {
      notice($("#shell-output"), "请输入要执行的命令。");
      return;
    }
    await runWith($("#btn-shell"), "运行中…", async function () {
      var res = await request("/api/shell", {
        method: "POST",
        body: withSerial({ cmd: command })
      });
      showResult($("#shell-output"), res, {
        title: "命令行",
        command: "adb shell " + command
      });
      rememberShell(command);
    });
  }

  async function pushUpload(file, remote) {
    var form = new FormData();
    form.append("file", file);
    if (remote) form.append("remote", remote);
    if (state.activeSerial) form.append("serial", state.activeSerial);
    var res = await request("/api/push", { method: "POST", form: form });
    showResult($("#push-output"), res, {
      title: "推送到设备",
      command: "adb push " + file.name + " " + (remote || ""),
      note: res.ok && res.bytes !== undefined ? "已发送 " + formatBytes(res.bytes) : ""
    });
    return res;
  }

  async function pushFile() {
    var fileInput = $("#push-file");
    var localPath = $("#push-local").value.trim();
    var remote = $("#push-remote").value.trim() || "/sdcard/Download/";
    var output = $("#push-output");
    if (!fileInput.files || !fileInput.files.length) {
      if (!localPath) {
        notice(output, "请选择文件，或填写项目目录内的本机路径。");
        return;
      }
    }
    await runWith($("#btn-push"), "推送中…", async function () {
      var res;
      if (fileInput.files && fileInput.files.length) {
        res = await pushUpload(fileInput.files[0], remote);
      } else {
        res = await request("/api/push", {
          method: "POST",
          body: withSerial({ local: localPath, remote: remote })
        });
        showResult(output, res, {
          title: "推送到设备",
          command: "adb push " + (res.local || localPath || "") + " " + remote,
          note: res.ok && res.bytes !== undefined ? "已发送 " + formatBytes(res.bytes) : ""
        });
      }
      if (res.ok) toast("文件已推送", "success");
    });
  }

  async function pullFile() {
    var remote = $("#pull-remote").value.trim();
    var output = $("#pull-output");
    if (!remote) {
      notice(output, "请输入设备上的文件路径。");
      return;
    }
    await runWith($("#btn-pull"), "拉取中…", async function () {
      var res = await request("/api/pull", {
        method: "POST",
        body: withSerial({ remote: remote })
      });
      showResult(output, res, {
        title: "从设备拉取",
        command: "adb pull " + remote + " pulls/",
        note: res.ok && res.name ? "已保存到 pulls/" + res.name + "（" + formatBytes(res.size) + "）" : ""
      });
      if (res.ok) refreshPulls();
    });
  }

  async function refreshPulls() {
    var res = await request("/api/pulls");
    var list = $("#pull-list");
    list.textContent = "";
    if (!res.ok) {
      list.appendChild(el("li", "empty", "无法读取已拉取文件：" + (res.stderr || "未知错误")));
      return;
    }
    var files = Array.isArray(res.files) ? res.files : [];
    if (!files.length) {
      list.appendChild(el("li", "empty", "暂无文件。"));
      return;
    }
    files.forEach(function (file) {
      var li = el("li");
      li.appendChild(el("span", "file-name", file.name));
      var meta = el("span", "file-meta");
      meta.appendChild(el("span", null, formatBytes(file.size)));
      meta.appendChild(el("span", null, file.modified));
      var link = el("a", null, "下载");
      link.href = file.url;
      meta.appendChild(link);
      li.appendChild(meta);
      list.appendChild(li);
    });
  }

  /* --------------------------------------------------------------------- */
  /* 拖拽文件                                                              */
  /* --------------------------------------------------------------------- */

  function isFileDrag(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    if (!types) return false;
    return Array.prototype.indexOf.call(types, "Files") >= 0;
  }

  function isScreenEvent(event) {
    var target = event.target;
    return !!(target && target.closest && target.closest("#screen-card"));
  }

  function showDropOverlay(show) {
    var overlay = $("#drop-overlay");
    if (overlay) overlay.hidden = !show;
  }

  async function handleDroppedFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    if (!state.deviceConnected) {
      toast("请先连接设备，再发送文件", "error");
      return;
    }
    if (files.length > 1) {
      toast("一次只处理一个文件，已选择第一个", "warn");
    }
    var file = files[0];
    var isApk = /\.apk$/i.test(file.name);
    var detail = file.name + " · " + formatBytes(file.size);

    var action;
    if (isApk) {
      action = await showChoices({
        title: "发送 APK",
        text: detail,
        options: [
          { value: "install", label: "安装到设备", hint: "adb install -r，覆盖安装现有版本", tone: "primary" },
          { value: "push", label: "仅推送到手机目录", hint: "不安装，只把文件放到设备目录" }
        ]
      });
    } else {
      action = await showChoices({
        title: "发送文件",
        text: detail,
        options: [
          { value: "push", label: "推送到手机目录", hint: "发送到设备目录（默认 /sdcard/Download/）", tone: "primary" }
        ]
      });
    }
    if (!action) return;

    if (action === "install") {
      switchTab("apps");
      toast("正在安装 APK…");
      var installRes = await uploadInstall(file);
      if (installRes.ok) toast("安装完成", "success");
      else toast("安装失败：" + firstLine(installRes.stderr || "请查看输出详情"), "error");
      return;
    }

    switchTab("files");
    var remote = $("#push-remote").value.trim() || "/sdcard/Download/";
    if (!$("#push-remote").value.trim()) $("#push-remote").value = remote;
    toast("正在推送到 " + remote + " …");
    var pushRes = await pushUpload(file, remote);
    if (pushRes.ok) toast("已推送到 " + remote, "success");
    else toast("推送失败：" + firstLine(pushRes.stderr || "请查看输出详情"), "error");
  }

  function initDragAndDrop() {
    var overlay = $("#drop-overlay");

    window.addEventListener("dragenter", function (event) {
      if (isScreenEvent(event)) return;
      if (!isFileDrag(event)) return;
      event.preventDefault();
      state.dragDepth += 1;
      showDropOverlay(true);
    });

    window.addEventListener("dragover", function (event) {
      if (isScreenEvent(event)) return;
      if (!isFileDrag(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      showDropOverlay(true);
    });

    window.addEventListener("dragleave", function (event) {
      if (isScreenEvent(event)) return;
      state.dragDepth = Math.max(0, state.dragDepth - 1);
      if (state.dragDepth === 0 || event.relatedTarget === null) {
        showDropOverlay(false);
      }
    });

    window.addEventListener("drop", function (event) {
      if (isScreenEvent(event)) return;
      if (!isFileDrag(event)) return;
      event.preventDefault();
      state.dragDepth = 0;
      showDropOverlay(false);
      handleDroppedFiles(event.dataTransfer && event.dataTransfer.files);
    });

    // 实时屏幕只用于触控操作：屏蔽图片原生拖拽与文件拖放上传。
    var screenStage = $("#screen-stage");
    if (screenStage) {
      ["dragstart", "dragenter", "dragover", "drop"].forEach(function (type) {
        screenStage.addEventListener(type, function (event) {
          event.preventDefault();
          event.stopPropagation();
          if (type === "dragstart" || type === "drop") {
            state.dragDepth = 0;
            showDropOverlay(false);
          }
        });
      });
    }

    var zone = $("#drop-zone");
    if (zone) {
      zone.addEventListener("click", function (event) {
        if (event.target === $("#push-file")) return;
        $("#push-file").click();
      });
      zone.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          $("#push-file").click();
        }
      });
    }
    if (overlay) {
      overlay.addEventListener("click", function () {
        state.dragDepth = 0;
        showDropOverlay(false);
      });
    }
  }

  /* --------------------------------------------------------------------- */
  /* 触控 / 重启                                                           */
  /* --------------------------------------------------------------------- */

  async function sendKey(name, button) {
    await runWith(button, "…", async function () {
      var res = await request("/api/key", { method: "POST", body: withSerial({ code: name }) });
      var code = res.key_code !== undefined ? res.key_code : name;
      showResult($("#touch-output"), res, {
        title: "按键",
        command: "adb shell input keyevent " + code
      });
    });
  }

  async function sendTap() {
    var x = parseInt($("#tap-x").value, 10);
    var y = parseInt($("#tap-y").value, 10);
    if (!isFinite(x) || !isFinite(y) || x < 0 || y < 0) {
      notice($("#touch-output"), "请输入有效的 X、Y 坐标。");
      return;
    }
    await runWith($("#btn-tap"), "发送中…", async function () {
      var res = await request("/api/tap", { method: "POST", body: withSerial({ x: x, y: y }) });
      showResult($("#touch-output"), res, {
        title: "轻触",
        command: "adb shell input tap " + x + " " + y
      });
    });
  }

  async function sendSwipe() {
    var values = {
      x1: parseInt($("#sw-x1").value, 10),
      y1: parseInt($("#sw-y1").value, 10),
      x2: parseInt($("#sw-x2").value, 10),
      y2: parseInt($("#sw-y2").value, 10),
      duration_ms: parseInt($("#sw-duration").value, 10)
    };
    var keys = Object.keys(values);
    for (var index = 0; index < keys.length; index += 1) {
      if (!isFinite(values[keys[index]]) || values[keys[index]] < 0) {
        notice($("#touch-output"), "请填写有效的滑动坐标与时长。");
        return;
      }
    }
    await runWith($("#btn-swipe"), "发送中…", async function () {
      var res = await request("/api/swipe", { method: "POST", body: withSerial(values) });
      showResult($("#touch-output"), res, {
        title: "滑动",
        command:
          "adb shell input swipe " +
          values.x1 +
          " " +
          values.y1 +
          " " +
          values.x2 +
          " " +
          values.y2 +
          " " +
          values.duration_ms
      });
    });
  }

  async function rebootDevice(mode) {
    var labels = { system: "系统", recovery: "恢复模式", bootloader: "引导模式" };
    var confirmed = await askConfirm({
      title: "重启设备",
      message: "要重启到" + labels[mode] + "吗？adb 连接会断开，设备恢复后需要重新连接。",
      confirmLabel: "重启",
      tone: "primary"
    });
    if (!confirmed) return;
    var button = document.querySelector('[data-reboot="' + mode + '"]');
    await runWith(button, "重启中…", async function () {
      var res = await request("/api/reboot", {
        method: "POST",
        body: withSerial({ mode: mode })
      });
      showResult($("#reboot-output"), res, {
        title: "重启",
        command: "adb reboot" + (mode === "system" ? "" : " " + mode)
      });
      await loadStatus();
    });
  }

  /* --------------------------------------------------------------------- */
  /* 事件绑定                                                              */
  /* --------------------------------------------------------------------- */

  function wire() {
    initTabs();

    $("#btn-refresh-device").addEventListener("click", function () {
      runWith($("#btn-refresh-device"), "刷新中…", loadStatus);
    });
    $("#btn-scan").addEventListener("click", scanNow);
    $("#btn-connect").addEventListener("click", connectDevice);
    $("#btn-pair").addEventListener("click", pairDevice);
    $("#btn-disconnect").addEventListener("click", disconnectDevice);

    $("#dev-picker").addEventListener("change", function (event) {
      var next = event.target.value || null;
      var changed = next !== state.activeSerial;
      state.activeSerial = next;
      state.manualSerial = true;
      if (changed) onSerialChanged();
      renderStatus(state.lastStatus || { ok: true, devices: state.devices });
    });

    $("#btn-info-pause").addEventListener("click", function () {
      state.infoPaused = !state.infoPaused;
      $("#btn-info-pause").textContent = state.infoPaused ? "继续刷新" : "暂停刷新";
      if (!state.infoPaused) loadInfo();
    });

    $("#btn-screen-start").addEventListener("click", startScreen);
    $("#btn-screen-stop").addEventListener("click", function () {
      stopScreen(true);
    });
    $("#btn-screen-float").addEventListener("click", function () {
      setFloating(!state.floating);
    });
    initFloatDrag();
    $("#btn-screen-full").addEventListener("click", toggleFullscreen);
    $("#btn-screen-save").addEventListener("click", saveScreen);
    $("#screen-img").addEventListener("click", sendScreenTap);
    document.addEventListener("fullscreenchange", updateFullscreenButton);
    $("#btn-shot").addEventListener("click", saveScreenFromOverview);
    $("#btn-open-screen").addEventListener("click", function () {
      switchTab("screen");
    });

    $("#btn-settings").addEventListener("click", openSettings);
    $("#mcp-pill").addEventListener("click", openSettings);
    $("#settings-close").addEventListener("click", closeSettings);
    $("#settings-done").addEventListener("click", closeSettings);
    $("#settings-modal").addEventListener("click", function (event) {
      if (event.target === $("#settings-modal")) closeSettings();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !$("#settings-modal").hidden) closeSettings();
    });
    $("#btn-browse-adb").addEventListener("click", browseAdbPath);
    $("#btn-adb-test").addEventListener("click", testAdbPath);
    $("#btn-adb-save").addEventListener("click", saveAdbPath);
    $("#mcp-toggle").addEventListener("change", onMcpToggleChange);
    $("#btn-copy-mcp").addEventListener("click", async function () {
      await copyText(window.location.origin + state.mcp.endpoint);
      toast("MCP 地址已复制", "success");
    });

    $("#btn-log-start").addEventListener("click", startLog);
    $("#btn-log-stop").addEventListener("click", function () {
      stopLog(false);
    });
    $("#btn-log-pause").addEventListener("click", toggleLogPause);
    $("#btn-log-clear").addEventListener("click", clearLog);
    $("#log-filter").addEventListener("keydown", function (event) {
      if (event.key === "Enter") logFilterChanged();
    });
    $("#log-filter").addEventListener("input", function () {
      if (state.log.timer) window.clearTimeout(state.log.timer);
      state.log.timer = window.setTimeout(logFilterChanged, 350);
    });
    $("#log-level").addEventListener("change", logFilterChanged);
    setLogButtons(false);

    $("#btn-packages").addEventListener("click", loadPackages);
    $("#pkg-third").addEventListener("change", function () {
      if (state.packagesLoaded) loadPackages();
    });
    $("#pkg-filter").addEventListener("input", function () {
      if (!state.packagesLoaded) return;
      if (state.pkgTimer) window.clearTimeout(state.pkgTimer);
      state.pkgTimer = window.setTimeout(loadPackages, 300);
    });
    $("#pkg-list").addEventListener("click", function (event) {
      var button = event.target.closest("button[data-act]");
      if (!button) return;
      runAppAction(button.dataset.act, button.dataset.pkg, button);
    });

    $("#btn-processes").addEventListener("click", loadProcesses);
    $("#process-filter").addEventListener("input", renderProcessRows);

    $("#btn-install").addEventListener("click", installApk);
    $("#btn-shell").addEventListener("click", runShell);
    $("#shell-cmd").addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        runShell();
      }
    });
    loadShellHistory();

    $("#btn-push").addEventListener("click", pushFile);
    $("#btn-pull").addEventListener("click", pullFile);
    $("#btn-pull-refresh").addEventListener("click", refreshPulls);
    initDragAndDrop();

    $$("[data-key]").forEach(function (button) {
      button.addEventListener("click", function () {
        sendKey(button.dataset.key, button);
      });
    });
    $("#btn-tap").addEventListener("click", sendTap);
    $("#btn-swipe").addEventListener("click", sendSwipe);

    $$("[data-reboot]").forEach(function (button) {
      button.addEventListener("click", function () {
        rebootDevice(button.dataset.reboot);
      });
    });

    $("#discovery-list").addEventListener("click", function (event) {
      var button = event.target.closest("button[data-pair-address]");
      if (!button) return;
      openPairForm(button.dataset.pairAddress, button.dataset.pairKind);
    });
  }

  function startPolling() {
    window.setInterval(function () {
      if (document.visibilityState === "visible") loadStatus();
    }, 4000);
    window.setInterval(function () {
      if (document.visibilityState === "visible") loadInfo();
    }, 2000);
  }

  function init() {
    wire();
    loadStatus();
    loadInfo();
    loadMeta();
    loadMcpStatus();
    refreshPulls();
    startPolling();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
