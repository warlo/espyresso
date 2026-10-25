"""Closed-loop simulation of the espresso machine.

``plant`` is a thermal model of the machine (same structure as the
controller's, Tom Brazier's six masses) whose coefficients were fitted to this
machine's logs (``plant_fit.json``, refit with ``tools/sim/fit.py``).
``closedloop`` runs the production control path (Temperature, PController,
SafetyGuard, Boiler, Watchdog) against it on a simulated clock.
``scenarios`` builds flow profiles for shots and preheats.

Pure Python so the regression tests run anywhere (see tools/sim/README.md).
"""
