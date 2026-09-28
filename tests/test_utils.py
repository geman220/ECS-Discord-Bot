# tests/test_utils.py

import asyncio
import pytest
import datetime
from unittest.mock import MagicMock, patch
from utils import (
    convert_to_pst,
    normalize_string,
    extract_designation,
    extract_customer_info,
    find_customer_info_in_order,
    find_membership_in_order,
    find_membership_item_in_order,
    find_membership_plan_for_year,
    find_subgroup_in_order,
    extract_base_product_title
)

def test_normalize_string():
    assert normalize_string("  Hello   World  ") == "hello world"
    assert normalize_string("Test STRING") == "test string"
    assert normalize_string(None) == ""
    assert normalize_string(123) == ""

def test_extract_designation_string():
    assert extract_designation("  Some Value  ") == "Some Value"

def test_extract_designation_dict():
    data = {"key1": "Value 1", "key2": "Value 2"}
    assert extract_designation(data) == "Value 1 Value 2"

def test_extract_designation_list():
    data = ["Item 1", "Item 2"]
    assert extract_designation(data) == "Item 1 Item 2"

def test_extract_designation_nested():
    data = {
        "key1": ["Item 1", "Item 2"],
        "key2": {"inner": "Value 3"}
    }
    # Item 1 Item 2 Value 3 (order might depend on dict order, but in modern Python it's stable)
    result = extract_designation(data)
    assert "Item 1" in result
    assert "Item 2" in result
    assert "Value 3" in result

def test_extract_customer_info():
    order = {
        'billing': {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@example.com'
        }
    }
    info = extract_customer_info(order)
    assert info['first_name'] == 'John'
    assert info['last_name'] == 'Doe'
    assert info['email'] == 'john@example.com'

def test_extract_base_product_title():
    assert extract_base_product_title("Product Name - Variation") == "Product Name"
    assert extract_base_product_title("Simple Product") == "Simple Product"

def test_membership_helpers_require_a_matching_membership_and_plan_name():
    order_without_membership = {"line_items": [], "billing": {"email": "buyer@example.com"}}
    plans = [{"id": 42, "name": "ECS Membership 2026"}]
    member_product_order = {"line_items": [{"name": "ECS Member 2026"}]}

    assert asyncio.run(find_membership_in_order(order_without_membership)) is None
    assert asyncio.run(find_membership_plan_for_year(plans, 2026)) == 42
    assert asyncio.run(find_membership_item_in_order(member_product_order, 2026)) == "ECS Member 2026"

def test_find_customer_info_matches_subgroup_metadata_on_order_items():
    order = {
        "line_items": [
            {"id": 1, "name": "ECS Membership 2024", "meta_data": []},
            {
                "id": 2,
                "name": "Other Item",
                "meta_data": [{"key": "Subgroup Designation", "value": "West Sound"}],
            },
        ],
        "billing": {"first_name": "Jane", "email": "jane@example.com"},
    }

    result = asyncio.run(find_customer_info_in_order(order, ["West Sound"], membership_year=2024))

    assert result == (["West Sound"], {
        "first_name": "Jane",
        "last_name": "",
        "email": "jane@example.com",
        "customer_id": "",
    })

def test_find_subgroup_in_order_returns_subgroup_product_and_line_item_ids(monkeypatch):
    order = {
        "id": 123,
        "customer_id": 77,
        "line_items": [
            {"id": 10, "product_id": 20, "name": "ECS Membership 2026"},
            {"id": 11, "product_id": 30, "name": "West Sound"},
        ],
    }

    async def fake_call_woocommerce_api(_url):
        return [{
            "id": 99,
            "plan_name": "ECS Membership 2026",
            "profile_fields": [],
        }]

    monkeypatch.setattr("utils.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(find_subgroup_in_order(order, [{"name": "West Sound"}]))

    assert result == (77, 123, 30, 11, "West Sound")

def test_find_membership_item_in_order_matches_any_year_by_default():
    order = {"line_items": [{"name": "ECS Membership 2025"}]}

    result = asyncio.run(find_membership_item_in_order(order))

    assert result == "ECS Membership 2025"

def test_find_subgroup_in_order_skips_already_reconciled_membership(monkeypatch):
    order = {
        "id": 123,
        "customer_id": 77,
        "line_items": [
            {"id": 10, "product_id": 20, "name": "ECS Membership 2026"},
            {"id": 11, "product_id": 30, "name": "West Sound"},
        ],
    }

    async def fake_call_woocommerce_api(_url):
        return [{
            "id": 99,
            "plan_name": "ECS Membership 2026",
            "profile_fields": [{"slug": "ecs-subgroup", "value": "West Sound"}],
        }]

    monkeypatch.setattr("utils.call_woocommerce_api", fake_call_woocommerce_api)

    result = asyncio.run(find_subgroup_in_order(order, [{"name": "West Sound"}]))

    assert result is None

@pytest.mark.asyncio
async def test_find_membership_in_order_awaits_membership_lookup(recwarn):
    order = {
        'id': 126,
        'line_items': [
            {
                'name': 'ECS Membership 2024',
                'meta_data': []
            }
        ],
        'billing': {
            'first_name': 'Alice',
            'last_name': 'Example',
            'email': 'alice@example.com'
        }
    }

    result = await find_membership_in_order(order, membership_year=2024)

    assert result is not None
    assert result['first_name'] == 'Alice'
    assert not any('was never awaited' in str(w.message) for w in recwarn)

@pytest.mark.asyncio
async def test_find_customer_info_in_order_success():
    order = {
        'id': 123,
        'line_items': [
            {
                'name': 'ECS Membership 2024',
                'meta_data': []
            },
            {
                'name': 'Other Item',
                'meta_data': [
                    {
                        'key': 'Subgroup Designation',
                        'value': 'West Sound'
                    }
                ]
            }
        ],
        'billing': {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@example.com'
        }
    }
    subgroups = ['West Sound', 'Armed Forces']
    
    # Mocking datetime to ensure 2024 is the current year or match the membership year
    with patch('datetime.datetime') as mock_date:
        mock_date.now.return_value = datetime.datetime(2024, 1, 1)
        # Note: we need to handle the case where find_customer_info_in_order calls datetime.datetime.now().year
        # In utils.py: membership_year = datetime.datetime.now().year
        
        result = await find_customer_info_in_order(order, subgroups, membership_year=2024)
        
        assert result is not None
        matched_subgroups, customer_info = result
        assert 'West Sound' in matched_subgroups
        assert customer_info['first_name'] == 'Jane'

@pytest.mark.asyncio
async def test_find_customer_info_in_order_no_membership():
    order = {
        'id': 124,
        'line_items': [
            {
                'name': 'Just a Scarf',
                'meta_data': []
            }
        ]
    }
    subgroups = ['West Sound']
    result = await find_customer_info_in_order(order, subgroups, membership_year=2024)
    assert result is None

@pytest.mark.asyncio
async def test_find_customer_info_in_order_no_subgroup():
    order = {
        'id': 125,
        'line_items': [
            {
                'name': 'ECS Membership 2024',
                'meta_data': []
            }
        ]
    }
    subgroups = ['West Sound']
    result = await find_customer_info_in_order(order, subgroups, membership_year=2024)
    assert result is None
