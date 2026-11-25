"""Band-limited H00 JONSWAP input and native FER spectral statistics."""
import math
import re

from aqwa_frequency import DOF
from aqwa_librium_result import FLOAT

BAND=(.06,.12)
DIRECTIONS=(-180,-90,0,90,180)
RESPONSE='R E S P O N S E   S P E C T R U M'


def jonswap(data, spec, band=BAND):
    if not isinstance(spec,dict) or set(spec)!={'hs_m','tp_s','gamma','direction_deg'}:
        raise ValueError('JONSWAP requires hs_m, tp_s, gamma and direction_deg.')
    hs,tp,gamma,direction=(spec[k] for k in ('hs_m','tp_s','gamma','direction_deg'))
    if any(type(v) not in (float,int) or not math.isfinite(v) for v in (hs,tp,gamma,direction)):
        raise ValueError('JONSWAP parameters must be finite numbers.')
    if not .05<=hs<=5 or not 1<=gamma<=7 or not 9<=tp<=16 or direction not in DIRECTIONS:
        raise ValueError('Test limits: Hs 0.05–5 m, Tp 9–16 s, gamma 1–7; direction must match the database (-180/-90/0/90/180).')
    if not isinstance(band,(list,tuple)) or len(band)!=2 or not all(
            type(f) in (int,float) and math.isfinite(f) for f in band) or not .02<=band[0]<1/tp<band[1]<=.6:
        raise ValueError('Invalid JONSWAP band; include peak and use supported bounds.')
    source=data.decode('ascii')
    def field(values):
        return ''.join(f'{v:10.7g}' for v in values)
    block='\r\n'.join(['          SPEC','      HRTZ','      SPDN'+' '*10+field((direction,)),
                      '      JONH'+' '*10+field((*band,gamma,hs,1/tp)),' END',''])
    result,n=re.subn(r'(?ms)^          SPEC\r?\n.*?^ END\r?\n',lambda _:block,source)
    if n!=1:
        raise ValueError('Expected one FER spectrum deck.')
    return result.encode('ascii')


def native_statistics(raw, motion, spec, band=BAND):
    j=re.search(r'(?m)^\s*1[ \t]+JONSWAP[ \t]+\d+[ \t]+\d+'+(r'[ \t]+('+FLOAT+r')')*6,raw)
    wave=re.search(rf'(?m)^[ \t]+1[ \t]+1[ \t]+({FLOAT})[ \t]+YES[ \t]+({FLOAT})[ \t]+(?:YES|NO)[ \t]+SINGLE DIRECTIONAL WAVES',raw)
    if not j or not wave:
        raise ValueError('Missing native JONSWAP settings or realized wave height.')
    lo,hi,gamma,_,peak,direction=map(float,j.groups())
    wave_dir,realized_hs=map(float,wave.groups())
    if any(abs(x-y)>.00006 for x,y in ((lo,band[0]*math.tau),(hi,band[1]*math.tau),
                                       (gamma,spec['gamma']),(peak,math.tau/spec['tp_s']))) or any(
         abs((d-spec['direction_deg']+180)%360-180)>.01 for d in (direction,wave_dir)) or realized_hs<=0:
        raise ValueError('Native spectrum settings do not match the preview.')
    sections=list(re.finditer(r'(?m)^\s*\* \* \* \* (.*?)\s+\* \* \* \*[ \t]*$',raw))
    spectra=[]
    for i,heading in enumerate(sections[:-1]):
        if heading[1]!=RESPONSE:
            continue
        section=raw[heading.end():sections[i+1].start()]
        if 'IN FRA AXIS FRAME' not in section:
            raise ValueError('Expected fixed reference axes for response density.')
        row_pattern=r'(?m)^[ \t]+(\d+)'+(r'[ \t]+('+FLOAT+r')')*8+r'[ \t]*$'
        for row in re.findall(row_pattern,section):
            idx,omega,sea,*values=map(float,row)
            if any(v<0 for v in (sea,*values)):
                raise ValueError('Negative response density in solver report.')
            spectra.append({'index':int(idx),'omega_rad_s':omega,'wave_ordinate_per_rad_s':sea,
                            'response_ordinate_per_rad_s':dict(zip(DOF,values))})
    if (len(spectra)<3 or [row['index'] for row in spectra]!=list(range(1,len(spectra)+1)) or
        any(x['omega_rad_s']>=y['omega_rad_s'] for x,y in zip(spectra,spectra[1:]))):
        raise ValueError('Missing, duplicate or unordered spectrum integration results.')
    section=raw.split('S I G N I F I C A N T   T E N S I O N S   I N   T H E   M O O R I N G   L I N E S',1)[-1]
    if not re.search(r'FROM NODE\s*-\s*97001\( 1\)\s+97005\( 1\)\s+97009\( 1\)',section):
        raise ValueError('Cannot verify the three fairlead node labels.')
    m=re.search(r'(?m)^[ \t]+1'+(r'[ \t]+('+FLOAT+r')')*3+r'[ \t]*$',section)
    if not m:
        raise ValueError('Missing significant tension amplitudes.')
    sigma=lambda values:{k:v/2 for k,v in values.items()}
    tensions=dict(zip(('line_1','line_2','line_3'),map(float,m.groups())))
    return {'scope':'band-limited wave-frequency only','response_density_axis':'fixed reference axes (FRA)',
            'native_band_limited_significant_wave_height_m':realized_hs,
            'native_spectrum_band_rad_s':[lo,hi],
            'native_response_integration_point_range_rad_s':[spectra[0]['omega_rad_s'],spectra[-1]['omega_rad_s']],
            'native_motion_statistics_axis':'local structure axes (LSA)',
            'motion_unit_by_dof':dict(zip(DOF,('m','m','m','deg','deg','deg'))),
            'integration_rows_native':spectra,'significant_motion_amplitude':motion,'motion_standard_deviation':sigma(motion),
            'fairlead_significant_dynamic_tension_amplitude_n':tensions,'fairlead_dynamic_tension_standard_deviation_n':sigma(tensions),
            'standard_deviation_basis':'native significant amplitude divided by two; printed precision'}
