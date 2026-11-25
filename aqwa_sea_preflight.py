"""H00 JONSWAP spectrum coverage and source-labelled wave-condition intake."""
import math

from aqwa_fer_sea_state import BAND, DIRECTIONS

TARGET=.99
SOURCE_KINDS=('site_data','literature','research_assumption','commissioning')


def validate_sea_state(sea_state, source_kind, source_note):
    if not isinstance(sea_state,dict) or set(sea_state)!={'hs_m','tp_s','gamma','direction_deg'}:
        raise ValueError('Supply hs_m, tp_s, gamma and direction_deg.')
    if not all(type(v) in (int,float) and math.isfinite(v) for v in sea_state.values()):
        raise ValueError('Sea-state values must be finite numbers.')
    h,t,g,d=(sea_state[k] for k in ('hs_m','tp_s','gamma','direction_deg'))
    if not .05<=h<=5 or not 9<=t<=16 or not 1<=g<=7 or d not in DIRECTIONS:
        raise ValueError('Current H00 trial limits: Hs 0.05–5 m, Tp 9–16 s, gamma 1–7; use a verified heading.')
    if source_kind not in SOURCE_KINDS or not isinstance(source_note,str) or not 3<=len(source_note.strip())<=240:
        raise ValueError('Supply the sea-state source type and a reference or explicit study assumption.')
    return dict(hs_m=float(h),tp_s=float(t),gamma=float(g),direction_deg=int(d))


def _integral(gamma, a, b):
    # x=f/fp, standard JONSWAP shape; substitute y=1.25*x**-4.
    # The transformed shape is exp(-y)*gamma**exp(-((x-1)/sigma)**2/2).
    # The omitted tail above y=40 contributes less than gamma*exp(-40).
    a,b=min(40.,a),min(40.,b)
    if b<=a:
        return 0.
    def val(y):
        x=(1.25/y)**.25 if y else math.inf
        s=.07 if y>1.25 else .09
        return math.exp(-y+math.log(gamma)*math.exp(-.5*((x-1)/s)**2))
    points=[a]+[v for v in (1.25,4.,12.) if a<v<b]+[b]
    total=0.
    for lo,hi in zip(points,points[1:]):
        n=400
        h=(hi-lo)/n
        total+=h/3*(val(lo)+val(hi)+sum((4 if i%2 else 2)*val(lo+i*h) for i in range(1,n)))
    return total


def energy_fraction(tp,gamma,lo,hi):
    def y(f):
        return 1.25/(f*tp)**4 if f else 40.
    return _integral(gamma,y(hi),y(lo))/_integral(gamma,0.,40.)


def _quantile(tp,gamma,p):
    lo,hi=0.,1.
    for _ in range(28):
        mid=(lo+hi)/2
        if energy_fraction(tp,gamma,0.,mid)<p:
            lo=mid
        else:
            hi=mid
    return (lo+hi)/2


def sea_plan(sea_state, source_kind, source_note, verified_wide=None):
    spec=validate_sea_state(sea_state,source_kind,source_note)
    t,g=spec['tp_s'],spec['gamma']
    # Split the tail budget deliberately asymmetrically, retaining a wider lower margin.
    # Round outward on the actual DAT frequency grid (0.0001 Hz here).
    lo=math.floor(_quantile(t,g,.001)*1e4)/1e4
    hi=math.ceil(_quantile(t,g,.991)*1e4)/1e4
    needed=(lo,hi)
    current=(.06,.125)
    support=tuple(verified_wide) if verified_wide else current
    guard=.004
    recommended_database=(math.floor((lo-guard)*1e4)/1e4,math.ceil((hi+guard)*1e4)/1e4)
    req_ok=support[0]<=recommended_database[0] and support[-1]>=recommended_database[1]
    wider=None
    if req_ok:
        # Test more of both tails, while reserving a guard for solver integration.
        wlo=max(support[0]+guard,round(lo*.90,4))
        whi=min(support[-1]-guard,round(hi*1.10,4))
        if lo-wlo>=.001 and whi-hi>=.001:
            wider=tuple(round(x,4) for x in (wlo,whi))
    return {'case':'H00','scope':'first_order_wave_frequency_only_at_8_m_s_mean_wind',
            'sea_state':spec,'sea_state_source':{'kind':source_kind,'note':source_note.strip(),
                                                'externally_verified':False},
            'wave_energy_target_fraction':TARGET,'existing_wave_band_hz':BAND,
            'existing_wave_band_energy_fraction':energy_fraction(t,g,*BAND),
            'existing_eight_point_hydrodynamic_band_hz':current,
            'existing_eight_point_max_energy_fraction':energy_fraction(t,g,*current),
            'reference_wave_band_hz':needed,'reference_wave_band_energy_fraction':energy_fraction(t,g,*needed),
            'wide_check_band_hz':wider,
            'wide_check_band_energy_fraction':energy_fraction(t,g,*wider) if wider else None,
            'minimum_suggested_hydrodynamic_endpoints_hz':recommended_database,
            'verified_hydrodynamic_band_hz':support,
            'additional_boundary_solve_needed':not req_ok,
            'candidate_frequency_regions':['add checked endpoints if needed','refine roll and pitch resonances near 0.07–0.08 Hz'],
            'ready_for_native_comparison':bool(verified_wide and wider),
            'comparison_blocker':('No completed wider LINE database is configured.' if not verified_wide else
                'Requested sea still needs more verified LINE support or frequency margin.' if not wider else None),
            'warning':'Analytical spectrum coverage is not response convergence or damping validation.'}
