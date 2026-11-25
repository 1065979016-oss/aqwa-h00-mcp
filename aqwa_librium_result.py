"""Parse the saved H00 AQWA-LIBRIUM equilibrium."""
import re

FLOAT = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[Ee][+-]?\d+)?'

NATIVE_SECTIONS = ('E Q U I L I B R I U M   S O L U T I O N',
                   'M O O R I N G   F O R C E S   A N D   S T I F F N E S S')

def read_native_equilibrium(path):
    path = path.resolve(strict=True)
    raw = path.read_text(encoding='latin-1')
    if ('FINISH DATE' not in raw or 'TERMINATED WITH ERRORS' in raw or
            any(heading not in raw for heading in NATIVE_SECTIONS) or
            re.search(r'\*{3,}\s*(?:(?:ANALYSIS )?WARNING|(?:INPUT DATA )?ERROR|FATAL)',raw,re.I)):
        raise ValueError('Native equilibrium output failed acceptance checks.')
    hydro = raw.split('EQUILIBRIUM POSITION WITH RESPECT TO FRA',1)[-1]
    mooring = raw.rsplit(NATIVE_SECTIONS[1],1)[1]
    xyz, angles = [], []
    for axis in 'XYZ':
        m = re.search(rf'(?m)^\s*{axis}\s*=\s*({FLOAT})\s+R{axis}\s*=\s*({FLOAT})',hydro)
        if not m:
            raise ValueError('Missing equilibrium pose.')
        p,a = map(float,m.groups()); xyz.append(p); angles.append(a)
    tension = re.findall(rf'(?m)^\s*([123])\s+COMP\s+{FLOAT}\s+{FLOAT}\s*9700[159]\s+({FLOAT})\s+',mooring)
    if [i for i,_ in tension] != ['1','2','3']:
        raise ValueError('Missing or ambiguous H00 equilibrium tensions.')
    modes = [float(x) for x in re.findall(rf'(?m)^\s*[1-6]\s+({FLOAT})\s+STABLE[ \t]*$',raw)]
    if len(modes)!=6 or min(modes)<=0:
        raise ValueError('H00 positive stability was not confirmed for six modes.')
    iterations = raw.split('I T E R A T I O N   T O W A R D S',1)[-1].split('HYDROSTATIC FORCES',1)[0]
    rows = re.findall(r'(?m)^\s*\d+\s+1' + (r'\s+('+FLOAT+r')')*12 + r'[ \t]*$',iterations)
    if not rows:
        raise ValueError('Missing final equilibrium residuals.')
    final = list(map(float, rows[-1]))
    return {'cog_xyz_fra_m':xyz,'rotation_xyz_fra_deg':angles,'fairlead_tension_n':[float(x) for _,x in tension],
            'force_residual_n':final[6:9],'moment_residual_nm':final[9:12],
            'six_positive_static_modes':True,'lis':str(path)}
