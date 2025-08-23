#!/usr/bin/env python3
"""
ESPN Match Finder

A simple script to help find ESPN match IDs for testing live reporting.
You can use this to find current/recent matches in various leagues.
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timedelta

# Common ESPN competition codes
COMPETITIONS = {
    # MLS & US Soccer
    'usa.1': 'MLS',
    'usa.nwsl': 'NWSL',
    'usa.open': 'US Open Cup',
    'usa.2': 'USL Championship',
    
    # European Top Leagues
    'eng.1': 'Premier League',
    'esp.1': 'La Liga',
    'ger.1': 'Bundesliga',
    'ita.1': 'Serie A',
    'fra.1': 'Ligue 1',
    'ned.1': 'Eredivisie',
    'por.1': 'Primeira Liga',
    
    # UEFA Competitions
    'uefa.champions': 'Champions League',
    'uefa.europa': 'Europa League',
    'uefa.europa_qual': 'Europa League Qualifying',
    'uefa.conference': 'Conference League',
    'uefa.nations': 'Nations League',
    'uefa.euro': 'European Championship',
    'uefa.euro_qual': 'Euro Qualifying',
    
    # CONMEBOL
    'conmebol.libertadores': 'Copa Libertadores',
    'conmebol.sudamericana': 'Copa Sudamericana',
    'conmebol.america': 'Copa América',
    'conmebol.america_qual': 'World Cup Qualifying CONMEBOL',
    
    # CONCACAF
    'concacaf.champions': 'CONCACAF Champions Cup',
    'concacaf.gold': 'Gold Cup',
    'concacaf.nations': 'Nations League',
    'concacaf.champions_qual': 'CONCACAF Champions Qualifying',
    
    # FIFA Competitions
    'fifa.world': 'World Cup',
    'fifa.wworld': 'Women\'s World Cup',
    'fifa.confederations': 'Confederations Cup',
    'fifa.club': 'Club World Cup',
    
    # Other Major Leagues
    'arg.1': 'Argentine Primera',
    'bra.1': 'Brazilian Serie A',
    'mex.1': 'Liga MX',
    'jpn.1': 'J1 League',
    'aus.1': 'A-League',
    'rsa.1': 'South African Premier',
    
    # European Second Tiers
    'eng.2': 'Championship',
    'esp.2': 'La Liga 2',
    'ger.2': '2. Bundesliga',
    'ita.2': 'Serie B',
    'fra.2': 'Ligue 2',
    
    # Domestic Cups
    'eng.fa': 'FA Cup',
    'esp.copa_del_rey': 'Copa del Rey',
    'ger.dfb_pokal': 'DFB Pokal',
    'ita.coppa_italia': 'Coppa Italia',
    'fra.coupe_de_france': 'Coupe de France',
    
    # International Friendlies
    'fifa.friendly': 'International Friendlies',
    'fifa.wfriendly': 'Women\'s Friendlies',
}

async def fetch_matches(competition_id: str, days_back: int = 7, days_forward: int = 7):
    """
    Fetch recent and upcoming matches for a competition.
    
    Args:
        competition_id: ESPN competition code (e.g., 'usa.1' for MLS)
        days_back: How many days back to search
        days_forward: How many days forward to search
    
    Returns:
        List of match data dictionaries
    """
    today = datetime.now()
    start_date = (today - timedelta(days=days_back)).strftime('%Y%m%d')
    end_date = (today + timedelta(days=days_forward)).strftime('%Y%m%d')
    
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition_id}/scoreboard"
    params = {
        'dates': f"{start_date}-{end_date}"
    }
    
    matches = []
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    events = data.get('events', [])
                    
                    for event in events:
                        competition = event.get('competitions', [{}])[0]
                        competitors = competition.get('competitors', [])
                        
                        if len(competitors) >= 2:
                            home_team = competitors[0].get('team', {})
                            away_team = competitors[1].get('team', {})
                            status = competition.get('status', {})
                            
                            match_info = {
                                'match_id': event.get('id'),
                                'date': event.get('date'),
                                'status': status.get('type', {}).get('name', 'Unknown'),
                                'home_team': home_team.get('displayName', 'Unknown'),
                                'away_team': away_team.get('displayName', 'Unknown'),
                                'home_score': competitors[0].get('score', '0'),
                                'away_score': competitors[1].get('score', '0'),
                                'venue': competition.get('venue', {}).get('fullName', 'Unknown'),
                                'competition': competition_id
                            }
                            matches.append(match_info)
                    
        except Exception as e:
            print(f"Error fetching matches for {competition_id}: {e}")
    
    return matches

def format_match_info(match):
    """Format match information for display."""
    date_obj = datetime.fromisoformat(match['date'].replace('Z', '+00:00'))
    formatted_date = date_obj.strftime('%Y-%m-%d %H:%M UTC')
    
    return (
        f"Match ID: {match['match_id']}\n"
        f"  {match['home_team']} vs {match['away_team']}\n"
        f"  Score: {match['home_score']}-{match['away_score']}\n"
        f"  Status: {match['status']}\n"
        f"  Date: {formatted_date}\n"
        f"  Venue: {match['venue']}\n"
        f"  Competition: {match['competition']}\n"
    )

async def find_live_matches():
    """Find currently live matches across multiple competitions."""
    print("🔴 Searching for LIVE matches...")
    live_matches = []
    
    for comp_id, comp_name in COMPETITIONS.items():
        print(f"  Checking {comp_name}...")
        matches = await fetch_matches(comp_id, days_back=1, days_forward=1)
        
        for match in matches:
            if match['status'] in ['STATUS_IN_PROGRESS', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF', 'STATUS_HALFTIME']:
                live_matches.append(match)
    
    return live_matches

async def find_recent_completed_matches():
    """Find recently completed matches for testing."""
    print("✅ Searching for recently completed matches...")
    completed_matches = []
    
    for comp_id, comp_name in COMPETITIONS.items():
        print(f"  Checking {comp_name}...")
        matches = await fetch_matches(comp_id, days_back=3, days_forward=0)
        
        for match in matches:
            if match['status'] in ['STATUS_FINAL', 'STATUS_FULL_TIME']:
                completed_matches.append(match)
    
    return completed_matches

async def find_upcoming_matches():
    """Find upcoming matches for testing."""
    print("📅 Searching for upcoming matches...")
    upcoming_matches = []
    
    for comp_id, comp_name in COMPETITIONS.items():
        print(f"  Checking {comp_name}...")
        matches = await fetch_matches(comp_id, days_back=0, days_forward=7)
        
        for match in matches:
            if match['status'] in ['STATUS_SCHEDULED', 'STATUS_PRE_GAME']:
                upcoming_matches.append(match)
    
    return upcoming_matches

async def main():
    """Main function to find various types of matches."""
    print("ESPN Match Finder for Live Reporting Testing")
    print("=" * 50)
    
    # Find live matches
    live_matches = await find_live_matches()
    if live_matches:
        print(f"\n🔴 LIVE MATCHES ({len(live_matches)} found):")
        print("-" * 30)
        for match in live_matches[:5]:  # Show first 5
            print(format_match_info(match))
    else:
        print("\n🔴 No live matches found.")
    
    # Find recent completed matches
    completed_matches = await find_recent_completed_matches()
    if completed_matches:
        print(f"\n✅ RECENT COMPLETED MATCHES ({len(completed_matches)} found, showing first 5):")
        print("-" * 40)
        for match in completed_matches[:5]:
            print(format_match_info(match))
    
    # Find upcoming matches
    upcoming_matches = await find_upcoming_matches()
    if upcoming_matches:
        print(f"\n📅 UPCOMING MATCHES ({len(upcoming_matches)} found, showing first 5):")
        print("-" * 30)
        for match in upcoming_matches[:5]:
            print(format_match_info(match))
    
    print("\n" + "=" * 50)
    print("How to test:")
    print("1. Copy any Match ID from above")
    print("2. Go to /test/live-reporting in your web interface")
    print("3. Enter the Match ID and corresponding competition code")
    print("4. Create a Discord thread first, then copy the thread ID")
    print("5. Click 'Start Live Reporting' to test!")
    print("\nNote: Live matches will show real events, completed matches won't update,")
    print("      and upcoming matches will only show pre-match info.")

if __name__ == "__main__":
    asyncio.run(main())