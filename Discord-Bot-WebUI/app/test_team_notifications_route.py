from flask import Blueprint, render_template_string, request, jsonify
import requests
import json
from app.decorators import role_required

test_bp = Blueprint('test_notifications', __name__, url_prefix='/test')

@test_bp.route('/team-notifications')
@role_required('Global Admin')
def test_team_notifications():
    """Test page for team notifications - accessible via browser"""
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Team Notifications Test</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .test-section { margin: 20px 0; padding: 20px; border: 1px solid #ddd; }
            button { padding: 10px 20px; margin: 10px 0; }
            .result { background: #f5f5f5; padding: 10px; margin: 10px 0; }
            input, textarea { width: 100%; padding: 8px; margin: 5px 0; }
        </style>
    </head>
    <body>
        <h1>🚀 Team Notifications Test Page</h1>
        
        <div class="test-section">
            <h2>1. Test Team Members Lookup</h2>
            <input type="text" id="teamRole" value="ECS-FC-PL-TEAM-H-PLAYER" placeholder="Discord Team Role (e.g., ECS-FC-PL-DRAGONS-PLAYER)">
            <button onclick="testTeamLookup()">Test Team Lookup</button>
            <div id="lookupResult" class="result"></div>
        </div>
        
        <div class="test-section">
            <h2>2. Test Send Notification</h2>
            <input type="text" id="sendTeamRole" value="ECS-FC-PL-TEAM-H-PLAYER" placeholder="Discord Team Role (e.g., ECS-FC-PL-VAN-GOAL-PLAYER)">
            <textarea id="message" placeholder="Test message">🧪 This is a test notification from the admin panel!</textarea>
            <input type="text" id="coachId" value="123456789012345678" placeholder="Coach Discord ID">
            <button onclick="testSendNotification()">Test Send Notification</button>
            <div id="sendResult" class="result"></div>
        </div>

        <script>
            async function testTeamLookup() {
                const teamRole = document.getElementById('teamRole').value;
                const resultDiv = document.getElementById('lookupResult');
                
                try {
                    const response = await fetch(`/api/team-notifications/teams/${teamRole}/members`);
                    const data = await response.json();
                    
                    if (response.ok) {
                        resultDiv.innerHTML = `
                            <h3>✅ Success!</h3>
                            <p><strong>Team:</strong> ${data.team_db_name}</p>
                            <p><strong>Total Members:</strong> ${data.total_members}</p>
                            <p><strong>Members with Push Tokens:</strong> ${data.total_with_tokens}</p>
                            <pre>${JSON.stringify(data, null, 2)}</pre>
                        `;
                    } else {
                        resultDiv.innerHTML = `<h3>❌ Error:</h3><pre>${JSON.stringify(data, null, 2)}</pre>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<h3>❌ Error:</h3><p>${error.message}</p>`;
                }
            }
            
            async function testSendNotification() {
                const teamRole = document.getElementById('sendTeamRole').value;
                const message = document.getElementById('message').value;
                const coachId = document.getElementById('coachId').value;
                const resultDiv = document.getElementById('sendResult');
                
                try {
                    const response = await fetch('/api/team-notifications/send', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            team_name: teamRole,
                            message: message,
                            coach_discord_id: coachId,
                            title: '⚽ Test Team Message'
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        resultDiv.innerHTML = `
                            <h3>✅ Notification Sent!</h3>
                            <p><strong>Team:</strong> ${data.team_name}</p>
                            <p><strong>Tokens Sent To:</strong> ${data.tokens_sent_to}</p>
                            <pre>${JSON.stringify(data, null, 2)}</pre>
                        `;
                    } else {
                        resultDiv.innerHTML = `<h3>❌ Error:</h3><pre>${JSON.stringify(data, null, 2)}</pre>`;
                    }
                } catch (error) {
                    resultDiv.innerHTML = `<h3>❌ Error:</h3><p>${error.message}</p>`;
                }
            }
        </script>
    </body>
    </html>
    """
    
    return render_template_string(html_template)