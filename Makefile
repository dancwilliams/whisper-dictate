PYINSTALLER_SPEC ?= packaging/pyinstaller/whisper_dictate_gui.spec
MODEL ?= small
DEVICE ?= cpu
COMPUTE_TYPE ?= int8_float32
CACHE_DIR ?=
USE_UV ?= 0

PYTHON ?= python
PYINSTALLER ?= pyinstaller

ifeq ($(USE_UV),1)
PYTHON := uv run python
PYINSTALLER := uv run pyinstaller
endif

.PHONY: prefetch-model
prefetch-model:
        $(PYTHON) scripts/prefetch_model.py --model $(MODEL) --device $(DEVICE) --compute-type $(COMPUTE_TYPE) $(if $(CACHE_DIR),--cache-dir $(CACHE_DIR),)

.PHONY: build-exe
build-exe:
        $(PYINSTALLER) $(PYINSTALLER_SPEC) --noconfirm

.PHONY: clean
clean:
	rm -rf build dist *.spec __pycache__
