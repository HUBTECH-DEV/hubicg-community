.PHONY: test check build manifest release-candidate

RELEASE_EPOCH ?= 1767225600

test:
	python3 -m pytest

check:
	python3 -m compileall -q src scripts tests
	PYTHONPATH=src python3 -m hubicg --root . validate
	PYTHONPATH=src python3 -m hubicg --root . roles verify
	PYTHONPATH=src python3 -m hubicg --root . files verify
	python3 scripts/build_manifest.py --check

build:
	python3 -m build

release-candidate:
	SOURCE_DATE_EPOCH=$(RELEASE_EPOCH) python3 -m build
	SOURCE_DATE_EPOCH=$(RELEASE_EPOCH) python3 scripts/normalize_sdist.py dist/hubicg-0.1.0.tar.gz
	python3 scripts/verify_release.py
	SOURCE_DATE_EPOCH=$(RELEASE_EPOCH) python3 scripts/build_sbom.py
	SOURCE_DATE_EPOCH=$(RELEASE_EPOCH) python3 scripts/build_provenance.py
	python3 scripts/build_checksums.py
	python3 scripts/build_checksums.py --check
	SOURCE_DATE_EPOCH=$(RELEASE_EPOCH) python3 scripts/verify_reproducible_build.py

manifest:
	python3 scripts/build_manifest.py
