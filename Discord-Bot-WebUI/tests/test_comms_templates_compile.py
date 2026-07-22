"""Compile-check every admin-panel communication template.

get_template() fully compiles through the app's Jinja env: resolves
{% extends %}, {% from ... import %} macros, {% call page_header() %} arg
validity, and block balance — everything short of runtime data. A failure here
is a page that would 500 on render. Guards the classic-branch strip + the
page_header header conversions.
"""
import glob
import os

import pytest


def _comms_templates():
    files = sorted(glob.glob('app/templates/admin_panel/communication/*.html'))
    files.append('app/templates/admin_panel/push_notifications_flowbite.html')
    return [f.split('app/templates/', 1)[1] for f in files]


@pytest.mark.parametrize('name', _comms_templates())
def test_comms_template_compiles(app, name):
    with app.app_context():
        app.jinja_env.get_template(name)  # raises on syntax/macro/balance error
