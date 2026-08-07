.PHONY: test check build manifest

test:
	python3 -m pytest

check:
	python3 -m compileall -q src tests
	PYTHONPATH=src python3 -m hubicg --root . validate
	PYTHONPATH=src python3 -m hubicg --root . roles verify
	PYTHONPATH=src python3 -m hubicg --root . files verify
	python3 scripts/build_manifest.py --check

build:
	python3 -m build

manifest:
	python3 scripts/build_manifest.py
