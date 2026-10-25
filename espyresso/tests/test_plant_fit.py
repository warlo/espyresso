"""The simulator's plant against real sessions (public fixtures made with
tools/sim/make_fixture.py: seconds, sensor, applied heater duty only).

Replays the logged heater duty through the plant, so this pins the plant
(espyresso/sim/plant_fit.json) without freezing controller behaviour.

* cold_start_95: 2026-05-15, setpoint 95.
* cold_start_99: 2026-10-25, setpoint 99 with the self-healing controller.

Both are in the current fit (Tom Brazier's weighed masses fixed, three cold
starts; open-loop RMSE ~1.4 and ~2.6 C on these downsampled fixtures; leave-
one-out about +-3-4 C). A refit that makes either worse should fail.
"""

from __future__ import annotations

import csv
import os
from typing import List, Tuple

import pytest

from espyresso.sim.plant import fitted, replay_sensor

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> Tuple[List[float], List[float], List[float]]:
    with open(os.path.join(FIXTURES, name)) as f:
        rows = [(float(r["t"]), float(r["raw_temp"]), float(r["heater"])) for r in csv.DictReader(f)]
    return [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]


@pytest.mark.parametrize("fixture,max_rmse", [("cold_start_95.csv", 1.5), ("cold_start_99.csv", 4.5)])
def test_plant_reproduces_logged_cold_start(fixture: str, max_rmse: float) -> None:
    t, measured, heater = _load(fixture)

    simulated = replay_sensor(fitted(), t, heater, measured[0])

    errors = [s - m for s, m in zip(simulated, measured)]
    rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
    assert rmse < max_rmse


def test_fitted_plant_beats_the_controllers_own_constants() -> None:
    from espyresso.sim.plant import nominal

    t, measured, heater = _load("cold_start_99.csv")

    def rmse(params: dict) -> float:
        sim = replay_sensor(params, t, heater, measured[0])
        return (sum((s - m) ** 2 for s, m in zip(sim, measured)) / len(sim)) ** 0.5

    assert rmse(fitted()) < rmse(nominal()) / 2
