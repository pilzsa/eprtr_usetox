/* lib/data.js — data contract, formatting and derived metrics.
 *
 * The JSON layout is deliberately compact (arrays, not objects).  This module is
 * the only place that knows the column positions, so app.jsx and map.js can work
 * with named fields.
 *
 *   facility: [idx, name, city, cc, country, sector, activity, lon, lat, plot,
 *              lau|null, [18 × all_kg]]
 *   release:  [fac_idx, air_all, water_all, all_kg, air_haz, water_haz, haz_kg,
 *              max_level, max_air, max_water, n_sub, n_haz, n_carc,
 *              n_unassessed, conf, top]
 *   top:      [pollutant_idx, kg, medium (0=air, 1=water), level]
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DashData = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var YEARS = [2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016,
    2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024];
  var DEFAULT_YEAR = 2022;
  // Screen radii in CSS pixels.  Fixed across years so a circle can be compared
  // between the past and the present; shared by the map and the size legend.
  var RADIUS_RANGE = [1.2, 16];

  var MEDIA = [
    { key: "air", label: "Air", short: "air" },
    { key: "water", label: "Water", short: "water" },
    { key: "both", label: "Air + water", short: "both" }
  ];

  var METRICS = [
    { key: "haz", label: "Hazard-classified mass", short: "classified mass", unit: "kg", kind: "mass" },
    { key: "total", label: "Total reported mass (incl. CO₂)", short: "total mass", unit: "kg", kind: "mass" },
    { key: "high", label: "High-hazard pollutants (level ≥ 3)", short: "high-hazard pollutants", unit: "", kind: "count" },
    { key: "carc", label: "Carcinogenic pollutants (IARC / CLP)", short: "carcinogenic pollutants", unit: "", kind: "count" }
  ];

  var LEVELS = [
    { level: 0, name: "Unassessed", desc: "Aggregate indicator, climate gas, or no classification possible." },
    { level: 1, name: "Reported, unclassified", desc: "CAS known, but no hit in the supplied hazard lists." },
    { level: 2, name: "Hazard-listed", desc: "CLP health or environmental classification." },
    { level: 3, name: "High hazard", desc: "IARC 2B, CLP Carc. 2, EPA HAP (air), or WFD priority (water)." },
    { level: 4, name: "Very high hazard", desc: "IARC 2A, CLP Carc. 1B, or ECHA SVHC." },
    { level: 5, name: "Known carcinogen", desc: "IARC 1 or CLP Carc. 1A." }
  ];

  var NUMERIC_RECORD_FIELDS = [
    "air", "water", "all", "airHaz", "waterHaz", "haz", "level",
    "airLevel", "waterLevel", "nSub", "nHaz", "nCarc", "nUnassessed", "conf"
  ];

  function isMissing(value) {
    return value === null || value === undefined || value === "" ||
      (typeof value === "number" && !isFinite(value));
  }

  function toNumber(value) {
    if (typeof value === "number") return value;
    if (isMissing(value)) return NaN;
    return Number(String(value).replace(",", "."));
  }

  function fmtKg(value) {
    var n = toNumber(value);
    if (isMissing(n)) return "—";
    if (n === 0) return "0 kg";
    var abs = Math.abs(n);
    var unit = abs >= 1e9 ? { f: 1e9, s: "Mt" } :
      abs >= 1e6 ? { f: 1e6, s: "kt" } :
      abs >= 1e3 ? { f: 1e3, s: "t" } : { f: 1, s: "kg" };
    var scaled = n / unit.f;
    var digits = Math.abs(scaled) >= 100 ? 0 : (Math.abs(scaled) >= 10 ? 1 : 2);
    return new Intl.NumberFormat("en-GB", {
      maximumFractionDigits: digits, minimumFractionDigits: 0
    }).format(scaled) + " " + unit.s;
  }

  function fmtInt(value) {
    var n = toNumber(value);
    if (isMissing(n)) return "—";
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(n);
  }

  function fmtPop(value) {
    var n = toNumber(value);
    if (isMissing(n) || n <= 0) return "—";
    if (n >= 1e6) return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(n / 1e6) + " M";
    if (n >= 1e3) return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(n / 1e3) + "k";
    return fmtInt(n);
  }

  function fmtKm(value) {
    var n = toNumber(value);
    if (isMissing(n)) return "—";
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(n) + " km";
  }

  function fmtArea(value) {
    var n = toNumber(value);
    if (isMissing(n) || n <= 0) return "—";
    return new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(n) + " km²";
  }

  function metricInfo(key) {
    return METRICS.find(function (m) { return m.key === key; }) || METRICS[0];
  }

  function mediumLabel(key) {
    var m = MEDIA.find(function (item) { return item.key === key; });
    return m ? m.label : key;
  }

  function formatMetric(value, metric) {
    var info = metricInfo(metric);
    if (info.kind === "count") return fmtInt(value);
    return fmtKg(value);
  }

  function levelInfo(level) {
    return LEVELS.find(function (item) { return item.level === Number(level); }) || LEVELS[0];
  }

  function levelClass(level) {
    return "haz-" + Math.max(0, Math.min(5, Number(level) || 0));
  }

  function levelColor(level) {
    return "var(--haz-" + Math.max(0, Math.min(5, Number(level) || 0)) + ")";
  }

  function normaliseText(value) {
    return String(value == null ? "" : value)
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  }

  /* ---- Data normalisation ------------------------------------------------ */

  function n(value) {
    var number = toNumber(value);
    return isMissing(number) ? 0 : number;
  }

  function normaliseRelease(row) {
    if (!row) return null;
    return {
      fac: row[0],
      air: n(row[1]),
      water: n(row[2]),
      all: n(row[3]),
      airHaz: n(row[4]),
      waterHaz: n(row[5]),
      haz: n(row[6]),
      level: n(row[7]),
      airLevel: n(row[8]),
      waterLevel: n(row[9]),
      nSub: n(row[10]),
      nHaz: n(row[11]),
      nCarc: n(row[12]),
      nUnassessed: n(row[13]),
      conf: n(row[14]),
      top: row[15] || []
    };
  }

  function normaliseFacility(row) {
    var plot = !!row[9];
    var lauRow = row[10];
    var lau = Array.isArray(lauRow) ? {
      id: lauRow[0],
      name: lauRow[1] || "",
      cc: lauRow[2] || row[3] || "",
      pop: n(lauRow[3]),
      area: n(lauRow[4])
    } : null;
    var history = (row[11] || []).map(function (value) {
      return value === null || value === undefined ? null : n(value);
    });
    var facility = {
      idx: row[0],
      name: row[1] || "",
      city: row[2] || "",
      cc: row[3] || "",
      country: row[4] || "",
      sector: row[5] || "",
      activity: row[6] || "",
      lon: toNumber(row[7]),
      lat: toNumber(row[8]),
      plot: plot,
      lau: lau,
      history: history,
      x: null,
      y: null,
      search: ""
    };
    facility.search = normaliseText([
      facility.name, facility.city, facility.cc, facility.country,
      facility.sector, lau ? lau.name : ""
    ].join(" "));
    if (plot && typeof Geo3035 !== "undefined" && !isMissing(facility.lon) && !isMissing(facility.lat)) {
      var projected = Geo3035.wgs84ToLaea3035(facility.lon, facility.lat);
      if (projected && isFinite(projected.east) && isFinite(projected.north)) {
        facility.x = projected.east;
        facility.y = projected.north;
      }
    } else if (plot && isFinite(facility.lon) && isFinite(facility.lat)) {
      // Without geo3035 (e.g. a Node smoke test) keep raw coordinates; map.js
      // cannot plot them, but the rest of the module still works.
      facility.x = facility.lon;
      facility.y = facility.lat;
    }
    return facility;
  }

  function normaliseCity(row) {
    var city = {
      id: row[0],
      name: row[1] || "",
      cc: row[2] || "",
      lon: toNumber(row[3]),
      lat: toNumber(row[4]),
      pop: n(row[5]),
      radius: n(row[6]),
      nFacilities: n(row[7]),
      search: ""
    };
    city.search = normaliseText([city.name, city.cc, "city"].join(" "));
    return city;
  }

  function normalisePollutant(row) {
    var levels = row.levels || {};
    return {
      idx: row.i,
      name: row.name,
      cas: row.cas || "",
      category: row.category || "",
      assessable: !!row.assessable,
      indicator: !!row.indicator,
      iarc: row.iarc || "",
      clpCarc: row.clp_carc || "",
      hap: !!row.hap,
      wfd: !!row.wfd,
      svhc: !!row.svhc,
      levelAir: n(levels.air),
      levelWater: n(levels.water),
      flags: row.flags || "",
      note: row.note || ""
    };
  }

  function coreFromJson(facilitiesJson, pollutantsJson, citiesJson) {
    var facilities = facilitiesJson.facilities.map(normaliseFacility);
    var byIdx = new Map();
    facilities.forEach(function (facility) { byIdx.set(facility.idx, facility); });
    return {
      years: facilitiesJson.years || YEARS,
      facilities: facilities,
      byIdx: byIdx,
      pollutants: pollutantsJson.pollutants.map(normalisePollutant),
      cities: citiesJson.cities.map(normaliseCity)
    };
  }

  /* ---- Loading ----------------------------------------------------------- */

  function fetchJson(url) {
    return fetch(url, { cache: "force-cache" }).then(function (response) {
      if (!response.ok) throw new Error("Cannot load " + url + " (HTTP " + response.status + ")");
      return response.json();
    });
  }

  function loadCore(basePath) {
    var base = basePath || "../data";
    return Promise.all([
      fetchJson(base + "/facilities.json"),
      fetchJson(base + "/pollutants.json"),
      fetchJson(base + "/cities.json")
    ]).then(function (results) {
      return coreFromJson(results[0], results[1], results[2]);
    });
  }

  function loadYear(year, basePath) {
    var base = basePath || "../data";
    return fetchJson(base + "/releases/" + year + ".json").then(function (json) {
      return json.records.map(normaliseRelease);
    });
  }

  function indexReleases(records) {
    var index = new Map();
    records.forEach(function (record) { if (record) index.set(record.fac, record); });
    return index;
  }

  /* ---- Metrics ----------------------------------------------------------- */

  function metricValue(record, metric, media) {
    if (!record) return 0;
    var m = media || "both";
    if (metric === "total") {
      return m === "air" ? record.air : (m === "water" ? record.water : record.all);
    }
    if (metric === "haz") {
      return m === "air" ? record.airHaz : (m === "water" ? record.waterHaz : record.haz);
    }
    if (metric === "high") return record.nHaz;
    if (metric === "carc") return record.nCarc;
    return record.haz;
  }

  function hasMedium(record, media) {
    if (!record) return false;
    if (!media || media === "both") return record.all > 0 || record.nSub > 0;
    return media === "air" ? record.air > 0 : record.water > 0;
  }

  function mediumLevel(record, media) {
    if (!record) return 0;
    if (media === "air") return record.airLevel;
    if (media === "water") return record.waterLevel;
    return record.level;
  }

  function passesFilter(record, media, minLevel) {
    if (!record || !hasMedium(record, media)) return false;
    return mediumLevel(record, media) >= (minLevel || 0);
  }

  function topPollutants(record, pollutants, media, limit) {
    if (!record || !record.top) return [];
    var out = [];
    for (var i = 0; i < record.top.length; i += 1) {
      var item = record.top[i];
      var code = item[2];
      if (media === "air" && code !== 0) continue;
      if (media === "water" && code !== 1) continue;
      out.push({
        pollutant: pollutants[item[0]],
        kg: n(item[1]),
        medium: code === 0 ? "air" : "water",
        level: n(item[3])
      });
    }
    out.sort(function (a, b) { return b.kg - a.kg; });
    return out.slice(0, limit || 8);
  }

  /* ---- Derived statistics ------------------------------------------------ */

  function computeStats(options) {
    var facilitiesById = options.facilitiesById;
    var releases = options.releases;
    var metric = options.metric || "haz";
    var media = options.media || "both";
    var minLevel = options.minLevel || 0;
    var levelCounts = [0, 0, 0, 0, 0, 0];
    var countries = {};
    var top = [];
    var total = 0;
    var highSum = 0;
    var count = 0;
    var maxLevel = 0;

    releases.forEach(function (record) {
      if (!passesFilter(record, media, minLevel)) return;
      var value = metricValue(record, metric, media);
      var level = mediumLevel(record, media);
      var facility = facilitiesById.get(record.fac);
      count += 1;
      total += value;
      highSum += record.nHaz;
      levelCounts[Math.max(0, Math.min(5, Math.round(level)))] += 1;
      if (level > maxLevel) maxLevel = level;
      if (facility) {
        var key = facility.cc || "??";
        if (!countries[key]) {
          countries[key] = {
            cc: key, name: facility.country || key, value: 0, facilities: 0
          };
        }
        countries[key].value += value;
        countries[key].facilities += 1;
      }
      top.push({ facility: facility, record: record, value: value });
    });

    top.sort(function (a, b) {
      if (b.value !== a.value) return b.value - a.value;
      return (mediumLevel(b.record, media) - mediumLevel(a.record, media)) ||
        String(a.facility && a.facility.name).localeCompare(String(b.facility && b.facility.name));
    });

    var countryRows = Object.keys(countries).map(function (key) { return countries[key]; });
    countryRows.sort(function (a, b) { return b.value - a.value; });

    return {
      facilities: count,
      total: total,
      highSum: highSum,
      maxLevel: maxLevel,
      levelCounts: levelCounts,
      countries: countryRows,
      top: top,
      topFacilities: top.slice(0, options.limit || 10)
    };
  }

  /* ---- Radius scale ------------------------------------------------------ */

  function quantile(sorted, p) {
    if (!sorted.length) return 0;
    var index = (sorted.length - 1) * p;
    var lower = Math.floor(index);
    var upper = Math.ceil(index);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower);
  }

  function makeRadiusScale(values, range) {
    var positives = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
    var r0 = range[0];
    var r1 = range[1];
    if (!positives.length) {
      return {
        domain: [0, 1], range: [r0, r1],
        radius: function () { return r0; }
      };
    }
    var low = quantile(positives, 0.025);
    var high = quantile(positives, 0.995);
    if (!(high > low)) high = low * 10 || 1;
    return {
      domain: [low, high],
      range: [r0, r1],
      radius: function (value) {
        var v = toNumber(value);
        if (isMissing(v) || v <= 0) return r0;
        var t = (v - low) / (high - low);
        t = Math.max(0, Math.min(1, t));
        return r0 + (r1 - r0) * Math.sqrt(t);
      }
    };
  }

  /** Stable log-domain scale: the same mass gets the same radius in every year. */
  function makeLogRadiusScale(domain, range) {
    var d0 = Math.log(Math.max(domain[0], 1e-9));
    var d1 = Math.log(Math.max(domain[1], domain[0] * 10));
    var r0 = range[0];
    var r1 = range[1];
    return {
      domain: [domain[0], domain[1]],
      range: [r0, r1],
      radius: function (value) {
        var v = toNumber(value);
        if (isMissing(v) || v <= 0) return r0;
        var t = (Math.log(v) - d0) / (d1 - d0);
        t = Math.max(0, Math.min(1, t));
        return r0 + (r1 - r0) * Math.sqrt(t);
      }
    };
  }

  function radiusLegend(scale, metric) {
    var low = scale.domain[0];
    var high = scale.domain[1];
    var mid = Math.sqrt(Math.max(low, 1e-9) * Math.max(high, 1e-9));
    return [low, mid, high].map(function (value) {
      return {
        value: value,
        radius: scale.radius(value),
        label: formatMetric(value, metric)
      };
    });
  }

  /* ---- Search ------------------------------------------------------------ */

  function scoreMatch(text, query) {
    if (!query) return 99;
    if (text === query) return 0;
    if (text.indexOf(query) === 0) return 1;
    if (text.indexOf(" " + query) >= 0) return 2;
    if (text.indexOf(query) >= 0) return 3;
    return 99;
  }

  function matchesAll(text, tokens) {
    for (var i = 0; i < tokens.length; i += 1) {
      if (text.indexOf(tokens[i]) < 0) return false;
    }
    return true;
  }

  function searchAll(query, data, limit) {
    var max = limit || 12;
    var normalized = normaliseText(query);
    if (!normalized) return { query: "", facilities: [], cities: [], total: 0 };
    var tokens = normalized.split(" ");
    var facilities = [];
    var cities = [];

    data.facilities.forEach(function (facility) {
      if (!matchesAll(facility.search, tokens)) return;
      facilities.push({
        item: facility,
        score: scoreMatch(facility.search, normalized) + (facility.plot ? 0 : 8),
        kind: "facility"
      });
    });
    data.cities.forEach(function (city) {
      if (!matchesAll(city.search, tokens)) return;
      cities.push({
        item: city,
        score: scoreMatch(city.search, normalized) + (city.nFacilities ? 0 : 4),
        kind: "city"
      });
    });

    facilities.sort(function (a, b) {
      return a.score - b.score || String(a.item.name).localeCompare(String(b.item.name));
    });
    cities.sort(function (a, b) {
      return a.score - b.score || b.item.pop - a.item.pop;
    });

    return {
      query: normalized,
      facilities: facilities.slice(0, max),
      cities: cities.slice(0, Math.min(6, max)),
      total: facilities.length + cities.length
    };
  }

  /* ---- URL helpers ------------------------------------------------------- */

  function clampYear(year, years) {
    var list = years || YEARS;
    var parsed = parseInt(year, 10);
    if (list.indexOf(parsed) < 0) return null;
    return parsed;
  }

  function hashFor(state) {
    return "#year=" + state.year +
      "&metric=" + state.metric +
      "&media=" + state.media +
      "&level=" + state.minLevel;
  }

  function parseHash(hash) {
    var out = {};
    String(hash || "").replace(/^#/, "").split("&").forEach(function (pair) {
      if (!pair) return;
      var parts = pair.split("=");
      out[decodeURIComponent(parts[0])] = decodeURIComponent(parts.slice(1).join("=") || "");
    });
    return out;
  }

  return {
    YEARS: YEARS,
    DEFAULT_YEAR: DEFAULT_YEAR,
    RADIUS_RANGE: RADIUS_RANGE,
    MEDIA: MEDIA,
    METRICS: METRICS,
    LEVELS: LEVELS,
    isMissing: isMissing,
    toNumber: toNumber,
    fmtKg: fmtKg,
    fmtInt: fmtInt,
    fmtPop: fmtPop,
    fmtKm: fmtKm,
    fmtArea: fmtArea,
    metricInfo: metricInfo,
    mediumLabel: mediumLabel,
    formatMetric: formatMetric,
    levelInfo: levelInfo,
    levelClass: levelClass,
    levelColor: levelColor,
    normaliseText: normaliseText,

    normaliseRelease: normaliseRelease,
    normaliseFacility: normaliseFacility,
    normaliseCity: normaliseCity,
    normalisePollutant: normalisePollutant,
    coreFromJson: coreFromJson,
    loadCore: loadCore,
    loadYear: loadYear,
    indexReleases: indexReleases,

    metricValue: metricValue,
    hasMedium: hasMedium,
    mediumLevel: mediumLevel,
    passesFilter: passesFilter,
    topPollutants: topPollutants,
    computeStats: computeStats,

    quantile: quantile,
    makeRadiusScale: makeRadiusScale,
    makeLogRadiusScale: makeLogRadiusScale,
    radiusLegend: radiusLegend,
    searchAll: searchAll,
    clampYear: clampYear,
    hashFor: hashFor,
    parseHash: parseHash
  };
});
