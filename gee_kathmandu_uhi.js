/**
 * Urban Heat and Green-Space Assessment — Kathmandu Valley, Nepal
 * Google Earth Engine (JavaScript Code Editor)
 *
 * Paste this whole file into https://code.earthengine.google.com and press Run,
 * then start the export tasks from the Tasks tab.
 *
 * Produces, for the pre-monsoon hot season:
 *   - Land surface temperature (deg C) from Landsat 8/9 Collection 2 Level 2
 *   - NDVI and NDBI from the same composite
 *   - Tree / green / built-up fractions from ESA WorldCover 10 m
 *   - Population SUM and a heat exposure index per unit
 *   - ward_summary.csv  -> feeds build_report.py
 *   - GeoTIFFs for map making in ArcGIS Pro
 */

// ============================================================ CONFIGURATION
var YEARS        = [2023, 2024, 2025];   // pooled to beat cloud cover
var MONTH_START  = 3;                    // March
var MONTH_END    = 5;                    // May - pre-monsoon hot season, before the
                                         // June-September monsoon makes optical and
                                         // thermal imagery over the valley unusable
var MAX_CLOUD    = 40;                   // per-scene cloud cover accepted (%)
var SCALE        = 30;                   // Landsat native resolution (m)
var NDVI_VEG     = 0.30;                 // NDVI at or above this counts as vegetated
var EXPORT_FOLDER = 'kathmandu_uhi';

// Summary units. Try them in this order:
//
//  'asset'         your uploaded ward/municipality shapefile. The only route to
//                  ward level, and the one the brief actually calls for.
//  'geoboundaries' community-hosted geoBoundaries CGAZ, which reaches ADM2 =
//                  DISTRICT for Nepal (Kathmandu ~395 km2). No upload needed.
//                  NOTE: this is a community asset, not part of the official GEE
//                  catalog. If the path below errors, the asset has moved - check
//                  gee-community-catalog.org and paste the current path.
//  'gaul'          FAO GAUL level 2, which for Nepal is the old ZONE (~9,000 km2).
//                  Too coarse for this analysis; kept only as a last resort.
var UNITS_SOURCE = 'geoboundaries';      // 'asset' | 'geoboundaries' | 'gaul'

var WARDS_ASSET     = null;              // e.g. 'projects/your-project/assets/ktm_wards'
var WARD_NAME_FIELD = 'NAME';            // attribute holding the ward name

var GEOB_ASSET = 'projects/sat-io/open-datasets/geoboundaries/CGAZ_ADM2';
var GEOB_FIELD = 'shapeName';
// =========================================================================

// ---------------------------------------------------------------- study area
// The valley extent is stated explicitly rather than derived from a boundary
// dataset. Deriving it meant that if the dataset spelled a district name
// differently, the filter matched nothing, the geometry came back empty, and
// every clip and export failed with no obvious cause.
var VALLEY = ee.Geometry.Rectangle([85.18, 27.55, 85.55, 27.85]);
var aoi = VALLEY;

// Summary units, in order of preference:
//   1. an uploaded ward asset
//   2. GAUL districts that INTERSECT the valley - selected by location, not by
//      name, so spelling in the dataset cannot silently empty the collection
//   3. the valley as a single unit, so the script still runs end to end
var gaulUnits = ee.FeatureCollection('FAO/GAUL/2015/level2').filterBounds(VALLEY);
var fallback  = ee.FeatureCollection([ee.Feature(VALLEY, {ADM2_NAME: 'Kathmandu Valley'})]);

var units, unitField;
if (UNITS_SOURCE === 'asset' && WARDS_ASSET) {
  units = ee.FeatureCollection(WARDS_ASSET).filterBounds(VALLEY);
  unitField = WARD_NAME_FIELD;
} else if (UNITS_SOURCE === 'geoboundaries') {
  units = ee.FeatureCollection(GEOB_ASSET).filterBounds(VALLEY);
  unitField = GEOB_FIELD;
  print('Using geoBoundaries ADM2 (district level). Set UNITS_SOURCE to ' +
        '"asset" once a ward shapefile is uploaded.');
} else {
  units = ee.FeatureCollection(
    ee.Algorithms.If(gaulUnits.size().gt(0), gaulUnits, fallback));
  unitField = 'ADM2_NAME';
  print('Using FAO GAUL level 2, which for Nepal is the ZONE - too coarse.');
}

// Units are trimmed to the study extent. Without this, a unit that merely
// touches the valley contributes its whole area to area_km2 while its raster
// statistics cover only the clipped part - two numbers that disagree.
units = units.map(function (f) {
  return f.setGeometry(f.geometry().intersection(VALLEY, 1));
});

// Check these before starting the exports.
print('Summary units found:', units.size());
print('Unit names:', units.aggregate_array(unitField));
print('Unit areas within the valley (km2):',
      units.map(function (f) {
        return f.set('a_km2', f.geometry().area(1).divide(1e6));
      }).aggregate_array('a_km2'));
// FAO GAUL 2015 stops at level 2, which for Nepal is the old ZONE, roughly
// 9,000 km2. If the areas above are in the thousands you are summarising zones,
// not wards, and the ward asset is required.

// ------------------------------------------------- Landsat 8/9 C2 L2 compositing
// Collection 2 Level 2 already supplies atmospherically corrected surface
// reflectance and surface temperature, so no TOA conversion or emissivity model.
function maskL2(img) {
  var qa = img.select('QA_PIXEL');
  var mask = qa.bitwiseAnd(1 << 1).eq(0)   // dilated cloud
        .and(qa.bitwiseAnd(1 << 2).eq(0))  // cirrus
        .and(qa.bitwiseAnd(1 << 3).eq(0))  // cloud
        .and(qa.bitwiseAnd(1 << 4).eq(0)); // cloud shadow
  var sat = img.select('QA_RADSAT').eq(0);

  var sr = img.select('SR_B.').multiply(0.0000275).add(-0.2);
  var st = img.select('ST_B10').multiply(0.00341802).add(149.0).subtract(273.15);

  return img.addBands(sr, null, true)
            .addBands(st.rename('LST'), null, true)
            .updateMask(mask).updateMask(sat)
            .copyProperties(img, ['system:time_start']);
}

// Landsat scenes carry no 'year' property, so the year window is expressed with
// calendarRange. ee.Filter.or is a static function, not a method on a filter.
var yearFilters = YEARS.map(function (y) {
  return ee.Filter.calendarRange(y, y, 'year');
});
var yearFilter = (yearFilters.length === 1)
  ? yearFilters[0]
  : ee.Filter.or.apply(null, yearFilters);

var collection = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2')
  .merge(ee.ImageCollection('LANDSAT/LC09/C02/T1_L2'))
  .filterBounds(aoi)
  .filter(yearFilter)
  .filter(ee.Filter.calendarRange(MONTH_START, MONTH_END, 'month'))
  .filter(ee.Filter.lt('CLOUD_COVER', MAX_CLOUD))
  .map(maskL2);

print('Scenes in composite:', collection.size());

var composite = collection.median().clip(aoi);

// ----------------------------------------------------------------- indices
var nir  = composite.select('SR_B5');
var red  = composite.select('SR_B4');
var swir = composite.select('SR_B6');

var ndvi = nir.subtract(red).divide(nir.add(red)).rename('NDVI');
var ndbi = swir.subtract(nir).divide(swir.add(nir)).rename('NDBI');
var lst  = composite.select('LST');

// LST anomaly: departure from the valley-wide mean. This is the number worth
// comparing between units - it removes the seasonal level and isolates pattern.
var baseline = ee.Geometry(ee.Algorithms.If(units.size().gt(0), units.geometry(), VALLEY));
var valleyMeanLST = ee.Number(lst.reduceRegion({
  reducer: ee.Reducer.mean(), geometry: baseline, scale: 100,
  maxPixels: 1e9, bestEffort: true
}).get('LST'));
print('Valley mean LST (deg C):', valleyMeanLST);

var lstAnom = lst.subtract(ee.Image.constant(valleyMeanLST)).rename('LST_anom');

// ------------------------------------------------- land cover fractions (10 m)
// WorldCover is used rather than an NDBI threshold: a threshold on a 30 m index
// is a poor impervious estimate where building material and bare pre-monsoon
// soil look spectrally similar.
var wc = ee.ImageCollection('ESA/WorldCover/v200').first().clip(aoi);
var treeFrac  = wc.eq(10).rename('tree_frac');
var grassFrac = wc.eq(30);
var cropFrac  = wc.eq(40);
var builtFrac = wc.eq(50).rename('built_frac');
var waterFrac = wc.eq(80).rename('water_frac');
var greenFrac = treeFrac.add(grassFrac).add(cropFrac).rename('green_frac');
var ndviVeg   = ndvi.gte(NDVI_VEG).rename('ndvi_veg_frac');

var pop = ee.ImageCollection('WorldPop/GP/100m/pop')
  .filter(ee.Filter.eq('country', 'NPL'))
  .filter(ee.Filter.eq('year', 2020))
  .mosaic().clip(aoi).rename('population');

// --------------------------------------------------------- zonal statistics
// One pass per unit. Population uses SUM (a mean would give people per pixel,
// which is not a population count); everything else uses an area-weighted mean.
var stack = lst.rename('lst_mean')
  .addBands(lstAnom.rename('lst_anom_mean'))
  .addBands(ndvi.rename('ndvi_mean'))
  .addBands(ndbi.rename('ndbi_mean'))
  .addBands(treeFrac).addBands(greenFrac).addBands(builtFrac)
  .addBands(waterFrac).addBands(ndviVeg);

var summary = units.map(function (f) {
  var geom = f.geometry();
  var m = stack.reduceRegion({
    reducer: ee.Reducer.mean(), geometry: geom, scale: SCALE,
    maxPixels: 1e9, bestEffort: true, tileScale: 4
  });
  var sd = lst.reduceRegion({
    reducer: ee.Reducer.stdDev(), geometry: geom, scale: SCALE,
    maxPixels: 1e9, bestEffort: true, tileScale: 4
  }).get('LST');
  var people = ee.Number(pop.reduceRegion({
    reducer: ee.Reducer.sum(), geometry: geom, scale: 100,
    maxPixels: 1e9, bestEffort: true, tileScale: 4
  }).get('population'));

  var anom = ee.Number(ee.Algorithms.If(m.get('lst_anom_mean'), m.get('lst_anom_mean'), 0));

  return ee.Feature(null, {
    unit_name:      f.get(unitField),
    area_km2:       geom.area(1).divide(1e6),
    population:     people,
    lst_mean:       m.get('lst_mean'),
    lst_anom_mean:  m.get('lst_anom_mean'),
    lst_sd:         sd,
    ndvi_mean:      m.get('ndvi_mean'),
    ndbi_mean:      m.get('ndbi_mean'),
    tree_frac:      m.get('tree_frac'),
    green_frac:     m.get('green_frac'),
    built_frac:     m.get('built_frac'),
    water_frac:     m.get('water_frac'),
    ndvi_veg_frac:  m.get('ndvi_veg_frac'),
    // people living under a positive heat anomaly; zero where a unit is cooler
    // than the valley mean. A screening rank, not a health-risk estimate.
    heat_exposure:  people.multiply(anom.max(0))
  });
});

var COLUMNS = ['unit_name', 'area_km2', 'population', 'lst_mean', 'lst_anom_mean',
               'lst_sd', 'ndvi_mean', 'ndbi_mean', 'tree_frac', 'green_frac',
               'built_frac', 'water_frac', 'ndvi_veg_frac', 'heat_exposure'];

print('Unit summary (first 10):', summary.limit(10));

// ------------------------------------------------------------------ display
Map.centerObject(aoi, 11);
var lstVis  = {min: 22, max: 42, palette: ['#2b83ba','#abdda4','#ffffbf','#fdae61','#d7191c']};
var ndviVis = {min: 0,  max: 0.8, palette: ['#d9d0c3','#e8e6b0','#a6c86a','#4a8c3f','#1d5c22']};
var anomVis = {min: -6, max: 6,  palette: ['#2166ac','#92c5de','#f7f7f7','#f4a582','#b2182b']};

Map.addLayer(lst,     lstVis,  'LST (deg C)');
Map.addLayer(lstAnom, anomVis, 'LST anomaly (deg C)', false);
Map.addLayer(ndvi,    ndviVis, 'NDVI', false);
Map.addLayer(wc.selfMask(), {}, 'ESA WorldCover', false);
Map.addLayer(units.style({color: '111111', fillColor: '00000000', width: 1}), {}, 'Units');

// simple discrete legend, so map screenshots stand on their own
var legend = ui.Panel({style: {position: 'bottom-left', padding: '8px 10px'}});
legend.add(ui.Label('Land surface temperature (deg C)',
                    {fontWeight: 'bold', fontSize: '12px', margin: '0 0 6px 0'}));
var stops = [['#2b83ba', '< 26'], ['#abdda4', '26 - 30'], ['#ffffbf', '30 - 34'],
             ['#fdae61', '34 - 38'], ['#d7191c', '> 38']];
stops.forEach(function (s) {
  legend.add(ui.Panel({
    widgets: [
      ui.Label('', {backgroundColor: s[0], padding: '8px', margin: '0 6px 3px 0',
                    border: '1px solid #999'}),
      ui.Label(s[1], {margin: '0 0 3px 0', fontSize: '11px'})],
    layout: ui.Panel.Layout.flow('horizontal')
  }));
});
Map.add(legend);

// ------------------------------------------------------------------ exports
Export.table.toDrive({
  collection: summary, description: 'ktm_ward_summary', fileNamePrefix: 'ward_summary',
  folder: EXPORT_FOLDER, fileFormat: 'CSV', selectors: COLUMNS
});
Export.image.toDrive({
  image: lst.toFloat(), description: 'ktm_LST_degC', fileNamePrefix: 'LST_degC',
  folder: EXPORT_FOLDER, region: aoi, scale: SCALE, crs: 'EPSG:32645', maxPixels: 1e10
});
Export.image.toDrive({
  image: ndvi.toFloat(), description: 'ktm_NDVI', fileNamePrefix: 'NDVI',
  folder: EXPORT_FOLDER, region: aoi, scale: SCALE, crs: 'EPSG:32645', maxPixels: 1e10
});
Export.image.toDrive({
  image: lstAnom.toFloat(), description: 'ktm_LST_anomaly', fileNamePrefix: 'LST_anomaly',
  folder: EXPORT_FOLDER, region: aoi, scale: SCALE, crs: 'EPSG:32645', maxPixels: 1e10
});
Export.table.toDrive({
  collection: units, description: 'ktm_units_boundaries', fileNamePrefix: 'units',
  folder: EXPORT_FOLDER, fileFormat: 'GeoJSON'
});
