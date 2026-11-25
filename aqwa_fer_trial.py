"""Read the H00 three-frequency moored transfer commissioning result."""
import hashlib
import re

from aqwa_frequency import DOF, match_frequency_row
from aqwa_librium_result import FLOAT, read_native_equilibrium
from aqwa_profile import checked_path

FREQ = (.06,.08,.12)

DIRECTION = (-180.,-90.,0.,90.,180.)

def diagnose_fer_report(raw):
    return [line.strip() for line in raw.splitlines() if re.match(
        r'\s*\*{3,}\s*(?:(?:ANALYSIS )?WARNING|(?:INPUT DATA )?ERROR|FATAL|TERMINATED WITH ERRORS)',line,re.I)]

def read_fer_trial(path, digest=None, frequencies=FREQ):
    source = path.read_bytes()
    actual = hashlib.sha256(source).hexdigest()
    if digest is not None and actual!=digest:
        raise ValueError('AQWA-FER trial report does not match the verified source.')
    raw = source.decode('latin-1')
    if 'FINISH DATE' not in raw or 'TERMINATED WITH ERRORS' in raw or 'NUMBER OF LINES=  3' not in raw:
        raise ValueError('AQWA-FER trial did not finish with all three mooring lines.')
    eq = read_native_equilibrium(checked_path('equilibrium.lis'))
    pos = re.search(r'(?m)^[ \t]+1\s+1\s+1' + (r'[ \t]+('+FLOAT+r')')*6+r'[ \t]*\r?$',
                    raw.split('TRANSLATIONAL POSITION(FRA)',1)[-1])
    if not pos or list(map(float,pos.groups())) != eq['cog_xyz_fra_m']+eq['rotation_xyz_fra_deg']:
        raise ValueError('The reported AQWA-FER starting position does not match the 8 m/s equilibrium.')
    rao = raw.split('RECALCULATED R.A.O.S-VARIATION WITH WAVE PERIOD/FREQUENCY',1)[-1].split(
        'RECALCULATED R.A.O.S-VARIATION WITH WAVE DIRECTION',1)[0]
    rows, seen, direction = [], set(), None
    for line in rao.splitlines():
        fields = line.split()
        if len(fields) not in (14,15) or not all(re.fullmatch(FLOAT,f) for f in fields):
            continue
        period,omega,*amplitude_phase = map(float,fields)
        if len(amplitude_phase)==13:
            direction=amplitude_phase.pop(0)
        f=match_frequency_row(period,omega,frequencies)
        key=(direction,f)
        if key in seen:
            raise ValueError('Duplicate native RAO point.')
        seen.add(key)
        rows.append({'frequency_hz':f,'direction_deg':direction,'motion':{
            dof:{'amplitude':v,'phase_deg':p,'amplitude_unit':'m/m' if i<3 else 'deg/m'}
            for i,(dof,v,p) in enumerate(zip(DOF,amplitude_phase[::2],amplitude_phase[1::2]))}})
    if seen!={(d,f) for d in DIRECTION for f in frequencies}:
        raise ValueError('Native RAO frequency/direction coverage incomplete.')
    title='S I G N I F I C A N T   M O T I O N S   O F   C E N T R E   O F   G R A V I T Y'
    section=raw.split(title,1)[-1].split('S I G N I F I C A N T   V E L O C I T I E S',1)[0]
    amplitude = re.search(r'(?m)^[ \t]+1[ \t]+1'+(r'[ \t]+('+FLOAT+r')')*6+r'[ \t]*\r?$',section)
    if not amplitude or not any(float(v)>0 for v in amplitude.groups()):
        raise ValueError('Missing/nonpositive trial wave-response summary; check restart preserved excitation.')
    flags=diagnose_fer_report(raw)
    return {'case':'H00','status':'diagnostic_only_not_for_design','solver_finished':True,
            'mean_wind_pose_matched':True,'mooring_line_count':3,'wave_excitation_only':True,
            'spectrum':'synthetic UDEF for commissioning only; not project sea state',
            'fluctuating_wind_modeled':False,'peak_or_spectrum_converged':False,
            'axis':'solver recalculated RAO table; phases in degrees',
            'diagnostics':[{'kind':'low_damping' if 'DAMPING' in flag else 'solver_diagnostic','message':flag} for flag in flags],
            'trial_significant_motion_amplitude':dict(zip(DOF,map(float,amplitude.groups()))),
            'raw_recalculated_rao':rows,'lis':str(path),'lis_sha256':actual}
