/* app.jsx — React shell for the EPRTR Atlas.
 *
 * Compiled in the browser by Babel (see index.html).  All data access goes
 * through lib/data.js, all map drawing through lib/map.js.
 */
const { useState, useEffect, useMemo, useRef } = React;
const D = window.DashData;
const DATA_BASE = "../data";

const METRIC_OPTIONS = D.METRICS.map((metric) => ({ value: metric.key, label: metric.label }));
const MEDIA_OPTIONS = D.MEDIA.map((media) => ({ value: media.key, label: media.label }));
const LEVEL_OPTIONS = [
  { value: 0, label: "All" },
  { value: 2, label: "≥ 2" },
  { value: 3, label: "≥ 3" },
  { value: 4, label: "≥ 4" },
  { value: 5, label: "5" }
];

function Icon(props) {
  const size = props.size || 18;
  const common = {
    width: size, height: size, viewBox: "0 0 24 24", fill: "none",
    stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round",
    strokeLinejoin: "round", "aria-hidden": "true", focusable: "false"
  };
  let body;
  switch (props.name) {
    case "search":
      body = <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.6-3.6" /></>;
      break;
    case "close":
      body = <path d="M6 6l12 12M18 6 6 18" />;
      break;
    case "help":
      body = <><circle cx="12" cy="12" r="9" /><path d="M9.4 9a2.7 2.7 0 0 1 5.2.8c0 1.8-2.6 2.1-2.6 4" /><path d="M12 17h.01" /></>;
      break;
    case "play":
      body = <path d="M8 5.5v13l10.5-6.5L8 5.5Z" fill="currentColor" stroke="none" />;
      break;
    case "pause":
      body = <><path d="M8 5h3v14H8zM13 5h3v14h-3z" fill="currentColor" stroke="none" /></>;
      break;
    case "plus":
      body = <path d="M12 5v14M5 12h14" />;
      break;
    case "minus":
      body = <path d="M5 12h14" />;
      break;
    case "reset":
      body = <><path d="M4 10a8 8 0 1 1 2.3 7" /><path d="M4 5v5h5" /></>;
      break;
    case "pin":
      body = <><path d="M12 21s6-5.1 6-10a6 6 0 1 0-12 0c0 4.9 6 10 6 10Z" /><circle cx="12" cy="11" r="2.2" /></>;
      break;
    case "city":
      body = <><path d="M4 21V8l5-3v16M9 21V5l6 3v13M15 21V11l5 2v8" /><path d="M2 21h20" /></>;
      break;
    case "factory":
      body = <><path d="M3 21V9l5 3V9l5 3V4h4v17H3Z" /><path d="M2 21h20M7 17h.01M11 17h.01M15 17h.01" /></>;
      break;
    case "arrow":
      body = <path d="M5 12h14M13 6l6 6-6 6" />;
      break;
    default:
      body = null;
  }
  return <svg {...common}>{body}</svg>;
}

function Segmented(props) {
  return (
    <div className={"segmented " + (props.className || "")} role="group" aria-label={props.ariaLabel}>
      {props.options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="segmented__btn"
          aria-pressed={props.value === option.value}
          onClick={() => props.onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function levelBadge(level) {
  const info = D.levelInfo(level);
  return (
    <span className={"badge badge--haz " + D.levelClass(level)} style={{ "--badge": D.levelColor(level) }}>
      {info.name}
    </span>
  );
}

function Sparkline(props) {
  const values = props.values || [];
  const width = 300;
  const height = 56;
  const pad = 4;
  const known = values.filter((value) => value !== null && value !== undefined && value > 0);
  const max = known.length ? Math.max(...known) : 1;
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
  const y = (value) => height - pad - (value / max) * (height - pad * 2);
  let line = "";
  let started = false;
  values.forEach((value, index) => {
    if (value === null || value === undefined) {
      started = false;
      return;
    }
    const x = pad + index * step;
    line += (started ? "L" : "M") + x.toFixed(1) + " " + y(value).toFixed(1) + " ";
    started = true;
  });
  const highlightIndex = (props.years || []).indexOf(props.highlightYear);
  const highlightValue = highlightIndex >= 0 ? values[highlightIndex] : null;

  return (
    <svg className="sparkline" viewBox={"0 0 " + width + " " + height} preserveAspectRatio="none" role="img"
      aria-label="Reported total release mass by year">
      <path className="sparkline__area" d={line + "L" + (width - pad) + " " + (height - pad) + " L" + pad + " " + (height - pad) + " Z"} />
      <path className="sparkline__path" d={line} />
      <line className="sparkline__axis" x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} />
      {highlightValue !== null && highlightValue !== undefined && (
        <circle className="sparkline__dot" cx={pad + highlightIndex * step} cy={y(highlightValue)} r="3" />
      )}
      <text className="sparkline__label" x={pad} y={height - 1}>{props.years[0]}</text>
      <text className="sparkline__label" x={width - pad} y={height - 1} textAnchor="end">{props.years[props.years.length - 1]}</text>
    </svg>
  );
}

function SearchBox(props) {
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(-1);
  const results = useMemo(() => {
    if (!props.core) return { facilities: [], cities: [], total: 0 };
    const found = D.searchAll(props.query, props.core, 9);
    // Keep the relevance order from searchAll, but put facilities that actually
    // report in the selected year first: a dead end is a poor first hit.
    found.facilities.sort((a, b) =>
      Number(!!props.recordMap.get(b.item.idx)) - Number(!!props.recordMap.get(a.item.idx))
    );
    return found;
  }, [props.query, props.core, props.recordMap]);
  const flat = results.facilities.concat(results.cities);
  useEffect(() => { setActive(-1); }, [props.query]);

  function choose(entry) {
    if (!entry) return;
    if (entry.kind === "facility") props.onFacility(entry.item);
    else props.onCity(entry.item);
    setFocused(false);
  }

  function onKeyDown(event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(flat.length - 1, index + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      choose(flat[active] || flat[0]);
    } else if (event.key === "Escape") {
      setFocused(false);
      props.onClear();
    }
  }

  const show = focused && props.query.trim().length > 0;

  return (
    <div className="search">
      <span className="search__icon"><Icon name="search" size={16} /></span>
      <input
        ref={props.inputRef}
        className="search__input"
        type="search"
        value={props.query}
        placeholder="Search city, facility or country…"
        aria-label="Search city, facility or country"
        aria-expanded={show}
        aria-controls="search-results"
        autoComplete="off"
        onChange={(event) => props.onQuery(event.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => window.setTimeout(() => setFocused(false), 120)}
        onKeyDown={onKeyDown}
      />
      {props.query && (
        <button type="button" className="search__clear" aria-label="Clear search"
          onMouseDown={(event) => event.preventDefault()} onClick={props.onClear}>
          <Icon name="close" size={14} />
        </button>
      )}
      {show && (
        <div className="search__results" id="search-results">
          {results.facilities.length > 0 && <div className="search__group">Facilities</div>}
          {results.facilities.map((entry, index) => {
            const record = props.recordMap.get(entry.item.idx);
            return (
              <button type="button" key={"f" + entry.item.idx}
                className="search__result"
                style={active === index ? { background: "var(--surface-3)" } : null}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(entry)}>
                <span className="search__result-mark"><Icon name="factory" size={16} /></span>
                <span>
                  <span className="search__result-name">{entry.item.name}</span>
                  <span className="search__result-sub">{entry.item.city} · {entry.item.cc} · {entry.item.sector}</span>
                </span>
                <span className="search__result-meta">
                  {record ? D.formatMetric(D.metricValue(record, props.metric, props.media), props.metric) : "no report"}
                </span>
              </button>
            );
          })}
          {results.cities.length > 0 && <div className="search__group">Cities / LAU</div>}
          {results.cities.map((entry, index) => {
            const flatIndex = results.facilities.length + index;
            return (
              <button type="button" key={"c" + entry.item.id}
                className="search__result"
                style={active === flatIndex ? { background: "var(--surface-3)" } : null}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(entry)}>
                <span className="search__result-mark"><Icon name="city" size={16} /></span>
                <span>
                  <span className="search__result-name">{entry.item.name}</span>
                  <span className="search__result-sub">{entry.item.cc} · {entry.item.nFacilities} facilities</span>
                </span>
                <span className="search__result-meta">{D.fmtPop(entry.item.pop)}</span>
              </button>
            );
          })}
          {flat.length === 0 && <div className="search__empty">No city, facility or country matches “{props.query}”.</div>}
          {results.total > flat.length && (
            <div className="search__empty">{results.total - flat.length} more results — refine the search.</div>
          )}
        </div>
      )}
    </div>
  );
}


function FacilityRow(props) {
  const record = props.record;
  const value = record ? D.metricValue(record, props.metric, props.media) : 0;
  const level = record ? D.mediumLevel(record, props.media) : 0;
  return (
    <button type="button" className="facility-row" onClick={props.onClick}>
      {props.rank !== undefined && <span className="facility-row__rank">{props.rank}</span>}
      <span className="facility-row__body">
        <span className="facility-row__name">{props.facility.name}</span>
        <span className="facility-row__meta">{props.facility.city} · {props.facility.cc}</span>
      </span>
      <span className="facility-row__value">
        {record ? D.formatMetric(value, props.metric) : "no report"}
        <span className="level-pip" style={{ "--pip": D.levelColor(level) }} title={D.levelInfo(level).name}></span>
      </span>
    </button>
  );
}

function FacilityList(props) {
  if (!props.rows.length) {
    return <p className="detail__empty">No facility matches the current filters in {props.year}.</p>;
  }
  return (
    <div className="facility-list">
      {props.rows.map((row, index) => (
        <FacilityRow
          key={row.facility.idx}
          rank={index + 1}
          facility={row.facility}
          record={row.record}
          metric={props.metric}
          media={props.media}
          onClick={() => props.onSelect(row.facility)}
        />
      ))}
    </div>
  );
}

function Legend(props) {
  const stats = props.stats;
  const levels = D.LEVELS.filter((level) => level.level === 0 || level.level >= 2 || stats.levelCounts[level.level] > 0);
  return (
    <div>
      <div className="legend">
        {levels.map((level) => (
          <div className="legend__row" key={level.level}>
            <span className="legend__swatch" style={{ background: D.levelColor(level.level) }}></span>
            <span>
              <span className="legend__name">{level.name}</span>
              <span className="legend__count">{D.fmtInt(stats.levelCounts[level.level])}</span>
              <span className="legend__desc">{level.desc}</span>
            </span>
          </div>
        ))}
      </div>
      <div className="size-legend" aria-label="Circle size legend">
        {props.sizeLegend.map((entry, index) => (
          <div className="size-legend__item" key={index}>
            <span className="size-legend__circle" style={{
              width: Math.max(6, entry.radius * 2) + "px",
              height: Math.max(6, entry.radius * 2) + "px"
            }}></span>
            <span className="size-legend__label">{entry.label}</span>
          </div>
        ))}
      </div>
      <p className="panel__note">Circle area is log-scaled: the same mass gets the same radius in every year. Colour = worst hazard class of the substances reported by the facility.</p>
    </div>
  );
}

function CountryList(props) {
  const rows = props.rows.slice(0, 9);
  if (!rows.length) return <p className="detail__empty">No country data for this selection.</p>;
  const max = Math.max(...rows.map((row) => row.value), 1);
  return (
    <div className="country-list">
      {rows.map((row) => (
        <div className="country-row" key={row.cc}
          title={row.name + ": " + D.formatMetric(row.value, props.metric) + " from " + row.facilities + " facilities"}>
          <span className="country-row__name">{row.name || row.cc}</span>
          <span className="country-row__bar">
            <span className="country-row__fill" style={{ width: Math.max(2, (row.value / max) * 100) + "%" }}></span>
          </span>
          <span className="country-row__value">{D.formatMetric(row.value, props.metric)}</span>
        </div>
      ))}
    </div>
  );
}


function FacilityDetail(props) {
  const facility = props.facility;
  const record = props.record;
  const top = record ? D.topPollutants(record, props.core.pollutants, props.media, 7) : [];
  const level = record ? D.mediumLevel(record, props.media) : 0;
  return (
    <section className="panel" aria-labelledby="detail-title">
      <div className="panel__head">
        <h2 className="panel__title" id="detail-title">Facility detail</h2>
        <button type="button" className="btn btn--ghost btn--icon" aria-label="Close facility detail" onClick={props.onClose}>
          <Icon name="close" size={16} />
        </button>
      </div>
      <div className="panel__body">
        <p className="detail__kicker">Facility · {props.year}</p>
        <h3 className="detail__name">{facility.name}</h3>
        <p className="detail__meta">
          {[facility.city, facility.country || facility.cc].filter(Boolean).join(", ")}<br />
          {facility.sector}{facility.activity ? " · activity " + facility.activity : ""}
        </p>
        <div className="detail__badges">
          {record && levelBadge(level)}
          {facility.lau && <span className="badge badge--outline"><Icon name="pin" size={12} />{facility.lau.name}</span>}
          {!facility.plot && <span className="badge badge--outline">No plotted coordinates</span>}
          {record && record.conf > 0 && <span className="badge badge--outline">Confidential component</span>}
          {record && record.nUnassessed > 0 && <span className="badge badge--outline">{record.nUnassessed} unassessed group(s)</span>}
        </div>

        {!record && <p className="detail__empty">No release record for this facility in {props.year}.</p>}

        {record && (
          <>
            <dl className="detail__grid">
              <div className="detail__cell"><dt>Classified mass</dt><dd>{D.fmtKg(record.haz)}</dd></div>
              <div className="detail__cell"><dt>Total mass</dt><dd>{D.fmtKg(record.all)}</dd></div>
              <div className="detail__cell"><dt>Air / water</dt><dd>{D.fmtKg(record.air)} / {D.fmtKg(record.water)}</dd></div>
              <div className="detail__cell"><dt>Substances</dt><dd>{D.fmtInt(record.nSub)} <span className="detail__muted">({D.fmtInt(record.nHaz)} ≥ 3)</span></dd></div>
            </dl>

            <div className="detail__section">
              <div className="detail__section-title">Largest reported substances</div>
              {top.length === 0 && <p className="detail__empty">No substance-level breakdown for this selection.</p>}
              {top.map((item, index) => (
                <div className="chemical" key={index}>
                  <span className="chemical__name" title={item.pollutant ? item.pollutant.name : ""}>
                    {item.pollutant ? item.pollutant.name : "Unknown"}
                  </span>
                  <span className="chemical__medium">{item.medium}</span>
                  <span className="level-pip" style={{ "--pip": D.levelColor(item.level) }} title={D.levelInfo(item.level).name}></span>
                  <span className="chemical__mass">{D.fmtKg(item.kg)}</span>
                </div>
              ))}
            </div>
          </>
        )}

        <div className="detail__section">
          <div className="detail__section-title">Reported mass over time</div>
          <Sparkline values={facility.history} years={props.core.years} highlightYear={props.year} />
          <p className="panel__note">All reported media, including CO₂ and other unclassified masses.</p>
        </div>

        <div className="place__actions">
          <button type="button" className="btn btn--primary" onClick={() => props.onZoom(facility)} disabled={!facility.plot}>
            <Icon name="pin" size={15} /> Zoom to facility
          </button>
          {facility.lau && (
            <button type="button" className="btn" onClick={() => props.onCity(facility.lau)}>City</button>
          )}
        </div>
      </div>
    </section>
  );
}


function CityDetail(props) {
  const city = props.city;
  const rows = props.rows;
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const maxLevel = rows.reduce((max, row) => Math.max(max, D.mediumLevel(row.record, props.media)), 0);
  return (
    <section className="panel" aria-labelledby="city-title">
      <div className="panel__head">
        <h2 className="panel__title" id="city-title">City / LAU detail</h2>
        <button type="button" className="btn btn--ghost btn--icon" aria-label="Close city detail" onClick={props.onClose}>
          <Icon name="close" size={16} />
        </button>
      </div>
      <div className="panel__body">
        <p className="detail__kicker">City · {props.year}</p>
        <h3 className="detail__name">{city.name}</h3>
        <p className="detail__meta">{city.cc} · {D.fmtPop(city.pop)} inhabitants · equivalent radius {D.fmtKm(city.radius)}</p>
        <div className="detail__badges">
          <span className="badge badge--outline">{city.nFacilities} facilities in the index</span>
          {rows.length > 0 && levelBadge(maxLevel)}
        </div>

        <dl className="detail__grid">
          <div className="detail__cell"><dt>Facilities with a report</dt><dd>{D.fmtInt(rows.length)}</dd></div>
          <div className="detail__cell"><dt>{D.metricInfo(props.metric).short}</dt><dd>{D.formatMetric(total, props.metric)}</dd></div>
        </dl>

        <div className="detail__section">
          <div className="detail__section-title">Facilities in this LAU</div>
          {rows.length === 0
            ? <p className="detail__empty">No facility in this municipality matches the current filters.</p>
            : rows.slice(0, 6).map((row, index) => (
              <FacilityRow key={row.facility.idx} rank={index + 1} facility={row.facility}
                record={row.record} metric={props.metric} media={props.media}
                onClick={() => props.onSelect(row.facility)} />
            ))}
        </div>
        <p className="panel__note">The dashed circle marks the LAU area as an equivalent-radius circle around its centroid; it is a locator, not the municipality boundary.</p>
        <div className="place__actions">
          <button type="button" className="btn" onClick={props.onClose}>
            <Icon name="reset" size={15} /> Reset view
          </button>
        </div>
      </div>
    </section>
  );
}


function AboutModal(props) {
  useEffect(() => {
    function onKey(event) {
      if (event.key === "Escape") props.onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={props.onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="about-title"
        onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title" id="about-title">About the data and the method</h2>
          <button type="button" className="btn btn--ghost btn--icon" aria-label="Close" onClick={props.onClose}>
            <Icon name="close" size={17} />
          </button>
        </div>
        <div className="modal__body">
          <h3>What this map shows</h3>
          <p>Each circle is one facility that reported an air and/or water release to the European
            Pollutant Release and Transfer Register (E-PRTR) in the selected year. Circle size encodes
            reported mass; colour encodes the worst hazard class among the substances the facility
            reported. The register covers large industrial installations above activity-specific
            thresholds, not households, traffic or diffuse agriculture.</p>

          <h3>Hazard classes</h3>
          <ul>
            <li><strong>0 — Unassessed:</strong> aggregate indicators (NOₓ, SOₓ, NMVOC, PM, TOC, N/P totals, AOX, chlorides), climate gases and substances without a usable CAS/classification.</li>
            <li><strong>2 — Hazard-listed:</strong> a CLP health or environmental classification.</li>
            <li><strong>3 — High hazard:</strong> IARC group 2B, CLP Carc. 2, EPA hazardous air pollutant (air only) or WFD priority substance (water only).</li>
            <li><strong>4 — Very high hazard:</strong> IARC group 2A, CLP Carc. 1B or ECHA SVHC.</li>
            <li><strong>5 — Known carcinogen:</strong> IARC group 1 or CLP Carc. 1A.</li>
          </ul>
          <p>The worst applicable class wins. Air and water are classified separately because the EPA
            HAP list applies to air and the WFD priority list to water. A high class means intrinsic
            hazard, <strong>not</strong> risk: mass, toxicity, exposure and site conditions are different
            things. The dashboard is a screening and communication tool, not a permit or compliance check.</p>

          <h3>Data processing</h3>
          <ul>
            <li>Source: EEA E-PRTR dataset <code>2007–2024 v16 r00</code>, air and water release tables.</li>
            <li>Facility coordinates are checked against a broad Europe window; coordinates at (0,0), outside the window or missing are kept in the data but not plotted.</li>
            <li>Each coordinate is joined by point-in-polygon to the 2024 LAU layer (EPSG:3035, 2 m spatial filter). There is no nearest-neighbour fallback: unmatched facilities have no LAU.</li>
            <li>LAU boundaries are pre-simplified for the browser and retain municipalities with ≥ 1,000 inhabitants or at least one facility.</li>
            <li>Mass is reported in kilograms. The “total mass” metric includes CO₂; the default “classified mass” excludes aggregates, climate gases and unassessable groups.</li>
            <li>The 2024 reporting year may be incomplete. Always compare with the quality report before drawing trend conclusions.</li>
          </ul>

          <h3>Sources</h3>
          <ul>
            <li><a href="https://www.eea.europa.eu/en/datahub" target="_blank" rel="noreferrer">EEA data hub — E-PRTR</a></li>
            <li><a href="https://www.iarc.who.int/agents-classified-by-the-iarc/" target="_blank" rel="noreferrer">IARC monographs — agents classified by carcinogenicity</a></li>
            <li><a href="https://echa.europa.eu/information-on-chemicals/cl-inventory-database" target="_blank" rel="noreferrer">ECHA CLP classification inventory</a> and the SVHC candidate list</li>
            <li><a href="https://environment.ec.europa.eu/topics/water/water-union/priority-substances_en" target="_blank" rel="noreferrer">EU Water Framework Directive priority substances</a></li>
            <li><a href="https://www.epa.gov/haps" target="_blank" rel="noreferrer">US EPA hazardous air pollutants</a></li>
            <li><a href="https://ec.europa.eu/eurostat/web/gisco/geodata/reference-data/administrative-units-statistical-units/lau" target="_blank" rel="noreferrer">GISCO LAU 2024</a> and Natural Earth admin-0 boundaries</li>
          </ul>

          <h3>Keyboard</h3>
          <dl className="kv">
            <dt><kbd>Ctrl</kbd>/<kbd>⌘</kbd> + <kbd>K</kbd></dt><dd>Focus search</dd>
            <dt><kbd>Space</kbd></dt><dd>Play / pause the year timeline (when the button is focused)</dd>
            <dt><kbd>Esc</kbd></dt><dd>Close this dialog or clear the search</dd>
          </dl>
        </div>
      </div>
    </div>
  );
}


function Timeline(props) {
  const index = Math.max(0, props.years.indexOf(props.year));
  const fill = props.years.length > 1 ? (index / (props.years.length - 1)) * 100 : 0;
  const positions = [0, 5, 10, 15, props.years.length - 1].filter((value, i, list) =>
    value >= 0 && value < props.years.length && list.indexOf(value) === i
  );
  return (
    <div className="timeline">
      <button type="button" className="timeline__play" onClick={props.onToggle}
        aria-label={props.playing ? "Pause timeline" : "Play timeline"}
        aria-pressed={props.playing}>
        <Icon name={props.playing ? "pause" : "play"} size={18} />
      </button>
      <div className="timeline__track">
        <input
          className="timeline__range"
          type="range"
          min="0"
          max={props.years.length - 1}
          step="1"
          value={index}
          style={{ "--fill": fill + "%" }}
          aria-label="Reporting year"
          aria-valuetext={String(props.year)}
          onChange={(event) => props.onYear(props.years[Number(event.target.value)])}
        />
        <div className="timeline__years" aria-hidden="true">
          {positions.map((position) => (
            <span key={position}>{props.years[position]}</span>
          ))}
        </div>
      </div>
      <div className="timeline__year">
        <strong>{props.year}</strong>
        <span>reporting year</span>
        <div className="timeline__loading">{props.loading ? "loading…" : ""}</div>
      </div>
    </div>
  );
}


function initialState() {
  const parsed = D.parseHash(window.location.hash);
  const metric = D.METRICS.some((item) => item.key === parsed.metric) ? parsed.metric : "haz";
  const media = D.MEDIA.some((item) => item.key === parsed.media) ? parsed.media : "both";
  const level = Number(parsed.level);
  return {
    year: D.clampYear(parsed.year, D.YEARS) || D.DEFAULT_YEAR,
    metric: metric,
    media: media,
    minLevel: [0, 2, 3, 4, 5].includes(level) ? level : 0
  };
}

function App() {
  const initial = useMemo(initialState, []);
  const [year, setYear] = useState(initial.year);
  const [metric, setMetric] = useState(initial.metric);
  const [media, setMedia] = useState(initial.media);
  const [minLevel, setMinLevel] = useState(initial.minLevel);
  const [showLau, setShowLau] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [query, setQuery] = useState("");

  const [core, setCore] = useState(null);
  const [coreError, setCoreError] = useState(null);
  const [records, setRecords] = useState([]);
  const [loadedYear, setLoadedYear] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mapError, setMapError] = useState(null);
  const [dotCount, setDotCount] = useState(0);
  const [selected, setSelected] = useState(null);
  const [city, setCity] = useState(null);
  const [about, setAbout] = useState(false);

  const mapHostRef = useRef(null);
  const mapRef = useRef(null);
  const cacheRef = useRef(new Map());
  const searchRef = useRef(null);

  /* ---- Core data ------------------------------------------------------- */
  useEffect(() => {
    let cancelled = false;
    D.loadCore(DATA_BASE).then((data) => {
      if (cancelled) return;
      setCore(data);
      document.body.dataset.ready = "true";
      const lastYear = data.years[data.years.length - 1];
      if (!D.clampYear(year, data.years) && data.years.length) {
        // A stale link may point at a year that is no longer published.
        setYear(D.clampYear(D.DEFAULT_YEAR, data.years) || lastYear);
      }
    }).catch((error) => {
      if (cancelled) return;
      console.error(error);
      setCoreError(error);
      document.body.dataset.ready = "error";
    });
    return () => { cancelled = true; };
    // The initial year is validated once against the loaded year list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ---- Map instance ---------------------------------------------------- */
  useEffect(() => {
    if (!core || !mapHostRef.current || mapRef.current) return;
    const map = DashMap.create(mapHostRef.current, {
      basePath: DATA_BASE + "/boundaries",
      onSelect: (facility) => {
        setSelected(facility);
        setCity(null);
        if (facility.plot) map.focusFacility(facility);
      },
      onBackgroundClick: () => {
        setSelected(null);
        setCity(null);
        map.clearFocus();
      },
      onCount: (count) => setDotCount(count),
      onError: (error) => {
        console.error(error);
        setMapError(error);
      }
    });
    mapRef.current = map;
    return () => {
      map.destroy();
      mapRef.current = null;
    };
  }, [core]);

  /* ---- Release year ---------------------------------------------------- */
  useEffect(() => {
    if (!core) return;
    let cancelled = false;
    setLoading(true);
    let promise = cacheRef.current.get(year);
    if (!promise) {
      promise = D.loadYear(year, DATA_BASE);
      cacheRef.current.set(year, promise);
      promise.catch(() => cacheRef.current.delete(year));
    }
    promise.then((list) => {
      if (cancelled) return;
      setRecords(list);
      setLoadedYear(year);
      setLoading(false);
      if (mapRef.current) mapRef.current.setData({ core: core, records: list, year: year });
    }).catch((error) => {
      if (cancelled) return;
      console.error(error);
      setRecords([]);
      setLoadedYear(year);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [core, year]);

  /* ---- Push the view state into d3 ------------------------------------- */
  useEffect(() => {
    if (!mapRef.current) return;
    mapRef.current.setView({
      metric: metric,
      media: media,
      minLevel: minLevel,
      showLau: showLau,
      selectedId: selected ? selected.idx : null
    });
  }, [core, metric, media, minLevel, showLau, selected]);

  useEffect(() => {
    document.title = "EPRTR Atlas — " + D.metricInfo(metric).short + ", " + year;
    const hash = D.hashFor({ year: year, metric: metric, media: media, minLevel: minLevel });
    if (window.location.hash !== hash) {
      window.history.replaceState(null, "", hash);
    }
  }, [year, metric, media, minLevel]);

  useEffect(() => {
    if (!playing || !core) return;
    const timer = window.setInterval(() => {
      setYear((current) => {
        const index = core.years.indexOf(current);
        return core.years[(index + 1) % core.years.length];
      });
    }, 900);
    return () => window.clearInterval(timer);
  }, [playing, core]);

  useEffect(() => {
    function onKey(event) {
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === "k") {
        event.preventDefault();
        if (searchRef.current) searchRef.current.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);


  /* ---- Derived views --------------------------------------------------- */
  const activeRecords = useMemo(
    () => (loadedYear === year ? records : []),
    [loadedYear, year, records]
  );
  const recordMap = useMemo(() => D.indexReleases(activeRecords), [activeRecords]);
  const stats = useMemo(() => {
    if (!core) {
      return { facilities: 0, total: 0, highSum: 0, maxLevel: 0, levelCounts: [0, 0, 0, 0, 0, 0], countries: [], top: [], topFacilities: [] };
    }
    return D.computeStats({
      facilitiesById: core.byIdx,
      releases: activeRecords,
      metric: metric,
      media: media,
      minLevel: minLevel,
      limit: 10
    });
  }, [core, activeRecords, metric, media, minLevel]);
  const selectedRecord = selected ? recordMap.get(selected.idx) : null;
  const topRows = useMemo(() => (stats.topFacilities || []).filter((row) => row.facility), [stats]);

  const cityRows = useMemo(() => {
    if (!city || !core) return [];
    return core.facilities
      .filter((facility) => facility.lau && facility.lau.id === city.id)
      .map((facility) => ({ facility: facility, record: recordMap.get(facility.idx) }))
      .filter((row) => row.record && D.passesFilter(row.record, media, minLevel))
      .map((row) => ({ facility: row.facility, record: row.record, value: D.metricValue(row.record, metric, media) }))
      .sort((a, b) => b.value - a.value);
  }, [city, core, recordMap, metric, media, minLevel]);

  const sizeLegend = useMemo(() => {
    const count = D.metricInfo(metric).kind === "count";
    return D.radiusLegend(D.makeLogRadiusScale(count ? [1, 20] : [1000, 1e9], D.RADIUS_RANGE), metric);
  }, [metric]);

  /* ---- Interactions ---------------------------------------------------- */
  function selectFacility(facility) {
    if (!facility) return;
    setSelected(facility);
    setCity(null);
    if (mapRef.current && facility.plot) mapRef.current.focusFacility(facility);
  }

  function focusCity(cityLike) {
    if (!cityLike || !core) return;
    let target = cityLike;
    if (!isFinite(target.lon) || !isFinite(target.lat) || !isFinite(target.radius)) {
      target = core.cities.find((item) => item.id === cityLike.id) || null;
    }
    if (!target) return;
    setCity(target);
    setSelected(null);
    if (mapRef.current) mapRef.current.focusCity(target);
  }

  function clearPlace() {
    setSelected(null);
    setCity(null);
    if (mapRef.current) {
      mapRef.current.clearFocus();
      mapRef.current.resetZoom();
    }
  }

  function changeYear(next) {
    setPlaying(false);
    setYear(next);
  }

  function resetFilters() {
    setMetric("haz");
    setMedia("both");
    setMinLevel(0);
    setShowLau(true);
    setQuery("");
  }

  if (coreError) {
    return (
      <div className="notice" role="alert">
        <h1>The data files could not be loaded</h1>
        <p>{String(coreError.message || coreError)}</p>
        <p>Serve the <code>dashboard/</code> directory over HTTP, for example
          <code> cd dashboard &amp;&amp; python3 -m http.server 8000</code>, and open
          <code> http://localhost:8000/frontend/</code>.</p>
      </div>
    );
  }

  if (!core) {
    return (
      <div className="boot">
        <span className="boot__mark" aria-hidden="true"></span>
        <div>
          <p className="boot__title">EPRTR Atlas</p>
          <p className="boot__text">Loading facilities, pollutants, cities, release tables and boundaries…</p>
        </div>
      </div>
    );
  }

  const countryCount = stats.countries.length;


  return (
    <div className="app-root">
      <header className="topbar">
        <div className="topbar__inner">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true"></span>
            <div>
              <p className="brand__eyebrow">European Pollutant Release and Transfer Register</p>
              <h1 className="brand__title">EPRTR Atlas</h1>
              <p className="brand__sub">Industrial air &amp; water releases · {core.years[0]}–{core.years[core.years.length - 1]}</p>
            </div>
          </div>
          <div className="header-actions">
            <button type="button" className="btn" onClick={() => setAbout(true)}>
              <Icon name="help" size={16} />
              <span className="btn__text">Method &amp; data</span>
            </button>
          </div>
          <Timeline
            year={year}
            years={core.years}
            playing={playing}
            loading={loading}
            onToggle={() => setPlaying((value) => !value)}
            onYear={changeYear}
          />
        </div>
      </header>

      <main className="shell" id="main">
        <aside className="sidebar" aria-label="Filters and details">
          <section className="panel" aria-labelledby="filters-title">
            <div className="panel__head">
              <h2 className="panel__title" id="filters-title">Explore</h2>
              {(metric !== "haz" || media !== "both" || minLevel !== 0 || !showLau || query) && (
                <button type="button" className="btn btn--ghost" onClick={resetFilters}>
                  <Icon name="reset" size={14} /> Reset
                </button>
              )}
            </div>
            <div className="panel__body">
              <div className="field">
                <SearchBox
                  core={core}
                  query={query}
                  onQuery={setQuery}
                  onClear={() => setQuery("")}
                  inputRef={searchRef}
                  recordMap={recordMap}
                  metric={metric}
                  media={media}
                  onFacility={selectFacility}
                  onCity={focusCity}
                />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="metric-select">Circle size</label>
                <select id="metric-select" className="select" value={metric}
                  onChange={(event) => setMetric(event.target.value)}>
                  {METRIC_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>

              <div className="field">
                <span className="field__label">Release medium</span>
                <Segmented options={MEDIA_OPTIONS} value={media} onChange={setMedia} ariaLabel="Release medium" />
              </div>

              <div className="field">
                <span className="field__label">Minimum hazard class</span>
                <Segmented className="segmented--levels" options={LEVEL_OPTIONS} value={minLevel}
                  onChange={setMinLevel} ariaLabel="Minimum hazard class" />
              </div>

              <div className="field">
                <label className="check">
                  <input type="checkbox" checked={showLau} onChange={(event) => setShowLau(event.target.checked)} />
                  LAU municipality outlines
                </label>
              </div>

              <p className="panel__note">
                Showing <strong>{D.fmtInt(dotCount)}</strong> plotted facilities
                {minLevel > 0 ? " at class " + minLevel + " or above" : ""} in {year}.
                Each circle is one facility; size is reported {D.metricInfo(metric).short} ({D.mediumLabel(media).toLowerCase()}).
              </p>
            </div>
          </section>

          {selected && (
            <FacilityDetail
              facility={selected}
              record={selectedRecord}
              core={core}
              year={year}
              metric={metric}
              media={media}
              onClose={() => setSelected(null)}
              onZoom={selectFacility}
              onCity={focusCity}
            />
          )}

          {city && (
            <CityDetail
              city={city}
              rows={cityRows}
              year={year}
              metric={metric}
              media={media}
              onClose={clearPlace}
              onSelect={selectFacility}
            />
          )}


          <section className="panel" aria-labelledby="stats-title">
            <div className="panel__head">
              <h2 className="panel__title" id="stats-title">Overview · {year}</h2>
            </div>
            <div className="stats">
              <div className="stat">
                <div className="stat__value">{D.fmtInt(stats.facilities)}</div>
                <div className="stat__label">facilities reporting</div>
                <div className="stat__sub">{D.fmtInt(stats.highSum)} all-media high-hazard records</div>
              </div>
              <div className="stat">
                <div className="stat__value">{D.formatMetric(stats.total, metric)}</div>
                <div className="stat__label">{D.metricInfo(metric).short}</div>
                <div className="stat__sub">{D.mediumLabel(media)} releases</div>
              </div>
              <div className="stat">
                <div className="stat__value">{D.fmtInt(countryCount)}</div>
                <div className="stat__label">countries</div>
                <div className="stat__sub">with a matching report</div>
              </div>
              <div className="stat">
                <div className="stat__value">{stats.facilities ? stats.maxLevel : "—"}</div>
                <div className="stat__label">highest class</div>
                <div className="stat__sub">{stats.facilities ? D.levelInfo(stats.maxLevel).name : "no records"}</div>
              </div>
            </div>
          </section>

          <section className="panel" aria-labelledby="legend-title">
            <div className="panel__head">
              <h2 className="panel__title" id="legend-title">Hazard &amp; size</h2>
            </div>
            <div className="panel__body">
              <Legend stats={stats} sizeLegend={sizeLegend} />
            </div>
          </section>

          {topRows.length > 0 && (
            <section className="panel" aria-labelledby="top-title">
              <div className="panel__head">
                <h2 className="panel__title" id="top-title">Largest {D.metricInfo(metric).short}</h2>
                <span className="panel__note" style={{ margin: 0 }}>{D.mediumLabel(media)}</span>
              </div>
              <div className="panel__body panel__body--flush">
                <FacilityList
                  rows={topRows}
                  metric={metric}
                  media={media}
                  year={year}
                  onSelect={selectFacility}
                />
              </div>
            </section>
          )}

          <section className="panel" aria-labelledby="countries-title">
            <div className="panel__head">
              <h2 className="panel__title" id="countries-title">Country ranking</h2>
              <span className="panel__note" style={{ margin: 0 }}>top 9</span>
            </div>
            <div className="panel__body">
              <CountryList rows={stats.countries} metric={metric} />
              <p className="panel__note">Sum of the selected metric over facilities with a report. Country totals are
                not normalised by population or economic output.</p>
            </div>
          </section>

          <section className="panel" aria-labelledby="method-note-title">
            <div className="panel__body">
              <h2 className="panel__title" id="method-note-title">Reading the map</h2>
              <p className="panel__note">Colour is intrinsic hazard, not risk. A large pale circle and a small dark
                circle are different kinds of concern; compare both. Facilities are E-PRTR reporters above
                activity thresholds, and 2024 may still be incomplete.</p>
              <div className="place__actions">
                <button type="button" className="btn" onClick={() => setAbout(true)}>
                  <Icon name="help" size={15} /> Method &amp; data sources
                </button>
              </div>
            </div>
          </section>
        </aside>


        <section className="map-panel" aria-label="Map of reported releases">
          <div className="map-panel__head">
            <div className="map-panel__title">
              <strong>{D.metricInfo(metric).short}</strong> · {D.mediumLabel(media).toLowerCase()} · {D.fmtInt(dotCount)} circles
            </div>
            <div className="map-panel__tools">
              <button type="button" className="btn btn--ghost" onClick={clearPlace}>
                <Icon name="reset" size={14} /> Reset view
              </button>
            </div>
          </div>

          <div className="map-wrap">
            <div className="map" ref={mapHostRef}></div>

            <div className="map__hud">
              <span className="map__pill"><strong>{year}</strong></span>
              <span className="map__pill">{D.metricInfo(metric).short}</span>
              <span className="map__pill">{D.mediumLabel(media)}</span>
              {minLevel > 0 && <span className="map__pill">class ≥ {minLevel}</span>}
              {loading && <span className="map__pill">loading {year}…</span>}
            </div>

            <div className="map__zoom-controls">
              <button type="button" className="btn" aria-label="Zoom in" title="Zoom in"
                onClick={() => mapRef.current && mapRef.current.zoomIn()}>
                <Icon name="plus" size={15} />
              </button>
              <button type="button" className="btn" aria-label="Zoom out" title="Zoom out"
                onClick={() => mapRef.current && mapRef.current.zoomOut()}>
                <Icon name="minus" size={15} />
              </button>
            </div>

            {mapError && (
              <div className="map__empty">
                <div><strong>Boundaries unavailable</strong>The release data still load, but the map cannot be drawn.</div>
              </div>
            )}

            {!mapError && !loading && dotCount === 0 && (
              <div className="map__empty">
                <div><strong>No plotted facilities</strong>Try another medium, a lower hazard class or a different year.</div>
              </div>
            )}
          </div>

          <div className="map__footer">
            <span>{D.fmtInt(stats.facilities)} facilities reporting · {D.fmtInt(dotCount)} plotted</span>
            <span>EEA E-PRTR v16 r00 · EPSG:3035 · Natural Earth &amp; GISCO LAU</span>
          </div>
        </section>
      </main>

      {about && <AboutModal onClose={() => setAbout(false)} />}
    </div>
  );
}

const rootNode = document.getElementById("root");
if (rootNode) {
  if (ReactDOM.createRoot) ReactDOM.createRoot(rootNode).render(<App />);
  else ReactDOM.render(<App />, rootNode);
}

