"""H00 wide-band FER qualification; no pulsating wind, drift or time-domain solve."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import uuid

from aqwa_profile import DIRECTION, checked_bytes, verified_inputs
from aqwa_fer_sea_state import jonswap, native_statistics
from aqwa_fer_trial import read_fer_trial
from aqwa_frequency import CARD
from aqwa_frequency_jobs import timestamp, write_status
from aqwa_frequency_results import AXES, extract
from aqwa_sea_preflight import energy_fraction, sea_plan
from aqwa_config import OUTPUT, WORK, solver_path

FINE=(.04,.05,.06,.07,.0715,.0721,.0725,.0729,.0732,.0736,.0745,.076,
      .08,.10,.125,.16,.20,.24,.28)
COARSE=tuple(f for f in FINE if f not in (.0721,.0729,.0736,.076))
WIDE_SHA={
    'DAT':'97357c4c585a9850a947cb3a9e07dec4e2770fe1f0d87dc64da370030c90ec31',
    'LIS':'ce73ff51f4f5b3908fee49fcb3189e5ddb3e35175d6a76149c9b4d163196ce2d',
    'HYD':'2e48524edfd0ad4230ad4a082ad7fe65db9a6b731bcb964e9109c638596557d1',
    'RES':'d38f4283e7927d34f2f93983dedbf59a403d2d645e4a0ff1b92fbcd692885efb',
}
ROOT=WORK/'full_sea_runs'
OUT=OUTPUT/'full_sea_runs'
FACTORS=(.75,1.25)
KEYS=('motion_standard_deviation','fairlead_dynamic_tension_standard_deviation_n')
ROTATION=('roll','pitch','yaw')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _supply():
    return {ext: checked_bytes('wide.' + ext.lower()) for ext in WIDE_SHA}


def preview_h00_full_sea(sea_state, source_kind, source_note):
    """Preflight a sourced H00 long-crested JONSWAP sea state."""
    supply=_supply()
    plan=sea_plan(sea_state,source_kind,source_note,(FINE[0],FINE[-1]) if supply else None)
    plan['line_database_verified']=bool(supply)
    if supply:
        band=plan['reference_wave_band_hz']
        wide=plan['wide_check_band_hz']
        if wide:
            plan['comparison_cases']=[
                {'label':name,'band_hz':b,'grid':grid,'rotational_damping_scale':factor}
                for name,b,grid,factor in (
                    ('coarse_grid',band,'coarse',1.),('reference',band,'fine',1.),
                    ('wider_band',wide,'fine',1.),
                    ('damping_low',wide,'fine',FACTORS[0]),('damping_high',wide,'fine',FACTORS[1]))]
        plan['line_artifact_sha256']=WIDE_SHA
        plan['staged_equilibrium_sha256']=digest(verified_inputs()['EQP'])
    return {**plan,'preview_sha256':digest(json.dumps(plan,sort_keys=True,allow_nan=False).encode('utf-8'))}


def card(key,values,first=None,second=None):
    idx=''.join(' '*5 if n is None else f'{n:5d}' for n in (first,second))
    body=[(f'{v:.6g}' if len(f'{v:.6g}')<=10 else f'{v:.4g}').rjust(10) for v in values]
    if any(len(x)!=10 for x in body):
        raise ValueError('AQWA record exceeds field width.')
    return '      '+key+idx+''.join(body)


def build_fer(base,spec,band,grid,scale,source,mats,loads):
    line=source.split('          FDR1',1)[1].split(' END',1)[0]
    headings=[x for x in line.splitlines() if x.startswith('     1DIRN')]
    deck=['          FDR1']+[f'     1HRTZ{i:5}{i:5}{f:10.6f}' for i,f in enumerate(grid,1)]+headings+[' END','          WFS1']
    # Same published LINE hydrostatic values used in the accepted eight-point replay.
    h=[[0.]*6 for _ in range(6)]
    h[2][2:]=[5.51981e6,378.225,21.8025,0]
    h[3][2:]=[378.225,1.34760e9,-3523.6,-22328.6]
    h[4][2:]=[21.8025,-3523.6,1.34764e9,-13878.7]
    deck.extend(card('LSTF',r,second=i) for i,r in enumerate(h,1))
    deck.extend((card('ZCGE',[2.8499099]),card('BFEQ',[7956000*9.80665])))
    for i,f in enumerate(grid,1):
        deck.append(card('HRTZ',[f],second=i))
        for key,tag in (('WAMS','added_mass'),('WDMP','radiation_damping')):
            deck.extend(card(key,r,1,j) for j,r in enumerate(mats[f][tag]['values'],1))
        for i_d,d in enumerate(DIRECTION,1):
            deck.append(card('DIRN',[d],second=i_d))
            components=loads[f,d]
            v=[components[a][k] for a in AXES for k in ('amplitude','phase_deg')]
            deck.extend((card('TDIF',v[:6]),card('RDIF',v[6:]),card('TFKV',[0]*6),card('RFKV',[0]*6)))
    fids=re.findall(r'(?m)^      FIDP[^\n]*',source)
    aids=re.findall(r'(?m)^      AIDP[^\n]*',source)
    if len(fids)!=6 or len(aids)!=3:
        raise ValueError('Missing original H00 additional damping records.')
    deck+=fids
    for row,c in zip((4,5,6),(3.2e7,3.2e7,8e7)):
        v=[0.]*6
        v[row-1]=c*scale
        deck.append(card('AIDP',v,second=row))
    deck+=[' END','          NONE']
    solve=jonswap(base,spec,band)
    marker=b'RESTART  4  5'
    if solve.count(marker)!=1 or solve.count(b'OPTIONS RDEP CRAO')!=1:
        raise ValueError('Unexpected FER input template.')
    return solve.replace(b'OPTIONS RDEP CRAO',b'OPTIONS CRNM RDEP CRAO').replace(
        marker,b'RESTART  2  5\r\n'+'\r\n'.join(deck).encode('ascii'))


def _folder(run_id):
    if not isinstance(run_id,str) or not re.fullmatch(r'[a-f0-9]{32}',run_id):
        raise ValueError('Use the 32-character full sea run_id.')
    p=ROOT/run_id
    if not p.is_dir() or p.resolve()!=p:
        raise ValueError('Full sea run not found.')
    return p


def _state(run_id):
    p=_folder(run_id)/'frequency_job.json'
    if p.resolve(strict=True)!=p:
        raise ValueError('Unexpected full sea status path.')
    s=json.loads(p.read_text(encoding='utf-8'))
    if s.get('run_id')!=run_id or s.get('case')!='H00':
        raise ValueError('Full sea run identifiers do not match.')
    return s


def get_h00_full_sea(run_id):
    s=_state(run_id)
    if s['status'] in ('queued','running') and (
            datetime.now(timezone.utc)-datetime.fromisoformat(s['updated_at'])).total_seconds()>120:
        return {**s,'status':'unresponsive','reason':'No recent solver progress. Inspect the run worker log.'}
    return s


def start_h00_full_sea(sea_state, source_kind, source_note, expected_preview_sha256):
    p=preview_h00_full_sea(sea_state,source_kind,source_note)
    if expected_preview_sha256!=p['preview_sha256']:
        raise ValueError('Use the current full sea preview checksum.')
    if not p['ready_for_native_comparison']:
        raise ValueError('A verified wider LINE database or a padded comparison band is missing. No solver job started.')
    solver_path()
    rid=uuid.uuid4().hex
    folder=ROOT/rid
    folder.mkdir(parents=True)
    state={**p,'run_id':rid,'status':'queued','created_at':timestamp()}
    write_status(folder,state)
    try:
        with (folder/'worker_console.txt').open('xb') as log:
            subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),rid],cwd=folder,
                             stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,close_fds=True,
                             creationflags=getattr(subprocess,'DETACHED_PROCESS',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
    except OSError as exc:
        state.update(status='failed',reason=str(exc))
        write_status(folder,state)
    return state


def changes(reference,candidate):
    result={}
    for k in KEYS:
        result[k]={}
        for name,a in reference[k].items():
            b=candidate[k][name]
            floor=5. if k==KEYS[1] else (.005 if name in ROTATION else .0005)
            delta=abs(b-a)
            result[k][name]={'reference':a,'candidate':b,'absolute_change':delta,
                             'relative_to_reference':delta/abs(a) if a else None,
                             'passes_internal_screen':delta<=max(.05*abs(a),floor)}
    return result


def solve_fer(folder,case,p,supply,base,source,mats,loads):
    grid=FINE if case['grid']=='fine' else COARSE
    files={'DAT':build_fer(base['DAT'],p['sea_state'],case['band_hz'],grid,case['rotational_damping_scale'],source,mats,loads),
           'EQP':base['EQP'],'HYD':supply['HYD'],'RES':supply['RES']}
    folder.mkdir()
    for ext,raw in files.items():
        with (folder/f'H00_FER.{ext}').open('xb') as f:
            f.write(raw)
    lis=folder/'H00_FER.LIS'
    with (folder/'solver_console.txt').open('xb') as log:
        s=subprocess.run([str(solver_path()),'/nowind','H00_FER'],cwd=folder,stdin=subprocess.DEVNULL,
                         stdout=log,stderr=subprocess.STDOUT,timeout=90,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    mes=folder/'H00_FER.MES'
    if s.returncode or (mes.exists() and mes.stat().st_size):
        raise ValueError(f'FER failed; inspect {lis}.')
    result=read_fer_trial(lis,frequencies=grid)
    if result['diagnostics'] and not (case['label'].startswith('damping_') and all(
            x['kind']=='low_damping' for x in result['diagnostics'])):
        raise ValueError(f'Unaccepted FER warnings: {result["diagnostics"]}; inspect {lis}.')
    wave=native_statistics(lis.read_text(encoding='latin-1'),result['trial_significant_motion_amplitude'],
                           p['sea_state'],case['band_hz'])
    omega=[r['omega_rad_s'] for r in wave['integration_rows_native']]
    if omega[0]<grid[0]*math.tau-.00005 or omega[-1]>grid[-1]*math.tau+.00005:
        raise ValueError('At least one native response point is outside the solved LINE database.')
    spec=p['sea_state']
    target_hs=spec['hs_m']*math.sqrt(energy_fraction(spec['tp_s'],spec['gamma'],*case['band_hz']))
    if abs(wave['native_band_limited_significant_wave_height_m']-target_hs)>max(.001,.02*target_hs):
        raise ValueError('Native realized Hs does not match the independent spectral variance check.')
    peaks={}
    for mode in ROTATION:
        branch=[(r['frequency_hz'],r['motion'][mode]['amplitude']) for r in result['raw_recalculated_rao']
                if r['direction_deg']==spec['direction_deg']]
        f,v=max(branch,key=lambda x:x[1])
        peaks[mode]={'frequency_hz':f,'amplitude_deg_per_m':v}
    return {**case,'line_frequency_hz':grid,'diagnostics':result['diagnostics'],'lis':str(lis),
            'source_lis_sha256':result['lis_sha256'],'sampled_rao_peaks_not_continuous':peaks,
            'input_sha256':{k:digest(v) for k,v in files.items()},**wave}


def worker(run_id):
    folder=_folder(run_id)
    state=_state(run_id)
    if state['status']!='queued':
        raise ValueError('Full sea job is not queued.')
    with (folder/'.worker_started').open('x'):
        pass
    def publish(status,**extra):
        state.update(status=status,**extra)
        write_status(folder,state)
    try:
        sr=state['sea_state_source']
        p=preview_h00_full_sea(state['sea_state'],sr['kind'],sr['note'])
        if p['preview_sha256']!=state['preview_sha256'] or not p['ready_for_native_comparison']:
            raise ValueError('Full sea plan changed since submission.')
        publish('running',stage='read_LINE_coefficients',completed_cases=[])
        supply=_supply()
        source=supply['DAT'].decode('ascii')
        # Confirm no model changes in the wide LINE run beyond sampling.
        edge=checked_bytes('edge.dat')
        if re.sub(CARD,b'',edge)!=re.sub(CARD,b'',supply['DAT']):
            raise ValueError('Wide LINE case changed beyond frequency sampling.')
        mats,loads=extract(supply['LIS'].decode('latin-1'),FINE,DIRECTION,max_frequency_hz=FINE[-1])
        mf={r['frequency_hz']:r for r in mats}
        lf={(r['frequency_hz'],r['direction_deg']):r['components'] for r in loads}
        base=verified_inputs()
        results={}
        damping_failures={}
        for case in p['comparison_cases']:
            label=case['label']
            publish('running',stage=label,completed_cases=list(results))
            try:
                results[label]=solve_fer(folder/label,case,p,supply,base,source,mf,lf)
            except (ValueError,OSError,subprocess.TimeoutExpired) as exc:
                if not label.startswith('damping_'):
                    raise
                damping_failures[label]=str(exc)
        refin=changes(results['reference'],results['coarse_grid'])
        wide=changes(results['wider_band'],results['reference'])
        numeric=all(m['passes_internal_screen'] for group in (refin,wide) for k in group.values() for m in k.values())
        damping={n:{'changes':changes(results['wider_band'],results[n]),'solver_diagnostics':results[n]['diagnostics']}
                 for n in ('damping_low','damping_high') if n in results}
        flags=bool(damping_failures) or any(v['solver_diagnostics'] for v in damping.values())
        report={**p,'run_id':run_id,'status':'computed_diagnostics_only','formal_site_result':False,
                'numerical_screen_pass':numeric,'damping_sensitivity_warning':flags,'damping_case_failures':damping_failures,
                'frequency_grid_comparison':refin,'frequency_band_comparison':wide,'damping_sensitivity':damping,
                'threshold':'Internal single-step screen: 5% or absolute floor (0.0005 m / 0.005 deg / 5 N), not a code/design acceptance.',
                'damping_model':'Only B44/B55/B66 of the trial set scaled, fixed underlying radiation and B33. Not calibrated.',
                'native_cases':results,'pulse_wind_or_time_domain':False}
        out=OUT/run_id
        out.mkdir(parents=True,exist_ok=False)
        target=out/'sea_state_qualification.json'
        raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode('utf-8')
        with target.open('xb') as f:
            f.write(raw)
        publish('completed',stage='report',completed_cases=list(results),report_json=str(target),
                report_sha256=digest(raw),numerical_screen_pass=numeric,damping_sensitivity_warning=flags)
    except Exception as exc:
        publish('failed',reason=str(exc))
        raise


def read_h00_full_sea(run_id):
    s=_state(run_id)
    if s['status']!='completed':
        raise ValueError('The full sea run has no completed report.')
    p=OUT/run_id/'sea_state_qualification.json'
    if p.resolve(strict=True)!=p:
        raise ValueError('Unexpected full sea report path.')
    raw=p.read_bytes()
    if digest(raw)!=s['report_sha256']:
        raise ValueError('Full sea report hash differs from completed status.')
    return {**json.loads(raw),'report_json':str(p)}


if __name__=='__main__' and len(sys.argv)==2:
    worker(sys.argv[1])
