from __future__ import annotations

from data_formulator.sandbox.runtime_packages import detect_explicit_runtime_package_requests


def test_detects_explicit_chinese_package_request(monkeypatch):
    monkeypatch.setattr(
        'importlib.util.find_spec',
        lambda name: None if name in {'xgboost', 'shap'} else object(),
    )

    requested = detect_explicit_runtime_package_requests('\u4e0b\u8f7dxgboost\u548cshap\u8fdb\u884c\u5206\u6790')

    assert [(item.package_name, item.import_name) for item in requested] == [
        ('xgboost', 'xgboost'),
        ('shap', 'shap'),
    ]


def test_does_not_turn_ordinary_analysis_into_an_install_request(monkeypatch):
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)

    assert detect_explicit_runtime_package_requests('\u8bf7\u5206\u6790xgboost\u548c\u9500\u552e\u989d\u7684\u5173\u7cfb') == []


def test_rejects_url_shaped_install_request(monkeypatch):
    monkeypatch.setattr('importlib.util.find_spec', lambda name: None)

    assert detect_explicit_runtime_package_requests('\u5b89\u88c5 https://example.com/xgboost.whl') == []
