lint:
	black .
	isort -rc espyresso

run:
	sudo python espyresso/main.py


