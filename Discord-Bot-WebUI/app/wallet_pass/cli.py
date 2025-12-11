# app/wallet_pass/cli.py

"""
Wallet Pass CLI Commands

Flask CLI commands for managing wallet passes, including:
- Database initialization
- Pass type seeding
- Pass management utilities
"""

import click
import json
from flask import current_app
from flask.cli import with_appcontext


@click.group()
def wallet():
    """Wallet pass management commands."""
    pass


@wallet.command()
@with_appcontext
def init_types():
    """Initialize wallet pass types (ECS Membership, Pub League)."""
    from app.core import db
    from app.models.wallet import WalletPassType

    # ECS Membership pass type
    ecs_type = WalletPassType.query.filter_by(code='ecs_membership').first()
    if not ecs_type:
        ecs_type = WalletPassType(
            code='ecs_membership',
            name='ECS Membership',
            description='Annual ECS membership card valid for one calendar year',
            template_name='ecs_membership',
            background_color='#1a472a',  # Different green for ECS
            foreground_color='#ffffff',
            label_color='#c8c8c8',
            logo_text='ECS',
            validity_type='annual',
            validity_duration_days=365,
            grace_period_days=30,
            woo_product_patterns=json.dumps([
                r'ECS\s+\d{4}\s+Membership',
                r'ECS\s+Membership\s+\d{4}',
                r'ECS\s+Membership\s+Card',
                r'ECS\s+Membership\s+Package\s+\d{4}'
            ]),
            apple_pass_type_id='pass.com.weareecs.membership',
            google_issuer_id='3388000000022958274',
            google_class_id='ecs_membership',
            is_active=True,
            display_order=1
        )
        db.session.add(ecs_type)
        click.echo('Created ECS Membership pass type')
    else:
        click.echo('ECS Membership pass type already exists')

    # Pub League pass type
    pub_type = WalletPassType.query.filter_by(code='pub_league').first()
    if not pub_type:
        pub_type = WalletPassType(
            code='pub_league',
            name='Pub League',
            description='Seasonal Pub League membership card valid for one season',
            template_name='pub_league',
            background_color='#213e96',  # ECS Blue
            foreground_color='#ffffff',
            label_color='#c8c8c8',
            logo_text='ECS Pub League',
            validity_type='seasonal',
            validity_duration_days=182,  # ~6 months (half year)
            grace_period_days=30,
            woo_product_patterns=json.dumps([
                r'ECS\s+Pub\s+League',
                r'Pub\s+League\s+(Spring|Fall|Summer|Winter)\s+\d{4}'
            ]),
            apple_pass_type_id='pass.com.weareecs.membership',
            google_issuer_id='3388000000022958274',
            google_class_id='pub_league',
            is_active=True,
            display_order=2
        )
        db.session.add(pub_type)
        click.echo('Created Pub League pass type')
    else:
        click.echo('Pub League pass type already exists')

    db.session.commit()

    # Initialize default field configurations
    click.echo('Initializing default field configurations...')
    from app.models.wallet_config import initialize_wallet_config_defaults
    initialize_wallet_config_defaults()

    click.echo('Wallet pass types initialized successfully!')


@wallet.command()
@with_appcontext
def init_fields():
    """Initialize default field configurations for pass types."""
    from app.models.wallet_config import initialize_wallet_config_defaults

    click.echo('Initializing default field configurations...')
    initialize_wallet_config_defaults()
    click.echo('Field configurations initialized successfully!')


@wallet.command()
@with_appcontext
def list_types():
    """List all wallet pass types."""
    from app.models.wallet import WalletPassType

    types = WalletPassType.query.order_by(WalletPassType.display_order).all()
    if not types:
        click.echo('No pass types found. Run "flask wallet init-types" first.')
        return

    click.echo('\nWallet Pass Types:')
    click.echo('-' * 60)
    for pt in types:
        status = 'Active' if pt.is_active else 'Inactive'
        click.echo(f'{pt.code}: {pt.name} ({pt.validity_type}) [{status}]')
        click.echo(f'  Background: {pt.background_color}')
        click.echo(f'  Grace Period: {pt.grace_period_days} days')
    click.echo('-' * 60)


@wallet.command()
@with_appcontext
def stats():
    """Show wallet pass statistics."""
    from app.models.wallet import WalletPass, WalletPassType, WalletPassCheckin, PassStatus
    from sqlalchemy import func

    click.echo('\nWallet Pass Statistics:')
    click.echo('=' * 60)

    # Get pass types
    types = WalletPassType.query.all()

    for pt in types:
        total = WalletPass.query.filter_by(pass_type_id=pt.id).count()
        active = WalletPass.query.filter_by(
            pass_type_id=pt.id,
            status=PassStatus.ACTIVE.value
        ).count()
        voided = WalletPass.query.filter_by(
            pass_type_id=pt.id,
            status=PassStatus.VOIDED.value
        ).count()

        click.echo(f'\n{pt.name}:')
        click.echo(f'  Total Passes: {total}')
        click.echo(f'  Active: {active}')
        click.echo(f'  Voided: {voided}')

    # Overall stats
    total_passes = WalletPass.query.count()
    total_checkins = WalletPassCheckin.query.count()

    click.echo(f'\n{"=" * 60}')
    click.echo(f'Total Passes Issued: {total_passes}')
    click.echo(f'Total Check-ins: {total_checkins}')


@wallet.command()
@click.argument('barcode')
@with_appcontext
def validate(barcode):
    """Validate a pass by barcode data."""
    from app.models.wallet import WalletPass

    wallet_pass = WalletPass.find_by_barcode(barcode)
    if not wallet_pass:
        click.echo(f'Pass not found for barcode: {barcode}')
        return

    click.echo(f'\nPass Found:')
    click.echo(f'  Member: {wallet_pass.member_name}')
    click.echo(f'  Type: {wallet_pass.pass_type.name}')
    click.echo(f'  Status: {wallet_pass.status}')
    click.echo(f'  Valid: {wallet_pass.is_valid}')
    click.echo(f'  Valid Until: {wallet_pass.valid_until}')
    click.echo(f'  Days Until Expiry: {wallet_pass.days_until_expiry}')


@wallet.command()
@click.option('--name', prompt='Member name', help='Name for the membership')
@click.option('--email', prompt='Member email', help='Email address')
@click.option('--year', prompt='Membership year', type=int, help='Year (e.g., 2025)')
@click.option('--order-id', default=None, type=int, help='WooCommerce order ID')
@with_appcontext
def create_ecs(name, email, year, order_id):
    """Create an ECS membership pass manually."""
    from app.core import db
    from app.models.wallet import create_ecs_membership_pass

    try:
        wallet_pass = create_ecs_membership_pass(
            member_name=name,
            member_email=email,
            year=year,
            woo_order_id=order_id
        )
        db.session.add(wallet_pass)
        db.session.commit()

        click.echo(f'\nECS Membership Pass Created:')
        click.echo(f'  Serial: {wallet_pass.serial_number}')
        click.echo(f'  Download Token: {wallet_pass.download_token}')
        click.echo(f'  Barcode: {wallet_pass.barcode_data}')
        click.echo(f'  Valid: {wallet_pass.valid_from.date()} to {wallet_pass.valid_until.date()}')
    except Exception as e:
        click.echo(f'Error creating pass: {e}', err=True)


@wallet.command()
@with_appcontext
def create_tables():
    """Create wallet pass database tables."""
    from app.core import db
    # Import all wallet models so db.create_all() creates all tables
    from app.models.wallet import (
        WalletPassType, WalletPass, WalletPassDevice, WalletPassCheckin
    )
    from app.models.wallet_config import (
        WalletLocation, WalletSponsor, WalletSubgroup,
        WalletPassFieldConfig, WalletBackField
    )
    from app.models.wallet_asset import (
        WalletAsset, WalletTemplate, WalletCertificate
    )

    click.echo('Creating wallet pass tables...')

    # Create tables for all wallet models
    with current_app.app_context():
        # This will create all tables that don't exist
        db.create_all()

    click.echo('Tables created successfully!')
    click.echo('Tables created:')
    click.echo('  - wallet_pass_type, wallet_pass, wallet_pass_device, wallet_pass_checkin')
    click.echo('  - wallet_location, wallet_sponsor, wallet_subgroup')
    click.echo('  - wallet_pass_field_config, wallet_back_field')
    click.echo('  - wallet_asset, wallet_template, wallet_certificate')
    click.echo('')
    click.echo('Now run "flask wallet init-types" to seed pass types.')


def register_cli(app):
    """Register wallet CLI commands with Flask app."""
    app.cli.add_command(wallet)
