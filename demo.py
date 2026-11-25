"""Offline synthetic report example. This module never starts the AQWA solver."""
import argparse
from html import escape
import json
from pathlib import Path

from aqwa_full_sea_batch import FINE, LINES, MOTIONS, _html
from aqwa_sea_preflight import sea_plan

ROOT = Path(__file__).resolve().parent
DATA = {
    # Invented values, not exported or fitted from an AQWA run.
    (.5,12.5,3.3,0): ((.18,.004,.08,.021,.79,.008), (1800,950,1100)),
    (.5,12.5,3.3,90): ((.04,.15,.10,.92,.26,.013), (940,1550,1320)),
}


def get_h00_replay_example():
    """Read the bundled synthetic fixture; compute only analytical coverage."""
    source = json.loads((ROOT/'examples'/'sea_states.json').read_text(encoding='utf-8'))
    support = (FINE[0], FINE[-1])
    rows = []
    for entry in source:
        p = sea_plan(entry['sea_state'],entry['source_kind'],entry['source_note'],support)
        row = {'case_name':entry['case_name'],'sea_state':p['sea_state'],
               'sea_state_source':p['sea_state_source'],
               'wide_check_band_energy_fraction':p['wide_check_band_energy_fraction'],
               'minimum_suggested_hydrodynamic_endpoints_hz':p['minimum_suggested_hydrodynamic_endpoints_hz'],
               'status':'blocked'}
        if p['ready_for_native_comparison']:
            key = tuple(p['sea_state'][k] for k in ('hs_m','tp_s','gamma','direction_deg'))
            if key not in DATA:
                raise ValueError('This offline example cannot produce results for new sea states.')
            motion, lines = DATA[key]
            row.update(status='completed', result={
                'usable_for_numerical_comparison':True, 'native_band_hz':p['wide_check_band_hz'],
                'motion_standard_deviation':dict(zip(MOTIONS,motion)),
                'motion_units':{k:('deg' if k in ('roll','pitch','yaw') else 'm') for k in MOTIONS},
                'fairlead_dynamic_tension_standard_deviation_n':dict(zip(LINES,lines)),
                'max_grid_relative_change':.002,'max_band_relative_change':.014,
                'damping_sensitivity_warning':True})
        rows.append(row)
    return {'case':'H00','status':'partial','data_mode':'synthetic_replay','solver_invoked':False,
            'completed_count':sum(r['status']=='completed' for r in rows),'cases':rows,
            'mean_wind_m_s':8,'fluctuating_wind_modeled':False,'time_domain_run':False,
            'formal_site_result':False,'verified_hydrodynamic_band_hz':support}


def chart_svg(report):
    """Create a clean, browser-independent preview for the repository README."""
    rows = [r for r in report['cases'] if r['status']=='completed']
    width, height = 880, 344
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
           '<title id="title">H00 roll and pitch standard deviation – synthetic replay</title>',
           '<desc id="desc">Two synthetic example sea states show different roll and pitch motion. No AQWA run.</desc>',
           '<rect width="880" height="344" fill="#f1f5f9" rx="16"/>',
           '<g font-family="system-ui, sans-serif" fill="#102941">',
           '<text x="34" y="45" font-size="26" font-weight="700">H00 · Frequency-domain batch automation</text>',
           '<text x="34" y="75" font-size="15" fill="#465d73">OFFLINE REPLAY · SYNTHETIC EXAMPLE · NO AQWA SOLVE</text>']
    for key,label,x,color in (('roll','Roll',34,'#117c83'),('pitch','Pitch',454,'#315ea9')):
        svg.append(f'<rect x="{x}" y="100" width="392" height="178" rx="10" fill="white" stroke="#d7e1eb"/>')
        svg.append(f'<text x="{x+17}" y="133" font-size="18" font-weight="650">{label} standard deviation (deg)</text>')
        for i,row in enumerate(rows):
            y = 160 + 40*i
            heading = row['sea_state']['direction_deg']
            value = row['result']['motion_standard_deviation'][key]
            svg.extend((f'<text x="{x+17}" y="{y+15}" font-size="14">{escape(str(heading))}° heading</text>',
                        f'<rect x="{x+116}" y="{y}" width="207" height="17" rx="3" fill="#e6eef5"/>',
                        f'<rect x="{x+116}" y="{y}" width="{207*value:.3f}" height="17" rx="3" fill="{color}"/>',
                        f'<text x="{x+331}" y="{y+14}" font-size="13">{value:.3f}</text>'))
        svg.append(f'<text x="{x+116}" y="261" font-size="12" fill="#465d73">Common scale: 0–1°</text>')
    svg.append('<text x="34" y="314" font-size="15" fill="#465d73">2 example results · 1 out-of-band case rejected in preflight</text></g></svg>')
    return '\n'.join(svg) + '\n'


def main():
    parser = argparse.ArgumentParser(description='Build a synthetic H00 report without AQWA.')
    parser.add_argument('--out',type=Path,default=Path('demo-output'),help='new output directory')
    opts = parser.parse_args()
    opts.out.mkdir(parents=True,exist_ok=False)
    report = get_h00_replay_example()
    (opts.out/'comparison.html').write_text(_html(report),encoding='utf-8')
    (opts.out/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (opts.out/'overview.svg').write_text(chart_svg(report),encoding='utf-8')
    print(opts.out/'comparison.html')


if __name__=='__main__':
    main()
