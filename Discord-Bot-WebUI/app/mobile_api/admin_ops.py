# app/mobile_api/admin_ops.py

"""
Mobile Admin — Announcements & Wallet Pass Lookup

Two small desk jobs that were web-only:

* ``POST /admin/announcements`` — "kickoff moved to 8, tell Blue FC". Rides the
  existing multi-channel composer spine (ComposedMessage + the notification
  orchestrator), so every member's channel preferences are honoured the same way
  they are from the website. Send-now only: the client has no scheduling UI and
  none is wanted, so nothing here builds one.

* ``GET/POST /admin/wallet/pass`` — the gate lookup. When someone at the door
  says "my pass doesn't work", this is what answers it, plus the two actions it
  can tell you to take. They are NOT interchangeable: ``/resend`` re-delivers
  the download link to a pass that never arrived; ``/reissue`` rebuilds the
  artifacts of a pass that arrived and renders wrong. Reaching for reissue on an
  undelivered pass rebuilds files nobody has and changes nothing the person can
  see.

Gate: ``@jwt_required()`` + ``@jwt_role_required(ADMIN_ROLES)`` — the same
``['Global Admin', 'Pub League Admin']`` pair the web pages and the app's own
``canManageMemberLifecycleProvider`` use.
"""

import logging
from datetime import datetime, timedelta

from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.mobile_api import mobile_api_v2
from app.core import db
from app.core.session_manager import managed_session
from app.decorators import jwt_role_required

logger = logging.getLogger(__name__)

ADMIN_ROLES = ['Global Admin', 'Pub League Admin']

# What an announcement goes out on when the client doesn't say. The app has no
# channel picker, so this default IS the behaviour for every mobile-sent
# announcement. in_app + push is the pair that reaches a phone without spending
# an email or an SMS on "kickoff moved by 30 minutes".
DEFAULT_CHANNELS = ('in_app', 'push')


def _body():
    """Request body as a dict, JSON or form."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict()
    return {}


# ==================== §7 announcements ====================

def _league_ids_for_type(session, league_type):
    """A league_type/lane/program spelling -> the CURRENT-season League ids.

    ``audience_service`` resolves the 'league' audience by ``League.id``, but the
    client sends a program vocabulary word ('premier'). Resolve through the
    registry so a newly registered program is targetable the day it is seeded,
    and so the app never has to carry a league-id table that goes stale at
    rollover.

    ⚠️ CURRENT SEASONS ONLY, and that restriction is load-bearing.
    ``League.season_id`` is NOT NULL, so there is one "Premier" row PER SEASON —
    a bare ``League.name == 'Premier'`` returns every Premier league that has
    ever existed, and the audience resolver would then sweep in everyone who
    played Premier in any past season and still has an active account. That is a
    silently over-broad blast with no error and no way to tell from the reach
    count that it happened.
    """
    from app.models import League, Season

    raw = (league_type or '').strip()
    if not raw:
        return [], None

    league_name, label = None, None
    try:
        from app.services import program_registry
        pr = (program_registry.by_form_value(raw)
              or program_registry.by_membership_lane(raw)
              or program_registry.by_key(raw)
              or program_registry.by_league_name(raw))
        if pr is not None:
            league_name = pr.league_name
            label = pr.display_name or pr.league_name
    except Exception:
        logger.warning("announcement league lookup fell back to a name match",
                       exc_info=True)

    if not league_name:
        # Registry miss — try the literal as a League.name before giving up, so
        # an admin typing the real league name isn't rejected.
        league_name = raw

    rows = (session.query(League)
            .join(Season, Season.id == League.season_id)
            .filter(League.name.ilike(league_name),
                    Season.is_current.is_(True))
            .all())
    return [l.id for l in rows], (label or league_name)


@mobile_api_v2.route('/admin/announcements', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_send_announcement():
    """Send an announcement now.

    Body: {"message": "...", "title": "...", "team_id": 42} OR
          {"message": "...", "title": "...", "league_type": "premier"}
    plus optional {"channels": ["in_app", "push", "email", "sms", "discord"]}.

    Exactly ONE of ``team_id`` / ``league_type`` — targeting both would be two
    announcements wearing one trench coat, and the reach preview could not
    honestly describe it.

    SEND NOW only. There is deliberately no ``scheduled_send_time``: the client
    has no scheduling UI, and an endpoint that silently accepted one would let a
    typo park an announcement in the future with nothing on the phone to show
    for it.

    Delivery runs through the same ComposedMessage + orchestrator path as the
    web composer, so opt-outs are honoured — this endpoint cannot force past
    them (no ``force_delivery``), because a phone-sized surface is the wrong
    place to make that call.
    """
    from app.models import ComposedMessage, Team
    from app.models.admin_config import AdminAuditLog
    from app.services import audience_service
    # The composer's own vocabulary and limits, imported rather than restated so
    # the two surfaces can't disagree about what a channel is or what "too long"
    # means.
    from app.admin_panel.routes.communication.composer import (
        VALID_CHANNELS, MAX_TITLE, MAX_MESSAGE)

    data = _body()
    actor_id = int(get_jwt_identity())

    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'message is required'}), 400

    # Title is optional in the client contract but required by the spine (it is
    # the push notification's headline). Fall back to something a member can
    # actually read on a lock screen rather than an empty bold line.
    title = (data.get('title') or '').strip() or 'League announcement'

    if len(title) > MAX_TITLE or len(message) > MAX_MESSAGE:
        return jsonify({'success': False,
                        'error': f'Title must be under {MAX_TITLE} characters '
                                 f'and the message under {MAX_MESSAGE}.'}), 400

    team_id = data.get('team_id')
    league_type = data.get('league_type')
    if bool(team_id) == bool(league_type):
        return jsonify({'success': False,
                        'error': 'Send to exactly one of team_id or league_type.'}), 400

    channels = [c for c in (data.get('channels') or []) if c in VALID_CHANNELS]
    if not channels:
        channels = list(DEFAULT_CHANNELS)

    try:
        with managed_session() as session:
            if team_id:
                try:
                    team_id = int(team_id)
                except (TypeError, ValueError):
                    return jsonify({'success': False,
                                    'error': 'team_id must be a number'}), 400
                team = session.query(Team).get(team_id)
                if team is None:
                    return jsonify({'success': False, 'error': 'Team not found'}), 404
                audience_type, audience_ids = 'team', [team_id]
            else:
                audience_ids, _label = _league_ids_for_type(session, league_type)
                if not audience_ids:
                    return jsonify({
                        'success': False,
                        'error': f"No league matches '{league_type}'.",
                    }), 404
                audience_type = 'league'

            # Re-resolved at send time; this is a sanity check so an empty
            # audience fails loudly NOW rather than silently sending to nobody.
            user_ids = audience_service.resolve_user_ids(
                session, audience_type, audience_ids)
            if not user_ids:
                return jsonify({'success': False,
                                'error': 'No members match that audience.'}), 400
            description = audience_service.describe(
                session, audience_type, audience_ids)

        # Idempotency: an identical announcement from the same admin inside 60s
        # is a double-tap or a client retry, not a second blast. Same window the
        # web composer uses.
        duplicate = db.session.query(ComposedMessage).filter(
            ComposedMessage.created_by_id == actor_id,
            ComposedMessage.title == title,
            ComposedMessage.message == message,
            ComposedMessage.created_at >= datetime.utcnow() - timedelta(seconds=60),
        ).first()
        if duplicate:
            return jsonify({
                'success': False,
                'error': 'You just sent that same announcement — check before resending.',
                'message_id': duplicate.id,
            }), 409

        msg = ComposedMessage(
            title=title,
            message=message,
            channels=channels,
            audience_type=audience_type,
            audience_ids=audience_ids,
            audience_description=description,
            priority='normal',
            force_delivery=False,
            status='scheduled',
            scheduled_send_time=None,
            total_recipients=len(user_ids),
            created_by_id=actor_id,
        )
        db.session.add(msg)
        # COMMIT BEFORE ENQUEUE. A worker can dequeue and look the row up before
        # a deferred commit lands; the task then dies with "Message not found"
        # (max_retries=0) and the row is stuck "scheduled" forever.
        db.session.commit()

        from app.tasks.tasks_composed_messages import send_composed_message
        try:
            result = send_composed_message.delay(msg.id)
        except Exception as enqueue_err:
            logger.error(f"Could not enqueue announcement {msg.id}: {enqueue_err}")
            msg.status = 'failed'
            msg.error_message = 'Could not queue the delivery task — check the task broker.'
            db.session.commit()
            return jsonify({
                'success': False,
                'error': 'The announcement was saved but could not be queued for '
                         'delivery. Check the task queue and retry.',
                'message_id': msg.id,
            }), 502

        msg.celery_task_id = getattr(result, 'id', None)
        db.session.commit()

        try:
            AdminAuditLog.log_action(
                user_id=actor_id, action='COMPOSE_MESSAGE',
                resource_type='ComposedMessage', resource_id=str(msg.id),
                new_value=(f'"{title}" via {"/".join(channels)} to {description} '
                           f'({len(user_ids)} members) [mobile, immediate]'),
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent'))
        except Exception as exc:
            logger.warning(f"audit log skipped for announcement {msg.id}: {exc}")

        return jsonify({
            'success': True,
            'message_id': msg.id,
            'recipients': len(user_ids),
            'channels': channels,
            'audience': description,
            'status_message': 'Sending now',
        }), 200

    except Exception as exc:
        logger.error(f"[MOBILE_API] announcement send failed: {exc}", exc_info=True)
        db.session.rollback()
        return jsonify({'success': False,
                        'error': 'Could not send the announcement.'}), 500


# ==================== §8 wallet pass lookup ====================

@mobile_api_v2.route('/admin/wallet/pass', methods=['GET'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_wallet_pass_lookup():
    """"My pass doesn't work" — answered at the gate. Query: ``player_id``.

    ``download_count`` is the field to look at FIRST and the reason this
    endpoint exists: 0 means the pass was issued but never landed on their
    phone, which is a completely different problem from a broken ``.pkpass``
    and is the one that actually happens. ``diagnosis`` names it so nobody has
    to remember that.

    Returns every pass for the player, not just the active one — a voided pass
    they are still showing you is itself the answer.
    """
    from app.models import Player
    from app.models.wallet import WalletPass

    player_id = request.args.get('player_id', type=int)
    if not player_id:
        return jsonify({'success': False, 'error': 'player_id is required'}), 400

    try:
        with managed_session() as session:
            player = session.query(Player).get(player_id)
            if player is None:
                return jsonify({'success': False, 'error': 'Player not found'}), 404

            rows = (session.query(WalletPass)
                    .filter(WalletPass.player_id == player_id)
                    .order_by(WalletPass.created_at.desc()).all())

            passes = []
            for wp in rows:
                item = wp.to_dict()
                if wp.status == 'active' and (wp.download_count or 0) == 0:
                    item['diagnosis'] = (
                        "Issued but never downloaded — it never reached their "
                        "phone. Resend the download link rather than reissuing.")
                    # Machine-readable twin of the sentence above, so the client
                    # can offer the button without parsing English. Matches the
                    # last path segment of POST /admin/wallet/pass/<action>.
                    item['suggested_action'] = 'resend'
                elif wp.status == 'voided':
                    item['diagnosis'] = (
                        f"Voided{f' — {wp.voided_reason}' if wp.voided_reason else ''}. "
                        f"Any copy on their phone is out of date.")
                elif not wp.is_valid:
                    item['diagnosis'] = "Outside its validity window."
                passes.append(item)

            active = next((p for p in passes if p.get('status') == 'active'), None)

            return jsonify({
                'success': True,
                'player_id': player_id,
                'player_name': player.name,
                'is_current_player': bool(player.is_current_player),
                'passes': passes,
                'active_pass': active,
                # Stated plainly: no pass at all is a different answer from a
                # broken one, and it means somebody never linked their order.
                'has_pass': bool(passes),
            }), 200

    except Exception as exc:
        logger.error(f"[MOBILE_API] wallet pass lookup for player {player_id} "
                     f"failed: {exc}", exc_info=True)
        return jsonify({'success': False,
                        'error': 'Could not look up the pass.'}), 500


def _mask_email(address):
    """'gecourville@gmail.com' -> 'g**********e@gmail.com'.

    Enough for an admin to confirm WHICH address the link went to and read the
    domain back to the person standing in front of them, without printing a full
    address into a response body or a log line. The member worklist deliberately
    carries no email at all (it is PII-encrypted at rest); this is the smallest
    thing that still answers "where did it go?".
    """
    address = (address or '').strip()
    if '@' not in address:
        return None
    local, _, domain = address.partition('@')
    if len(local) <= 2:
        return f"{local[:1]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def _pass_division(session, wallet_pass, player):
    """Division label for the pass-ready email, best available source.

    The order line item is the authority (it is what the buyer paid for and what
    minted the pass); the player's league is the fallback; the pass type name is
    the floor. Never guessed from the team name — a player is moved between
    teams within a division all season.
    """
    try:
        from app.models.pub_league_order import PubLeagueOrder, PubLeagueOrderLineItem
        if wallet_pass.woo_order_id and player is not None:
            row = (session.query(PubLeagueOrderLineItem)
                   .join(PubLeagueOrder,
                         PubLeagueOrderLineItem.order_id == PubLeagueOrder.id)
                   .filter(PubLeagueOrder.woo_order_id == wallet_pass.woo_order_id,
                           PubLeagueOrderLineItem.assigned_player_id == player.id)
                   .first())
            if row is not None and row.division:
                return row.division
    except Exception as exc:
        logger.warning(f"division lookup for pass {wallet_pass.id} failed: {exc}")
    league = getattr(player, 'league', None) if player is not None else None
    if league is not None and getattr(league, 'name', None):
        return league.name
    pass_type = getattr(wallet_pass, 'pass_type', None)
    return getattr(pass_type, 'name', None) or 'ECS FC'


@mobile_api_v2.route('/admin/wallet/pass/resend', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_wallet_pass_resend():
    """Email the pass download link again. Body: {"player_id": 908}

    This is the action `GET /admin/wallet/pass` tells the admin to take. Its
    ``diagnosis`` for a ``download_count`` of 0 reads "Resend the download link
    rather than reissuing" — and until now there was no endpoint to do it, so
    the app printed an instruction it could not follow.

    ⚠️ RESEND IS NOT REISSUE, and the difference is the whole point.
    ``/reissue`` rebuilds the Apple/Google artifacts and pushes a refresh to
    devices that already hold the pass — it fixes a pass that renders wrong. It
    does nothing whatsoever for a pass that never arrived, because there is no
    device registered to push to. This re-DELIVERS: it sends the same
    pass-ready email, with the same ``download_token``, that
    ``generate_wallet_pass_for_line_item`` sends when the pass is first created.

    Nothing about the pass changes — no new token, no rotated barcode, no
    version bump — so a copy already on someone's phone keeps working. That also
    means ``download_count`` stays 0 until they actually tap the link, which is
    what makes it a truthful delivery signal afterwards.

    Repeat sends are allowed on purpose: "I still didn't get it" is the normal
    second call, and a cooldown that silently swallowed the retry would look
    exactly like the original failure. Every send is audit-logged.
    """
    from app.models import Player
    from app.models.wallet import WalletPass

    data = _body()
    player_id = data.get('player_id')
    try:
        player_id = int(player_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'player_id is required'}), 400

    try:
        with managed_session() as session:
            player = session.query(Player).get(player_id)
            if player is None:
                return jsonify({'success': False, 'error': 'Player not found'}), 404

            wallet_pass = (session.query(WalletPass)
                           .filter(WalletPass.player_id == player_id,
                                   WalletPass.status == 'active')
                           .order_by(WalletPass.created_at.desc()).first())
            if wallet_pass is None:
                # Same wording as reissue: no active pass is an entitlement
                # question for the order desk, not something a gate button
                # should manufacture.
                return jsonify({
                    'success': False,
                    'error': f'{player.name} has no active pass to send. If they '
                             f'paid, link their order line item on the order desk — '
                             f'that is what issues a pass.',
                }), 409

            # Same precedence generate_wallet_pass_for_line_item uses, plus the
            # address stamped on the pass itself as a last resort. Reported back
            # so the admin can say WHICH inbox to check rather than "an email".
            source, recipient = None, None
            if player.user and player.user.email:
                source, recipient = 'account', player.user.email
            elif wallet_pass.member_email:
                source, recipient = 'pass', wallet_pass.member_email
            else:
                try:
                    from app.models.pub_league_order import PubLeagueOrder
                    order = (session.query(PubLeagueOrder)
                             .filter(PubLeagueOrder.woo_order_id ==
                                     wallet_pass.woo_order_id).first()
                             if wallet_pass.woo_order_id else None)
                    if order is not None and order.customer_email:
                        source, recipient = 'order', order.customer_email
                except Exception as exc:
                    logger.warning(f"order email lookup for pass {wallet_pass.id} "
                                   f"failed: {exc}")

            if not recipient:
                # A dead end stated plainly beats a success nobody receives.
                return jsonify({
                    'success': False,
                    'error': f'No email address on file for {player.name} — not on '
                             f'their account, the pass, or the order. There is '
                             f'nowhere to send the link.',
                    'player_id': player_id,
                    'pass_id': wallet_pass.id,
                }), 409

            from flask import url_for
            download_url = url_for('public_wallet.download_pass_by_token',
                                   token=wallet_pass.download_token, _external=True)

            from app.pub_league.email_helpers import send_pass_ready_email
            sent = send_pass_ready_email(
                recipient_email=recipient,
                recipient_name=player.name,
                division=_pass_division(session, wallet_pass, player),
                # No platform= — the template appends `&platform=...` per button.
                download_url=download_url,
            )
            if not sent:
                return jsonify({
                    'success': False,
                    'error': 'The mail server would not accept the message. The pass '
                             'is fine — this is a delivery failure, so try again or '
                             'send the link another way.',
                    'player_id': player_id,
                    'pass_id': wallet_pass.id,
                }), 502

            actor_id = int(get_jwt_identity())
            already = (wallet_pass.download_count or 0)
            try:
                from app.models.admin_config import AdminAuditLog
                AdminAuditLog.log_action(
                    user_id=actor_id, action='WALLET_PASS_RESEND',
                    resource_type='wallet_pass', resource_id=str(wallet_pass.id),
                    new_value=(f'download link re-sent to the {source} address for '
                               f'player {player_id}; download_count was {already}'),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent'))
            except Exception as exc:
                logger.warning(f"audit log skipped for pass resend "
                               f"{wallet_pass.id}: {exc}")

            logger.info("Admin %s re-sent wallet pass %s download link for player %s "
                        "(%s address, download_count=%s)",
                        actor_id, wallet_pass.id, player_id, source, already)

            return jsonify({
                'success': True,
                'message': f'Download link sent to {player.name}.',
                'player_id': player_id,
                'pass_id': wallet_pass.id,
                # Masked; `sent_to_source` says which of the three it came from.
                'sent_to': _mask_email(recipient),
                'sent_to_source': source,
                # Unchanged by a resend — it only moves when they actually tap
                # the link, which is what makes it worth watching afterwards.
                'download_count': already,
                'previously_downloaded': already > 0,
                # Nothing about the pass changed. Say so, so nobody reads this
                # as having invalidated the copy on their phone.
                'pass_changed': False,
            }), 200

    except Exception as exc:
        logger.error(f"[MOBILE_API] wallet pass resend for player {player_id} "
                     f"failed: {exc}", exc_info=True)
        return jsonify({'success': False,
                        'error': 'Could not send the download link.'}), 500


@mobile_api_v2.route('/admin/wallet/pass/reissue', methods=['POST'])
@jwt_required()
@jwt_role_required(ADMIN_ROLES)
def admin_wallet_pass_reissue():
    """Regenerate a player's pass artifacts and nudge their devices.

    Body: {"player_id": 908}

    ⚠️ This does NOT mint a new pass or rotate the barcode. It rebuilds the
    Apple/Google artifacts from current data and pushes a refresh, so a stale or
    failed-to-render pass fixes itself. Rotating the barcode would invalidate
    the copy already on their phone — the opposite of what someone standing at
    the gate needs.

    ⚠️ It also will NOT create a pass for a player who has none. Issuing a pass
    is a paid-entitlement decision that belongs with the order desk (link the
    line item), not with a gate button; the response says so instead of quietly
    manufacturing an entitlement.
    """
    from app.models import Player
    from app.models.wallet import WalletPass

    data = _body()
    player_id = data.get('player_id')
    try:
        player_id = int(player_id)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'player_id is required'}), 400

    try:
        with managed_session() as session:
            player = session.query(Player).get(player_id)
            if player is None:
                return jsonify({'success': False, 'error': 'Player not found'}), 404

            wallet_pass = (session.query(WalletPass)
                           .filter(WalletPass.player_id == player_id,
                                   WalletPass.status == 'active')
                           .order_by(WalletPass.created_at.desc()).first())
            if wallet_pass is None:
                return jsonify({
                    'success': False,
                    'error': f'{player.name} has no active pass to reissue. If they '
                             f'paid, link their order line item on the order desk — '
                             f'that is what issues a pass.',
                }), 409

            from app.wallet_pass.services.pass_service import pass_service
            result = pass_service.generate_both_platforms(wallet_pass)
            regenerated = [k for k in ('apple', 'google') if result.get(k)]
            errors = {k: result.get(f'{k}_error')
                      for k in ('apple', 'google') if result.get(f'{k}_error')}

            pushed = {}
            try:
                from app.wallet_pass.services.push_service import trigger_wallet_refresh
                # Commits on the session owning the row, before the push —
                # trigger_wallet_refresh handles that ordering itself.
                pushed = trigger_wallet_refresh(wallet_pass, session=session)
            except Exception as exc:
                logger.warning(f"wallet refresh push skipped for pass "
                               f"{wallet_pass.id}: {exc}")

            if not regenerated:
                # Say what failed rather than reporting a success nobody got.
                return jsonify({
                    'success': False,
                    'error': 'Could not regenerate the pass on either platform.',
                    'errors': errors,
                }), 502

            logger.info("Admin %s reissued wallet pass %s for player %s (%s)",
                        get_jwt_identity(), wallet_pass.id, player_id, regenerated)

            return jsonify({
                'success': True,
                'message': f'Pass rebuilt for {player.name} '
                           f'({", ".join(regenerated)}).',
                'player_id': player_id,
                'pass_id': wallet_pass.id,
                'regenerated': regenerated,
                'errors': errors or None,
                'push': {'apple': pushed.get('apple'), 'google': pushed.get('google')},
                # Unchanged on purpose — see the docstring.
                'barcode_rotated': False,
            }), 200

    except Exception as exc:
        logger.error(f"[MOBILE_API] wallet reissue for player {player_id} "
                     f"failed: {exc}", exc_info=True)
        return jsonify({'success': False,
                        'error': 'Could not reissue the pass.'}), 500
