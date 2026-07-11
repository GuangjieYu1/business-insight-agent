import pytest

from data_formulator.product import ProductMode, get_product_brand_config


def test_default_product_is_data_formulator():
    config = get_product_brand_config(environ={})
    assert config.mode == ProductMode.DATA_FORMULATOR
    assert config.name == "Data Formulator"


def test_business_insight_defaults_and_overrides():
    config = get_product_brand_config(
        environ={
            "APP_PRODUCT_MODE": "business_insight",
            "APP_BRAND_NAME": "Insight Flow",
        }
    )
    assert config.mode == ProductMode.BUSINESS_INSIGHT
    assert config.name == "Insight Flow"
    assert config.short_name == "Insight Agent"


def test_invalid_product_mode_rejected():
    with pytest.raises(ValueError, match="Unsupported APP_PRODUCT_MODE"):
        get_product_brand_config(environ={"APP_PRODUCT_MODE": "unknown"})
