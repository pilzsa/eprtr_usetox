/* dashboard/frontend/lib/geo3035.js
 * WGS84 -> EPSG:3035 (ETRS89-extended / LAEA Europe) in closed form.
 *
 * Port of `wgs84_to_laea3035()` in `dashboard/census_profile.py` (EPSG method 9820,
 * forward Lambert azimuthal equal-area on the GRS80 ellipsoid via the authalic
 * latitude).  The Python module dissolves the same formula over numpy arrays; this
 * file is the scalar/1-D version for the browser.  `dashboard/tests/test_frontend.py`
 * projects a fixed set of German points through **both** implementations and fails if
 * they disagree by more than 1 mm, so the map and `plants.csv` can never drift apart.
 *
 * Documentation: every definition of the returned object carries a marker
 *     // @doc kind=<const|function> name=<Identifier> desc=<what it is>,
 * which build_frontend_docs.py turns into the JS sheet of
 * frontend_documentation.xlsx (tests/test_frontend.py fails on a missing marker).
 *
 * Why closed form instead of pyproj/PROJ in the browser: the dashboard must work
 * offline, in a single static file tree, with no geo stack.  EPSG:3035 is defined by
 * exactly this formula, so nothing is approximated.
 *
 * Loadable two ways (no bundler needed):
 *   <script src="lib/geo3035.js"></script>   -> window.Geo3035
 *   const Geo3035 = require('./lib/geo3035.js')  -> module.exports
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.Geo3035 = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** Defining parameters of EPSG:3035 - do not change independently of the Python side. */
  // @doc kind=const name=PARAMS desc=Definierende Parameter von EPSG:3035: GRS80-Ellipsoid, natürlicher Ursprung (52° N, 10° O), falscher Ost-/Nordwert sowie die 100-m-Kantenlänge des Zensus-Gitters. Muss mit census_profile.py übereinstimmen.
  var PARAMS = {
    ellipsoid: "GRS80",
    a: 6378137.0,              // semi-major axis, metres
    f: 1.0 / 298.257222101,    // flattening (inverse flattening 298.257222101)
    lat0: 52.0,                // latitude of natural origin, degrees
    lon0: 10.0,                // longitude of natural origin, degrees
    fe: 4321000.0,             // false easting, metres
    fn: 3210000.0,             // false northing, metres
    latticeStepM: 100          // Zensus 2022 grid: cells of 100 m, midpoints at 100*k+50 m
  };

  var RAD = Math.PI / 180;
  var E2 = PARAMS.f * (2.0 - PARAMS.f);          // first eccentricity squared
  var E = Math.sqrt(E2);
  var LAT0 = PARAMS.lat0 * RAD;
  var LON0 = PARAMS.lon0 * RAD;

  /**
   * q(phi) - the ellipsoidal "authalic" quantity of EPSG method 9820.
   * @param {number} phi latitude in radians
   * @returns {number}
   */
  // @doc kind=function name=authalicQ desc=Authalische Größe q(phi) der EPSG-Methode 9820: der ellipsoidische Faktor, der die flächentreue Lambert-Projektion exakt macht. Wird einmal je Punkt ausgewertet.
  function authalicQ(phi) {
    var s = Math.sin(phi);
    return (1 - E2) * (s / (1 - E2 * s * s) - (1 / (2 * E)) * Math.log((1 - E * s) / (1 + E * s)));
  }

  // constants that do not depend on the input point (computed once, like in Python)
  var Q_POLE = authalicQ(Math.PI / 2);
  var Q0 = authalicQ(LAT0);
  var BETA0 = Math.asin(Q0 / Q_POLE);
  var RQ = PARAMS.a * Math.sqrt(Q_POLE / 2.0);
  var M0 = Math.cos(LAT0) / Math.sqrt(1 - E2 * Math.sin(LAT0) * Math.sin(LAT0));
  var D = PARAMS.a * M0 / (RQ * Math.cos(BETA0));
  var SIN_B0 = Math.sin(BETA0);
  var COS_B0 = Math.cos(BETA0);

  /**
   * Project one WGS84/ETRS89 point to EPSG:3035.
   * @param {number} lon longitude in degrees (east positive)
   * @param {number} lat latitude in degrees (north positive)
   * @returns {{east: number, north: number}} metres
   */
  // @doc kind=function name=wgs84ToLaea3035 desc=Ein Punkt in WGS84/ETRS89 (Grad) nach EPSG:3035 (Meter), geschlossene Form statt PROJ. Portierung von census_profile.wgs84_to_laea3035(); tests/test_frontend.py vergleicht beide Seiten und lässt nur 1 mm Abweichung zu.
  function wgs84ToLaea3035(lon, lat) {
    var dl = lon * RAD - LON0;
    var beta = Math.asin(Math.max(-1, Math.min(1, authalicQ(lat * RAD) / Q_POLE)));
    var b = RQ * Math.sqrt(2.0 / (1 + SIN_B0 * Math.sin(beta) + COS_B0 * Math.cos(beta) * Math.cos(dl)));
    return {
      east: PARAMS.fe + b * D * Math.cos(beta) * Math.sin(dl),
      north: PARAMS.fn + (b / D) * (COS_B0 * Math.sin(beta) - SIN_B0 * Math.cos(beta) * Math.cos(dl))
    };
  }

  /**
   * Project a whole GeoJSON ring/line: [[lon, lat], ...] -> [[east, north], ...].
   * Used for the Bundesland polygons, so they land on exactly the same axes as the
   * plant coordinates of `plants.csv`.
   * @param {Array<Array<number>>} coords
   * @returns {Array<Array<number>>}
   */
  // @doc kind=function name=projectPath desc=Ganzen GeoJSON-Ring oder -Linienzug projizieren ([[lon, lat], ...] -> [[east, north], ...]), damit die Bundeslandgrenzen auf genau denselben Achsen liegen wie die Anlagenkoordinaten aus plants.csv.
  function projectPath(coords) {
    var out = new Array(coords.length);
    for (var i = 0; i < coords.length; i++) {
      var p = wgs84ToLaea3035(coords[i][0], coords[i][1]);
      out[i] = [p.east, p.north];
    }
    return out;
  }

  /**
   * Project every polygon of a GeoJSON (Multi)Polygon geometry.
   * @param {{type: string, coordinates: Array}} geometry
   * @returns {Array<Array<Array<number>>>} list of projected polygons (outer + holes)
   */
  // @doc kind=function name=projectGeometry desc=Alle Polygone einer (Multi)Polygon-Geometrie projizieren und die Ringe (Außenring + Löcher) so zurückgeben, wie d3.geoPath sie erwartet.
  function projectGeometry(geometry) {
    var polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    return polys.map(function (rings) {
      return rings.map(projectPath);
    });
  }

  /** The 100 m cell index of a projected point (same rule as `lattice_key()` in Python). */
  // @doc kind=function name=cellIndex desc=Index der 100-m-Zelle eines projizierten Punktes (Boden zur 100-m-Kante; Zellmittelpunkte liegen bei 100*k+50 m) - dieselbe Regel wie lattice_key() in census_profile.py.
  function cellIndex(east, north) {
    return {
      ix: Math.floor(east / PARAMS.latticeStepM),
      iy: Math.floor(north / PARAMS.latticeStepM)
    };
  }

  return {
    PARAMS: PARAMS,
    authalicQ: authalicQ,
    wgs84ToLaea3035: wgs84ToLaea3035,
    projectPath: projectPath,
    projectGeometry: projectGeometry,
    cellIndex: cellIndex
  };
});
