# Canonical uwuAOSP source version.
# Keep the revision as an integer. Display padding is applied by consumers.
UWU_VERSION_MAJOR := 17
UWU_VERSION_QPR := 0
UWU_VERSION_REVISION := 82

ifeq ($(shell test $(UWU_VERSION_REVISION) -lt 1000 && printf true),true)
UWU_RELEASE_REVISION_DISPLAY := $(shell printf '%03d' '$(UWU_VERSION_REVISION)')
else
UWU_RELEASE_REVISION_DISPLAY := $(UWU_VERSION_REVISION)
endif

UWU_RELEASE_VERSION := $(UWU_VERSION_MAJOR).$(UWU_VERSION_QPR).$(UWU_RELEASE_REVISION_DISPLAY)

PRODUCT_PRODUCT_PROPERTIES += \
    ro.uwu.release=$(UWU_RELEASE_VERSION)
