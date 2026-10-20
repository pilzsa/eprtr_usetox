/* EPRTR Atlas - substance composition, hazard classifications and the two
 * donut charts.  Loaded by the React explorer (index.html -> app.jsx) and by
 * the native Quarto map page (analysis/js/page-map.js), so both shells render
 * exactly the same markup from the same data.
 *
 * Data: dashboard/data/substances.json
 *   {"years":[2007,...],
 *    "rows":[[year, pollutant_idx, air_kg, water_kg, air_facilities, water_facilities], ...]}
 * Masses are kg_counted from build_dataset.py (CO2 excluding biomass is not
 * counted twice), so the totals equal the map's "total mass" metric.
 *
 * Public API
 *   load(basePath)                    -> Promise<model>
 *   buildIndex(json)                  -> model
 *   composition(model, pollutants, year, media) -> {totalKg, hazKg, rows, ...}
 *   classificationTags(pollutant)     -> [{kind, text, title}]
 *   clpClasses(note)                  -> ["Acute Tox. 3", ...]
 *   basis(pollutant, level)           -> ["IARC Group 1", ...]
 *   render(host, options)             -> draws charts + table, keeps its state
 *   fmtMass(kg), fmtPct(share)
 *
 * A substance is hazardous when the level for the reported medium is >= 2,
 * the same rule as the "classified mass" metric.
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.DashSubstances = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var COLORS = ["#0b7285", "#e0783b", "#bd3f5c", "#6f1d56",
                "#2f9e44", "#4c6ef5", "#b08900", "#5f6b7a"];
  var CLP_PATTERN = /(Acute Tox\.|Skin Corr\.|Skin Irrit\.|Skin Sens\.|Eye Dam\.|Eye Irrit\.|STOT (?:SE|RE)|Carc\.|Muta\.|Repr\.|Resp\. Sens\.|Asp\. Tox\.|Lact\.|Aquatic (?:Acute|Chronic)|Ozone)\s*\d?[A-Z]?(?:\s*\/\s*\d[A-Z]?)?/g;
  var ROWS_BEFORE_MORE = 12;

  function num(value) {
    var n = Number(value);
    return isFinite(n) ? n : 0;
  }

  function txt(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  /* The shells pass the normalised objects from lib/data.js (levelAir,
   * clpCarc); the raw pollutants.json uses levels.air and clp_carc.  Both
   * shapes are accepted so the module can be exercised in Node. */
  function levelOf(pollutant, medium) {
    if (!pollutant) return 0;
    var levels = pollutant.levels || {};
    var value = medium === "air"
      ? (pollutant.levelAir !== undefined ? pollutant.levelAir : levels.air)
      : (pollutant.levelWater !== undefined ? pollutant.levelWater : levels.water);
    return num(value);
  }

  function iarcOf(pollutant) {
    return txt(pollutant && pollutant.iarc);
  }

  function clpCarcOf(pollutant) {
    return txt(pollutant && (pollutant.clpCarc || pollutant.clp_carc));
  }

  function pollutantAt(pollutants, idx) {
    if (!pollutants) return null;
    if (typeof pollutants.get === "function") return pollutants.get(idx) || null;
    var item = pollutants[idx];
    if (item && (item.idx === undefined || Number(item.idx) === Number(idx))) return item;
    for (var i = 0; i < pollutants.length; i += 1) {
      if (Number(pollutants[i].idx) === Number(idx)) return pollutants[i];
    }
    return null;
  }

  function fmtMass(kg) {
    var value = Number(kg);
    if (!isFinite(value)) return "\u2014";
    if (value === 0) return "0 kg";
    var abs = Math.abs(value);
    var units = [[1e9, "Mt"], [1e6, "kt"], [1e3, "t"], [1, "kg"]];
    var factor = 1;
    var unit = "kg";
    for (var i = 0; i < units.length; i += 1) {
      if (abs >= units[i][0]) { factor = units[i][0]; unit = units[i][1]; break; }
    }
    var scaled = value / factor;
    var decimals = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : 2;
    return scaled.toLocaleString("en-GB", {
      minimumFractionDigits: 0,
      maximumFractionDigits: decimals
    }) + " " + unit;
  }

  function fmtExactKg(kg) {
    return Number(kg).toLocaleString("en-GB", { maximumFractionDigits: 3 }) + " kg";
  }

  function fmtPct(share) {
    var value = Number(share);
    if (!isFinite(value) || value <= 0) return "0%";
    var percent = value * 100;
    if (percent < 0.01) return "<0.01%";
    if (percent < 1) return percent.toFixed(2) + "%";
    if (percent < 10) return percent.toFixed(1) + "%";
    return percent.toFixed(0) + "%";
  }

  /* ---------------------------------------------------------------- data */

  function load(basePath) {
    var base = basePath || "../data";
    return fetch(base + "/substances.json", { cache: "force-cache" })
      .then(function (response) {
        if (!response.ok) throw new Error("substances.json: HTTP " + response.status);
        return response.json();
      })
      .then(buildIndex);
  }

  function buildIndex(json) {
    var payload = json || {};
    var index = new Map();
    (payload.rows || []).forEach(function (row) {
      var year = num(row[0]);
      var list = index.get(year);
      if (!list) { list = []; index.set(year, list); }
      list.push({
        p: num(row[1]),
        air: num(row[2]),
        water: num(row[3]),
        airFacilities: num(row[4]),
        waterFacilities: num(row[5])
      });
    });
    var years = (payload.years || Array.from(index.keys())).map(num).sort(function (a, b) {
      return a - b;
    });
    return { years: years, index: index, massBasis: payload.mass_basis || "" };
  }

  function composition(model, pollutants, year, media) {
    var medium = media || "both";
    var entries = (model && model.index.get(Number(year))) || [];
    var rows = [];
    var totalKg = 0;
    var hazKg = 0;
    var levelTotals = [0, 0, 0, 0, 0, 0];

    entries.forEach(function (entry) {
      var pollutant = pollutantAt(pollutants, entry.p);
      if (!pollutant) return;
      var airKg = medium === "water" ? 0 : entry.air;
      var waterKg = medium === "air" ? 0 : entry.water;
      var kg = airKg + waterKg;
      if (!(kg > 0)) return;
      var level = 0;
      if (airKg > 0) level = Math.max(level, levelOf(pollutant, "air"));
      if (waterKg > 0) level = Math.max(level, levelOf(pollutant, "water"));
      level = Math.max(0, Math.min(5, level));
      var hazardous = level >= 2;
      totalKg += kg;
      if (hazardous) hazKg += kg;
      levelTotals[level] += kg;
      rows.push({
        idx: entry.p,
        pollutant: pollutant,
        airKg: airKg,
        waterKg: waterKg,
        kg: kg,
        level: level,
        hazardous: hazardous,
        airFacilities: medium === "water" ? 0 : entry.airFacilities,
        waterFacilities: medium === "air" ? 0 : entry.waterFacilities
      });
    });

    rows.sort(function (a, b) { return b.kg - a.kg || a.idx - b.idx; });
    rows.forEach(function (row) {
      row.share = totalKg > 0 ? row.kg / totalKg : 0;
      row.shareHaz = hazKg > 0 ? row.kg / hazKg : 0;
    });
    var hazardousRows = rows.filter(function (row) { return row.hazardous; });

    return {
      year: Number(year),
      media: medium,
      totalKg: totalKg,
      hazKg: hazKg,
      shareHaz: totalKg > 0 ? hazKg / totalKg : 0,
      levelTotals: levelTotals,
      rows: rows,
      hazardous: hazardousRows,
      nSubstances: rows.length,
      nHazardous: hazardousRows.length
    };
  }



  /* ------------------------------------------------------- classifications */

  function clpClasses(note) {
    var value = txt(note);
    if (!value) return [];
    var matches = value.match(CLP_PATTERN) || [];
    var seen = {};
    var out = [];
    matches.forEach(function (match) {
      var label = match.replace(/\s+/g, " ").replace(/[.;,]+$/, "").trim();
      var key = label.toLowerCase();
      if (!label || seen[key]) return;
      seen[key] = true;
      out.push(label);
    });
    return out.slice(0, 5);
  }

  function classificationTags(pollutant) {
    var tags = [];
    if (!pollutant) return tags;
    var iarc = iarcOf(pollutant);
    var clpCarc = clpCarcOf(pollutant);
    if (iarc) {
      tags.push({
        kind: "iarc",
        text: "IARC Group " + iarc,
        title: "IARC Monographs carcinogenicity group " + iarc
      });
    }
    if (clpCarc) {
      tags.push({
        kind: "clp",
        text: "CLP Carc. " + clpCarc,
        title: "Harmonised CLP classification: carcinogen category " + clpCarc
      });
    }
    if (pollutant.svhc) {
      tags.push({
        kind: "svhc",
        text: "ECHA SVHC",
        title: "On the ECHA candidate list of substances of very high concern"
      });
    }
    if (pollutant.hap) {
      tags.push({
        kind: "hap",
        text: "EPA HAP (air)",
        title: "US EPA hazardous air pollutant; raises the air level to at least 3"
      });
    }
    if (pollutant.wfd) {
      tags.push({
        kind: "wfd",
        text: "WFD priority (water)",
        title: "Water Framework Directive priority substance; raises the water level to at least 3"
      });
    }
    if (!tags.length && !pollutant.assessable) {
      tags.push({
        kind: "none",
        text: "not assessable",
        title: "Aggregate indicator, climate gas or no usable CAS number"
      });
    }
    return tags;
  }

  function basis(pollutant, level) {
    var out = [];
    if (!pollutant) return out;
    var iarc = iarcOf(pollutant);
    var clpCarc = clpCarcOf(pollutant);
    if (level >= 5) {
      if (iarc === "1") out.push("IARC Group 1");
      if (clpCarc === "1A") out.push("CLP Carc. 1A");
    } else if (level === 4) {
      if (iarc === "2A") out.push("IARC Group 2A");
      if (clpCarc === "1B") out.push("CLP Carc. 1B");
      if (pollutant.svhc) out.push("ECHA SVHC");
    } else if (level === 3) {
      if (iarc === "2B") out.push("IARC Group 2B");
      if (clpCarc) out.push("CLP Carc. " + clpCarc);
      if (pollutant.hap) out.push("EPA HAP (air)");
      if (pollutant.wfd) out.push("WFD priority (water)");
    } else if (level === 2) {
      if (iarc) out.push("IARC Group " + iarc);
      if (clpCarc) out.push("CLP Carc. " + clpCarc);
      clpClasses(pollutant.note).forEach(function (name) { out.push("CLP " + name); });
    }
    if (!out.length) {
      if (level === 0) out.push("not assessable: aggregate indicator, climate gas or no CAS");
      else if (level === 1) out.push("CAS known, no hazard-list hit");
      else out.push("listed below level 3");
    }
    return out;
  }

  /* --------------------------------------------------------------- charts */

  function el(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== null && content !== undefined) node.textContent = content;
    return node;
  }

  function svgEl(tag, attributes) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attributes || {}).forEach(function (key) {
      node.setAttribute(key, attributes[key]);
    });
    return node;
  }

  function polar(cx, cy, radius, angle) {
    return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
  }

  function arcPath(cx, cy, rOuter, rInner, start, end) {
    var large = end - start > Math.PI ? 1 : 0;
    var a = polar(cx, cy, rOuter, start);
    var b = polar(cx, cy, rOuter, end);
    var c = polar(cx, cy, rInner, end);
    var d = polar(cx, cy, rInner, start);
    return [
      "M", a[0].toFixed(2), a[1].toFixed(2),
      "A", rOuter, rOuter, "0", large, "1", b[0].toFixed(2), b[1].toFixed(2),
      "L", c[0].toFixed(2), c[1].toFixed(2),
      "A", rInner, rInner, "0", large, "0", d[0].toFixed(2), d[1].toFixed(2),
      "Z"
    ].join(" ");
  }


  /* A single-ring donut.  `slices` are drawn to true proportion: when the
   * hazardous share is tiny the ring really does look uniform, which is the
   * message the numbers next to it state explicitly. */
  function donut(slices, options) {
    var opts = options || {};
    var size = 132;
    var thickness = 20;
    var svg = svgEl("svg", {
      viewBox: "0 0 " + size + " " + size,
      "class": "donut",
      role: "img"
    });
    if (opts.label) {
      var title = svgEl("title");
      title.textContent = opts.label;
      svg.appendChild(title);
    }
    var cx = size / 2;
    var cy = size / 2;
    var rOuter = size / 2 - 2;
    var rInner = rOuter - thickness;
    var total = slices.reduce(function (sum, slice) {
      return sum + Math.max(0, num(slice.value));
    }, 0);

    if (!(total > 0)) {
      svg.appendChild(svgEl("circle", {
        cx: cx, cy: cy, r: (rOuter + rInner) / 2,
        fill: "none", "stroke-width": thickness, "class": "donut__empty"
      }));
      return svg;
    }

    var angle = -Math.PI / 2;
    slices.forEach(function (slice) {
      var value = Math.max(0, num(slice.value));
      if (!(value > 0)) return;
      var sweep = (value / total) * Math.PI * 2;
      var shape;
      if (sweep >= Math.PI * 2 - 1e-6) {
        shape = svgEl("circle", {
          cx: cx, cy: cy, r: (rOuter + rInner) / 2,
          fill: "none", "stroke-width": thickness
        });
        shape.style.stroke = slice.color;
      } else {
        shape = svgEl("path", { d: arcPath(cx, cy, rOuter, rInner, angle, angle + sweep) });
        shape.style.fill = slice.color;
      }
      shape.setAttribute("class", "donut__slice");
      var tip = svgEl("title");
      tip.textContent = slice.label + ": " + fmtMass(value) + " (" + fmtPct(value / total) + ")";
      shape.appendChild(tip);
      svg.appendChild(shape);
      angle += sweep;
    });

    if (opts.center) {
      var main = svgEl("text", {
        x: cx, y: cy + 1, "text-anchor": "middle", "class": "donut__center"
      });
      main.textContent = opts.center;
      svg.appendChild(main);
    }
    if (opts.sub) {
      var sub = svgEl("text", {
        x: cx, y: cy + 13, "text-anchor": "middle", "class": "donut__sub"
      });
      sub.textContent = opts.sub;
      svg.appendChild(sub);
    }
    return svg;
  }



  function legend(items) {
    var list = el("ul", "donut-legend");
    items.forEach(function (item) {
      var row = el("li", "donut-legend__row");
      var swatch = el("span", "donut-legend__swatch");
      swatch.style.background = item.color;
      var label = el("span", "donut-legend__label", item.label);
      label.title = item.title || item.label;
      var value = el("span", "donut-legend__value", item.value);
      value.title = item.valueTitle || item.value;
      row.appendChild(swatch);
      row.appendChild(label);
      row.appendChild(value);
      list.appendChild(row);
    });
    return list;
  }

  function donutCard(caption, bodyNode, note) {
    var card = el("figure", "donut-card");
    card.appendChild(el("figcaption", "donut-card__title", caption));
    card.appendChild(bodyNode);
    if (note) card.appendChild(el("p", "donut-card__note", note));
    return card;
  }

  function chartColumn(model, fmtKg) {
    var column = el("div", "composition__charts");
    var hazKg = model.hazKg;
    var restKg = Math.max(0, model.totalKg - hazKg);
    var totalSlices = [
      { label: "Hazard-classified (level \u2265 2)", value: hazKg, color: "var(--haz-3)" },
      { label: "Non-hazardous (level 0\u20131)", value: restKg, color: "var(--haz-1)" }
    ];

    var bodyA = el("div", "donut-card__body");
    bodyA.appendChild(donut(totalSlices, {
      label: "Reported mass in " + model.year + ": " + fmtMass(model.totalKg) +
        ", of which " + fmtMass(hazKg) + " is hazard-classified",
      center: fmtPct(model.shareHaz),
      sub: "hazardous"
    }));
    bodyA.appendChild(legend(totalSlices.map(function (slice) {
      return {
        label: slice.label,
        color: slice.color,
        value: fmtKg(slice.value),
        valueTitle: fmtExactKg(slice.value) + " \u00b7 " +
          fmtPct(slice.value / model.totalKg) + " of the reported mass",
        title: slice.label + ": " + fmtPct(slice.value / model.totalKg)
      };
    })));

    column.appendChild(donutCard(
      "All reported mass vs hazardous",
      bodyA,
      "Every reported kilogram is included, CO\u2082 and other non-assessable labels too."
    ));

    var top = model.hazardous.slice(0, 7);
    var otherKg = model.hazardous.slice(7).reduce(function (sum, row) {
      return sum + row.kg;
    }, 0);
    var slices = top.map(function (row, index) {
      return {
        label: row.pollutant.name,
        value: row.kg,
        color: COLORS[index % COLORS.length],
        level: row.level
      };
    });
    if (otherKg > 0) {
      slices.push({
        label: "Other hazardous (" + (model.hazardous.length - top.length) + ")",
        value: otherKg,
        color: COLORS[COLORS.length - 1]
      });
    }

    var bodyB = el("div", "donut-card__body");
    if (slices.length) {
      bodyB.appendChild(donut(slices, {
        label: "Hazard-classified mass in " + model.year + " by substance",
        center: fmtKg(hazKg),
        sub: "classified"
      }));
      bodyB.appendChild(legend(slices.map(function (slice) {
        return {
          label: slice.label,
          color: slice.color,
          value: fmtKg(slice.value),
          title: slice.label + (slice.level ? " \u00b7 level " + slice.level : "") +
            ": " + fmtPct(slice.value / hazKg) + " of the classified mass",
          valueTitle: fmtExactKg(slice.value) + " \u00b7 " +
            fmtPct(slice.value / hazKg) + " of the classified mass"
        };
      })));
    } else {
      bodyB.appendChild(el("p", "detail__empty",
        "No hazard-classified mass is reported for this selection."));
    }

    column.appendChild(donutCard(
      "Hazard-classified substances by mass",
      bodyB,
      "Top seven substances plus the remainder; exact values and classifications below."
    ));
    return column;
  }

  /* ---------------------------------------------------------------- table */

  function subtitle(row, view, fmtKg) {
    var pollutant = row.pollutant;
    var parts = [];
    if (pollutant.cas) parts.push("CAS " + pollutant.cas);
    parts.push(fmtPct(view === "haz" ? row.shareHaz : row.share) +
      (view === "haz" ? " of classified" : " of total"));
    if (row.airKg > 0) parts.push("air " + fmtKg(row.airKg));
    if (row.waterKg > 0) parts.push("water " + fmtKg(row.waterKg));
    if (row.airKg > 0 && row.waterKg > 0 &&
        levelOf(pollutant, "air") !== levelOf(pollutant, "water")) {
      parts.push("level " + levelOf(pollutant, "air") + " air / " +
        levelOf(pollutant, "water") + " water");
    }
    return parts.join(" \u00b7 ");
  }

  function tagChip(tag) {
    var chip = el("span", "chip chip--" + tag.kind, tag.text);
    chip.title = tag.title || tag.text;
    return chip;
  }

  /* A note such as "CLP Acute Tox. 3, Skin Corr. 1B." only repeats the chips
   * above it; keep notes that add a detail (route, "not carcinogenic", ...). */
  function noteAddsDetail(note) {
    var rest = txt(note).replace(CLP_PATTERN, " ");
    rest = rest.replace(/\bCLP\b/gi, " ")
      .replace(/\bIARC\s*(?:Group\s*)?\d[A-Z]?\b/gi, " ")
      .replace(/[\s,;:.()\/]+/g, " ")
      .replace(/\b(?:and|or)\b/gi, " ")
      .trim();
    return rest.length > 0;
  }

  function substanceRow(row, view, fmtKg, levelColor) {
    var pollutant = row.pollutant;
    var node = el("article", "substance");
    node.style.setProperty("--pip", levelColor(row.level));

    var top = el("div", "substance__top");
    top.appendChild(el("span", "level-pip"));
    var name = el("span", "substance__name", pollutant.name);
    name.title = pollutant.name + (pollutant.category ? " \u00b7 " + pollutant.category : "");
    top.appendChild(name);
    var mass = el("span", "substance__mass", fmtKg(row.kg));
    mass.title = fmtExactKg(row.kg);
    top.appendChild(mass);
    node.appendChild(top);

    node.appendChild(el("div", "substance__meta", subtitle(row, view, fmtKg)));

    var tags = classificationTags(pollutant);
    var seen = tags.map(function (tag) { return tag.text.toLowerCase(); });
    clpClasses(pollutant.note).forEach(function (classText) {
      var label = "CLP " + classText;
      if (tags.some(function (tag) { return tag.text.indexOf(classText) >= 0; })) return;
      if (seen.indexOf(label.toLowerCase()) >= 0) return;
      seen.push(label.toLowerCase());
      tags.push({
        kind: "clp",
        text: label,
        title: "Harmonised CLP classification: " + classText
      });
    });
    if (tags.length) {
      var tagBox = el("div", "substance__tags");
      tags.slice(0, 6).forEach(function (tag) { tagBox.appendChild(tagChip(tag)); });
      if (tags.length > 6) {
        var more = el("span", "chip", "+" + (tags.length - 6));
        more.title = tags.slice(6).map(function (tag) { return tag.text; }).join(", ");
        tagBox.appendChild(more);
      }
      node.appendChild(tagBox);
    }

    var why = el("div", "substance__basis");
    why.appendChild(el("strong", null, "Level " + row.level));
    why.appendChild(document.createTextNode(" \u00b7 " + basis(pollutant, row.level).join(" + ")));
    if (row.level === 2 && iarcOf(pollutant) === "3") {
      why.title = "IARC Group 3 is not classifiable as carcinogenic to humans; " +
        "it still counts as a hazard-listed substance (level 2).";
    }
    node.appendChild(why);

    if (pollutant.note && noteAddsDetail(pollutant.note)) {
      var note = el("p", "substance__note", pollutant.note);
      note.title = pollutant.note;
      node.appendChild(note);
    }
    return node;
  }

  function tableSection(model, state, host, fmtKg, levelColor) {
    var section = el("div", "composition__table");
    var head = el("div", "composition__head");
    var toggle = el("div", "comp-toggle");
    toggle.setAttribute("role", "group");
    toggle.setAttribute("aria-label", "Substance table filter");
    [["all", "All reported mass (" + model.nSubstances + ")"],
     ["haz", "Hazard-classified (" + model.nHazardous + ")"]].forEach(function (pair) {
      var button = el("button", null, pair[1]);
      button.type = "button";
      button.setAttribute("aria-pressed", state.view === pair[0] ? "true" : "false");
      button.addEventListener("click", function () {
        if (state.view === pair[0]) return;
        state.view = pair[0];
        state.expanded = false;
        render(host, host.__compositionOptions);
      });
      toggle.appendChild(button);
    });
    head.appendChild(toggle);
    head.appendChild(el("span", "composition__summary",
      fmtMass(model.totalKg) + " reported \u00b7 " + fmtMass(model.hazKg) +
      " classified (" + fmtPct(model.shareHaz) + ")"));
    section.appendChild(head);

    var rows = state.view === "haz" ? model.hazardous : model.rows;
    if (!rows.length) {
      section.appendChild(el("p", "detail__empty", "No reported mass for this selection."));
      return section;
    }

    var visible = state.expanded ? rows : rows.slice(0, ROWS_BEFORE_MORE);
    var list = el("div", "substance-list");
    visible.forEach(function (row) {
      list.appendChild(substanceRow(row, state.view, fmtKg, levelColor));
    });
    section.appendChild(list);

    if (rows.length > ROWS_BEFORE_MORE) {
      var more = el("button", "comp-more",
        state.expanded ? "Show fewer" : "Show all " + rows.length + " substances");
      more.type = "button";
      more.addEventListener("click", function () {
        state.expanded = !state.expanded;
        render(host, host.__compositionOptions);
      });
      section.appendChild(more);
    }

    section.appendChild(el("p", "composition__note",
      state.view === "haz"
        ? "Ranked by reported mass. Level 2 means a CLP health or environmental " +
          "classification; levels 3\u20135 add an IARC group, a CLP carcinogen " +
          "category, the ECHA SVHC list, the EPA HAP list (air) or the WFD " +
          "priority list (water)."
        : "Ranked by total reported mass, including CO\u2082 and other labels that " +
          "cannot be hazard-classified. Switch to the second view for the " +
          "classified subset."));
    return section;
  }

  /* --------------------------------------------------------------- render */

  function render(host, options) {
    var opts = options || {};
    if (!host) return;
    host.__compositionOptions = opts;
    var state = host.__compositionState ||
      (host.__compositionState = { view: "all", expanded: false });
    var model = opts.composition;

    host.textContent = "";
    if (!model) {
      host.appendChild(el("p", "detail__empty",
        opts.emptyText || "No substance detail for this selection."));
      return;
    }
    var fmtKg = opts.formatKg || fmtMass;
    var levelColor = opts.levelColor || function (level) {
      return "var(--haz-" + level + ")";
    };

    var wrap = el("div", "composition");
    wrap.appendChild(chartColumn(model, fmtKg));
    wrap.appendChild(tableSection(model, state, host, fmtKg, levelColor));
    host.appendChild(wrap);
  }

  return {
    load: load,
    buildIndex: buildIndex,
    composition: composition,
    classificationTags: classificationTags,
    clpClasses: clpClasses,
    basis: basis,
    donut: donut,
    render: render,
    fmtMass: fmtMass,
    fmtPct: fmtPct
  };
});
