# tests/test_utils.py

import pytest
import datetime
from unittest.mock import MagicMock, patch
from utils import (
    convert_to_pst,
    normalize_string,
    extract_designation,
    extract_customer_info,
    find_customer_info_in_order,
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
