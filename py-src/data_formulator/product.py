# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Product-mode and branding configuration.

This module intentionally keeps branding separate from the core package name so
this fork can continue to merge upstream Data Formulator changes without a
large-scale rename.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum


class ProductMode(StrEnum):
    DATA_FORMULATOR = "data_formulator"
    BUSINESS_INSIGHT = "business_insight"


@dataclass(frozen=True, slots=True)
class ProductBrandConfig:
    mode: ProductMode
    name: str
    short_name: str
    description: str

    def as_frontend_config(self) -> dict[str, str]:
        return {
            "APP_PRODUCT_MODE": self.mode.value,
            "APP_BRAND_NAME": self.name,
            "APP_BRAND_SHORT_NAME": self.short_name,
            "APP_BRAND_DESCRIPTION": self.description,
        }


def _parse_mode(value: str | None) -> ProductMode:
    raw = (value or ProductMode.DATA_FORMULATOR.value).strip().lower()
    try:
        return ProductMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in ProductMode)
        raise ValueError(f"Unsupported APP_PRODUCT_MODE '{raw}'. Expected one of: {allowed}") from exc


def get_product_brand_config(
    *,
    mode_value: str | None = None,
    environ: dict[str, str] | None = None,
) -> ProductBrandConfig:
    env = environ if environ is not None else os.environ
    mode = _parse_mode(mode_value if mode_value is not None else env.get("APP_PRODUCT_MODE"))

    if mode is ProductMode.BUSINESS_INSIGHT:
        defaults = ProductBrandConfig(
            mode=mode,
            name="Business Insight Agent",
            short_name="Insight Agent",
            description="Evidence-driven business analysis for messy operational data.",
        )
    else:
        defaults = ProductBrandConfig(
            mode=mode,
            name="Data Formulator",
            short_name="Data Formulator",
            description="AI-powered data exploration and visualization.",
        )

    return ProductBrandConfig(
        mode=mode,
        name=env.get("APP_BRAND_NAME", defaults.name).strip() or defaults.name,
        short_name=env.get("APP_BRAND_SHORT_NAME", defaults.short_name).strip() or defaults.short_name,
        description=env.get("APP_BRAND_DESCRIPTION", defaults.description).strip() or defaults.description,
    )
