/* lib/map.js — EPSG:3035 D3 map with countries, LAU outlines and facilities.
 *
 * Data are already projected to EPSG:3035 metres, so no geo projection library
 * is needed: d3.geoIdentity().reflectY(true).fitExtent() simply scales the
 * plane into the SVG and flips the northing axis.  This is the same approach as
 * the Germany POC dashboard and keeps the map fully offline.
 */
(function (root) {
  "use strict";

  var D3 = root.d3;
  var Topo = root.Topo;
  var DashData = root.DashData;

  var MASS_DOMAIN = [1000, 1e9];      // 1 t .. 1 Mt
  var COUNT_DOMAIN = [1, 20];         // 1 .. 20 substances
  function fetchJson(url) {
    return fetch(url, { cache: "force-cache" }).then(function (response) {
      if (!response.ok) throw new Error("Cannot load " + url + " (HTTP " + response.status + ")");
      return response.json();
    });
  }

  function loadBoundaries(base) {
    var countries = fetchJson(base + "/countries.topojson").then(function (topology) {
      return Topo.object(topology, Topo.firstObjectName(topology));
    });
    var lau = fetchJson(base + "/lau/lau3035.topojson").then(function (topology) {
      return Topo.object(topology, Topo.firstObjectName(topology));
    }).catch(function (error) {
      // LAU is an optional underlay; a missing 5 MB file must not break the map.
      if (root.console) console.warn("LAU underlay unavailable:", error);
      return null;
    });
    return Promise.all([countries, lau]).then(function (result) {
      return { countries: result[0], lau: result[1] };
    });
  }

  function create(container, options) {
    var opts = options || {};
    var svg = D3.select(container).append("svg")
      .attr("class", "map__svg")
      .attr("role", "img")
      .attr("aria-label", "Map of industrial pollutant releases in Europe");
    var gZoom = svg.append("g").attr("class", "map__zoom");
    var layer = {
      countries: gZoom.append("g").attr("class", "map__countries-layer"),
      lau: gZoom.append("g").attr("class", "map__lau-layer"),
      focus: gZoom.append("g").attr("class", "map__focus"),
      dots: gZoom.append("g").attr("class", "map__dots")
    };

    var tooltip = D3.select(container).append("div")
      .attr("class", "tooltip")
      .attr("role", "status")
      .style("display", "none");

    var width = 0;
    var height = 0;
    var boundaries = null;
    var core = null;
    var releaseMap = new Map();
    var year = DashData.DEFAULT_YEAR;
    var metric = "haz";
    var media = "both";
    var minLevel = 0;
    var selectedId = null;
    var showLau = true;
    var focus = null;
    var currentTransform = D3.zoomIdentity;
    var readyResolve;
    var ready = new Promise(function (resolve) { readyResolve = resolve; });

    var projection = D3.geoIdentity().reflectY(true);
    var path = D3.geoPath(projection);

    function dimensions() {
      var rect = container.getBoundingClientRect();
      width = Math.max(320, Math.round(rect.width || container.clientWidth || 900));
      height = Math.max(320, Math.round(rect.height || container.clientHeight || 620));
      svg.attr("viewBox", "0 0 " + width + " " + height)
        .attr("width", width)
        .attr("height", height);
    }

    function fitProjection() {
      if (!boundaries || !boundaries.countries) return;
      dimensions();
      var pad = width < 640 ? 6 : 12;
      projection.fitExtent([[pad, pad], [width - pad, height - pad]], boundaries.countries);
      drawBoundaries();
      drawDots();
      drawFocus();
    }

    function drawBoundaries() {
      if (!boundaries) return;
      layer.countries.selectAll("path")
        .data(boundaries.countries ? [boundaries.countries] : [])
        .join("path")
        .attr("class", "map__countries")
        .attr("d", path)
        .attr("vector-effect", "non-scaling-stroke");
      // One path for all 31k LAUs renders far faster than 31k DOM nodes.
      layer.lau.selectAll("path")
        .data(boundaries.lau && showLau ? [boundaries.lau] : [])
        .join("path")
        .attr("class", "map__lau")
        .attr("d", path)
        .attr("vector-effect", "non-scaling-stroke");
    }

    function radiusScale() {
      var kind = DashData.metricInfo(metric).kind;
      var domain = kind === "count" ? COUNT_DOMAIN : MASS_DOMAIN;
      return DashData.makeLogRadiusScale(domain, DashData.RADIUS_RANGE);
    }

    var zoom = D3.zoom()
      .scaleExtent([1, 100])
      .on("zoom", function (event) {
        currentTransform = event.transform;
        gZoom.attr("transform", event.transform);
        // Counter-scale the markers so circles keep their screen size while the
        // map zooms.  One custom property beats rewriting 8k radius attributes
        // on every frame.
        gZoom.style("--dot-inv", 1 / event.transform.k);
      });

    var resizeFrame = null;
    function resize() {
      var previousWidth = width;
      dimensions();
      if (width !== previousWidth || !boundaries) fitProjection();
      else {
        svg.attr("viewBox", "0 0 " + width + " " + height)
          .attr("width", width).attr("height", height);
        drawFocus();
      }
    }

    svg.call(zoom).on("dblclick.zoom", null);
    svg.on("click", function (event) {
      if (event.target === svg.node() && opts.onBackgroundClick) opts.onBackgroundClick();
    });

    var observer = null;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(function () {
        if (resizeFrame) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(resize);
      });
      observer.observe(container);
    } else {
      root.addEventListener("resize", resize);
    }

    loadBoundaries(opts.basePath || "../data/boundaries").then(function (result) {
      boundaries = result;
      fitProjection();
      readyResolve(api);
    }).catch(function (error) {
      readyResolve(null);
      if (root.console) console.error(error);
      if (opts.onError) opts.onError(error);
    });

    function buildRows() {
      if (!core) return [];
      var scale = radiusScale();
      var rows = [];
      releaseMap.forEach(function (record) {
        if (!DashData.passesFilter(record, media, minLevel)) return;
        var facility = core.byIdx.get(record.fac);
        if (!facility || !facility.plot || !isFinite(facility.x) || !isFinite(facility.y)) return;
        var value = DashData.metricValue(record, metric, media);
        if (!(value > 0)) return;
        rows.push({
          id: facility.idx,
          facility: facility,
          record: record,
          value: value,
          level: DashData.mediumLevel(record, media),
          radius: scale.radius(value)
        });
      });
      return rows;
    }

    function drawDots() {
      if (!boundaries || !core) return;
      var rows = buildRows();
      var selection = layer.dots.selectAll("circle.map__dot")
        .data(rows, function (d) { return d.id; });

      selection.exit().remove();

      var enter = selection.enter().append("circle")
        .attr("class", "map__dot")
        .attr("role", "img")
        .on("mouseenter", function (event, d) { showTooltip(event, d); })
        .on("mousemove", function (event) { positionTooltip(event); })
        .on("mouseleave", hideTooltip)
        .on("click", function (event, d) {
          event.stopPropagation();
          if (opts.onSelect) opts.onSelect(d.facility);
        });

      enter.merge(selection)
        .attr("cx", function (d) {
          var point = projection([d.facility.x, d.facility.y]);
          return point ? point[0] : -100;
        })
        .attr("cy", function (d) {
          var point = projection([d.facility.x, d.facility.y]);
          return point ? point[1] : -100;
        })
        .attr("r", function (d) { return d.radius; })
        .attr("class", function (d) {
          return "map__dot " + DashData.levelClass(d.level) +
            (d.id === selectedId ? " is-selected" : "");
        })
        .style("--dot", function (d) { return DashData.levelColor(d.level); })
        .attr("aria-label", function (d) {
          return d.facility.name + ", " + DashData.formatMetric(d.value, metric) +
            ", hazard level " + d.level;
        });
      if (opts.onCount) opts.onCount(rows.length);
    }

    function drawFocus() {
      layer.focus.selectAll("*").remove();
      if (!focus) return;
      var point = projection([focus.x, focus.y]);
      if (!point) return;
      if (focus.radiusKm) {
        var radius = focus.radiusKm * 1000 * projection.scale();
        layer.focus.append("circle")
          .attr("class", "map__radius")
          .attr("cx", point[0]).attr("cy", point[1]).attr("r", radius);
      }
      layer.focus.append("circle")
        .attr("class", "map__radius-dot")
        .attr("cx", point[0]).attr("cy", point[1]).attr("r", 4);
      layer.focus.append("text")
        .attr("class", "map__radius-label")
        .attr("x", point[0] + 8)
        .attr("y", point[1] - 7)
        .text(focus.label || "");
    }

    function showTooltip(event, d) {
      var facility = d.facility;
      var record = d.record;
      var sub = [facility.city, facility.country || facility.cc].filter(Boolean).join(", ");
      tooltip.html(
        '<div class="tooltip__title"></div>' +
        '<div class="tooltip__sub"></div>' +
        '<div class="tooltip__row"><span>' + DashData.metricInfo(metric).label + '</span><b class="tooltip__value"></b></div>' +
        '<div class="tooltip__row"><span>Air / water</span><b class="tooltip__airwater"></b></div>' +
        '<div class="tooltip__row"><span>Hazard class</span><b class="tooltip__level"></b></div>' +
        '<div class="tooltip__hint">Click to pin this facility</div>'
      );
      tooltip.select(".tooltip__title").text(facility.name);
      tooltip.select(".tooltip__sub").text(sub + (facility.sector ? " · " + facility.sector : ""));
      tooltip.select(".tooltip__value").text(DashData.formatMetric(d.value, metric));
      tooltip.select(".tooltip__airwater").text(
        DashData.fmtKg(record.air) + " / " + DashData.fmtKg(record.water)
      );
      tooltip.select(".tooltip__level").text(DashData.levelInfo(d.level).name);
      tooltip.style("display", "block");
      positionTooltip(event);
    }

    function positionTooltip(event) {
      var rect = container.getBoundingClientRect();
      var x = event.clientX - rect.left;
      var y = event.clientY - rect.top;
      var tipNode = tooltip.node();
      var tipWidth = tipNode ? tipNode.offsetWidth : 240;
      var tipHeight = tipNode ? tipNode.offsetHeight : 130;
      var left = x + 14;
      var top = y + 14;
      if (left + tipWidth > width - 8) left = Math.max(8, x - tipWidth - 14);
      if (top + tipHeight > height - 8) top = Math.max(8, y - tipHeight - 14);
      tooltip.style("left", left + "px").style("top", top + "px");
    }

    function hideTooltip() {
      tooltip.style("display", "none");
    }


    function zoomTo(x, y, scale) {
      var point = projection([x, y]);
      if (!point) return;
      var k = Math.max(1, Math.min(100, scale));
      var transform = D3.zoomIdentity
        .translate(width / 2 - point[0] * k, height / 2 - point[1] * k)
        .scale(k);
      svg.transition().duration(650).call(zoom.transform, transform);
    }

    var api = {
      ready: ready,
      setData: function (next) {
        if (next.core) core = next.core;
        if (next.records) releaseMap = DashData.indexReleases(next.records);
        if (next.year) year = next.year;
        drawDots();
      },
      setView: function (view) {
        if (view.metric) metric = view.metric;
        if (view.media) media = view.media;
        if (view.minLevel !== undefined) minLevel = view.minLevel;
        if (view.showLau !== undefined && view.showLau !== showLau) {
          showLau = view.showLau;
          drawBoundaries();
        }
        if (view.selectedId !== undefined) selectedId = view.selectedId;
        drawDots();
      },
      focusFacility: function (facility) {
        if (!facility || !isFinite(facility.x) || !isFinite(facility.y)) return;
        focus = { x: facility.x, y: facility.y, label: facility.city || facility.name };
        drawFocus();
        zoomTo(facility.x, facility.y, Math.max(10, currentTransform.k));
      },
      focusCity: function (city) {
        if (!city || !isFinite(city.lon) || !isFinite(city.lat)) return;
        var point = root.Geo3035.wgs84ToLaea3035(city.lon, city.lat);
        if (!point) return;
        var radiusKm = city.radius > 0 ? city.radius : 2;
        focus = { x: point.east, y: point.north, radiusKm: radiusKm, label: city.name };
        drawFocus();
        var radiusPx = radiusKm * 1000 * projection.scale();
        var zoomLevel = radiusPx > 0
          ? Math.min(30, Math.max(2.5, (Math.min(width, height) * 0.32) / radiusPx))
          : 8;
        zoomTo(point.east, point.north, zoomLevel);
      },
      clearFocus: function () {
        focus = null;
        drawFocus();
      },
      zoomIn: function () {
        svg.transition().duration(250).call(zoom.scaleBy, 1.5);
      },
      zoomOut: function () {
        svg.transition().duration(250).call(zoom.scaleBy, 1 / 1.5);
      },
      resetZoom: function () {
        svg.transition().duration(450).call(zoom.transform, D3.zoomIdentity);
      },
      reset: function () {
        focus = null;
        drawFocus();
        selectedId = null;
        drawDots();
        svg.transition().duration(450).call(zoom.transform, D3.zoomIdentity);
      },
      resize: resize,
      destroy: function () {
        if (observer) observer.disconnect();
        else root.removeEventListener("resize", resize);
        tooltip.remove();
        svg.remove();
      },
      width: function () { return width; },
      height: function () { return height; }
    };

    return api;
  }

  root.DashMap = { create: create, loadBoundaries: loadBoundaries };
})(typeof self !== "undefined" ? self : this);

