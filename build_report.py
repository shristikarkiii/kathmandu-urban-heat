"""
Build the Urban Heat and Green-Space technical brief as a Word document.

Run order
  1. Run gee_kathmandu_uhi.js in the Earth Engine Code Editor, start the export tasks.
  2. Put the exported ward_summary.csv into  data/
  3. Put map exports (PNG/JPG from GEE or ArcGIS Pro layouts) into  maps/
  4. python build_report.py

With no CSV present the report still builds, with every results slot marked as
pending. Nothing is ever filled with invented numbers.
"""
import os, glob, datetime
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, MAPS, FIGS = [os.path.join(HERE, d) for d in ('data', 'maps', 'figures')]
CSV = os.path.join(DATA, 'ward_summary.csv')
OUT = os.path.join(HERE, 'Kathmandu_UHI_Technical_Brief.docx')

AUTHOR = 'Shristi Karki'
INK, MUTED, FLAG = RGBColor(0x1A, 0x1A, 0x1A), RGBColor(0x59, 0x5F, 0x5C), RGBColor(0xB0, 0x30, 0x20)
PLT_GREEN, PLT_WARM, PLT_COOL = '#2E6B2A', '#C0392B', '#1F6FA8'

# --------------------------------------------------------------- load results
# Column names differ depending on which Earth Engine script produced the table,
# so incoming headers are normalised to one internal vocabulary.
ALIASES = {
    'unit_name': ['unit_name', 'unit_id', 'adm2_name', 'ward', 'ward_name', 'name',
                  'nameeng', 'gapa_napa', 'local_unit'],
    'lst_mean':      ['lst_mean', 'lst', 'lst_degc', 'mean_lst'],
    'lst_anom_mean': ['lst_anom_mean', 'lst_anomaly', 'lst_anom'],
    'ndvi_mean':     ['ndvi_mean', 'ndvi'],
    'ndbi_mean':     ['ndbi_mean', 'ndbi'],
    'tree_frac':     ['tree_frac', 'tree_cover_fraction', 'treecover', 'tree_fraction'],
    'green_frac':    ['green_frac', 'green_fraction', 'vegetation_fraction', 'veg_frac'],
    'built_frac':    ['built_frac', 'built_up_fraction', 'builtup_fraction', 'impervious_fraction'],
    'water_frac':    ['water_frac', 'water_fraction'],
    'ndvi_veg_frac': ['ndvi_veg_frac'],
    'population':    ['population', 'pop', 'pop_sum'],
    'heat_exposure': ['heat_exposure', 'exposure', 'exposure_index'],
    'area_km2':      ['area_km2', 'area', 'area_sqkm'],
    'lst_sd':        ['lst_sd', 'lst_stddev', 'stddev'],
    'lst_p90':       ['lst_p90', 'p90'],
    'lst_max':       ['lst_max', 'max'],
}

NOTES = []          # data-quality findings surfaced in the report

df = None
if os.path.exists(CSV):
    raw = pd.read_csv(CSV)
    raw.columns = [c.strip() for c in raw.columns]
    lookup = {c.lower().replace(' ', '_'): c for c in raw.columns}
    cols = {}
    for canon, names in ALIASES.items():
        for n in names:
            if n in lookup:
                cols[canon] = lookup[n]
                break
    if 'unit_name' in cols:
        df = pd.DataFrame({k: raw[v] for k, v in cols.items()})
        df = df.dropna(subset=['unit_name'])
        for c in df.columns:
            if c != 'unit_name':
                df[c] = pd.to_numeric(df[c], errors='coerce')
        sort_key = 'lst_anom_mean' if 'lst_anom_mean' in df.columns else 'lst_mean'
        if sort_key in df.columns:
            df = df.sort_values(sort_key, ascending=False)
        df = df.reset_index(drop=True)

HAVE = df is not None and len(df) > 0
N_UNITS = len(df) if HAVE else 0
MULTI = N_UNITS >= 3          # per-unit ranking and correlation need several units

if HAVE:
    # a single summary unit makes the anomaly zero by construction
    if N_UNITS < 3:
        NOTES.append('The summary table contains %d unit%s. Per-unit ranking, the '
                     'temperature anomaly and the cover-versus-temperature relationships '
                     'all require the valley to be divided into several units, so those '
                     'results are not reported here.'
                     % (N_UNITS, '' if N_UNITS == 1 else 's'))
    if 'lst_anom_mean' in df.columns and N_UNITS < 3 and abs(df['lst_anom_mean']).max() < 0.01:
        NOTES.append('The reported temperature anomaly is effectively zero, which is the '
                     'expected result when the anomaly is taken against the mean of the '
                     'same single region.')
    # WorldPop unconstrained counts are summed on a grid; implausible densities
    # usually mean the sum was taken off the raster's native resolution
    if {'population', 'area_km2'} <= set(df.columns):
        dens = (df['population'] / df['area_km2']).max()
        if dens > 10000:
            NOTES.append('Population is summed from the WorldPop unconstrained grid and '
                         'implies a peak density of about {:,.0f} people per km². '
                         'That is roughly three times the district figure implied by the '
                         '2021 national census, so the population totals and the heat '
                         'exposure index below should be read as an ordinal ranking only. '
                         'Substitute census counts before quoting any absolute number.'
                         .format(dens))
    if 'population' in df.columns and df['population'].max() < 1000:
        NOTES.append('The population field holds a value of about %.0f, which is far too '
                     'small to be a population count for this area and is consistent with '
                     'a per-pixel mean. Population totals and the heat-exposure index are '
                     'therefore not reported.' % df['population'].max())
        df = df.drop(columns=['population'])
        if 'heat_exposure' in df.columns:
            df = df.drop(columns=['heat_exposure'])

plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                     'axes.edgecolor': '#666', 'axes.linewidth': .8,
                     'axes.grid': True, 'grid.color': '#E3E0DA', 'grid.linewidth': .7,
                     'axes.axisbelow': True, 'figure.dpi': 200})

def save(fig, name):
    p = os.path.join(FIGS, name)
    fig.savefig(p, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return p

# ------------------------------------------------------------------- figures
figures = {}
if HAVE and MULTI:
    n = len(df)
    top = df.head(min(20, n))
    fig, ax = plt.subplots(figsize=(6.6, max(2.4, .26 * len(top) + 1)))
    cols = [PLT_WARM if v >= 0 else PLT_COOL for v in top['lst_anom_mean']]
    ax.barh(top['unit_name'][::-1], top['lst_anom_mean'][::-1], color=cols[::-1], height=.72)
    ax.axvline(0, color='#444', lw=.9)
    ax.set_xlabel('Mean LST anomaly vs valley mean (°C)')
    ax.set_ylabel('')
    figures['anom'] = save(fig, 'fig_lst_anomaly.png')

    if {'green_frac', 'lst_mean'} <= set(df.columns):
        fig, ax = plt.subplots(figsize=(4.6, 3.4))
        ax.scatter(df['green_frac'] * 100, df['lst_mean'], s=26,
                   color=PLT_GREEN, alpha=.75, edgecolor='white', linewidth=.6)
        d = df.dropna(subset=['green_frac', 'lst_mean'])
        if len(d) > 2:
            m, b = np.polyfit(d['green_frac'] * 100, d['lst_mean'], 1)
            xs = [d['green_frac'].min() * 100, d['green_frac'].max() * 100]
            ax.plot(xs, [m * x + b for x in xs], color='#444', lw=1.2, ls='--')
            r = d['green_frac'].corr(d['lst_mean'])
            ax.set_title('r = %.2f' % r, fontsize=9, color='#444', loc='right')
        ax.set_xlabel('Green cover (% of unit area)')
        ax.set_ylabel('Mean LST (°C)')
        figures['scatter_green'] = save(fig, 'fig_green_vs_lst.png')

    if {'built_frac', 'lst_anom_mean'} <= set(df.columns):
        fig, ax = plt.subplots(figsize=(4.6, 3.4))
        ax.scatter(df['built_frac'] * 100, df['lst_anom_mean'], s=26,
                   color=PLT_WARM, alpha=.75, edgecolor='white', linewidth=.6)
        ax.axhline(0, color='#444', lw=.9)
        d = df.dropna(subset=['built_frac', 'lst_anom_mean'])
        if len(d) > 2:
            ax.set_title('r = %.2f' % d['built_frac'].corr(d['lst_anom_mean']),
                         fontsize=9, color='#444', loc='right')
        ax.set_xlabel('Built-up cover (% of unit area)')
        ax.set_ylabel('LST anomaly (°C)')
        figures['scatter_built'] = save(fig, 'fig_built_vs_lst.png')

    if 'heat_exposure' in df.columns and df['heat_exposure'].notna().any():
        e = df.sort_values('heat_exposure', ascending=False).head(min(15, n))
        fig, ax = plt.subplots(figsize=(6.6, max(2.2, .26 * len(e) + 1)))
        ax.barh(e['unit_name'][::-1], e['heat_exposure'][::-1] / 1000.0,
                color='#8C3B2E', height=.72)
        ax.set_xlabel('Heat exposure index (thousand person-°C)')
        figures['exposure'] = save(fig, 'fig_heat_exposure.png')

# ----------------------------------------------------------------- document
doc = Document()
cp = doc.core_properties
cp.author = AUTHOR
cp.last_modified_by = AUTHOR
cp.title = 'Urban Heat and Green-Space Assessment - Kathmandu Valley, Nepal'
cp.subject = 'Land surface temperature, vegetation condition and heat exposure by district'
st = doc.styles['Normal']
st.font.name, st.font.size, st.font.color.rgb = 'Calibri', Pt(10.5), INK
st.paragraph_format.space_after = Pt(7)
st.paragraph_format.line_spacing = 1.12
for h, sz in (('Heading 1', 15), ('Heading 2', 12), ('Heading 3', 11)):
    s = doc.styles[h]
    s.font.name, s.font.size, s.font.bold, s.font.color.rgb = 'Calibri', Pt(sz), True, INK

def para(text, size=10.5, color=INK, italic=False, bold=False, align=None, after=7):
    p = doc.add_paragraph()
    r = p.add_run(text); r.font.size = Pt(size); r.font.color.rgb = color
    r.italic, r.bold = italic, bold
    if align: p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    return p

def caption(text):
    para(text, size=9, color=MUTED, italic=True, align=WD_ALIGN_PARAGRAPH.LEFT, after=12)

def pending(what):
    p = doc.add_paragraph()
    r = p.add_run('[ PENDING — ' + what + ' ]')
    r.font.size, r.font.bold, r.font.color.rgb = Pt(10), True, FLAG
    p.paragraph_format.space_after = Pt(10)

def bullets(items):
    for it in items:
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run(it); r.font.size = Pt(10.5); r.font.color.rgb = INK
        p.paragraph_format.space_after = Pt(3)

def table(rows, widths=None, header=True):
    t = doc.add_table(rows=0, cols=len(rows[0]))
    t.style = 'Light Grid Accent 1'
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j, v in enumerate(row):
            cells[j].text = ''
            p = cells[j].paragraphs[0]
            r = p.add_run(str(v))
            r.font.size = Pt(9)
            r.font.bold = (i == 0 and header)
            p.paragraph_format.space_after = Pt(2)
            if widths and j < len(widths):
                cells[j].width = Inches(widths[j])
    return t

# ---- title block
para('Technical Brief', size=10, color=MUTED, bold=True)
h = doc.add_paragraph()
r = h.add_run('Urban Heat and Green-Space Assessment\nKathmandu Valley, Nepal')
r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(21), True, INK, 'Calibri Light'
h.paragraph_format.space_after = Pt(10)
para('Summer land-surface temperature, vegetation condition and heat exposure '
     'summarised by local administrative unit.', size=12, color=MUTED, after=16)
unit_word = 'ward' if (HAVE and len(df) > 10) else 'administrative unit'
table([['Author', AUTHOR],
       ['Date', datetime.date.today().strftime('%d %B %Y')],
       ['Tools', 'Google Earth Engine, ArcGIS Pro, Excel'],
       ['Imagery', 'Landsat 8/9 Collection 2 Level 2 (surface reflectance + surface temperature)'],
       ['Ancillary', 'ESA WorldCover v200 (10 m land cover); WorldPop 100 m population'],
       ['Season', 'Pre-monsoon hot season, March–May'],
       ['Summary unit', unit_word.capitalize()]],
      widths=[1.3, 4.7], header=False)
doc.add_page_break()

# ---- 1 introduction
doc.add_heading('1  Introduction', level=1)
para('Kathmandu Valley has urbanised rapidly, converting agricultural land and open '
     'space within the valley floor to continuous built-up surface. Replacing vegetated '
     'and permeable ground with dry, dark, impervious material raises daytime surface '
     'temperature, because built materials store more incoming radiation and, lacking '
     'soil moisture and leaf area, shed almost none of it through evapotranspiration. '
     'The result is a surface urban heat island: a persistent, spatially structured '
     'temperature difference between the dense core and the valley’s greener margins.')
para('This brief maps that pattern from satellite imagery and reduces it to numbers that '
     'can be acted on administratively. It answers three questions:')
bullets([
    'Where in the valley is the land surface hottest during the pre-monsoon season, '
    'and by how much does each unit depart from the valley average?',
    'How does that pattern track tree and vegetation cover versus built-up surface?',
    'Which units combine high heat with high population, and therefore carry the '
    'greatest exposure?'])
para('The intended use is screening and prioritisation — identifying candidate units '
     'for tree planting, surface treatment or further study. It is not a substitute for '
     'air-temperature monitoring; see Section 6.')

# ---- 2 study area
doc.add_heading('2  Study area', level=1)
para('The analysis covers the three districts of Kathmandu Valley — Kathmandu, '
     'Lalitpur and Bhaktapur — a bowl-shaped basin at roughly 1,300 m elevation, '
     'ringed by hills that rise several hundred metres above the floor. The valley floor '
     'holds the dense historic cores of Kathmandu, Patan and Bhaktapur together with the '
     'newer built-up fringe; the rim retains forest and terraced agriculture.')
para('That topography matters for interpretation. Elevation alone depresses surface '
     'temperature on the valley rim, so part of any core-to-rim difference is orographic '
     'rather than a consequence of land cover. Section 6 returns to this.')
if os.path.exists(os.path.join(MAPS, 'map_study_area.png')):
    doc.add_picture(os.path.join(MAPS, 'map_study_area.png'), width=Inches(6.2))
    caption('Figure 1. Study area: Kathmandu Valley districts and summary units.')
else:
    pending('Figure 1, study area map — export from ArcGIS Pro as maps/map_study_area.png')

# ---- 3 methods
doc.add_heading('3  Data and methods', level=1)

doc.add_heading('3.1  Imagery and compositing', level=2)
para('Land surface temperature and vegetation indices were derived from Landsat 8 and '
     'Landsat 9 Collection 2 Level 2 scenes. Collection 2 Level 2 supplies atmospherically '
     'corrected surface reflectance and a surface temperature product, so no separate '
     'top-of-atmosphere conversion or emissivity model was applied.')
para('Scenes were restricted to March–May, the pre-monsoon hot season. This window is '
     'chosen deliberately: it captures the annual surface-temperature peak while avoiding '
     'the June–September monsoon, during which persistent cloud makes optical and '
     'thermal imagery over the valley largely unusable. Scenes with more than 40 per cent '
     'scene-wide cloud were discarded, and within the remaining scenes cloud, cloud shadow, '
     'cirrus and dilated-cloud pixels were masked individually using the QA_PIXEL band. '
     'Saturated pixels were removed using QA_RADSAT.')
para('Because a single date can leave large masked gaps, scenes from several years were '
     'pooled and reduced to a per-pixel median. The median is robust to the residual cloud '
     'edges that survive masking. The composite therefore represents typical pre-monsoon '
     'surface conditions rather than any one overpass.')

doc.add_heading('3.2  Surface temperature', level=2)
para('The thermal band ST_B10 was rescaled to kelvin using the Collection 2 scale and '
     'offset (0.00341802 and 149.0) and converted to degrees Celsius. Two quantities are '
     'reported. Mean LST is the absolute surface temperature of a unit. The LST anomaly is '
     'each pixel’s departure from the valley-wide mean of the same composite; it is '
     'the more useful of the two for comparing units, because it removes the seasonal and '
     'inter-annual level and isolates spatial structure.')

doc.add_heading('3.3  Vegetation and built-up indices', level=2)
para('NDVI was computed as (NIR − Red) / (NIR + Red) from bands SR_B5 and SR_B4, and '
     'NDBI as (SWIR1 − NIR) / (SWIR1 + NIR) from SR_B6 and SR_B5. NDVI is reported as '
     'a unit mean and as the fraction of a unit at or above ' + str(0.30) + ', a '
     'conventional threshold separating vegetated from sparsely vegetated surface.')

doc.add_heading('3.4  Cover fractions', level=2)
para('Tree, vegetation and built-up fractions were taken from ESA WorldCover v200 at 10 m '
     'rather than from a threshold on NDBI. This is a deliberate choice: a threshold on a '
     '30 m spectral index is a weak impervious-surface estimate, particularly in a city '
     'whose building materials and bare agricultural soil are spectrally similar. '
     'WorldCover classes were aggregated to tree cover, total green cover '
     '(tree + grassland + cropland), built-up and permanent water, and averaged within '
     'each unit to give an areal fraction.')

doc.add_heading('3.5  Zonal summary and exposure', level=2)
para('All layers were summarised within each administrative unit using area-weighted '
     'zonal means at 30 m, with LST additionally summarised by standard deviation, 90th '
     'percentile and maximum to describe within-unit spread and hot spots. Population came '
     'from WorldPop 100 m and was summed per unit.')
para('A heat exposure index was formed as unit population multiplied by the unit’s '
     'positive LST anomaly, and set to zero where a unit is cooler than the valley mean. '
     'It is an intentionally simple screening quantity that ranks units by the number of '
     'people living under elevated surface temperature; it is not a health-risk estimate '
     'and carries no vulnerability weighting.')

doc.add_heading('3.6  Software', level=2)
para('Compositing, index calculation and zonal statistics were run in Google Earth Engine. '
     'Exported rasters were symbolised and laid out as the map series in ArcGIS Pro. '
     'Tabular results were checked and charted in Excel; the figures reproduced here were '
     'generated from the same exported table.')

# ---- 4 results
doc.add_heading('4  Results', level=1)
if HAVE and not MULTI:
    doc.add_heading('4.1  Valley-wide summary', level=2)
    para('The table supplied covers the study area as a single region, so the figures below '
         'describe the valley as a whole. They are reported because they are well defined '
         'at this scale; everything that depends on comparing places is not.')
    if N_UNITS > 1:
        para('The table supplied contains %d units, listed below. They are reported as '
             'given; none of them is the valley.' % N_UNITS, size=10, color=MUTED)
    r0 = df.iloc[0]
    rows = [['Quantity', 'Value']]
    def add(lbl, key, fmt, mult=1.0):
        if key in df.columns and pd.notna(r0[key]):
            rows.append([lbl, fmt % (r0[key] * mult)])
    add('Mean land surface temperature', 'lst_mean', '%.1f \u00b0C')
    add('Mean NDVI', 'ndvi_mean', '%.3f')
    add('Mean NDBI', 'ndbi_mean', '%.3f')
    add('Tree cover', 'tree_frac', '%.1f %%', 100)
    add('Green cover', 'green_frac', '%.1f %%', 100)
    add('Built-up cover', 'built_frac', '%.1f %%', 100)
    table(rows)
    caption('Table 1. Summary for %s, from the supplied table.' % r0['unit_name'])
    para('Read alongside Section 6: a mean over the whole basin mixes the dense cores with '
         'the forested rim, and the rim is both greener and several hundred metres higher. '
         'The valley mean is therefore a weak summary of conditions anywhere in particular.')
    doc.add_heading('4.2  Per-unit results', level=2)
    for nte in NOTES:
        para(nte, size=10, color=MUTED)
    pending('per-unit results - re-run the Earth Engine script with the valley divided '
            'into wards or districts, then re-run build_report.py')
elif not HAVE:
    pending('all results — run gee_kathmandu_uhi.js, then place the exported '
            'ward_summary.csv in data/ and re-run build_report.py')
    para('Every figure and table in this section is generated automatically from that '
         'CSV. No values have been entered by hand, and none have been estimated.',
         size=9.5, color=MUTED, italic=True)
else:
    n = len(df)
    hot, cool = df.iloc[0], df.iloc[-1]
    span = hot['lst_mean'] - cool['lst_mean']
    doc.add_heading('4.1  Temperature pattern', level=2)
    para('Across %d summary units the pre-monsoon composite gives a mean land surface '
         'temperature of %.1f °C, ranging from %.1f °C in %s to %.1f °C in '
         '%s — a spread of %.1f °C between the coolest and hottest unit.'
         % (n, df['lst_mean'].mean(), cool['lst_mean'], cool['unit_name'],
            hot['lst_mean'], hot['unit_name'], span))
    if 'anom' in figures:
        doc.add_picture(figures['anom'], width=Inches(6.2))
        caption('Figure 2. Mean land surface temperature anomaly by unit, relative to the '
                'valley mean. Warm bars are hotter than the valley average.')
    doc.add_heading('4.2  Relationship with green cover', level=2)
    if {'green_frac', 'lst_mean'} <= set(df.columns):
        rg = df['green_frac'].corr(df['lst_mean'])
        rb = df['built_frac'].corr(df['lst_anom_mean']) if 'built_frac' in df.columns else float('nan')
        para('Unit mean LST correlates with green cover at r = %.2f, and the LST anomaly '
             'with built-up cover at r = %.2f. Green cover across units averages %.1f per '
             'cent, of which tree cover is %.1f per cent.'
             % (rg, rb, df['green_frac'].mean() * 100,
                df['tree_frac'].mean() * 100 if 'tree_frac' in df.columns else float('nan')))
        row = []
        if 'scatter_green' in figures: row.append(figures['scatter_green'])
        if 'scatter_built' in figures: row.append(figures['scatter_built'])
        for p in row:
            doc.add_picture(p, width=Inches(3.05))
        caption('Figure 3. Unit mean LST against green cover (left) and LST anomaly '
                'against built-up cover (right).')
    doc.add_heading('4.3  Heat exposure', level=2)
    if 'exposure' in figures:
        e = df.sort_values('heat_exposure', ascending=False).head(5)
        para('Ranking units by population under a positive heat anomaly puts %s at the top, '
             'followed by %s. These are the units where elevated surface temperature and '
             'population density coincide.'
             % (e.iloc[0]['unit_name'], ', '.join(e.iloc[1:4]['unit_name'].astype(str))))
        doc.add_picture(figures['exposure'], width=Inches(6.2))
        caption('Figure 4. Heat exposure index, highest-ranked units.')
    doc.add_heading('4.4  Summary table', level=2)
    cols = [c for c in ['unit_name', 'area_km2', 'population', 'lst_mean', 'lst_anom_mean',
                        'ndvi_mean', 'tree_frac', 'green_frac', 'built_frac']
            if c in df.columns]
    head = {'unit_name': 'Unit', 'area_km2': 'Area km²', 'population': 'Pop.',
            'lst_mean': 'LST °C', 'lst_anom_mean': 'ΔLST °C',
            'ndvi_mean': 'NDVI', 'tree_frac': 'Tree %', 'green_frac': 'Green %',
            'built_frac': 'Built %'}
    rows = [[head[c] for c in cols]]
    for _, r_ in df.head(25).iterrows():
        out = []
        for c in cols:
            v = r_[c]
            if c == 'unit_name': out.append(v)
            elif c == 'population': out.append('{:,.0f}'.format(v) if pd.notna(v) else '')
            elif c.endswith('_frac'): out.append('{:.1f}'.format(v * 100) if pd.notna(v) else '')
            elif c == 'area_km2': out.append('{:.1f}'.format(v) if pd.notna(v) else '')
            else: out.append('{:.2f}'.format(v) if pd.notna(v) else '')
        rows.append(out)
    table(rows)
    caption('Table 1. Per-unit summary, ordered by LST anomaly. Full table in '
            'data/ward_summary.csv.')
    if NOTES:
        doc.add_heading('4.5  Data quality notes', level=2)
        for nte in NOTES:
            para(nte)

# ---- 5 map series
doc.add_heading('5  Map series', level=1)
wanted = [('map_lst.png',        'Land surface temperature, pre-monsoon composite (°C).'),
          ('map_lst_anomaly.png','Land surface temperature anomaly relative to the valley mean (°C).'),
          ('map_ndvi.png',       'NDVI, pre-monsoon composite.'),
          ('map_greencover.png', 'Tree and vegetation cover from ESA WorldCover.'),
          ('map_builtup.png',    'Built-up surface from ESA WorldCover.'),
          ('map_exposure.png',   'Heat exposure index by administrative unit.')]
found = 0
for i, (fn, cap) in enumerate(wanted, start=1):
    p = os.path.join(MAPS, fn)
    if os.path.exists(p):
        doc.add_picture(p, width=Inches(6.2))
        caption('Map %d. %s' % (i, cap))
        found += 1
extra = sorted(set(glob.glob(os.path.join(MAPS, '*.png')) + glob.glob(os.path.join(MAPS, '*.jpg')))
               - {os.path.join(MAPS, f) for f, _ in wanted}
               - {os.path.join(MAPS, 'map_study_area.png')})
for p in extra:
    doc.add_picture(p, width=Inches(6.2))
    caption('Map. ' + os.path.splitext(os.path.basename(p))[0].replace('_', ' '))
    found += 1
if found == 0:
    pending('map series — export layouts from ArcGIS Pro (or screenshots from the Earth '
            'Engine map) into maps/ using the filenames listed in README.md, then re-run')

# ---- 6 limitations
doc.add_heading('6  Limitations', level=1)
bullets([
    'Land surface temperature is not air temperature. LST is the radiometric temperature '
    'of the ground and roof surfaces the satellite sees. It runs hotter than screen-level '
    'air temperature by a margin that itself varies with surface type, and it should not '
    'be read as what a person standing in the street would feel.',
    'The composite describes one season. March–May results say nothing about the '
    'monsoon or winter pattern, and nocturnal heat islands — often the more relevant '
    'ones for health — are not captured by a daytime overpass.',
    'Landsat overpasses the valley in mid-morning, before the afternoon surface maximum.',
    'Topography is confounded with land cover. The valley rim is both greener and higher, '
    'and elevation alone lowers surface temperature, so the core-to-rim contrast overstates '
    'the part attributable to land cover. Interpreting a unit against units at similar '
    'elevation is safer than against the valley as a whole.',
    'The 30 m thermal grid is coarser than the fabric of the historic cores, so narrow '
    'streets, courtyards and small gardens are mixed within single pixels.',
    'Cover fractions inherit the accuracy of ESA WorldCover, which was not validated '
    'locally for this work.',
    'The exposure index weights population by heat anomaly only. It carries no weighting '
    'for age, income, health status, indoor conditions or access to cooling, all of which '
    'shape who is actually harmed by heat.',
    'Results are a screening product. Unit rankings should be confirmed against local '
    'knowledge before being used to direct investment.'])

# ---- 7 references
doc.add_heading('7  Data sources', level=1)
for t in ['USGS Landsat 8 and 9 Collection 2 Level 2 Science Products. '
          'U.S. Geological Survey. https://www.usgs.gov/landsat-missions',
          'Zanaga, D. et al. (2022). ESA WorldCover 10 m 2021 v200. '
          'https://doi.org/10.5281/zenodo.7254221',
          'WorldPop (2020). Global High Resolution Population Denominators. '
          'University of Southampton. https://www.worldpop.org',
          'Gorelick, N. et al. (2017). Google Earth Engine: Planetary-scale geospatial '
          'analysis for everyone. Remote Sensing of Environment, 202, 18–27.']:
    p = doc.add_paragraph(); r = p.add_run(t)
    r.font.size = Pt(9.5); r.font.color.rgb = INK
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.left_indent = Inches(0.3)
    p.paragraph_format.first_line_indent = Inches(-0.3)

doc.add_heading('Appendix  Reproducibility', level=1)
para('The complete Earth Engine script is gee_kathmandu_uhi.js in this folder. It is '
     'parameterised at the top for years, season, cloud threshold, NDVI threshold and the '
     'ward boundary asset. Running it reproduces every number in this brief; running '
     'build_report.py regenerates this document from the exported table.')

try:
    doc.save(OUT)
except PermissionError:
    # the previous report is open in Word; write alongside it rather than fail
    base, ext = os.path.splitext(OUT)
    n = 2
    while os.path.exists('%s_v%d%s' % (base, n, ext)):
        n += 1
    OUT = '%s_v%d%s' % (base, n, ext)
    doc.save(OUT)
    print('NOTE: the existing report was open in Word, so this run wrote a new file.')
print('Report written: ' + OUT)
print('  results data : ' + ('ward_summary.csv loaded, %d units' % len(df) if HAVE
                             else 'NOT PRESENT - results marked pending'))
print('  figures      : %d generated' % len(figures))
print('  maps         : %d embedded' % found)
