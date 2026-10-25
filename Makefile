deps:
	sudo apt install python3-pygame python3-pip pigpiod

# On the Pi: systemd unit, failsafe hooks, hardware watchdog, persistent journal
install:
	sudo services/install.sh

lint:
	black .
	isort -rc espyresso

test:
	python3 -m pytest -q espyresso/tests

# Closed-loop simulation report (real controller against the fitted plant)
sim:
	python3 tools/sim/report.py

# Refit the plant from logs (log/pi), see tools/sim/README.md. FIT_ARGS=--write saves it.
fit:
	uv run -q --no-project --with pandas --with numpy --with scipy python tools/sim/fit.py $(FIT_ARGS)

# Copy logs from the Pi into log/pi (make fetch-logs PI=pi@<host>)
PI ?= pi@raspberrypi.local
fetch-logs:
	rsync -a $(PI):espyresso/log/ log/pi/
	rsync -a $(PI):espyresso/shot_stat.txt log/pi/

run:
	sudo python3 -m espyresso
