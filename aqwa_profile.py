"""Pinned H00 inputs. Files themselves are intentionally not distributed."""
import hashlib

from aqwa_config import input_root

DIRECTION = (-180., -90., 0., 90., 180.)
WIDE_SHA={
    'DAT':'97357c4c585a9850a947cb3a9e07dec4e2770fe1f0d87dc64da370030c90ec31',
    'LIS':'ce73ff51f4f5b3908fee49fcb3189e5ddb3e35175d6a76149c9b4d163196ce2d',
    'HYD':'2e48524edfd0ad4230ad4a082ad7fe65db9a6b731bcb964e9109c638596557d1',
    'RES':'d38f4283e7927d34f2f93983dedbf59a403d2d645e4a0ff1b92fbcd692885efb',
}
EXPECTED = {
    **{'wide.' + ext.lower(): value for ext,value in WIDE_SHA.items()},
    'base.dat':'77432c009b46e6de3dae5f36b5fef1ac27ba18373105700710c651a8f956ced6',
    'equilibrium.eqp':'f0bd4b9019279e1c8e20c06dbf4e7abcb94f3b2626ffe3573ce1d52246f393cd',
    'equilibrium.lis':'28abcac0ffe6cc8bd909b4f2b01e36793ef78a7491e7a91c446fa0e2837cf4f2',
    # Edge deck verified by comparing its non-frequency records to the pinned wide DAT.
    'edge.dat':None,
}


def checked_bytes(name):
    root = input_root()
    expected = EXPECTED[name]
    path = root / name
    if not path.is_file() or path.resolve() != path:
        raise ValueError(f'Missing or linked private H00 input: {name}')
    raw = path.read_bytes()
    if expected and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f'Private H00 input fingerprint does not match this release: {name}')
    return raw


def checked_path(name):
    checked_bytes(name)
    return input_root() / name


def verified_inputs():
    return {'DAT':checked_bytes('base.dat'), 'EQP':checked_bytes('equilibrium.eqp')}
