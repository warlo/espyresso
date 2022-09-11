deps:
	sudo apt install python3-pygame python3-pip pigpiod

links:
	sudo systemctl enable pigpiod
	sudo ln -s services/espyresso.service /etc/systemd/system

lint:
	black .
	isort -rc espyresso

run:
	sudo python espyresso/main.py


