"""Numerical targets, model invariants, boundaries and delivered exports."""
import math
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from PIL import Image
import analysis as a


@pytest.fixture
def base():
    return a.calculate(a.Inputs())


@pytest.mark.parametrize('key,expected,tolerance', [
    ('omega',314.159,.0005), ('phase_kv',76.210,.0005),
    ('conductor_kw',140.850,.0005), ('xs',.05814957,5e-9),
    ('emf_total',87.22436,5e-6), ('impedance_angle_deg',33.690,.0005)])
def test_instruction_scalar_targets(base,key,expected,tolerance):
    assert base[key] == pytest.approx(expected,abs=tolerance)


def test_bonding_targets_and_power_balance(base):
    sp, be, cb = base['rows']
    assert abs(base['impedance']) == pytest.approx(.540833,abs=5e-7)
    assert abs(be['current_a']) == pytest.approx(161.278,abs=.0005)
    assert be['circulating_loss_kw'] == pytest.approx(35.114,abs=.0005)
    assert be['lambda_circ'] == pytest.approx(.249302,abs=5e-7)
    assert sp['current_a'] == sp['circulating_loss_kw'] == 0
    assert abs(cb['emf_v']) < 1e-9
    assert abs(cb['current_a']) < 1e-9
    for row in base['rows']:
        assert row['partial_combined_loss_kw'] == pytest.approx(base['conductor_kw'] + row['circulating_loss_kw'])


def test_formula_functions_and_units():
    assert a.angular_frequency(50) == pytest.approx(100*math.pi)
    assert a.phase_voltage(132) == pytest.approx(76.2102355330306)
    assert a.conductor_losses(500,.0626,3) == pytest.approx(140.85)
    assert a.sheath_reactance(50,82,65) == pytest.approx(.0581495704719767)
    assert a.induced_emf(500,.06,3) == 90
    assert a.loop_impedance(.45,.3) == .45+.3j
    assert a.circulating_current(90,.45+.3j) == pytest.approx(138.461538461538-92.3076923076923j)
    assert a.circulating_losses(3+4j,.45) == pytest.approx(.03375)
    with pytest.raises(ValueError):
        a.circulating_current(1,0j)


def test_phasor_components_and_sign(base):
    v = a.cross_bonding_phasors(30)
    np.testing.assert_allclose(v.real,[30,-15,-15],atol=1e-12)
    np.testing.assert_allclose(v.imag,[0,-15*math.sqrt(3),15*math.sqrt(3)],atol=1e-12)
    assert abs(sum(v)) < 1e-9
    ib = base['rows'][1]['current_a']
    assert ib.imag < 0
    assert ib * base['impedance'] == pytest.approx(base['emf_total'])
    assert math.degrees(np.angle(ib)) == pytest.approx(-base['impedance_angle_deg'])


@pytest.mark.parametrize('factor',[.5,.8,1.2,1.346,2])
def test_current_scaling(base,factor):
    r = a.calculate(replace(a.Inputs(),current_a=500*factor))
    assert r['emf_total'] == pytest.approx(base['emf_total']*factor)
    assert r['conductor_kw'] == pytest.approx(base['conductor_kw']*factor**2)
    assert r['rows'][1]['circulating_loss_kw'] == pytest.approx(base['rows'][1]['circulating_loss_kw']*factor**2)


@pytest.mark.parametrize('length',[.5,1,1.5,2,2.5,3])
def test_length_scaling(base,length):
    r = a.calculate(replace(a.Inputs(),length_km=length))
    assert r['emf_total'] == pytest.approx(base['emf_total']*length/3)
    assert r['conductor_kw'] == pytest.approx(base['conductor_kw']*length/3)
    assert abs(r['cross_emf']) < 1e-9


@pytest.mark.parametrize('changes',[
    {'length_km':-1},{'length_km':0},{'screen_diameter_mm':0},
    {'screen_diameter_mm':-65},{'screen_diameter_mm':82},{'screen_diameter_mm':90},
    {'spacing_mm':70},{'spacing_mm':0},{'overall_diameter_mm':-1},
    {'minor_sections':0},{'minor_sections':2},{'minor_sections':3.0},
    {'phases':1},{'phases':3.0},{'current_a':-1},{'current_a':True},
    {'frequency_hz':0},{'frequency_hz':float('nan')},{'length_km':float('inf')},
    {'voltage_ll_kv':0},{'conductor_resistance_ohm_km':0},
    {'loop_resistance_ohm':-1},{'loop_reactance_ohm':-1},{'loss_resistance_ohm':-1},
    {'loop_resistance_ohm':0,'loop_reactance_ohm':0}])
def test_invalid_inputs(changes):
    with pytest.raises(ValueError):
        a.calculate(replace(a.Inputs(),**changes))


def test_zero_current_and_reporting():
    r = a.calculate(replace(a.Inputs(),current_a=0))
    assert r['emf_total'] == r['conductor_kw'] == 0
    assert math.isnan(r['rows'][1]['lambda_circ'])
    assert a.fmt(1e-14) == '0.000000000'


def test_spacing_is_independent_driver(base):
    r = a.calculate(replace(a.Inputs(),spacing_mm=100))
    assert r['xs'] > base['xs']


def test_loss_resistance_is_separate(base):
    r = a.calculate(replace(a.Inputs(),loss_resistance_ohm=.9))
    assert r['rows'][1]['current_a'] == base['rows'][1]['current_a']
    assert r['rows'][1]['circulating_loss_kw'] == pytest.approx(2*base['rows'][1]['circulating_loss_kw'])


def test_exports_roundtrip_and_images(tmp_path,base):
    a.export_results(a.Inputs(),base,tmp_path)
    assert len(list(tmp_path.glob('*.csv'))) == 5
    assert len(list(tmp_path.glob('*.png'))) == 6
    for path in tmp_path.glob('*.png'):
        with Image.open(path) as image:
            assert image.width >= 1000 and image.height >= 700
            image.verify()
    t = pd.read_csv(tmp_path/'current_sensitivity.csv')
    assert list(t.current_a) == [250,400,500,600,673]
    np.testing.assert_allclose(t.induced_emf_v/t.current_a,base['xs']*3)
    np.testing.assert_allclose(t.both_end_circulating_loss_kw/t.current_a**2,
                               base['rows'][1]['circulating_loss_kw']/500**2)
    lengths = pd.read_csv(tmp_path/'length_sensitivity.csv')
    np.testing.assert_allclose(lengths.induced_emf_v/lengths.length_km,base['emf_per_km'])
    b = pd.read_csv(tmp_path/'bonding_comparison.csv')
    assert list(b.induced_emf_type) == ['Open-end EMF','Loop-driving EMF','Net major-section EMF']
    assert b.iloc[1].circulating_loss_kw == pytest.approx(35.1142533630906)
    assert b.iloc[2].circulating_loss_kw < 1e-20
    ph = pd.read_csv(tmp_path/'cross_bonding_phasors.csv')
    assert ph.iloc[-1].magnitude_v < 1e-9
    assert math.isnan(ph.iloc[-1].angle_deg)
    assert 'Resultant,NaN,' in (tmp_path/'cross_bonding_phasors.csv').read_text()
    np.testing.assert_array_equal(ph.iloc[:3].angle_deg, [0, -120, 120])
    # At and above the reporting threshold, preserve the computed angle.
    for magnitude in (1e-9, 2e-9):
        result = dict(base, cross_emf=1j * magnitude)
        table = a.build_tables(a.Inputs(), result)['cross_bonding_phasors']
        assert table.iloc[-1].angle_deg == pytest.approx(90)
    losses = pd.read_csv(tmp_path/'loss_comparison.csv')
    np.testing.assert_allclose(losses.partial_combined_loss_kw,losses.conductor_loss_kw+losses.circulating_loss_kw)
