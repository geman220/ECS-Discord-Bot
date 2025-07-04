# ECS Discord Bot & League Management System

## Overview
The ECS Discord Bot is a comprehensive soccer team and league management system designed for the Emerald City Supporters. This system combines a sophisticated Discord bot with a full-featured Flask web application to provide complete league administration, match management, player tracking, and fan engagement capabilities.

## System Architecture

### **Dual-Platform Solution**
- **Discord Bot**: Real-time match updates, fan engagement, and team communication
- **Flask Web Application**: Administrative interface, league management, and player portal
- **Integrated Backend**: Shared database and API communication for seamless operation

### **Key Technologies**
- **Discord.py**: Advanced async Discord bot framework
- **Flask**: Production-ready web application with Socket.IO
- **PostgreSQL**: Primary database with SQLAlchemy ORM
- **Redis**: Session management and task queue
- **Celery**: Background task processing with specialized workers
- **Docker**: Containerized deployment with microservices architecture

## Discord Bot Features

### **Match Management**
- **Automated Match Threads**: Create and manage match discussion threads
- **Live Match Updates**: Real-time score updates and match events
- **Prediction System**: Fan score predictions with closed betting
- **Weather Integration**: Match day weather updates for home games
- **Schedule Integration**: Automatic thread creation from schedule database

### **Team & League Commands**
- **Team Communication**: Coach messaging to team players with role mentions
- **Role Management**: Automated Discord role assignment and verification
- **Player Lookup**: Search players by Discord user with permission controls
- **Team Verification**: Check Discord presence of team members
- **Notification Preferences**: Individual SMS/email/DM notification settings

### **Fan Engagement**
- **Ticket Integration**: Links to home and away match tickets
- **Team Statistics**: Real-time Seattle Sounders season stats
- **Membership Verification**: ECS membership verification with order numbers
- **WooCommerce Integration**: Ticket sales and order management
- **Multiple League Support**: MLS, US Open Cup, Concacaf, and more

### **Administrative Tools**
- **Schedule Management**: Add, update, and delete match dates
- **User Management**: Member verification and role assignment
- **System Administration**: Bot updates, version control, and diagnostics
- **Data Export**: CSV reports and member list generation

## Flask Web Application Features

### **League Management System**
- **Multi-Season Support**: Manage multiple seasons with historical data
- **League Structure**: Premier/Classic divisions for Pub League and ECS FC
- **Team Management**: Complete team administration with Discord integration
- **Player Registration**: Comprehensive player profiles and team assignments
- **Coach Management**: Role-based permissions and team assignments

### **Automated Scheduling**
- **Round-Robin Generation**: Intelligent tournament scheduling algorithm
- **Multi-Field Support**: Balanced field assignments across venues
- **Special Week Handling**: FUN weeks, BYE weeks, and tournament weeks
- **Back-to-Back Scheduling**: Multiple matches per team per day
- **Schedule Preview**: Approval workflow before committing schedules

### **Match Operations**
- **RSVP System**: Player availability tracking with notifications
- **Live Match Reporting**: Real-time match event tracking
- **Statistics Management**: Goals, assists, cards, and performance metrics
- **Substitute Management**: Automated sub request and assignment
- **Team Verification**: Dual-team verification for match accuracy

### **User Management**
- **Multi-Role Authentication**: Global Admin, League Admin, Coach, Player roles
- **Discord OAuth Integration**: Seamless Discord account linking
- **Permission System**: Granular access control across all features
- **Profile Management**: Comprehensive player profiles with photos
- **2FA Support**: TOTP-based two-factor authentication

### **Real-Time Features**
- **Socket.IO Integration**: Live updates for drafts and match reporting
- **Draft System**: Real-time player drafting with live updates
- **Role Synchronization**: Automatic Discord role assignment
- **Notification System**: Multi-channel notifications (SMS, email, Discord)

### **Administrative Interface**
- **Season Management**: Create and manage league seasons
- **Statistics Dashboard**: League-wide performance metrics
- **User Administration**: Player approval and role management
- **System Monitoring**: Database health and task queue monitoring
- **Data Export**: Comprehensive reporting and analytics

## Integration Architecture

### **Communication Layer**
- **FastAPI Bridge**: Discord bot exposes REST API on port 5001
- **HTTP Client**: Flask app communicates with Discord bot via HTTP requests
- **Shared Database**: PostgreSQL database accessed by both systems
- **Redis Message Queue**: Background task coordination and caching

### **Background Processing**
- **Celery Task Queue**: Distributed task processing with specialized workers
- **Discord Worker**: Handles Discord API operations and role management
- **Live Reporting Worker**: Processes match updates and statistics
- **Player Sync Worker**: Synchronizes player data between systems
- **General Worker**: Handles email, SMS, and miscellaneous tasks

### **Data Synchronization**
- **Shared Models**: Unified database schema across both applications
- **Role Synchronization**: Automatic Discord role assignment from web interface
- **Real-Time Updates**: Socket.IO events for live interface updates
- **Audit Trails**: Change tracking for statistics and player modifications

## Pub League Management

### **Complete League Administration**
- **Season Creation**: Automated season setup with league structure
- **Team Management**: Team creation with automatic Discord integration
- **Player Registration**: Web-based registration with Discord linking
- **Coach Assignment**: Role-based permissions and team management
- **Schedule Generation**: Automated round-robin tournament creation

### **Discord Integration**
- **Automatic Role Creation**: Team-specific Discord roles and channels
- **Permission Management**: Coach and player role differentiation
- **Communication Tools**: Team messaging and notification systems
- **Verification System**: Discord account linking and role assignment

### **Match Management**
- **Automated Scheduling**: Round-robin with field optimization
- **RSVP Tracking**: Player availability with notification systems
- **Live Reporting**: Real-time match event tracking
- **Statistics**: Comprehensive player and team performance metrics
- **Standings**: Automated league table updates

### **Player Experience**
- **Profile Management**: Personal statistics and team history
- **Availability Tracking**: Match RSVP with notification preferences
- **Statistics Dashboard**: Personal performance metrics and history
- **Team Communication**: Integration with Discord for team coordination

## Getting Started

### Prerequisites

#### **System Requirements**
- **Docker & Docker Compose**: For containerized deployment
- **PostgreSQL**: Primary database server
- **Redis**: Session management and task queue
- **Python 3.11+**: For development and local testing

#### **Required Environment Variables**

**Discord Integration:**
- `BOT_TOKEN`: Discord Bot Token
- `SERVER_ID`: Discord Server ID
- `ADMIN_ROLE`: Discord Admin Role ID
- `DEV_ID`: Discord Developer ID

**Database & Cache:**
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string

**WooCommerce Integration:**
- `WC_KEY`: WooCommerce API Key
- `WC_SECRET`: WooCommerce API Secret
- `URL`: WooCommerce Site URL

**External APIs:**
- `OPENWEATHER_API_KEY`: Weather data for match days
- `SERPAPI_API`: Search API for ticket information
- `TEAM_NAME`: MLS Team Name (e.g., "Seattle Sounders FC")
- `TEAM_ID`: ESPN Team ID for statistics
- `VENUE_LONG`: Home venue longitude
- `VENUE_LAT`: Home venue latitude

**WordPress Integration:**
- `WP_USERNAME`: WordPress admin username
- `WP_APP_PASSWORD`: WordPress application password

**Internal Communication:**
- `FLASK_URL`: Flask application URL (default: http://webui:5000)
- `FLASK_TOKEN`: Internal API authentication token
- `BOT_API_URL`: Discord bot API URL (default: http://discord-bot:5001)

**Email & SMS:**
- `MAIL_SERVER`: SMTP server for email notifications
- `MAIL_USERNAME`: SMTP username
- `MAIL_PASSWORD`: SMTP password
- `TWILIO_ACCOUNT_SID`: Twilio account SID for SMS
- `TWILIO_AUTH_TOKEN`: Twilio authentication token
- `TWILIO_PHONE_NUMBER`: Twilio phone number for SMS

**Security:**
- `SECRET_KEY`: Flask application secret key
- `JWT_SECRET_KEY`: JWT signing secret
- `SECURITY_PASSWORD_SALT`: Password encryption salt

### Match Schedule Configuration

#### **Match Dates JSON**
The `match_dates.json` file contains all known match dates for the current season. Matches are automatically added to the database and Discord threads are created 24 hours before kickoff.

```json
{
  "matches": [
    { "date": "YYYYMMDD", "competition": "endpoint" }
  ]
}
```

**Format Requirements:**
- **date:** `YYYYMMDD` format (e.g., "20240315")
- **competition:** ESPN API endpoint identifier

**ESPN Competition Endpoints:**
- **MLS Regular Season**: `usa.1`
- **MLS Playoffs**: `usa.1` (same endpoint)
- **US Open Cup**: `usa.open`
- **FIFA Club World Cup**: `fifa.cwc`
- **Concacaf Champions League**: `concacaf.league`
- **Leagues Cup**: `concacaf.league.cup`

**Finding Competition Endpoints:**
1. Visit [ESPN Soccer Competitions](https://www.espn.com/soccer/competitions)
2. Select your competition
3. Copy the last part of the URL (e.g., `concacaf.league` from `https://www.espn.com/soccer/league/_/name/concacaf.league`)

### Installation Options

#### **Option 1: Docker Deployment (Recommended)**

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/yourusername/ECS-Discord-Bot.git
   cd ECS-Discord-Bot
   ```

2. **Create Environment File:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration values
   ```

3. **Configure Match Dates:**
   ```bash
   # Edit match_dates.json with your team's schedule
   ```

4. **Deploy with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

5. **Initialize Database:**
   ```bash
   docker-compose exec webui python -c "from app import create_app; from app.extensions import db; app = create_app(); app.app_context().push(); db.create_all()"
   ```

6. **Create Admin User:**
   ```bash
   docker-compose exec webui python -c "from app import create_app; from app.models import User; from app.extensions import db; app = create_app(); app.app_context().push(); admin = User(username='admin', email='admin@example.com', is_admin=True); admin.set_password('your_password'); db.session.add(admin); db.session.commit()"
   ```

#### **Option 2: Local Development Setup**

1. **Clone and Setup Virtual Environment:**
   ```bash
   git clone https://github.com/yourusername/ECS-Discord-Bot.git
   cd ECS-Discord-Bot
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   cd Discord-Bot-WebUI
   pip install -r requirements.txt
   ```

3. **Setup Local Services:**
   ```bash
   # Install PostgreSQL and Redis locally
   # Or use Docker for just these services:
   docker run -d --name postgres -p 5432:5432 -e POSTGRES_DB=ecsbot -e POSTGRES_USER=ecsbot -e POSTGRES_PASSWORD=password postgres:13
   docker run -d --name redis -p 6379:6379 redis:alpine
   ```

4. **Configure Environment:**
   ```bash
   cp .env.example .env
   # Edit .env with local configuration
   ```

5. **Run Services:**
   ```bash
   # Terminal 1: Discord Bot
   python ECS_Discord_Bot.py
   
   # Terminal 2: Flask Web App
   cd Discord-Bot-WebUI
   python wsgi.py
   
   # Terminal 3: Celery Worker
   cd Discord-Bot-WebUI
   celery -A app.extensions.celery worker --loglevel=info
   
   # Terminal 4: Celery Beat (Scheduler)
   cd Discord-Bot-WebUI
   celery -A app.extensions.celery beat --loglevel=info
   ```

#### **Initial Configuration**

1. **Access Web Interface:**
   - Open `http://localhost:5000` in your browser
   - Log in with admin credentials

2. **Configure Discord Bot:**
   - Execute `/createschedule` command as admin in Discord
   - This imports match dates and creates database entries

3. **Setup Pub League (Optional):**
   - Create new season in web interface
   - Configure leagues and teams
   - Set up scheduling parameters

4. **Test Integration:**
   - Verify Discord bot responds to commands
   - Check web interface loads correctly
   - Test role assignment and notifications

### Service Architecture

#### **Docker Services**
- **discord-bot**: Discord bot with FastAPI server
- **webui**: Flask web application
- **redis**: Session storage and task queue
- **celery-worker**: General background tasks
- **celery-discord-worker**: Discord-specific tasks
- **celery-live-reporting-worker**: Match reporting tasks
- **celery-beat**: Scheduled task coordinator
- **flower**: Task monitoring (optional)

#### **Port Configuration**
- **5000**: Flask web application
- **5001**: Discord bot FastAPI server (internal)
- **6379**: Redis server
- **5432**: PostgreSQL database
- **5555**: Flower task monitoring (optional)

## Usage

### Discord Bot Commands

#### **General Commands**
- `/record` - Display team season statistics
- `/nextmatch` - Show next scheduled match
- `/awaytickets` - Get links to away match tickets
- `/verify` - Verify ECS membership with order number
- `/predict` - Make score predictions for matches
- `/predictions` - View all predictions for current match

#### **Pub League Commands**
- `/team` - Send message to team players (coaches only)
- `/checkmyteam` - Verify team Discord presence
- `/notifications` - Manage notification preferences
- `/checkroles` - Lookup player Discord roles (admin/coach)

#### **Admin Commands**
- `/createschedule` - Import match schedule from JSON
- `/addmatchdate` - Add new match date
- `/updatematchdate` - Update existing match date
- `/deletematchdate` - Remove match date
- `/checkorder` - Verify ECS membership orders
- `/newseason` - Start new season with role creation
- `/update` - Update bot from GitHub
- `/version` - Display bot version information

### Web Interface

#### **League Administration**
1. **Season Management**: Create and manage league seasons
2. **Team Management**: Add teams, assign coaches, manage rosters
3. **Player Management**: Player registration, profile management, statistics
4. **Schedule Management**: Generate and manage match schedules
5. **Match Operations**: RSVP tracking, live reporting, statistics

#### **User Features**
1. **Profile Management**: Personal statistics and team history
2. **RSVP System**: Match availability with notifications
3. **Statistics Dashboard**: Performance metrics and leaderboards
4. **Team Communication**: Discord integration for coordination

### API Integration

#### **External API** (Read-Only)
The system provides a comprehensive API for third-party integrations:

**Base URL**: `https://your-domain.com/api/v1/`

**Authentication**: API Key required

**Endpoints**:
- `GET /players` - Player statistics and information
- `GET /teams` - Team data and performance
- `GET /matches` - Match results and schedules
- `GET /standings` - League standings and rankings
- `GET /stats` - Comprehensive league statistics

**Example**:
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
     https://your-domain.com/api/v1/players
```

### Advanced Features

#### **Automated Scheduling**
- Round-robin tournament generation
- Multi-field optimization
- Special week handling (FUN, BYE, TST)
- Conflict detection and resolution

#### **Real-Time Updates**
- Live match reporting via Socket.IO
- Real-time draft system
- Automatic Discord role synchronization
- Multi-channel notifications

#### **Statistics & Analytics**
- Player performance tracking
- Team statistics and standings
- Historical data analysis
- Export capabilities for external analysis

## Troubleshooting

### Common Issues

1. **Discord Bot Not Responding**
   - Check bot token and permissions
   - Verify server ID configuration
   - Check Docker container logs: `docker-compose logs discord-bot`

2. **Web Interface Not Loading**
   - Check Flask application logs: `docker-compose logs webui`
   - Verify database connection
   - Check Redis connectivity

3. **Role Assignment Issues**
   - Verify Discord bot has "Manage Roles" permission
   - Check role hierarchy (bot role must be higher than assigned roles)
   - Review Celery worker logs: `docker-compose logs celery-discord-worker`

4. **Background Tasks Not Running**
   - Check Celery worker status: `docker-compose ps`
   - Verify Redis connection
   - Review task logs: `docker-compose logs celery-worker`

### Log Files
- **Discord Bot**: `docker-compose logs discord-bot`
- **Web Application**: `docker-compose logs webui`
- **Background Tasks**: `docker-compose logs celery-worker`
- **Database**: Check PostgreSQL logs
- **Redis**: `docker-compose logs redis`

### Performance Optimization
- **Database**: Regular maintenance and indexing
- **Redis**: Monitor memory usage and configure eviction policies
- **Image Caching**: Use Redis for optimized image serving
- **Background Tasks**: Monitor queue sizes and worker performance

## Contributing
Contributions are welcome! This project follows standard open-source contribution practices.

### Development Setup
1. Fork the repository
2. Create a feature branch
3. Follow the local development setup instructions
4. Make your changes with tests
5. Submit a pull request

### Code Style
- Follow PEP 8 for Python code
- Use type hints where appropriate
- Include docstrings for classes and functions
- Write tests for new functionality

### Pull Request Process
1. Ensure all tests pass
2. Update documentation as needed
3. Follow the existing commit message style
4. Reference related issues in PR description

## Support

### Documentation
- [Admin Commands](docs/AdminCommands.md)
- [General Commands](docs/GeneralCommands.md)
- [Match Commands](docs/MatchCommands.md)
- [Pub League Commands](docs/PubLeagueCommands.md)
- [WooCommerce Commands](docs/WooCommerceCommands.md)

### Getting Help
- **Issues**: Submit bug reports via GitHub Issues
- **Discussions**: Use GitHub Discussions for questions
- **Discord**: Join the ECS Discord server for community support

### Professional Support
For organizations interested in customizing this system for their league:
- Custom feature development
- Deployment and hosting assistance
- Training and documentation
- Ongoing maintenance and support

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments
- **Emerald City Supporters**: For the inspiration and requirements
- **Discord.py Community**: For the excellent Discord bot framework
- **Flask Community**: For the robust web framework
- **Contributors**: All developers who have contributed to this project

---

**Note**: This system is designed specifically for soccer/football leagues but can be adapted for other sports with minimal modifications. The architecture is modular and extensible to support various league formats and requirements.
