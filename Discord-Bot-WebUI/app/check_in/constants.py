# app/check_in/constants.py

"""Tunable constants for match check-in.

Kept here so admin code, mobile API code, and the wallet-pass relevantDate
calculator can all reference one source of truth.
"""

# How many hours before/after kickoff a check-in is accepted.
# Spec value; may become configurable later if leagues want different windows.
MATCH_CHECKIN_WINDOW_HOURS = 2

# Lookback window for "next match" calculations on wallet passes.
# 14 days covers a typical inter-match gap.
NEXT_MATCH_WINDOW_DAYS = 14

# How long after kickoff a venue check-in token stays valid. Kept comfortably
# wider than MATCH_CHECKIN_WINDOW_HOURS so a printed/NFC code keeps resolving
# through the full match + a grace period, then dies (the public landing then
# truthfully says "Codes expire after the match window closes").
TOKEN_EXPIRY_HOURS_AFTER_KICKOFF = 6
