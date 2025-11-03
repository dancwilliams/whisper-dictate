PYINSTALLER_SPEC ?= packaging/pyinstaller/whisper_dictate_gui.spec
MODEL ?= small
DEVICE ?= cpu
COMPUTE_TYPE ?= int8_float32
CACHE_DIR ?=

.PHONY: prefetch-model
prefetch-model:
	python scripts/prefetch_model.py --model $(MODEL) --device $(DEVICE) --compute-type $(COMPUTE_TYPE) $(if $(CACHE_DIR),--cache-dir $(CACHE_DIR),)

.PHONY: build-exe
build-exe:
	pyinstaller $(PYINSTALLER_SPEC) --noconfirm

.PHONY: clean
clean:
	rm -rf build dist *.spec __pycache__
