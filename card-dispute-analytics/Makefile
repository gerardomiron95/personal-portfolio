PY      ?= .venv/bin/python
PORT    ?= 8000
ARGS    ?=

.PHONY: all setup data build check serve clean

all: data build check

setup:            ## create .venv and install numpy, pandas, pyarrow
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt

data:             ## raw Parquet files -> data/raw/  (pass flags with ARGS="--claims 400000")
	$(PY) generate_raw.py $(ARGS)

build:            ## data/raw -> data/agg/*.csv + data/data.json
	$(PY) build_aggregates.py

check:            ## integrity, reproducibility and reconciliation checks
	$(PY) check.py

serve:            ## open http://localhost:$(PORT)/web/
	@echo "Dashboard: http://localhost:$(PORT)/web/"
	python3 -m http.server $(PORT)

clean:
	rm -rf data/raw/*.parquet data/raw/_meta.json data/agg/*.csv data/data.json
