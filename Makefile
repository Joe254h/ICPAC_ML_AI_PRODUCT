dev:
	docker compose up --build

test:
	python -m pytest
	cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build
