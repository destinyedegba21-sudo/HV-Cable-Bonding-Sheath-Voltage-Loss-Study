"""Illustrative balanced-trefoil calculations, plots and CSVs."""
from dataclasses import dataclass, replace
from pathlib import Path
import argparse
import math
import numpy as np


@dataclass(frozen=True)
class Inputs:
    """Units are explicit. Rc is manufacturer data; remaining drivers are assumptions."""
    voltage_ll_kv: float = 132.0
    frequency_hz: float = 50.0
    current_a: float = 500.0
    length_km: float = 3.0
    phases: int = 3
    minor_sections: int = 3
    conductor_resistance_ohm_km: float = 0.0626
    spacing_mm: float = 82.0
    screen_diameter_mm: float = 65.0
    overall_diameter_mm: float = 82.0
    loop_resistance_ohm: float = 0.45
    loop_reactance_ohm: float = 0.30
    loss_resistance_ohm: float = 0.45  # Assumed per-phase loss path, not measured screen R.

    def validate(self) -> None:
        for name, value in vars(self).items():
            if isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite number")
        for name in ('voltage_ll_kv', 'frequency_hz', 'length_km',
                     'conductor_resistance_ohm_km', 'spacing_mm',
                     'screen_diameter_mm', 'overall_diameter_mm'):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ('current_a', 'loop_resistance_ohm', 'loop_reactance_ohm',
                     'loss_resistance_ohm'):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if (type(self.phases) is not int or type(self.minor_sections) is not int
                or self.phases != 3 or self.minor_sections != 3):
            raise ValueError('This model requires three phases and three equal minor sections')
        if self.spacing_mm < self.overall_diameter_mm:
            raise ValueError('Cable spacing cannot be smaller than overall diameter')
        if self.screen_diameter_mm >= self.overall_diameter_mm:
            raise ValueError('Mean screen diameter must be smaller than overall diameter')
        if self.loop_resistance_ohm == self.loop_reactance_ohm == 0:
            raise ValueError('Loop impedance must be nonzero')


def angular_frequency(frequency_hz: float) -> float:
    """Return angular frequency in rad/s."""
    return 2 * math.pi * frequency_hz


def phase_voltage(voltage_ll_kv: float) -> float:
    """Return RMS phase voltage in kV from line-to-line kV."""
    return voltage_ll_kv / math.sqrt(3)


def conductor_losses(current_a: float, resistance_ohm_km: float,
                     length_km: float, phases: int = 3) -> float:
    """Three-phase conductor I-squared-R loss in kW."""
    return phases * current_a**2 * resistance_ohm_km * length_km / 1000


def sheath_reactance(frequency_hz: float, spacing_mm: float,
                     screen_diameter_mm: float) -> float:
    """Preliminary balanced-trefoil approximation in ohm/km; log ratio is unitless."""
    return 2 * angular_frequency(frequency_hz) * 1e-7 * math.log(
        2 * spacing_mm / screen_diameter_mm) * 1000


def induced_emf(current_a: float, reactance_ohm_km: float, length_km: float) -> float:
    """Induced longitudinal EMF in V, referenced at zero degrees."""
    return current_a * reactance_ohm_km * length_km


def loop_impedance(resistance_ohm: float, reactance_ohm: float) -> complex:
    """Return illustrative loop impedance in ohms."""
    return complex(resistance_ohm, reactance_ohm)


def circulating_current(emf_v: complex, impedance_ohm: complex) -> complex:
    """Return current phasor in A, preserving its angle."""
    if impedance_ohm == 0:
        raise ValueError('Loop impedance must be nonzero')
    return emf_v / impedance_ohm


def circulating_losses(current_a: complex, loss_resistance_ohm: float,
                       phases: int = 3) -> float:
    """Circulating-current loss only, kW; resistance is per phase."""
    return phases * abs(current_a)**2 * loss_resistance_ohm / 1000


def cross_bonding_phasors(minor_emf_v: float) -> np.ndarray:
    """Three equal minor-section EMFs at 0, -120, +120 degrees, in V."""
    return minor_emf_v * np.exp(1j * np.deg2rad([0., -120., 120.]))


def calculate(inputs: Inputs) -> dict:
    """Validate inputs and compute full-precision outputs without side effects."""
    inputs.validate()
    p = inputs
    xs = sheath_reactance(p.frequency_hz, p.spacing_mm, p.screen_diameter_mm)
    emf = induced_emf(p.current_a, xs, p.length_km)
    pc = conductor_losses(p.current_a, p.conductor_resistance_ohm_km, p.length_km, p.phases)
    z = loop_impedance(p.loop_resistance_ohm, p.loop_reactance_ohm)
    ib = circulating_current(emf, z)
    phasors = cross_bonding_phasors(emf / p.minor_sections)
    ec = complex(sum(phasors))
    ic = circulating_current(ec, z)
    rows = []
    for name, kind, e, i in (
        ('Single-point', 'Open-end EMF', complex(emf), 0j),
        ('Both-end', 'Loop-driving EMF', complex(emf), ib),
        ('Ideal cross-bonding', 'Net major-section EMF', ec, ic),
    ):
        ps = circulating_losses(i, p.loss_resistance_ohm, p.phases)
        rows.append(dict(bonding=name, emf_type=kind, emf_v=e, current_a=i,
                         circulating_loss_kw=ps, lambda_circ=ps / pc if pc else math.nan,
                         partial_combined_loss_kw=pc + ps))
    return dict(omega=angular_frequency(p.frequency_hz), phase_kv=phase_voltage(p.voltage_ll_kv),
                conductor_kw=pc, xs=xs, emf_per_km=induced_emf(p.current_a, xs, 1),
                emf_total=emf, impedance=z, impedance_angle_deg=math.degrees(np.angle(z)),
                minor_length_km=p.length_km / p.minor_sections,
                minor_emf_v=emf / p.minor_sections, phasors=phasors, cross_emf=ec, rows=rows)


def fmt(value: float) -> str:
    """Suppress sub-1e-9 residuals only in the displayed report."""
    return f'{0.0 if abs(value) < 1e-9 else value:.9f}'


def report(p: Inputs, r: dict) -> None:
    print('HV cable bonding illustrative calculation')
    print(f'Inputs: {p.voltage_ll_kv:g} kV LL, {p.frequency_hz:g} Hz, {p.current_a:g} A, {p.length_km:g} km')
    for label, value in [('Angular frequency (rad/s)', r['omega']),
                         ('Phase voltage (kV)', r['phase_kv']),
                         ('Conductor loss (kW)', r['conductor_kw']),
                         ('Sheath reactance (ohm/km)', r['xs']),
                         ('Induced EMF (V/km)', r['emf_per_km']),
                         ('Route induced EMF (V)', r['emf_total']),
                         ('Loop impedance magnitude (ohm)', abs(r['impedance'])),
                         ('Loop impedance angle (deg)', r['impedance_angle_deg'])]:
        print(f'{label:34s} {fmt(value)}')
    ib = r['rows'][1]['current_a']
    print(f'Both-end current phasor (A): {ib.real:.12g} {ib.imag:+.12g}j; angle {math.degrees(np.angle(ib)):.9f} deg')
    print('\nBonding              EMF type                  |EMF| V       |I| A      Circ kW      Lambda      Partial kW')
    for row in r['rows']:
        values = [abs(row['emf_v']), abs(row['current_a']), row['circulating_loss_kw'],
                  row['lambda_circ'], row['partial_combined_loss_kw']]
        print(f"{row['bonding']:21s}{row['emf_type']:24s}" + ' '.join(f'{fmt(v):>12s}' for v in values))
    print('\nCurrent sensitivity (A -> induced route EMF V):')
    for current in (250, 400, 500, 600, 673):
        print(f'{current:4d} -> {fmt(induced_emf(current, r["xs"], p.length_km))}')
    print('Length sensitivity (km -> induced route EMF V):')
    for length in (.5, 1, 1.5, 2, 2.5, 3):
        print(f'{length:3g} -> {fmt(induced_emf(p.current_a, r["xs"], length))}')
    print(f"Cross-bonding raw resultant (V): {r['cross_emf']!r}")
    print('Zero net major-section EMF does not imply zero local sheath-to-earth voltage.')
    print('Losses exclude eddy-current, dielectric and other unmodelled components.')
    print('No ampacity, fault, SVL, insulation-coordination or IEC 60287 design determination.')


def build_tables(p: Inputs, r: dict) -> dict:
    """Build numeric tables without rounding computed quantities."""
    import pandas as pd
    currents = []
    for current in (250, 400, 500, 600, 673):
        result = calculate(replace(p, current_a=current))
        currents.append(dict(current_a=current, length_km=p.length_km,
                             induced_emf_v=result['emf_total'],
                             both_end_circulating_loss_kw=result['rows'][1]['circulating_loss_kw']))
    lengths = [dict(length_km=length, current_a=p.current_a,
                    induced_emf_v=calculate(replace(p, length_km=length))['emf_total'])
               for length in (.5, 1, 1.5, 2, 2.5, 3)]
    bonding, losses = [], []
    for row in r['rows']:
        e, i = row['emf_v'], row['current_a']
        bonding.append(dict(bonding=row['bonding'], induced_emf_type=row['emf_type'],
                            emf_magnitude_v=abs(e), emf_real_v=e.real, emf_imag_v=e.imag,
                            current_magnitude_a=abs(i), current_real_a=i.real, current_imag_a=i.imag,
                            circulating_loss_kw=row['circulating_loss_kw'], lambda_circ=row['lambda_circ']))
        losses.append(dict(bonding=row['bonding'], conductor_loss_kw=r['conductor_kw'],
                           circulating_loss_kw=row['circulating_loss_kw'],
                           partial_combined_loss_kw=row['partial_combined_loss_kw']))
    phasors = [dict(section=f'Section {n}', angle_deg=angle, magnitude_v=abs(z),
                    real_v=z.real, imag_v=z.imag)
               for n, angle, z in zip((1, 2, 3), (0, -120, 120), r['phasors'])]
    z = r['cross_emf']
    phasors.append(dict(section='Resultant', angle_deg=(math.nan if abs(z) < 1e-9
                                                     else float(np.degrees(np.angle(z)))),
                        magnitude_v=abs(z), real_v=z.real, imag_v=z.imag))
    return {name: pd.DataFrame(data) for name, data in (
        ('current_sensitivity', currents), ('length_sensitivity', lengths),
        ('bonding_comparison', bonding), ('loss_comparison', losses),
        ('cross_bonding_phasors', phasors))}


def export_results(p: Inputs, r: dict, output_dir: Path) -> None:
    """Export five precise CSV tables and six labelled PNG figures."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    tables = build_tables(p, r)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(output_dir / f'{name}.csv', index=False, float_format='%.17g',
                     na_rep='NaN' if name == 'cross_bonding_phasors' else '')
    colors = ['#3366a0', '#d77d2b', '#33876e']
    plt.rcParams.update({'font.size': 11, 'axes.spines.top': False,
                         'axes.spines.right': False, 'figure.facecolor': 'white'})

    def save(fig, name):
        fig.savefig(output_dir / f'{name}.png', dpi=180, bbox_inches='tight')
        plt.close(fig)

    for name, x, xlabel, title in (
        ('current_sensitivity', 'current_a', 'Conductor current (A)',
         f'Induced longitudinal EMF vs current | {p.length_km:g} km'),
        ('length_sensitivity', 'length_km', 'Route length (km)',
         f'Induced longitudinal EMF vs length | {p.current_a:g} A')):
        t = tables[name]
        fig, ax = plt.subplots(figsize=(8, 5), layout='constrained')
        ax.plot(t[x], t.induced_emf_v, 'o-', color=colors[0], label='Route induced EMF')
        ax.set(xlabel=xlabel, ylabel='Induced EMF (V)', title=title)
        ax.grid(alpha=.2)
        ax.legend()
        save(fig, f'induced_emf_vs_{"current" if x == "current_a" else "length"}')

    fig, ax = plt.subplots(figsize=(8, 5), layout='constrained')
    grid = np.linspace(250, 673, 200)
    losses = [calculate(replace(p, current_a=float(i)))['rows'][1]['circulating_loss_kw'] for i in grid]
    ax.plot(grid, losses, color=colors[1], label='Fixed equivalent impedance: quadratic response')
    t = tables['current_sensitivity']
    ax.scatter(t.current_a, t.both_end_circulating_loss_kw, color=colors[1])
    ax.set(xlabel='Conductor current (A)', ylabel='Circulating-current loss (kW)',
           title=f'Both-end circulating-current sheath loss | {p.length_km:g} km')
    ax.text(.02, .94, f'Z = {p.loop_resistance_ohm:g} + j{p.loop_reactance_ohm:g} ohm; Rloss = {p.loss_resistance_ohm:g} ohm/phase',
            transform=ax.transAxes, va='top', fontsize=9)
    ax.grid(alpha=.2)
    ax.legend(loc='lower right', fontsize=9)
    save(fig, 'both_end_loss_vs_current')

    labels = ['Single-point', 'Both-end', 'Ideal cross-bonding']
    t = tables['loss_comparison']
    for combined in (False, True):
        fig, ax = plt.subplots(figsize=(8, 5), layout='constrained')
        circ = [0 if abs(v) < 1e-9 else v for v in t.circulating_loss_kw]
        if combined:
            ax.bar(labels, t.conductor_loss_kw, color=colors[0], label='Conductor loss')
            ax.bar(labels, circ, bottom=t.conductor_loss_kw, color=colors[1], label='Circulating-current sheath loss')
            values = t.partial_combined_loss_kw
            title = 'Partial conductor + circulating-current loss comparison'
            note = 'Excludes eddy-current, dielectric and other unmodelled losses'
        else:
            ax.bar(labels, circ, color=colors)
            values = circ
            title = 'Circulating-current sheath loss by bonding arrangement'
            note = 'Ideal zero circulating loss does not imply zero total metallic-screen loss'
        for i, value in enumerate(values):
            ax.annotate(f'{value:.3f} kW', (i, value), xytext=(0, 5), textcoords='offset points', ha='center')
        ax.set(ylabel='Loss (kW)', title=f'{title}\n{p.current_a:g} A, {p.length_km:g} km')
        ax.set_ylim(0, max(max(values) * 1.23, 1))
        ax.text(.5, -.18, note, transform=ax.transAxes, ha='center', fontsize=9)
        ax.grid(axis='y', alpha=.2)
        ax.set_axisbelow(True)
        if combined:
            ax.legend(fontsize=9)
        save(fig, 'partial_combined_losses' if combined else 'circulating_losses_by_bonding')

    fig, ax = plt.subplots(figsize=(7, 7), layout='constrained')
    for n, angle, z, color in zip((1, 2, 3), (0, -120, 120), r['phasors'], colors):
        ax.quiver(0, 0, z.real, z.imag, angles='xy', scale_units='xy', scale=1,
                  color=color, label=f'Section {n}: {abs(z):.3f} V at {angle} deg')
    z = r['cross_emf']
    ax.plot(z.real, z.imag, 'ko', label=f'Resultant: {abs(z):.3g} V (approximately zero)')
    limit = max(r['minor_emf_v'] * 1.25, 1)
    ax.set(xlim=(-limit, limit), ylim=(-limit, limit), xlabel='Real EMF component (V)',
           ylabel='Imaginary EMF component (V)', title='Ideal cross-bonding: equal minor-section EMFs')
    ax.axhline(0, color='gray', linewidth=.6)
    ax.axvline(0, color='gray', linewidth=.6)
    ax.set_aspect('equal')
    ax.grid(alpha=.2)
    ax.legend(loc='upper left', fontsize=9)
    ax.text(.5, -.13, 'Net major-section cancellation does not imply zero local sheath-to-earth voltage',
            transform=ax.transAxes, ha='center', fontsize=8)
    save(fig, 'cross_bonding_phasors')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-a', type=float, default=500.)
    parser.add_argument('--length-km', type=float, default=3.)
    parser.add_argument('--no-export', action='store_true', help='Print calculations only')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'outputs')
    args = parser.parse_args()
    p = replace(Inputs(), current_a=args.current_a, length_km=args.length_km)
    try:
        results = calculate(p)
    except ValueError as exc:
        parser.error(str(exc))
    report(p, results)
    if not args.no_export:
        export_results(p, results, args.output_dir)
        print(f'Generated six PNGs and five CSVs in {args.output_dir}')


if __name__ == '__main__':
    main()
