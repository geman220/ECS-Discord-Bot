"""Census of every place the app messages a person.

WHY THIS EXISTS
---------------
`TRIGGER_OVERLAPS` (app/models/automation.py) tells an admin building an
automation what the app ALREADY sends on the same event, so they don't
double-message people. It cannot be generated from code: "does the Thursday RSVP
DM overlap the player-inactive trigger?" is a semantic judgement, not something
static analysis can answer.

What CAN be mechanised is noticing that the ground truth moved. This test walks
the AST of every module under app/ and collects the set of call sites that send
something to a human — email, SMS, push, Discord DM, in-app. That set is pinned
in `notification_senders.txt`. When someone adds (or deletes) a sender, this test
fails and tells them to go and look at TRIGGER_OVERLAPS.

So the inventory stays hand-WRITTEN, but it stops going stale SILENTLY, which is
the failure mode that actually bites: a warning surface that quietly stops being
true still looks authoritative.

Entries are `path::enclosing_function::sender` with no line numbers, so ordinary
edits inside a file do not churn the manifest.

To update after an intentional change:
    python -m tests.test_notification_census --write
"""
import ast
import os
import sys

import pytest

APP_ROOT = 'app'
MANIFEST = os.path.join(os.path.dirname(__file__), 'notification_senders.txt')

# Direct-call senders. Names, not import paths: these are called unqualified or
# as an attribute, and matching on the bare name is what survives the codebase's
# mix of `from app.email import send_email` and `helpers.send_email`.
SENDER_NAMES = {
    'NotificationPayload',      # constructing one always precedes an orchestrator send
    'send_email',
    'send_sms',
    'send_discord_dm',
    'send_ecs_fc_dm_sync',
    'send_welcome_message',
}
# `orchestrator.send(...)` — the unified multi-channel dispatch.
RECEIVER_METHODS = {('orchestrator', 'send')}


def _enclosing_function_names(tree):
    """Map id(node) -> name of the function it sits inside ('<module>' if none)."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                names[id(child)] = node.name
    return names


def collect_senders(app_root=APP_ROOT):
    """Every user-facing send call site, as a sorted list of stable keys."""
    found = set()
    for root, dirs, files in os.walk(app_root):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for filename in sorted(files):
            if not filename.endswith('.py'):
                continue
            path = os.path.join(root, filename).replace(os.sep, '/')
            try:
                tree = ast.parse(open(path, encoding='utf-8').read())
            except (SyntaxError, UnicodeDecodeError):
                # A module we cannot parse is a bigger problem than this test,
                # and other suites will catch it. Skipping keeps the census
                # from failing for an unrelated reason.
                continue
            enclosing = _enclosing_function_names(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                sender = None
                if isinstance(func, ast.Name) and func.id in SENDER_NAMES:
                    sender = func.id
                elif isinstance(func, ast.Attribute):
                    if func.attr in SENDER_NAMES:
                        sender = func.attr
                    elif (isinstance(func.value, ast.Name)
                          and (func.value.id, func.attr) in RECEIVER_METHODS):
                        sender = f'{func.value.id}.{func.attr}'
                if sender:
                    where = enclosing.get(id(node), '<module>')
                    found.add(f'{path}::{where}::{sender}')
    return sorted(found)


def _read_manifest():
    with open(MANIFEST, encoding='utf-8') as fh:
        return sorted(
            line.strip() for line in fh
            if line.strip() and not line.startswith('#')
        )


def test_notification_senders_match_the_manifest():
    current = set(collect_senders())
    recorded = set(_read_manifest())

    added = sorted(current - recorded)
    removed = sorted(recorded - current)
    if not added and not removed:
        return

    lines = ['The set of places this app messages people has changed.', '']
    if added:
        lines += [
            'NEW senders (%d):' % len(added),
            *[f'  + {a}' for a in added],
            '',
            'For each one, ask: does it fire on the same event as an automation',
            'trigger? If so, update TRIGGER_OVERLAPS in app/models/automation.py',
            'so the editor stops telling admins that nothing else sends there.',
            '',
        ]
    if removed:
        lines += [
            'REMOVED senders (%d):' % len(removed),
            *[f'  - {r}' for r in removed],
            '',
            'A deleted sender is the more dangerous direction: TRIGGER_OVERLAPS may',
            'now warn about a message that no longer exists, which pushes admins',
            'away from an automation they actually need.',
            '',
        ]
    lines += ['Once reviewed, refresh the manifest:',
              '  python -m tests.test_notification_census --write']
    pytest.fail('\n'.join(lines))


def test_every_manifest_entry_points_at_a_real_file():
    """Guards a stale manifest after a file rename."""
    missing = sorted({e.split('::', 1)[0] for e in _read_manifest()
                      if not os.path.exists(e.split('::', 1)[0])})
    assert not missing, (
        'Manifest references files that no longer exist: %s' % missing)


if __name__ == '__main__':
    if '--write' in sys.argv:
        senders = collect_senders()
        with open(MANIFEST, 'w', encoding='utf-8') as fh:
            fh.write('# Auto-generated census of user-facing send call sites.\n')
            fh.write('# Regenerate: python -m tests.test_notification_census --write\n')
            fh.write('# Adding an entry here means you have CHECKED whether it\n')
            fh.write('# overlaps an automation trigger (app/models/automation.py\n')
            fh.write('# TRIGGER_OVERLAPS) — not just that the test was red.\n')
            for entry in senders:
                fh.write(entry + '\n')
        print(f'Wrote {len(senders)} senders to {MANIFEST}')
    else:
        for entry in collect_senders():
            print(entry)
