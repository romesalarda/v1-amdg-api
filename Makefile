.PHONY: help build up down restart logs shell migrate makemigrations createsuperuser test clean

help:
	@echo "AMDG API - Available Commands:"
	@echo ""
	@echo "  make build          - Build Docker images"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make logs           - View logs from all services"
	@echo "  make shell          - Open Django shell"
	@echo "  make bash           - Open bash in web container"
	@echo "  make migrate        - Run database migrations"
	@echo "  make makemigrations - Create new migrations"
	@echo "  make createsuperuser- Create Django superuser"
	@echo "  make test           - Run tests"
	@echo "  make collectstatic  - Collect static files"
	@echo "  make clean          - Stop and remove volumes"
	@echo "  make rebuild        - Clean build and start"
	@echo ""

build:
	docker-compose build

up:
	docker-compose up -d
	@echo "Services started! API available at http://localhost:8000"

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f

shell:
	docker-compose exec web python manage.py shell

bash:
	docker-compose exec web bash

migrate:
	docker-compose exec web python manage.py migrate

makemigrations:
	docker-compose exec web python manage.py makemigrations

createsuperuser:
	docker-compose exec web python manage.py createsuperuser

test:
	docker-compose exec web python manage.py test

collectstatic:
	docker-compose exec web python manage.py collectstatic --noinput

clean:
	docker-compose down -v
	@echo "All containers and volumes removed"

rebuild: clean build up
	@echo "Rebuild complete!"

install-local:
	pip install -r requirements.txt
	@echo "Python dependencies installed"

run-local:
	python manage.py runserver 0.0.0.0:8000
