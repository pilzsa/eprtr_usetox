/* lib/topo.js — minimal TopoJSON decoder (no topojson-client dependency).
 *
 * Only the pieces used by the dashboard are implemented:
 *   - quantised delta-encoded arcs (transform.scale / transform.translate)
 *   - Polygon and MultiPolygon geometries
 *   - shared arcs, including reversed arcs (negative index)
 *
 * The boundary files were produced with mapshaper:
 *   countries: EPSG:3035, props {n, cc, c}
 *   LAU:       EPSG:3035, props {c}, POP_2024 >= 1000 or contains a facility
 */
(function (root, factory) {
  "use strict";
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Topo = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function decodeArcs(topology) {
    var transform = topology.transform;
    var arcs = topology.arcs || [];
    var out = new Array(arcs.length);
    var i, j, arc, x, y, point;

    for (i = 0; i < arcs.length; i += 1) {
      arc = arcs[i];
      if (transform) {
        x = 0;
        y = 0;
        point = new Array(arc.length);
        for (j = 0; j < arc.length; j += 1) {
          x += arc[j][0];
          y += arc[j][1];
          point[j] = [
            x * transform.scale[0] + transform.translate[0],
            y * transform.scale[1] + transform.translate[1]
          ];
        }
        out[i] = point;
      } else {
        out[i] = arc;
      }
    }
    return out;
  }

  function arcSlice(arcs, index) {
    var arc = index < 0 ? arcs[~index] : arcs[index];
    return index < 0 ? arc.slice().reverse() : arc;
  }

  function ringCoordinates(ring, arcs) {
    var coordinates = [];
    for (var i = 0; i < ring.length; i += 1) {
      var segment = arcSlice(arcs, ring[i]);
      // The first point of a following arc is shared with the previous arc.
      if (i > 0) segment = segment.slice(1);
      for (var j = 0; j < segment.length; j += 1) coordinates.push(segment[j]);
    }
    return coordinates;
  }

  function geometryCoordinates(geometry, arcs) {
    if (!geometry || !geometry.arcs) return null;
    if (geometry.type === "Polygon") {
      return geometry.arcs.map(function (ring) { return ringCoordinates(ring, arcs); });
    }
    if (geometry.type === "MultiPolygon") {
      return geometry.arcs.map(function (polygon) {
        return polygon.map(function (ring) { return ringCoordinates(ring, arcs); });
      });
    }
    return null;
  }

  function feature(geometry, arcs) {
    if (geometry.type === "GeometryCollection") {
      return {
        type: "FeatureCollection",
        features: geometry.geometries.map(function (child) { return feature(child, arcs); })
      };
    }
    var coordinates = geometryCoordinates(geometry, arcs);
    return {
      type: "Feature",
      id: geometry.id,
      properties: geometry.properties || {},
      geometry: coordinates === null ? null : { type: geometry.type, coordinates: coordinates }
    };
  }

  /** Decode one named object of a topology into a FeatureCollection. */
  function object(topology, name) {
    var collection = topology.objects && topology.objects[name];
    if (!collection) throw new Error("Topology has no object named " + name);
    var arcs = decodeArcs(topology);
    if (collection.type === "GeometryCollection") {
      return {
        type: "FeatureCollection",
        features: collection.geometries.map(function (geometry) { return feature(geometry, arcs); })
      };
    }
    return feature(collection, arcs);
  }

  /** First object name, useful while the mapshaper output name is not fixed. */
  function firstObjectName(topology) {
    return topology.objects ? Object.keys(topology.objects)[0] : null;
  }

  return {
    decodeArcs: decodeArcs,
    feature: feature,
    object: object,
    firstObjectName: firstObjectName
  };
});
