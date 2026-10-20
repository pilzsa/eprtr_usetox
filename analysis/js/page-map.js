/* analysis/js/page-map.js - the Quarto map shell.
 *
 * Loads exactly the same engine as the React explorer (`lib/map.js`,
 * `lib/data.js`, `lib/geo3035.js`, `lib/topo.js`, d3) from the staged
 * `map/frontend/` directory, so both shells draw the same dots with the same
 * palette and the same radius scale.  No React, no Babel: ~500 KB instead of
 * the 3.4 MB explorer.
 *
 * Query parameters (all optional):
 *   year=2024  metric=haz|total|high|carc  media=air|water|both
 *   level=0|2|3|4|5  dense=1  focus=<facility index>
 */
(function () {
  "use strict";

  var DATA_BASE = "map/data";
  var FILES = [
    "map/frontend/vendor/d3.min.js",
    "map/frontend/lib/geo3035.js",
    "map/frontend/lib/data.js",
    "map/frontend/lib/substances.js",
    "map/frontend/lib/topo.js",
    "map/frontend/lib/map.js"
  ];

  var host = document.getElementById("pm-map");
  var page = document.getElementById("atlas-map-page");
  if (!host || !page) return;

  var D = null;
  var S = null;
  var map = null;
  var core = null;
  var enrichment = null;
  var composition = null;
  var cache = new Map();
  var records = [];
  var selected = null;

  var state = {
    year: null,
    metric: "haz",
    media: "both",
    level: 0,
    dense: false,
    focus: null
  };

  function el(id) { return document.getElementById(id); }

  function fail(message, detail) {
    var box = el("pm-notice");
    if (!box) return;
    box.hidden = false;
    box.innerHTML = "";
    var strong = document.createElement("strong");
    strong.textContent = message;
    box.appendChild(strong);
    if (detail) {
      var p = document.createElement("p");
      p.textContent = detail;
      box.appendChild(p);
    }
    var p2 = document.createElement("p");
    var link = document.createElement("a");
    link.href = "map/frontend/";
    link.textContent = "Open the full explorer instead";
    p2.appendChild(link);
    box.appendChild(p2);
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = src;
      script.async = false;
      script.onload = function () { resolve(); };
      script.onerror = function () { reject(new Error("Cannot load " + src)); };
      document.head.appendChild(script);
    });
  }

  function loadLibraries() {
    return FILES.reduce(function (chain, src) {
      return chain.then(function () { return loadScript(src); });
    }, Promise.resolve());
  }

  function fmtKg(value) { return D ? D.fmtKg(value) : String(value); }
  function fmtInt(value) { return D ? D.fmtInt(value) : String(value); }
  function fmtPop(value) { return D ? D.fmtPop(value) : String(value); }

  /* ---- URL state --------------------------------------------------------- */

  function readUrl() {
    var params = new URLSearchParams(window.location.search);
    var years = D.YEARS;
    var year = D.clampYear(params.get("year"), years);
    state.year = year || (years.length ? years[years.length - 1] : null);
    var metric = params.get("metric");
    state.metric = D.METRICS.some(function (item) { return item.key === metric; }) ? metric : "haz";
    var media = params.get("media");
    state.media = D.MEDIA.some(function (item) { return item.key === media; }) ? media : "both";
    var level = parseInt(params.get("level"), 10);
    state.level = [0, 2, 3, 4, 5].indexOf(level) >= 0 ? level : 0;
    state.dense = params.get("dense") === "1";
    var focus = parseInt(params.get("focus"), 10);
    state.focus = isFinite(focus) ? focus : null;
  }

  function writeUrl() {
    var params = new URLSearchParams();
    params.set("year", state.year);
    params.set("metric", state.metric);
    params.set("media", state.media);
    if (state.level) params.set("level", state.level);
    if (state.dense) params.set("dense", "1");
    if (selected) params.set("focus", selected.idx);
    window.history.replaceState(null, "", window.location.pathname + "?" + params.toString());
  }

  /* ---- Controls ---------------------------------------------------------- */

  function fillControls() {
    var yearSelect = el("pm-year");
    yearSelect.innerHTML = "";
    D.YEARS.forEach(function (year) {
      var option = document.createElement("option");
      option.value = String(year);
      option.textContent = String(year);
      yearSelect.appendChild(option);
    });
    yearSelect.value = String(state.year);

    var metricSelect = el("pm-metric");
    metricSelect.innerHTML = "";
    D.METRICS.forEach(function (metric) {
      var option = document.createElement("option");
      option.value = metric.key;
      option.textContent = metric.label;
      metricSelect.appendChild(option);
    });
    metricSelect.value = state.metric;

    el("pm-media").value = state.media;
    el("pm-level").value = String(state.level);
    el("pm-dense").checked = state.dense;
    el("pm-dense").disabled = !enrichment || !enrichment.population;
  }

  function bindControls() {
    el("pm-year").addEventListener("change", function (event) {
      state.year = parseInt(event.target.value, 10);
      loadYear();
    });
    el("pm-metric").addEventListener("change", function (event) {
      state.metric = event.target.value;
      applyView();
    });
    el("pm-media").addEventListener("change", function (event) {
      state.media = event.target.value;
      applyView();
    });
    el("pm-level").addEventListener("change", function (event) {
      state.level = parseInt(event.target.value, 10);
      applyView();
    });
    el("pm-dense").addEventListener("change", function (event) {
      state.dense = event.target.checked;
      applyView();
    });
    el("pm-zoom-in").addEventListener("click", function () { if (map) map.zoomIn(); });
    el("pm-zoom-out").addEventListener("click", function () { if (map) map.zoomOut(); });
    el("pm-reset").addEventListener("click", function () {
      selected = null;
      state.focus = null;
      if (map) { map.clearFocus(); map.resetZoom(); }
      renderDetail(null);
      applyView();
    });
  }

  /* ---- Data -------------------------------------------------------------- */

  function currentRecords() {
    if (!records.length) return records;
    if (!state.dense || !enrichment || !enrichment.population) return records;
    return records.filter(function (record) {
      var info = D.populationInfo(enrichment, record.fac);
      return info && info.density3 != null && info.density3 >= 1000;
    });
  }

  function applyView() {
    if (!map || !core) return;
    map.setData({ core: core, records: currentRecords(), year: state.year });
    map.setView({
      metric: state.metric,
      media: state.media,
      minLevel: state.level,
      showLau: true,
      selectedId: selected ? selected.idx : null
    });
    writeUrl();
    renderStatus();
    renderComposition();
  }

  function loadYear() {
    if (!core) return;
    setStatus("loading " + state.year + "…");
    var promise = cache.get(state.year);
    if (!promise) {
      promise = D.loadYear(state.year, DATA_BASE);
      cache.set(state.year, promise);
      promise.catch(function () { cache.delete(state.year); });
    }
    promise.then(function (list) {
      records = list;
      applyView();
      focusFromUrl();
    }).catch(function (error) {
      console.error(error);
      fail("The release table for " + state.year + " could not be loaded", error.message);
    });
  }

  function focusFromUrl() {
    if (state.focus === null || state.focusApplied) return;
    state.focusApplied = true;
    var facility = core.byIdx.get(state.focus);
    if (!facility) return;
    selectFacility(facility);
  }

  function selectFacility(facility) {
    if (!facility) return;
    selected = facility;
    renderDetail(facility);
    if (map && facility.plot) map.focusFacility(facility);
    writeUrl();
  }

  /* ---- Detail card ------------------------------------------------------- */

  function addRow(list, label, value) {
    var cell = document.createElement("div");
    cell.className = "detail__cell";
    var dt = document.createElement("dt");
    dt.textContent = label;
    var dd = document.createElement("dd");
    if (value instanceof Node) dd.appendChild(value);
    else dd.textContent = value;
    cell.appendChild(dt);
    cell.appendChild(dd);
    list.appendChild(cell);
  }

  function renderDetail(facility) {
    var box = el("pm-detail");
    if (!box) return;
    box.innerHTML = "";
    if (!facility) {
      var hint = document.createElement("p");
      hint.className = "detail__empty";
      hint.textContent = "Click a circle to see the facility, the people living within 5 km and its IED permit.";
      box.appendChild(hint);
      return;
    }
    var record = null;
    for (var i = 0; i < records.length; i += 1) {
      if (records[i].fac === facility.idx) { record = records[i]; break; }
    }
    var level = record ? D.mediumLevel(record, state.media) : 0;

    var kicker = document.createElement("p");
    kicker.className = "detail__kicker";
    kicker.textContent = "Facility · " + state.year;
    box.appendChild(kicker);

    var title = document.createElement("h3");
    title.className = "detail__name";
    title.textContent = facility.name;
    box.appendChild(title);

    var meta = document.createElement("p");
    meta.className = "detail__meta";
    meta.textContent = [facility.city, facility.country || facility.cc].filter(Boolean).join(", ") +
      (facility.sector ? " · " + facility.sector : "");
    box.appendChild(meta);

    var badges = document.createElement("div");
    badges.className = "detail__badges";
    var badge = document.createElement("span");
    badge.className = "badge badge--haz " + D.levelClass(level);
    badge.style.setProperty("--badge", D.levelColor(level));
    badge.textContent = D.levelInfo(level).name;
    badges.appendChild(badge);
    if (facility.lau) {
      var lauBadge = document.createElement("span");
      lauBadge.className = "badge badge--outline";
      lauBadge.textContent = facility.lau.name;
      badges.appendChild(lauBadge);
    }
    box.appendChild(badges);

    var grid = document.createElement("dl");
    grid.className = "detail__grid";
    if (record) {
      addRow(grid, "Classified mass", fmtKg(record.haz));
      addRow(grid, "Total mass", fmtKg(record.all));
      addRow(grid, "Substances", fmtInt(record.nSub) + " (" + fmtInt(record.nHaz) + " ≥ 3)");
    } else {
      addRow(grid, "Release record", "none in " + state.year);
    }
    box.appendChild(grid);

    if (enrichment) renderEnrichment(box, facility);
  }

  function renderEnrichment(box, facility) {
    var pop = D.populationInfo(enrichment, facility.idx);
    var popTitle = document.createElement("div");
    popTitle.className = "detail__section-title";
    popTitle.textContent = "People living nearby (JRC 2021)";
    box.appendChild(popTitle);
    if (pop && pop.covered) {
      var popGrid = document.createElement("dl");
      popGrid.className = "detail__grid";
      addRow(popGrid, "500 m", fmtPop(pop.p500));
      addRow(popGrid, "1 km", fmtPop(pop.p1));
      addRow(popGrid, "3 km", fmtPop(pop.p3));
      addRow(popGrid, "5 km", fmtPop(pop.p5));
      addRow(popGrid, "Density ≤ 3 km", fmtInt(Math.round(pop.density3)) + " /km²");
      box.appendChild(popGrid);
    } else {
      var note = document.createElement("p");
      note.className = "detail__empty";
      note.textContent = pop ? "Population " + pop.status + " for this location; no estimate is shown."
        : "No population record for this facility.";
      box.appendChild(note);
    }

    var permit = D.permitInfo(enrichment, facility.idx);
    var permitTitle = document.createElement("div");
    permitTitle.className = "detail__section-title";
    permitTitle.textContent = "IED permit";
    box.appendChild(permitTitle);
    if (permit) {
      var permitGrid = document.createElement("dl");
      permitGrid.className = "detail__grid";
      addRow(permitGrid, "Granted", permit.granted || "not reported");
      addRow(permitGrid, "Last update", permit.updated || "not reported");
      addRow(permitGrid, "Reported", permit.firstYear + "–" + permit.lastYear);
      box.appendChild(permitGrid);
      if (permit.url) {
        var p = document.createElement("p");
        p.className = "panel__note";
        var a = document.createElement("a");
        a.href = permit.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.textContent = "Open the permit document ↗";
        p.appendChild(a);
        box.appendChild(p);
      }
    } else {
      var noPermit = document.createElement("p");
      noPermit.className = "detail__empty";
      noPermit.textContent = "No permit record in the EEA IED table (2017–2024).";
      box.appendChild(noPermit);
    }
  }

  /* ---- Status, legend, start-up ------------------------------------------ */

  function setStatus(text) {
    var node = el("pm-status");
    if (node) node.textContent = text;
  }

  function renderStatus() {
    if (!D) return;
    setStatus(D.fmtInt(state.count || 0) + " plotted facilities · " + state.year +
      " · " + D.mediumLabel(state.media).toLowerCase() +
      (state.dense ? " · dense areas only" : ""));
  }

  function renderLegend() {
    var box = el("pm-legend");
    if (!box) return;
    box.innerHTML = "";
    D.LEVELS.forEach(function (info) {
      var row = document.createElement("div");
      row.className = "legend__row";
      var swatch = document.createElement("span");
      swatch.className = "legend__swatch";
      swatch.style.background = D.levelColor(info.level);
      var label = document.createElement("span");
      label.textContent = info.level + " · " + info.name;
      row.appendChild(swatch);
      row.appendChild(label);
      box.appendChild(row);
    });
    var note = document.createElement("p");
    note.className = "panel__note";
    note.textContent = "Circle size follows the selected mass metric; colour is the highest hazard " +
      "level among the substances the facility reported. Hazard is not risk.";
    box.appendChild(note);
  }

  /* The composition block is optional: if substances.json is missing the map
   * keeps working and only this panel says so. */
  function renderComposition() {
    var box = el("pm-composition");
    if (!box) return;
    if (!S || !composition || !core) {
      box.innerHTML = "";
      var note = document.createElement("p");
      note.className = "panel__note";
      note.textContent = "Substance detail (substances.json) is not available on this page.";
      box.appendChild(note);
      return;
    }
    S.render(box, {
      composition: S.composition(composition, core.pollutants, state.year, state.media),
      formatKg: fmtKg,
      levelColor: D.levelColor
    });
    var caption = el("pm-composition-note");
    if (caption) {
      caption.textContent = state.year + " · " + D.mediumLabel(state.media);
    }
  }

  function start() {
    loadLibraries().then(function () {
      D = window.DashData;
      S = window.DashSubstances;
      if (!D || !window.DashMap) throw new Error("map libraries did not expose their globals");
      readUrl();
      var enrich = D.loadEnrichment(DATA_BASE).catch(function () { return null; });
      var detail = S
        ? S.load(DATA_BASE).catch(function (error) {
          console.warn("Substance detail unavailable", error);
          return null;
        })
        : Promise.resolve(null);
      return Promise.all([D.loadCore(DATA_BASE), enrich, detail]);
    }).then(function (results) {
      core = results[0];
      enrichment = results[1];
      composition = results[2];
      fillControls();
      bindControls();
      renderLegend();
      renderDetail(null);
      renderComposition();

      map = window.DashMap.create(host, {
        basePath: DATA_BASE + "/boundaries",
        onSelect: function (facility) {
          selected = facility;
          renderDetail(facility);
          writeUrl();
        },
        onBackgroundClick: function () {
          selected = null;
          renderDetail(null);
          writeUrl();
        },
        onCount: function (count) {
          state.count = count;
          renderStatus();
        },
        onError: function (error) {
          console.error(error);
          fail("The map could not be drawn", error && error.message);
        }
      });

      var resizeTimer = null;
      window.addEventListener("resize", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(function () { if (map) map.resize(); }, 120);
      });

      loadYear();
    }).catch(function (error) {
      console.error(error);
      fail("The map is not available on this page", error && error.message);
    });
  }

  start();
})();
