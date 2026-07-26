from __future__ import annotations

from data_formulator.sandbox.runtime_packages import detect_explicit_runtime_package_requests


def test_detects_explicit_chinese_package_request(monkeypatch):
    monkeypatch.setattr(
        'importlib.util.find_spec',
        lambda name: None if name in {'xgboost', 'shap'} else object(),
    )

    requested = detect_explicit_runtime_package_requests('下载xgboost和shap进行分析')

    assert [(item.package_name, item.import_name) for item in requested] == [
        ('xgboost', 'xgboost'),
        ('shap', 'shap'),
    ]


def test_does_not_turn_ordinary_analysis_into_an_install_request(monkeypatch):
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)

    assert detect_explicit_runtime_package_requests('请分析xgboost和销售额的关系') == []


def test_rejects_url_shaped_install_request(monkeypatch):
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)

    assert detect_explicit_runtime_package_requests('安装 https://example.com/xgboost.whl') == []
