PYINSTALLER_SPEC ?= packaging/pyinstaller/whisper_dictate_gui.spec
USE_UV ?= 0

PYINSTALLER ?= pyinstaller

ifeq ($(USE_UV),1)
PYINSTALLER := uv run pyinstaller
endif

.PHONY: build-exe
build-exe:
	$(PYINSTALLER) $(PYINSTALLER_SPEC) --noconfirm

.PHONY: clean
clean:
	rm -rf build dist *.spec __pycache__
