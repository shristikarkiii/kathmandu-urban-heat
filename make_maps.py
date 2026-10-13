"""
Render the map series for the Kathmandu Valley urban heat brief.

Inputs   src/Kathmandu_UHI/*.tif        LST and NDVI rasters exported from Earth Engine
         src/valley_adm2.geojson        district polygons clipped to the valley extent
         data/ward_summary.csv          per-district statistics
Output   maps/*.png                     picked up automatically by build_report.py
"""
import json, os
import numpy as np
import pandas as pd
import rasterio
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, Normalize
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.collections import PatchCollection

HERE = os.path.dirname(os.path.abspath(__file__))
SRC, MAPS = os.path.join(HERE, 'src'), os.path.join(HERE, 'maps')
TIF = os.path.join(SRC, 'Kathmandu_UHI')
os.makedirs(MAPS, exist_ok=True)

# geoBoundaries and the Earth Engine asset transliterate two districts differently
ALIAS = {'Kabherepalanchok': 'Kavrepalanchok', 'Makawanpur': 'Makwanpur'}

df = pd.read_csv(os.path.join(HERE, 'data', 'ward_summary.csv')).set_index('unit_name')
gj = json.load(open(os.path.join(SRC, 'valley_adm2.geojson')))

with rasterio.open(os.path.join(TIF, 'Kathmandu_LST_30m.tif')) as s:
    LST = s.read(1, masked=True)
    B = s.bounds
EXT = [B.left, B.right, B.bottom, B.top]
with rasterio.open(os.path.join(TIF, 'Kathmandu_NDVI_30m.tif')) as s:
    NDVI = s.read(1, masked=True)

# The supplied anomaly raster is centred on 27.61 C, the mean of an earlier run.
# Recentering on the mean behind the summary table keeps map and table consistent.
BASELINE = 28.376
ANOM = LST - BASELINE

LAT = 0.5 * (B.bottom + B.top)
ASPECT = 110.9 / (111.32 * np.cos(np.radians(LAT)))     # degrees are not square
KM_PER_DEG_LON = 111.32 * np.cos(np.radians(LAT))

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9})

CMAP_LST  = LinearSegmentedColormap.from_list('lst',  ['#2b6ca3','#7fb2d4','#d8e6c4','#f6e08a','#e8934a','#c0392b','#8b1a13'])
CMAP_ANOM = LinearSegmentedColormap.from_list('anom', ['#1a5276','#5499c7','#d6eaf8','#f7f7f7','#f9d5c3','#e07b53','#922b21'])
CMAP_NDVI = LinearSegmentedColormap.from_list('ndvi', ['#b8a98d','#ded6b8','#bcd08a','#7fae55','#3f7d34','#1d5320'])
CMAP_SEQ  = {'green': LinearSegmentedColormap.from_list('g', ['#f2f6ec','#cfe3bd','#94c47d','#4f8f45','#1f5c22']),
             'built': LinearSegmentedColormap.from_list('b', ['#f7f4f2','#e6cfc6','#d09a86','#b1614a','#7d2d1c']),
             'expo':  LinearSegmentedColormap.from_list('e', ['#f8f4f1','#eccfb9','#dc9a72','#c05f3c','#7f2a16'])}


def rings(geom):
    """Every exterior ring of a Polygon or MultiPolygon, as an Nx2 array."""
    cs = geom['coordinates']
    polys = cs if geom['type'] == 'MultiPolygon' else [cs]
    return [np.asarray(p[0]) for p in polys]


def draw_boundaries(ax, lw=0.9, color='#22252a', labels=True):
    for f in gj['features']:
        name = ALIAS.get(f['properties']['shapeName'], f['properties']['shapeName'])
        big = None
        for r in rings(f['geometry']):
            ax.plot(r[:, 0], r[:, 1], color=color, lw=lw, zorder=5)
            if big is None or len(r) > len(big):
                big = r
        if labels and big is not None:
            # label the visible part of the district, not the whole polygon: most
            # of these are clipped by the study extent and their true centroid
            # lies off the map
            inside = big[(big[:, 0] > EXT[0]) & (big[:, 0] < EXT[1]) &
                         (big[:, 1] > EXT[2]) & (big[:, 1] < EXT[3])]
            if len(inside) < 3:
                continue
            mx = 0.035 * (EXT[1] - EXT[0]); my = 0.035 * (EXT[3] - EXT[2])
            cx = float(np.clip(inside[:, 0].mean(), EXT[0] + mx, EXT[1] - mx))
            cy = float(np.clip(inside[:, 1].mean(), EXT[2] + my, EXT[3] - my))
            if True:
                ax.text(cx, cy, name, ha='center', va='center', fontsize=7.6,
                        color='#15181a', zorder=7,
                        path_effects=[__import__('matplotlib.patheffects', fromlist=['x'])
                                      .withStroke(linewidth=2.4, foreground='white')])


def frame(ax, title, sub=''):
    ax.set_xlim(EXT[0], EXT[1]); ax.set_ylim(EXT[2], EXT[3])
    ax.set_aspect(ASPECT)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color('#9a948a'); sp.set_linewidth(0.9)
    ax.set_title(title, fontsize=11.5, fontweight='bold', color='#15181a',
                 loc='left', pad=21)
    if sub:
        ax.text(0, 1.006, sub, transform=ax.transAxes, fontsize=8.2,
                color='#5d6360', va='bottom')
    # north arrow
    ax.annotate('N', xy=(0.962, 0.955), xytext=(0.962, 0.875),
                xycoords='axes fraction', textcoords='axes fraction',
                ha='center', fontsize=9, fontweight='bold', color='#2c2f33',
                arrowprops=dict(arrowstyle='-|>', color='#2c2f33', lw=1.3))
    # scale bar, 5 km
    km = 5.0
    dx = km / KM_PER_DEG_LON
    x0 = EXT[0] + 0.045 * (EXT[1] - EXT[0])
    y0 = EXT[2] + 0.045 * (EXT[3] - EXT[2])
    ax.plot([x0, x0 + dx], [y0, y0], color='#15181a', lw=3.1, solid_capstyle='butt', zorder=8)
    ax.text(x0 + dx / 2, y0 + 0.012 * (EXT[3] - EXT[2]), '%g km' % km, ha='center',
            fontsize=7.6, color='#15181a', zorder=8,
            path_effects=[__import__('matplotlib.patheffects', fromlist=['x'])
                          .withStroke(linewidth=2.4, foreground='white')])


def finish(fig, name, note='Landsat 8/9 C2 L2, pre-monsoon (Mar-May) median composite'):
    fig.text(0.012, 0.014, note, fontsize=7.2, color='#7a807c')
    fig.savefig(os.path.join(MAPS, name), dpi=220, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print('  wrote', name)


def raster_map(arr, cmap, norm, title, sub, cbar_label, name, note=None):
    fig, ax = plt.subplots(figsize=(7.4, 6.4))
    im = ax.imshow(arr, extent=EXT, origin='upper', cmap=cmap, norm=norm,
                   interpolation='bilinear', zorder=1)
    draw_boundaries(ax)
    frame(ax, title, sub)
    cb = fig.colorbar(im, ax=ax, fraction=0.037, pad=0.02)
    cb.set_label(cbar_label, fontsize=9)
    cb.outline.set_linewidth(0.7); cb.outline.set_edgecolor('#9a948a')
    finish(fig, name, note or 'Landsat 8/9 C2 L2, pre-monsoon (Mar-May) median composite')


def choropleth(column, cmap, title, sub, cbar_label, name, scale=1.0, note=None):
    vals = {}
    for f in gj['features']:
        n = ALIAS.get(f['properties']['shapeName'], f['properties']['shapeName'])
        if n in df.index:
            vals[n] = df.loc[n, column] * scale
    lo, hi = min(vals.values()), max(vals.values())
    norm = Normalize(lo, hi)
    fig, ax = plt.subplots(figsize=(7.4, 6.4))
    patches, colors = [], []
    for f in gj['features']:
        n = ALIAS.get(f['properties']['shapeName'], f['properties']['shapeName'])
        if n not in vals:
            continue
        for r in rings(f['geometry']):
            patches.append(PathPatch(Path(r)))
            colors.append(vals[n])
    pc = PatchCollection(patches, cmap=cmap, norm=norm, edgecolor='none', zorder=2)
    pc.set_array(np.asarray(colors))
    ax.add_collection(pc)
    draw_boundaries(ax)
    frame(ax, title, sub)
    cb = fig.colorbar(pc, ax=ax, fraction=0.037, pad=0.02)
    cb.set_label(cbar_label, fontsize=9)
    cb.outline.set_linewidth(0.7); cb.outline.set_edgecolor('#9a948a')
    finish(fig, name, note or 'ESA WorldCover v200 (10 m), summarised by district')


print('Rendering map series...')

# 1 study area
fig, ax = plt.subplots(figsize=(7.4, 6.4))
ax.add_collection(PatchCollection(
    [PathPatch(Path(r)) for f in gj['features'] for r in rings(f['geometry'])],
    facecolor='#efece6', edgecolor='none', zorder=1))
draw_boundaries(ax, lw=1.1)
frame(ax, 'Study area', 'Kathmandu Valley extent and the districts intersecting it')
finish(fig, 'map_study_area.png', 'District boundaries: geoBoundaries gbOpen NPL ADM2')

# 2 LST
lo, hi = np.percentile(LST.compressed(), [2, 98])
raster_map(LST, CMAP_LST, Normalize(lo, hi),
           'Land surface temperature',
           'Pre-monsoon median, degrees Celsius',
           'LST (°C)', 'map_lst.png')

# 3 anomaly, diverging about zero
lim = float(np.percentile(np.abs(ANOM.compressed()), 98))
raster_map(ANOM, CMAP_ANOM, TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim),
           'Land surface temperature anomaly',
           'Departure from the %.1f °C valley mean' % BASELINE,
           'ΔLST (°C)', 'map_lst_anomaly.png')

# 4 NDVI
raster_map(NDVI, CMAP_NDVI, Normalize(0, 0.85),
           'Vegetation condition (NDVI)',
           'Pre-monsoon median', 'NDVI', 'map_ndvi.png')

# 5-7 choropleths
choropleth('green_frac', CMAP_SEQ['green'], 'Green cover by district',
           'Tree, grassland and cropland as a share of district area within the valley',
           'Green cover (%)', 'map_greencover.png', scale=100)
choropleth('built_frac', CMAP_SEQ['built'], 'Built-up cover by district',
           'Built-up surface as a share of district area within the valley',
           'Built-up cover (%)', 'map_builtup.png', scale=100)
choropleth('heat_exposure', CMAP_SEQ['expo'], 'Heat exposure index by district',
           'Population under a positive heat anomaly - ordinal ranking only',
           'Exposure (thousand person-°C)', 'map_exposure.png', scale=1e-3,
           note='WorldPop 100 m population; see the data quality note in the brief')

print('Done. %d maps in maps/' % len(os.listdir(MAPS)))
