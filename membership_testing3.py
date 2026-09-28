#!/usr/bin/env python3
"""
testing3.py — Membership & subgroup reconciliation runner

For every order (within a configurable window) that contains an ECS Membership:

  1. Detect the membership year and the customer's membership record.
  2. Look for a standalone subgroup item in the same order.
  3. If the customer HAS a membership record and the 'ecs-subgroup' profile field is
     absent or blank, PUT the subgroup value from the standalone item onto it.
  4. If the customer has NO membership record, POST to create one (using the
     matching plan for that year), then set the subgroup if one was found.

Flags:
    --dry-run       Preview every action without writing to WooCommerce (default).
    --apply         Apply membership and subgroup updates to WooCommerce.
  --year          Restrict to orders whose membership year matches (e.g. 2026).
  --after         ISO-8601 date/datetime; only orders after this point (default: 7 days ago).
  --order-id      Process one specific order ID only.
  --page          Start pagination at this page (default: 1).
  --max-pages     Stop after N pages (default: unlimited).
  --log-level     debug | info | warning  (default: info)

Usage examples:
    python membership_testing3.py --dry-run
    python membership_testing3.py --year 2026
    python membership_testing3.py --apply --order-id 1012865 --log-level debug
    python membership_testing3.py --after 2026-02-01 --year 2026
"""

import argparse
import asyncio
import datetime
import json
import logging
import re
import sys

from config import BOT_CONFIG
from api_helpers import call_woocommerce_api
from utils import (
    find_membership_item_in_order,
    find_subgroup_item_in_order,
    find_membership_plan_for_year,
    normalize_string,
)

wc_url: str = BOT_CONFIG["wc_url"]  # e.g. https://site.com/wp-json/wc/v3/orders/
ELIGIBLE_ORDER_STATUSES = {"processing", "completed"}

# ---------------------------------------------------------------------------
# Helpers inlined from woocommerce_commands.py (avoid importing the Discord cog)
# ---------------------------------------------------------------------------

async def init_subgroups() -> list[dict]:
    """
    Pull the list of known subgroup products from WooCommerce (category = 'Subgroup').
    Returns a list of  {"name": ..., "name_normalized": ..., "id": ...}  dicts.
    """
    base_wc_url = wc_url.replace("/orders/", "/")
    categories = await call_woocommerce_api(f"{base_wc_url}products/categories?per_page=100")
    if not categories:
        logging.error("Could not fetch product categories from WooCommerce.")
        return []

    subgroup_category = next(
        (c for c in categories if c.get("name", "").lower() == "subgroup"), None
    )
    if subgroup_category is None:
        logging.error("'Subgroup' product category not found in WooCommerce.")
        return []

    products = await call_woocommerce_api(
        f"{base_wc_url}products?category={subgroup_category['id']}&per_page=100"
    )
    if not products:
        return []

    return [
        {
            "name": p.get("name", ""),
            "name_normalized": normalize_string(p.get("name", "")),
            "id": p.get("id", ""),
        }
        for p in products
    ]


async def get_membership_records_for_customer(customer_id: int | str) -> list[dict]:
    """Return all WC Membership records for the given customer."""
    base_url = wc_url.replace("/orders/", "/memberships/members/")
    result = await call_woocommerce_api(f"{base_url}?customer={customer_id}")
    return result if isinstance(result, list) else []


async def get_membership_record(member_id: int | str) -> dict | None:
    """Fetch a single WC Membership record by member ID."""
    base_url = wc_url.replace("/orders/", "/memberships/members/")
    return await call_woocommerce_api(f"{base_url}{member_id}")


async def create_membership_record(
    customer_id: int | str,
    plan_id: int | str,
    order_id: int | str,
    *,
    dry_run: bool = False,
) -> dict | None:
    """
    POST a new WC Membership record.  Returns the created record dict, or None on failure.
    """
    base_url = wc_url.replace("/orders/", "/memberships/members")
    payload = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "order_id": order_id,
        "status": "active",
    }

    if dry_run:
        logging.info(
            f"[DRY-RUN] Would POST {base_url} — "
            f"customer_id={customer_id}, plan_id={plan_id}, order_id={order_id}"
        )
        return {"id": "DRY-RUN", "customer_id": customer_id, "plan_id": plan_id}

    try:
        response = await call_woocommerce_api(base_url, method="POST", data=json.dumps(payload))
        if response and response.get("id"):
            logging.info(
                f"Created membership record ID {response['id']} for customer {customer_id} "
                f"/ plan {plan_id} / order {order_id}."
            )
            return response
        else:
            logging.error(
                f"Failed to create membership for customer {customer_id} / plan {plan_id}. "
                f"Response: {response}"
            )
            return None
    except Exception as exc:
        logging.exception(f"Exception creating membership for customer {customer_id}: {exc}")
        return None


async def update_ecs_subgroup(
    member_id: int | str,
    subgroup_value: str,
    *,
    dry_run: bool = False,
) -> bool:
    """
    PUT the 'ecs-subgroup' profile field on a membership record.
    """
    base_url = wc_url.replace("/orders/", "/memberships/members/")
    api_url = f"{base_url}{member_id}"
    payload = {"profile_fields": [{"slug": "ecs-subgroup", "value": subgroup_value}]}

    if dry_run:
        logging.info(
            f"[DRY-RUN] Would PUT {api_url} — ecs-subgroup = '{subgroup_value}'"
        )
        return True

    try:
        response = await call_woocommerce_api(api_url, method="PUT", data=json.dumps(payload))
        if response and response.get("id"):
            # Verify the field actually changed in the response
            actual = next(
                (
                    f.get("value", "")
                    for f in response.get("profile_fields", [])
                    if f.get("slug") == "ecs-subgroup"
                ),
                None,
            )
            if actual == subgroup_value:
                logging.info(
                    f"Updated ecs-subgroup = '{subgroup_value}' for member ID {member_id}."
                )
                return True
            else:
                logging.warning(
                    f"PUT member {member_id} returned HTTP 200 but ecs-subgroup is "
                    f"'{actual}' (expected '{subgroup_value}'). Content-Type header may be missing."
                )
                return False
        else:
            logging.error(
                f"Failed to update ecs-subgroup for member ID {member_id}. Response: {response}"
            )
            return False
    except Exception as exc:
        logging.exception(f"Exception updating ecs-subgroup for member ID {member_id}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Plan-ID cache so we only fetch the plans list once per run
# ---------------------------------------------------------------------------
_plan_cache: dict[int, int | None] = {}   # year -> plan_id


async def get_plan_id_for_year(year: int) -> int | None:
    if year in _plan_cache:
        return _plan_cache[year]

    base_url = wc_url.replace("/orders/", "/memberships/")
    plans = await call_woocommerce_api(f"{base_url}plans?per_page=100")
    if not plans:
        logging.error("Could not fetch membership plans from WooCommerce.")
        _plan_cache[year] = None
        return None

    plan_id = await find_membership_plan_for_year(plans, year)
    _plan_cache[year] = plan_id
    if plan_id:
        logging.debug(f"Resolved plan_id={plan_id} for year {year}.")
    else:
        logging.warning(f"No membership plan found for year {year}.")
    return plan_id


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def process_order(
    order: dict,
    subgroups: list[dict],
    *,
    year_filter: int | None,
    dry_run: bool,
    stats: dict,
) -> None:
    order_id = order.get("id", "?")
    customer_id = order.get("customer_id")
    order_status = normalize_string(order.get("status", ""))

    # Step 1 — Does the order contain an ECS Membership?
    membership_product_name = await find_membership_item_in_order(order, year_filter)
    if not membership_product_name:
        return

    if order_status not in ELIGIBLE_ORDER_STATUSES:
        logging.info(
            f"Order {order_id}: status '{order.get('status', '')}' is not eligible for reconciliation — skipping."
        )
        return

    stats["orders_with_membership"] += 1

    year_match = re.search(r"\d{4}", membership_product_name)
    if not year_match:
        logging.warning(
            f"Order {order_id}: cannot extract year from '{membership_product_name}' — skipping."
        )
        return
    order_year = int(year_match.group())

    if year_filter is not None and order_year != year_filter:
        return

    logging.info(
        f"Order {order_id}: customer {customer_id}, "
        f"membership='{membership_product_name}' (year {order_year})"
    )

    # Step 2 — Is there a standalone subgroup item in the same order?
    subgroup_item = await find_subgroup_item_in_order(order, subgroups)
    if subgroup_item:
        _, subgroup_name = subgroup_item
        logging.info(f"Order {order_id}: standalone subgroup item found → '{subgroup_name}'")
    else:
        subgroup_name = None
        logging.debug(f"Order {order_id}: no standalone subgroup item.")

    # Fetch the customer's existing membership records
    if not customer_id or int(customer_id) == 0:
        logging.info(f"Order {order_id}: guest order (customer_id=0) — skipping.")
        stats["memberships_skipped_guest"] += 1
        return

    existing_memberships = await get_membership_records_for_customer(customer_id)
    plan_names_for_year = {
        normalize_string(f"ECS Member {order_year}"),
        normalize_string(f"ECS Membership {order_year}"),
    }

    matching_record = next(
        (
            m for m in existing_memberships
            if normalize_string(m.get("plan_name", "")) in plan_names_for_year
        ),
        None,
    )

    if matching_record:
        # ----------------------------------------------------------------
        # Step 3 — Customer has a membership record; check ecs-subgroup
        # ----------------------------------------------------------------
        member_id = matching_record.get("id")
        existing_subgroup = next(
            (
                f.get("value", "")
                for f in matching_record.get("profile_fields", [])
                if f.get("slug") == "ecs-subgroup"
            ),
            "",
        )

        if subgroup_name:
            if existing_subgroup:
                if existing_subgroup.strip().lower() == subgroup_name.strip().lower():
                    logging.info(
                        f"Order {order_id}: member {member_id} already has "
                        f"ecs-subgroup='{existing_subgroup}' — no update needed."
                    )
                    stats["subgroup_already_set"] += 1
                else:
                    logging.info(
                        f"Order {order_id}: member {member_id} has ecs-subgroup='{existing_subgroup}' "
                        f"but order has '{subgroup_name}' — updating."
                    )
                    stats["subgroup_updates_attempted"] += 1
                    ok = await update_ecs_subgroup(member_id, subgroup_name, dry_run=dry_run)
                    if ok:
                        stats["subgroup_updates_succeeded"] += 1
                    else:
                        stats["subgroup_updates_failed"] += 1
            else:
                logging.info(
                    f"Order {order_id}: member {member_id} has no ecs-subgroup; "
                    f"setting '{subgroup_name}'."
                )
                stats["subgroup_updates_attempted"] += 1
                ok = await update_ecs_subgroup(member_id, subgroup_name, dry_run=dry_run)
                if ok:
                    stats["subgroup_updates_succeeded"] += 1
                else:
                    stats["subgroup_updates_failed"] += 1
        else:
            logging.debug(
                f"Order {order_id}: member {member_id} exists; no standalone subgroup to apply."
            )

    else:
        # ----------------------------------------------------------------
        # Step 4 — No membership record found; create one
        # ----------------------------------------------------------------
        logging.info(
            f"Order {order_id}: customer {customer_id} has no membership record "
            f"for 'ECS Member {order_year}' — will create."
        )
        stats["memberships_create_attempted"] += 1

        plan_id = await get_plan_id_for_year(order_year)
        if not plan_id:
            logging.error(
                f"Order {order_id}: no plan_id found for year {order_year} — cannot create membership."
            )
            stats["memberships_create_failed"] += 1
            return

        new_record = await create_membership_record(
            customer_id, plan_id, order_id, dry_run=dry_run
        )
        if not new_record:
            stats["memberships_create_failed"] += 1
            return

        stats["memberships_create_succeeded"] += 1

        # If there's a subgroup item, set it on the new record too
        if subgroup_name:
            new_member_id = new_record.get("id")
            logging.info(
                f"Order {order_id}: setting ecs-subgroup='{subgroup_name}' "
                f"on new member ID {new_member_id}."
            )
            stats["subgroup_updates_attempted"] += 1
            ok = await update_ecs_subgroup(new_member_id, subgroup_name, dry_run=dry_run)
            if ok:
                stats["subgroup_updates_succeeded"] += 1
            else:
                stats["subgroup_updates_failed"] += 1


async def run_reconciliation(
    *,
    dry_run: bool = True,
    year: int | None = None,
    after: str | None = None,
    order_id: int | None = None,
    start_page: int = 1,
    max_pages: int | None = None,
) -> dict:
    stats = {
        "orders_examined": 0,
        "orders_with_membership": 0,
        "memberships_create_attempted": 0,
        "memberships_create_succeeded": 0,
        "memberships_create_failed": 0,
        "memberships_skipped_guest": 0,
        "subgroup_already_set": 0,
        "subgroup_updates_attempted": 0,
        "subgroup_updates_succeeded": 0,
        "subgroup_updates_failed": 0,
    }

    # Resolve subgroup list once
    logging.info("Fetching subgroup product list from WooCommerce...")
    subgroups = await init_subgroups()
    logging.info(f"Found {len(subgroups)} subgroup products.")

    # Default date window: 7 days (mirrors the Discord commands)
    if after is None:
        after_dt = datetime.datetime.now() - datetime.timedelta(days=7)
        after = after_dt.strftime("%Y-%m-%dT%H:%M:%S")
    elif "T" not in after:
        # Bare date supplied (e.g. 2026-01-26) — WooCommerce requires a full datetime
        after = after + "T00:00:00"

    per_page = 100
    page = start_page
    pages_processed = 0

    # Single-order mode
    if order_id is not None:
        url = f"{wc_url}{order_id}"
        logging.info(f"Fetching single order: {url}")
        order = await call_woocommerce_api(url)
        if not order:
            logging.error(f"Order {order_id} not found or API error.")
            return stats
        stats["orders_examined"] += 1
        await process_order(order, subgroups, year_filter=year, dry_run=dry_run, stats=stats)
        return stats

    # Paginated mode
    while True:
        orders_url = (
            f"{wc_url}?order=desc&page={page}&per_page={per_page}"
            f"&status=any&after={after}"
        )
        logging.info(f"Fetching page {page}: {orders_url}")
        fetched_orders = await call_woocommerce_api(orders_url)

        if not fetched_orders:
            logging.info(f"No orders returned on page {page}. Stopping.")
            break

        for order in fetched_orders:
            stats["orders_examined"] += 1
            await process_order(order, subgroups, year_filter=year, dry_run=dry_run, stats=stats)

        pages_processed += 1

        if len(fetched_orders) < per_page:
            logging.info(
                f"Page {page} returned {len(fetched_orders)} orders (< {per_page}). Last page."
            )
            break

        if max_pages is not None and pages_processed >= max_pages:
            logging.info(f"Reached --max-pages limit of {max_pages}. Stopping.")
            break

        page += 1
        await asyncio.sleep(1)

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Membership & subgroup reconciliation runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true",
                      help="Preview all actions without writing to WooCommerce (default).")
    mode.add_argument("--apply", dest="dry_run", action="store_false",
                      help="Apply membership and subgroup updates to WooCommerce.")
    p.set_defaults(dry_run=True)
    p.add_argument("--year", type=int, metavar="YYYY",
                   help="Only process orders whose membership year matches (e.g. 2026).")
    p.add_argument("--after", metavar="DATE",
                   help="Only orders after this ISO-8601 date (default: 7 days ago).")
    p.add_argument("--order-id", type=int, metavar="ID",
                   help="Process only this single WooCommerce order ID.")
    p.add_argument("--page", type=int, default=1, metavar="N",
                   help="Start pagination at page N (default: 1).")
    p.add_argument("--max-pages", type=int, default=None, metavar="N",
                   help="Stop after N pages (default: all pages).")
    p.add_argument("--log-level", default="info",
                   choices=["debug", "info", "warning", "error"],
                   help="Logging verbosity (default: info).")
    return p.parse_args(argv)


async def _main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    if not wc_url:
        sys.exit("[ERROR] WC_URL is not set in your .env file.")

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print()
    print("=" * 62)
    print(f"  Membership & Subgroup Reconciliation  —  {mode} mode")
    if args.dry_run:
        print("  No data will be written to WooCommerce.")
    if args.year:
        print(f"  Year filter  : {args.year}")
    if args.after:
        print(f"  After        : {args.after}")
    if args.order_id:
        print(f"  Single order : {args.order_id}")
    if args.max_pages:
        print(f"  Max pages    : {args.max_pages}")
    print("=" * 62)
    print()

    stats = await run_reconciliation(
        dry_run=args.dry_run,
        year=args.year,
        after=args.after,
        order_id=args.order_id,
        start_page=args.page,
        max_pages=args.max_pages,
    )

    print()
    print("=" * 62)
    print("  SUMMARY")
    print("=" * 62)
    for key, value in stats.items():
        print(f"  {key.replace('_', ' ').capitalize():<42} {value}")
    print()


if __name__ == "__main__":
    asyncio.run(_main())
